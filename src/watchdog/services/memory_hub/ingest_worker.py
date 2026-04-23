from __future__ import annotations

from datetime import UTC, datetime, timedelta

from watchdog.services.memory_hub.ingest_queue import MemoryIngestQueueStore
from watchdog.services.memory_hub.service import MemoryHubService
from watchdog.services.session_service.models import SessionEventRecord


def _iso_z(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class MemoryIngestWorker:
    def __init__(
        self,
        *,
        store: MemoryIngestQueueStore,
        memory_hub_service: MemoryHubService,
        max_attempts: int = 3,
        initial_backoff_seconds: float = 5.0,
    ) -> None:
        self._store = store
        self._memory_hub_service = memory_hub_service
        self._max_attempts = max(1, int(max_attempts))
        self._initial_backoff_seconds = max(0.0, float(initial_backoff_seconds))

    def process_next(self, *, now: datetime | None = None) -> bool:
        current_time = now or datetime.now(UTC)
        record = self._store.claim_next(now=current_time)
        if record is None:
            return False
        try:
            event = SessionEventRecord.model_validate(record.event_payload)
            self._memory_hub_service.ingest_session_event(event)
        except Exception as exc:
            if record.attempts >= self._max_attempts:
                self._store.mark_failed(
                    record.event_id,
                    failure_code="memory_ingest_failed",
                    failure_detail=str(exc),
                )
                return True
            backoff_seconds = self._initial_backoff_seconds * (2 ** max(record.attempts - 1, 0))
            next_retry_at = _iso_z(current_time + timedelta(seconds=backoff_seconds))
            self._store.mark_retrying(
                record.event_id,
                next_retry_at=next_retry_at,
                failure_code="memory_ingest_retrying",
                failure_detail=str(exc),
            )
            return True
        self._store.mark_processed(record.event_id)
        return True

    def drain_all(self, *, limit: int | None = None, now: datetime | None = None) -> int:
        processed = 0
        while limit is None or processed < limit:
            if not self.process_next(now=now):
                break
            processed += 1
        return processed
