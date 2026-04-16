from __future__ import annotations

import fcntl
import os
import threading
import uuid
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from watchdog.services.session_service.models import SessionEventRecord

_PATH_LOCKS: dict[str, threading.Lock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


def _path_lock(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _PATH_LOCKS_GUARD:
        existing = _PATH_LOCKS.get(key)
        if existing is not None:
            return existing
        created = threading.Lock()
        _PATH_LOCKS[key] = created
        return created


def _utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class MemoryIngestQueueRecord(BaseModel):
    event_id: str
    project_id: str
    session_id: str
    event_type: str
    occurred_at: str
    queue_seq: int
    status: str = "pending"
    attempts: int = 0
    failure_code: str | None = None
    failure_detail: str | None = None
    next_retry_at: str | None = None
    enqueued_at: str
    updated_at: str
    event_payload: dict[str, Any] = Field(default_factory=dict)


class MemoryIngestEnqueueFailureRecord(BaseModel):
    event_id: str
    project_id: str
    session_id: str
    event_type: str
    failure_code: str
    failure_detail: str | None = None
    recorded_at: str
    event_payload: dict[str, Any] = Field(default_factory=dict)


class _MemoryIngestQueueFile(BaseModel):
    next_queue_seq: int = 1
    records: dict[str, MemoryIngestQueueRecord] = Field(default_factory=dict)


class _MemoryIngestFailureFile(BaseModel):
    failures: dict[str, MemoryIngestEnqueueFailureRecord] = Field(default_factory=dict)


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
    return parsed.astimezone(UTC)


class MemoryIngestQueueStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = _path_lock(path)
        self._lock_path = path.with_name(f".{path.name}.lock")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._guard_io():
            if not self._path.exists():
                self._write(_MemoryIngestQueueFile())

    @contextmanager
    def _guard_io(self):
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def _read(self) -> _MemoryIngestQueueFile:
        raw = self._path.read_text(encoding="utf-8")
        if not raw.strip():
            return _MemoryIngestQueueFile()
        return _MemoryIngestQueueFile.model_validate_json(raw)

    def _write(self, data: _MemoryIngestQueueFile) -> None:
        tmp = self._path.with_name(f"{self._path.name}.{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_text(data.model_dump_json(indent=2), encoding="utf-8")
            tmp.replace(self._path)
        finally:
            with suppress(FileNotFoundError):
                tmp.unlink()

    def enqueue_event(self, event: SessionEventRecord) -> MemoryIngestQueueRecord:
        with self._guard_io():
            data = self._read()
            existing = data.records.get(event.event_id)
            if existing is not None:
                return existing
            now = _utcnow()
            record = MemoryIngestQueueRecord(
                event_id=event.event_id,
                project_id=event.project_id,
                session_id=event.session_id,
                event_type=event.event_type,
                occurred_at=event.occurred_at,
                queue_seq=data.next_queue_seq,
                enqueued_at=now,
                updated_at=now,
                event_payload=event.model_dump(mode="json"),
            )
            data.next_queue_seq += 1
            data.records[event.event_id] = record
            self._write(data)
        return record

    def list_records(self) -> list[MemoryIngestQueueRecord]:
        with self._guard_io():
            records = list(self._read().records.values())
        return sorted(records, key=lambda record: record.queue_seq)

    def list_pending(self, *, session_id: str | None = None) -> list[MemoryIngestQueueRecord]:
        records = [
            record
            for record in self.list_records()
            if record.status == "pending"
            and (session_id is None or record.session_id == session_id)
        ]
        return records

    def claim_next(self, *, now: datetime | None = None) -> MemoryIngestQueueRecord | None:
        current_time = now or datetime.now(UTC)
        with self._guard_io():
            data = self._read()
            pending = sorted(
                (
                    record
                    for record in data.records.values()
                    if record.status == "pending"
                    or (
                        record.status == "retrying"
                        and (
                            _parse_iso(record.next_retry_at) is None
                            or _parse_iso(record.next_retry_at) <= current_time
                        )
                    )
                ),
                key=lambda record: record.queue_seq,
            )
            if not pending:
                return None
            current = pending[0]
            claimed = current.model_copy(
                update={
                    "status": "processing",
                    "attempts": current.attempts + 1,
                    "failure_code": None,
                    "failure_detail": None,
                    "next_retry_at": None,
                    "updated_at": _utcnow(),
                }
            )
            data.records[current.event_id] = claimed
            self._write(data)
        return claimed

    def mark_processed(self, event_id: str) -> MemoryIngestQueueRecord | None:
        with self._guard_io():
            data = self._read()
            current = data.records.get(event_id)
            if current is None:
                return None
            updated = current.model_copy(
                update={
                    "status": "processed",
                    "failure_code": None,
                    "failure_detail": None,
                    "next_retry_at": None,
                    "updated_at": _utcnow(),
                }
            )
            data.records[event_id] = updated
            self._write(data)
        return updated

    def mark_failed(
        self,
        event_id: str,
        *,
        failure_code: str,
        failure_detail: str | None = None,
    ) -> MemoryIngestQueueRecord | None:
        with self._guard_io():
            data = self._read()
            current = data.records.get(event_id)
            if current is None:
                return None
            updated = current.model_copy(
                update={
                    "status": "failed",
                    "failure_code": failure_code,
                    "failure_detail": failure_detail,
                    "updated_at": _utcnow(),
                }
            )
            data.records[event_id] = updated
            self._write(data)
        return updated

    def mark_retrying(
        self,
        event_id: str,
        *,
        next_retry_at: str,
        failure_code: str,
        failure_detail: str | None = None,
    ) -> MemoryIngestQueueRecord | None:
        with self._guard_io():
            data = self._read()
            current = data.records.get(event_id)
            if current is None:
                return None
            updated = current.model_copy(
                update={
                    "status": "retrying",
                    "failure_code": failure_code,
                    "failure_detail": failure_detail,
                    "next_retry_at": next_retry_at,
                    "updated_at": _utcnow(),
                }
            )
            data.records[event_id] = updated
            self._write(data)
        return updated

    def recover_inflight(self) -> list[MemoryIngestQueueRecord]:
        recovered: list[MemoryIngestQueueRecord] = []
        with self._guard_io():
            data = self._read()
            changed = False
            for event_id, current in list(data.records.items()):
                if current.status != "processing":
                    continue
                updated = current.model_copy(
                    update={
                        "status": "pending",
                        "failure_code": "worker_interrupted",
                        "failure_detail": "processing record recovered after restart",
                        "next_retry_at": None,
                        "updated_at": _utcnow(),
                    }
                )
                data.records[event_id] = updated
                recovered.append(updated)
                changed = True
            if changed:
                self._write(data)
        return recovered


class MemoryIngestEnqueueFailureStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = _path_lock(path)
        self._lock_path = path.with_name(f".{path.name}.lock")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._guard_io():
            if not self._path.exists():
                self._write(_MemoryIngestFailureFile())

    @contextmanager
    def _guard_io(self):
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def _read(self) -> _MemoryIngestFailureFile:
        raw = self._path.read_text(encoding="utf-8")
        if not raw.strip():
            return _MemoryIngestFailureFile()
        return _MemoryIngestFailureFile.model_validate_json(raw)

    def _write(self, data: _MemoryIngestFailureFile) -> None:
        tmp = self._path.with_name(f"{self._path.name}.{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_text(data.model_dump_json(indent=2), encoding="utf-8")
            tmp.replace(self._path)
        finally:
            with suppress(FileNotFoundError):
                tmp.unlink()

    def record_failure(
        self,
        event: SessionEventRecord,
        *,
        failure_code: str,
        failure_detail: str | None = None,
    ) -> MemoryIngestEnqueueFailureRecord:
        with self._guard_io():
            data = self._read()
            record = MemoryIngestEnqueueFailureRecord(
                event_id=event.event_id,
                project_id=event.project_id,
                session_id=event.session_id,
                event_type=event.event_type,
                failure_code=failure_code,
                failure_detail=failure_detail,
                recorded_at=_utcnow(),
                event_payload=event.model_dump(mode="json"),
            )
            data.failures[event.event_id] = record
            self._write(data)
        return record

    def list_failures(self) -> list[MemoryIngestEnqueueFailureRecord]:
        with self._guard_io():
            failures = list(self._read().failures.values())
        return sorted(failures, key=lambda record: (record.recorded_at, record.event_id))


class MemoryIngestEnqueuer:
    def __init__(
        self,
        *,
        queue_store: MemoryIngestQueueStore,
        failure_store: MemoryIngestEnqueueFailureStore | None = None,
    ) -> None:
        self._queue_store = queue_store
        self._failure_store = failure_store

    def enqueue_event(self, event: SessionEventRecord) -> MemoryIngestQueueRecord:
        try:
            return self._queue_store.enqueue_event(event)
        except Exception as exc:
            if self._failure_store is not None:
                self._failure_store.record_failure(
                    event,
                    failure_code="memory_ingest_enqueue_failed",
                    failure_detail=str(exc),
                )
            raise
