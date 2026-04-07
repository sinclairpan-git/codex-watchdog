from __future__ import annotations

from datetime import UTC, datetime, timedelta

from watchdog.services.delivery.http_client import DeliveryAttemptResult, OpenClawDeliveryClient
from watchdog.services.delivery.store import DeliveryOutboxRecord, DeliveryOutboxStore
from watchdog.services.session_spine.store import SessionSpineStore
from watchdog.settings import Settings


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _iso_z(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class DeliveryWorker:
    def __init__(
        self,
        *,
        store: DeliveryOutboxStore,
        delivery_client: OpenClawDeliveryClient,
        settings: Settings,
        session_spine_store: SessionSpineStore | None = None,
    ) -> None:
        self._store = store
        self._delivery_client = delivery_client
        self._settings = settings
        self._session_spine_store = session_spine_store

    def _next_ready_record(
        self,
        *,
        now: datetime,
        session_id: str | None,
    ) -> DeliveryOutboxRecord | None:
        records = self._store.list_pending_delivery_records(session_id=session_id)
        if not records:
            return None
        if session_id is not None:
            head = records[0]
            next_retry = _parse_iso(head.next_retry_at)
            if next_retry is None or next_retry <= now:
                return head
            return None
        seen_sessions: set[str] = set()
        for record in records:
            if record.session_id in seen_sessions:
                continue
            next_retry = _parse_iso(record.next_retry_at)
            if next_retry is None or next_retry <= now:
                return record
            if record.failure_code == "suppressed_local_manual_activity":
                continue
            seen_sessions.add(record.session_id)
        return None

    def _apply_retryable_failure(
        self,
        *,
        record: DeliveryOutboxRecord,
        result: DeliveryAttemptResult,
        now: datetime,
    ) -> DeliveryOutboxRecord:
        attempt = record.delivery_attempt + 1
        if attempt >= self._settings.delivery_max_attempts:
            notes = list(record.operator_notes)
            notes.append(
                f"delivery_dead_letter failure_code={result.failure_code or 'unknown'} attempts={attempt}"
            )
            updated = record.model_copy(
                update={
                    "delivery_status": "delivery_failed",
                    "delivery_attempt": attempt,
                    "failure_code": result.failure_code,
                    "next_retry_at": None,
                    "operator_notes": notes,
                    "updated_at": _iso_z(now),
                }
            )
            return self._store.update_delivery_record(updated)
        delay = self._settings.delivery_initial_backoff_seconds * (2 ** (attempt - 1))
        next_retry_at = _iso_z(now + timedelta(seconds=delay))
        notes = list(record.operator_notes)
        notes.append(
            "delivery_retry_scheduled "
            f"failure_code={result.failure_code or 'unknown'} "
            f"attempts={attempt} next_retry_at={next_retry_at}"
        )
        updated = record.model_copy(
            update={
                "delivery_status": "retrying",
                "delivery_attempt": attempt,
                "failure_code": result.failure_code,
                "next_retry_at": next_retry_at,
                "operator_notes": notes,
                "updated_at": _iso_z(now),
            }
        )
        return self._store.update_delivery_record(updated)

    def _apply_stale_progress_summary(
        self,
        *,
        record: DeliveryOutboxRecord,
        occurred_at: str,
        age_seconds: int,
        now: datetime,
    ) -> DeliveryOutboxRecord:
        notes = list(record.operator_notes)
        notes.append(
            "delivery_skipped "
            "failure_code=stale_progress_summary "
            f"occurred_at={occurred_at} age_seconds={age_seconds}"
        )
        updated = record.model_copy(
            update={
                "delivery_status": "delivery_failed",
                "failure_code": "stale_progress_summary",
                "next_retry_at": None,
                "operator_notes": notes,
                "updated_at": _iso_z(now),
            }
        )
        return self._store.update_delivery_record(updated)

    def _apply_local_manual_activity_deferral(
        self,
        *,
        record: DeliveryOutboxRecord,
        last_local_manual_activity_at: str,
        age_seconds: int,
        next_retry_at: str,
        now: datetime,
    ) -> DeliveryOutboxRecord:
        notes = list(record.operator_notes)
        notes.append(
            "delivery_deferred "
            "failure_code=suppressed_local_manual_activity "
            f"last_local_manual_activity_at={last_local_manual_activity_at} "
            f"age_seconds={age_seconds} "
            f"next_retry_at={next_retry_at}"
        )
        updated = record.model_copy(
            update={
                "delivery_status": "retrying",
                "failure_code": "suppressed_local_manual_activity",
                "next_retry_at": next_retry_at,
                "operator_notes": notes,
                "updated_at": _iso_z(now),
            }
        )
        return self._store.update_delivery_record(updated)

    def _stale_progress_summary(
        self,
        *,
        record: DeliveryOutboxRecord,
        now: datetime,
    ) -> tuple[str, int] | None:
        payload = record.envelope_payload
        if payload.get("envelope_type") != "notification":
            return None
        if payload.get("notification_kind") != "progress_summary":
            return None
        occurred_at = payload.get("occurred_at") or payload.get("created_at") or record.created_at
        parsed = _parse_iso(occurred_at)
        if parsed is None:
            return None
        age_seconds = int((now - parsed.astimezone(UTC)).total_seconds())
        if age_seconds <= max(self._settings.progress_summary_max_age_seconds, 0.0):
            return None
        return (occurred_at, age_seconds)

    def _suppressed_for_local_manual_activity(
        self,
        *,
        record: DeliveryOutboxRecord,
        now: datetime,
    ) -> tuple[str, int, str] | None:
        if self._session_spine_store is None:
            return None
        payload = record.envelope_payload
        if payload.get("envelope_type") != "notification":
            return None
        severity = str(payload.get("severity") or "")
        if severity == "critical":
            return None
        notification_kind = str(payload.get("notification_kind") or "")
        if notification_kind not in {"progress_summary", "decision_result", "approval_result"}:
            return None
        try:
            session_record = self._session_spine_store.get(record.project_id)
        except Exception:
            return None
        if session_record is None:
            return None
        last_local_manual_activity_at = getattr(
            session_record,
            "last_local_manual_activity_at",
            None,
        )
        parsed = _parse_iso(last_local_manual_activity_at)
        if parsed is None:
            return None
        parsed_utc = parsed.astimezone(UTC)
        age_seconds = int((now - parsed_utc).total_seconds())
        if age_seconds < 0:
            return None
        quiet_window_seconds = max(self._settings.local_manual_activity_quiet_window_seconds, 0.0)
        if quiet_window_seconds <= 0:
            return None
        next_retry = parsed_utc + timedelta(seconds=quiet_window_seconds)
        if next_retry <= now:
            return None
        return (str(last_local_manual_activity_at), age_seconds, _iso_z(next_retry))

    def process_next_ready(
        self,
        *,
        now: datetime,
        session_id: str | None = None,
    ) -> DeliveryOutboxRecord | None:
        record = self._next_ready_record(now=now, session_id=session_id)
        if record is None:
            return None
        stale_progress = self._stale_progress_summary(record=record, now=now)
        if stale_progress is not None:
            occurred_at, age_seconds = stale_progress
            return self._apply_stale_progress_summary(
                record=record,
                occurred_at=occurred_at,
                age_seconds=age_seconds,
                now=now,
            )
        suppressed = self._suppressed_for_local_manual_activity(record=record, now=now)
        if suppressed is not None:
            last_local_manual_activity_at, age_seconds, next_retry_at = suppressed
            return self._apply_local_manual_activity_deferral(
                record=record,
                last_local_manual_activity_at=last_local_manual_activity_at,
                age_seconds=age_seconds,
                next_retry_at=next_retry_at,
                now=now,
            )
        result = self._delivery_client.deliver_record(record)
        if result.delivery_status == "delivered":
            notes = list(record.operator_notes)
            notes.append(
                "delivery_succeeded "
                f"receipt_id={result.receipt_id or ''} "
                f"attempts={record.delivery_attempt + 1}"
            )
            updated = record.model_copy(
                update={
                    "delivery_status": "delivered",
                    "delivery_attempt": record.delivery_attempt + 1,
                    "receipt_id": result.receipt_id,
                    "failure_code": None,
                    "next_retry_at": None,
                    "operator_notes": notes,
                    "updated_at": _iso_z(now),
                }
            )
            return self._store.update_delivery_record(updated)
        if result.delivery_status == "retryable_failure":
            return self._apply_retryable_failure(record=record, result=result, now=now)
        notes = list(record.operator_notes)
        notes.append(
            f"delivery_failed failure_code={result.failure_code or 'unknown'} attempts={record.delivery_attempt + 1}"
        )
        updated = record.model_copy(
            update={
                "delivery_status": "delivery_failed",
                "delivery_attempt": record.delivery_attempt + 1,
                "failure_code": result.failure_code,
                "next_retry_at": None,
                "operator_notes": notes,
                "updated_at": _iso_z(now),
            }
        )
        return self._store.update_delivery_record(updated)
