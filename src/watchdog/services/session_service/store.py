from __future__ import annotations

import fcntl
import os
import threading
import uuid
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, Field

from watchdog.services.session_service.models import (
    RecoveryTransactionRecord,
    SessionEventRecord,
    SessionLineageRecord,
)

_PATH_LOCKS: dict[str, threading.Lock] = {}
_PATH_LOCKS_GUARD = threading.Lock()

RecordT = TypeVar(
    "RecordT",
    SessionEventRecord,
    SessionLineageRecord,
    RecoveryTransactionRecord,
)


def _path_lock(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _PATH_LOCKS_GUARD:
        existing = _PATH_LOCKS.get(key)
        if existing is not None:
            return existing
        created = threading.Lock()
        _PATH_LOCKS[key] = created
        return created


class _SessionServiceStoreFile(BaseModel):
    next_log_seq: int = 1
    events: list[SessionEventRecord] = Field(default_factory=list)
    lineage: list[SessionLineageRecord] = Field(default_factory=list)
    recovery_transactions: list[RecoveryTransactionRecord] = Field(default_factory=list)


class SessionServiceStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = _path_lock(path)
        self._lock_path = path.with_name(f".{path.name}.lock")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._guard_io():
            if not self._path.exists():
                self._write(_SessionServiceStoreFile())

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

    def _read(self) -> _SessionServiceStoreFile:
        raw = self._path.read_text(encoding="utf-8")
        if not raw.strip():
            return _SessionServiceStoreFile()
        return _SessionServiceStoreFile.model_validate_json(raw)

    def _write(self, data: _SessionServiceStoreFile) -> None:
        tmp = self._path.with_name(f"{self._path.name}.{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_text(data.model_dump_json(indent=2), encoding="utf-8")
            tmp.replace(self._path)
        finally:
            with suppress(FileNotFoundError):
                tmp.unlink()

    @staticmethod
    def _normalized(record: RecordT) -> dict[str, object]:
        return record.model_dump(mode="json", exclude={"log_seq"})

    @classmethod
    def _dedupe_by_idempotency(
        cls,
        records: list[RecordT],
        incoming: RecordT,
        *,
        label: str,
    ) -> RecordT | None:
        for existing in records:
            if existing.idempotency_key != incoming.idempotency_key:
                continue
            if cls._normalized(existing) != cls._normalized(incoming):
                raise ValueError(f"conflicting {label} for idempotency key: {incoming.idempotency_key}")
            return existing
        return None

    @classmethod
    def _assign_log_seq(
        cls,
        data: _SessionServiceStoreFile,
        record: RecordT,
    ) -> RecordT:
        assigned = record.model_copy(update={"log_seq": data.next_log_seq})
        data.next_log_seq += 1
        return assigned

    def append_event(self, record: SessionEventRecord) -> SessionEventRecord:
        with self._guard_io():
            data = self._read()
            existing = self._dedupe_by_idempotency(data.events, record, label="session event")
            if existing is not None:
                return existing
            for persisted in data.events:
                if persisted.event_id == record.event_id:
                    raise ValueError(f"conflicting session event id: {record.event_id}")
            assigned = self._assign_log_seq(data, record)
            data.events.append(assigned)
            self._write(data)
        return assigned

    def append_lineage(self, record: SessionLineageRecord) -> SessionLineageRecord:
        with self._guard_io():
            data = self._read()
            existing = self._dedupe_by_idempotency(data.lineage, record, label="session lineage")
            if existing is not None:
                return existing
            for persisted in data.lineage:
                if persisted.lineage_id == record.lineage_id:
                    raise ValueError(f"conflicting session lineage id: {record.lineage_id}")
            assigned = self._assign_log_seq(data, record)
            data.lineage.append(assigned)
            self._write(data)
        return assigned

    def append_recovery_transaction(
        self,
        record: RecoveryTransactionRecord,
    ) -> RecoveryTransactionRecord:
        with self._guard_io():
            data = self._read()
            existing = self._dedupe_by_idempotency(
                data.recovery_transactions,
                record,
                label="recovery transaction",
            )
            if existing is not None:
                return existing
            assigned = self._assign_log_seq(data, record)
            data.recovery_transactions.append(assigned)
            self._write(data)
        return assigned

    def list_events(
        self,
        *,
        session_id: str | None = None,
        event_type: str | None = None,
        related_id_key: str | None = None,
        related_id_value: str | None = None,
        correlation_id: str | None = None,
    ) -> list[SessionEventRecord]:
        with self._guard_io():
            data = self._read()
        records = data.events
        if session_id is not None:
            records = [record for record in records if record.session_id == session_id]
        if event_type is not None:
            records = [record for record in records if record.event_type == event_type]
        if correlation_id is not None:
            records = [record for record in records if record.correlation_id == correlation_id]
        if related_id_key is not None:
            records = [
                record
                for record in records
                if record.related_ids.get(related_id_key) == related_id_value
            ]
        return list(records)

    def list_lineage(
        self,
        *,
        parent_session_id: str | None = None,
        child_session_id: str | None = None,
        recovery_transaction_id: str | None = None,
    ) -> list[SessionLineageRecord]:
        with self._guard_io():
            data = self._read()
        records = data.lineage
        if parent_session_id is not None:
            records = [record for record in records if record.parent_session_id == parent_session_id]
        if child_session_id is not None:
            records = [record for record in records if record.child_session_id == child_session_id]
        if recovery_transaction_id is not None:
            records = [
                record
                for record in records
                if record.recovery_transaction_id == recovery_transaction_id
            ]
        return list(records)

    def list_recovery_transactions(
        self,
        *,
        parent_session_id: str | None = None,
        child_session_id: str | None = None,
        recovery_transaction_id: str | None = None,
        status: str | None = None,
    ) -> list[RecoveryTransactionRecord]:
        with self._guard_io():
            data = self._read()
        records = data.recovery_transactions
        if parent_session_id is not None:
            records = [record for record in records if record.parent_session_id == parent_session_id]
        if child_session_id is not None:
            records = [record for record in records if record.child_session_id == child_session_id]
        if recovery_transaction_id is not None:
            records = [
                record
                for record in records
                if record.recovery_transaction_id == recovery_transaction_id
            ]
        if status is not None:
            records = [record for record in records if record.status == status]
        return list(records)

    def get_latest_recovery_transaction(
        self,
        recovery_transaction_id: str,
    ) -> RecoveryTransactionRecord | None:
        records = self.list_recovery_transactions(
            recovery_transaction_id=recovery_transaction_id,
        )
        if not records:
            return None
        return max(records, key=lambda record: record.log_seq or 0)
