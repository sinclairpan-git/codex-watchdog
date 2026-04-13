from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from watchdog.services.delivery.http_client import DeliveryAttemptResult, OpenClawDeliveryClient
from watchdog.services.delivery.store import DeliveryOutboxRecord, DeliveryOutboxStore
from watchdog.services.session_service.service import SessionService
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
        session_service: SessionService | None = None,
    ) -> None:
        self._store = store
        self._delivery_client = delivery_client
        self._settings = settings
        self._session_spine_store = session_spine_store
        self._session_service = session_service

    @staticmethod
    def _notification_payload(record: DeliveryOutboxRecord) -> dict[str, Any] | None:
        payload = record.envelope_payload
        if payload.get("envelope_type") != "notification":
            return None
        return payload

    @staticmethod
    def _notification_related_ids(
        record: DeliveryOutboxRecord,
        payload: dict[str, Any],
        *,
        extra: dict[str, str] | None = None,
    ) -> dict[str, str]:
        related_ids = {"envelope_id": record.envelope_id}
        event_id = payload.get("event_id")
        if isinstance(event_id, str) and event_id:
            related_ids["notification_event_id"] = event_id
        notification_kind = payload.get("notification_kind")
        if isinstance(notification_kind, str) and notification_kind:
            related_ids["notification_kind"] = notification_kind
        for field in ("interaction_context_id", "interaction_family_id", "actor_id"):
            value = payload.get(field)
            if isinstance(value, str) and value:
                related_ids[field] = value
        if extra:
            related_ids.update(extra)
        return related_ids

    @staticmethod
    def _notification_payload_fields(
        record: DeliveryOutboxRecord,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        mirrored: dict[str, Any] = {
            "outbox_seq": record.outbox_seq,
            "delivery_status": record.delivery_status,
            "delivery_attempt": record.delivery_attempt,
        }
        for field in (
            "event_id",
            "notification_kind",
            "severity",
            "title",
            "summary",
            "reason",
            "occurred_at",
            "decision_result",
            "action_name",
            "interaction_context_id",
            "interaction_family_id",
            "actor_id",
            "channel_kind",
            "action_window_expires_at",
        ):
            value = payload.get(field)
            if value is not None:
                mirrored[field] = value
        return mirrored

    def _record_notification_event(
        self,
        *,
        event_type: str,
        record: DeliveryOutboxRecord,
        payload: dict[str, Any],
        correlation_id: str,
        causation_id: str | None = None,
        related_ids: dict[str, str] | None = None,
        event_payload: dict[str, Any] | None = None,
    ) -> None:
        if self._session_service is None:
            return
        self._session_service.record_event(
            event_type=event_type,
            project_id=record.project_id,
            session_id=record.session_id,
            occurred_at=_iso_z(datetime.now(UTC)),
            correlation_id=correlation_id,
            causation_id=causation_id,
            related_ids=self._notification_related_ids(
                record,
                payload,
                extra=related_ids,
            ),
            payload=event_payload
            or self._notification_payload_fields(record, payload),
        )

    def _record_notification_announced(
        self,
        *,
        record: DeliveryOutboxRecord,
        payload: dict[str, Any],
    ) -> None:
        self._record_notification_event(
            event_type="notification_announced",
            record=record,
            payload=payload,
            correlation_id=f"corr:notification:{record.envelope_id}:announce",
            causation_id=str(payload.get("event_id") or record.envelope_id),
        )

    def _record_notification_delivery_result(
        self,
        *,
        record: DeliveryOutboxRecord,
        payload: dict[str, Any],
        result: DeliveryAttemptResult,
    ) -> None:
        attempt = record.delivery_attempt
        outcome_payload = self._notification_payload_fields(record, payload)
        outcome_payload.update(
            {
                "delivery_status": result.delivery_status,
                "accepted": result.accepted,
            }
        )
        if result.failure_code is not None:
            outcome_payload["failure_code"] = result.failure_code
        if result.status_code is not None:
            outcome_payload["status_code"] = result.status_code
        event_type = (
            "notification_delivery_succeeded"
            if result.delivery_status == "delivered"
            else "notification_delivery_failed"
        )
        self._record_notification_event(
            event_type=event_type,
            record=record,
            payload=payload,
            correlation_id=f"corr:notification:{record.envelope_id}:attempt:{attempt}",
            causation_id=str(payload.get("event_id") or record.envelope_id),
            event_payload=outcome_payload,
        )
        if result.receipt_id:
            receipt_payload = self._notification_payload_fields(record, payload)
            receipt_payload["receipt_id"] = result.receipt_id
            if result.received_at is not None:
                receipt_payload["received_at"] = result.received_at
            self._record_notification_event(
                event_type="notification_receipt_recorded",
                record=record,
                payload=payload,
                correlation_id=f"corr:notification:{record.envelope_id}:receipt:{result.receipt_id}",
                causation_id=str(payload.get("event_id") or record.envelope_id),
                related_ids={"receipt_id": result.receipt_id},
                event_payload=receipt_payload,
            )

    def _record_notification_requeued(
        self,
        *,
        record: DeliveryOutboxRecord,
        payload: dict[str, Any],
        reason: str,
        next_retry_at: str | None = None,
        failure_code: str | None = None,
    ) -> None:
        requeue_payload = self._notification_payload_fields(record, payload)
        requeue_payload["reason"] = reason
        if next_retry_at is not None:
            requeue_payload["next_retry_at"] = next_retry_at
        if failure_code is not None:
            requeue_payload["failure_code"] = failure_code
        retry_point = next_retry_at or f"attempt:{record.delivery_attempt}"
        self._record_notification_event(
            event_type="notification_requeued",
            record=record,
            payload=payload,
            correlation_id=f"corr:notification:{record.envelope_id}:requeue:{retry_point}",
            causation_id=str(payload.get("event_id") or record.envelope_id),
            event_payload=requeue_payload,
        )

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
        updated = self._store.update_delivery_record(updated)
        notification_payload = self._notification_payload(record)
        if notification_payload is not None:
            self._record_notification_requeued(
                record=updated,
                payload=notification_payload,
                reason="suppressed_local_manual_activity",
                next_retry_at=next_retry_at,
                failure_code="suppressed_local_manual_activity",
            )
        return updated

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
        notification_payload = self._notification_payload(record)
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
        if notification_payload is not None:
            self._record_notification_announced(record=record, payload=notification_payload)
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
            updated = self._store.update_delivery_record(updated)
            if notification_payload is not None:
                self._record_notification_delivery_result(
                    record=updated,
                    payload=notification_payload,
                    result=result,
                )
            return updated
        if result.delivery_status == "retryable_failure":
            updated = self._apply_retryable_failure(record=record, result=result, now=now)
            if notification_payload is not None:
                self._record_notification_delivery_result(
                    record=updated,
                    payload=notification_payload,
                    result=result,
                )
                if updated.delivery_status == "retrying":
                    self._record_notification_requeued(
                        record=updated,
                        payload=notification_payload,
                        reason="retryable_delivery_failure",
                        next_retry_at=updated.next_retry_at,
                        failure_code=result.failure_code,
                    )
            return updated
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
        updated = self._store.update_delivery_record(updated)
        if notification_payload is not None:
            self._record_notification_delivery_result(
                record=updated,
                payload=notification_payload,
                result=result,
            )
        return updated
