from __future__ import annotations

from datetime import UTC, datetime, timedelta

from watchdog.services.delivery.http_client import DeliveryAttemptResult, OpenClawDeliveryClient
from watchdog.services.delivery.store import DeliveryOutboxRecord, DeliveryOutboxStore
from watchdog.settings import Settings


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def _iso_z(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class DeliveryWorker:
    def __init__(
        self,
        *,
        store: DeliveryOutboxStore,
        delivery_client: OpenClawDeliveryClient,
        settings: Settings,
    ) -> None:
        self._store = store
        self._delivery_client = delivery_client
        self._settings = settings

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
            seen_sessions.add(record.session_id)
            next_retry = _parse_iso(record.next_retry_at)
            if next_retry is None or next_retry <= now:
                return record
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
                f"delivery_failed failure_code={result.failure_code or 'unknown'} attempts={attempt}"
            )
            updated = record.model_copy(
                update={
                    "delivery_status": "delivery_failed",
                    "delivery_attempt": attempt,
                    "failure_code": result.failure_code,
                    "next_retry_at": None,
                    "operator_notes": notes,
                }
            )
            return self._store.update_delivery_record(updated)
        delay = self._settings.delivery_initial_backoff_seconds * (2 ** (attempt - 1))
        notes = list(record.operator_notes)
        notes.append(
            f"delivery_retry_scheduled failure_code={result.failure_code or 'unknown'} attempts={attempt}"
        )
        updated = record.model_copy(
            update={
                "delivery_status": "retrying",
                "delivery_attempt": attempt,
                "failure_code": result.failure_code,
                "next_retry_at": _iso_z(now + timedelta(seconds=delay)),
                "operator_notes": notes,
            }
        )
        return self._store.update_delivery_record(updated)

    def process_next_ready(
        self,
        *,
        now: datetime,
        session_id: str | None = None,
    ) -> DeliveryOutboxRecord | None:
        record = self._next_ready_record(now=now, session_id=session_id)
        if record is None:
            return None
        result = self._delivery_client.deliver_record(record)
        if result.delivery_status == "delivered":
            notes = list(record.operator_notes)
            notes.append(f"delivery_succeeded receipt_id={result.receipt_id or ''}")
            updated = record.model_copy(
                update={
                    "delivery_status": "delivered",
                    "delivery_attempt": record.delivery_attempt + 1,
                    "receipt_id": result.receipt_id,
                    "failure_code": None,
                    "next_retry_at": None,
                    "operator_notes": notes,
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
            }
        )
        return self._store.update_delivery_record(updated)
