from __future__ import annotations
from copy import deepcopy
import fcntl
import os
import re
import threading
import uuid
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from watchdog.services.delivery.envelopes import ApprovalEnvelope, DecisionEnvelope, NotificationEnvelope


def _fact_snapshot_order(value: str) -> tuple[int, str]:
    match = re.fullmatch(r"fact-v(\d+)", value)
    if match is None:
        return (2**31 - 1, value)
    return (int(match.group(1)), value)


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


class DeliveryOutboxRecord(BaseModel):
    envelope_id: str
    envelope_type: str
    correlation_id: str
    session_id: str
    project_id: str
    native_thread_id: str | None = None
    policy_version: str
    fact_snapshot_version: str
    idempotency_key: str
    audit_ref: str
    created_at: str
    updated_at: str | None = None
    outbox_seq: int
    delivery_status: str = "pending"
    delivery_attempt: int = 0
    receipt_id: str | None = None
    next_retry_at: str | None = None
    failure_code: str | None = None
    operator_notes: list[str] = Field(default_factory=list)
    envelope_payload: dict[str, Any] = Field(default_factory=dict)

    @property
    def effective_native_thread_id(self) -> str | None:
        payload = self.envelope_payload if isinstance(self.envelope_payload, dict) else {}
        for candidate in (self.native_thread_id, payload.get("native_thread_id")):
            normalized = str(candidate or "").strip()
            if normalized:
                return normalized
        return None


class _DeliveryStoreFile(BaseModel):
    next_outbox_seq: int = 1
    decision_outbox: dict[str, DeliveryOutboxRecord] = Field(default_factory=dict)
    delivery_outbox: dict[str, DeliveryOutboxRecord] = Field(default_factory=dict)


class DeliveryOutboxStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = _path_lock(path)
        self._lock_path = path.with_name(f".{path.name}.lock")
        self._cache: _DeliveryStoreFile | None = None
        self._cache_signature: tuple[int, int] | None = None
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._guard_io():
            if not self._path.exists():
                self._write(_DeliveryStoreFile())

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

    def _read(self) -> _DeliveryStoreFile:
        signature = self._file_signature()
        if self._cache is not None and signature == self._cache_signature:
            return deepcopy(self._cache)
        raw = self._path.read_text(encoding="utf-8")
        if not raw.strip():
            data = _DeliveryStoreFile()
        else:
            data = _DeliveryStoreFile.model_validate_json(raw)
        self._cache = deepcopy(data)
        self._cache_signature = self._file_signature()
        return data

    def _write(self, data: _DeliveryStoreFile) -> None:
        tmp = self._path.with_name(f"{self._path.name}.{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_text(data.model_dump_json(indent=2), encoding="utf-8")
            tmp.replace(self._path)
            self._cache = deepcopy(data)
            self._cache_signature = self._file_signature()
        finally:
            with suppress(FileNotFoundError):
                tmp.unlink()

    def _file_signature(self) -> tuple[int, int] | None:
        with suppress(FileNotFoundError):
            stat = self._path.stat()
            return (stat.st_mtime_ns, stat.st_size)
        return None

    def enqueue_envelopes(
        self,
        envelopes: list[DecisionEnvelope | NotificationEnvelope | ApprovalEnvelope],
    ) -> list[DeliveryOutboxRecord]:
        persisted: list[DeliveryOutboxRecord] = []
        with self._guard_io():
            data = self._read()
            for envelope in envelopes:
                existing = data.delivery_outbox.get(envelope.envelope_id)
                if existing is not None:
                    refreshed = self._refresh_existing_record(existing, envelope)
                    if refreshed is not None:
                        data.decision_outbox[refreshed.envelope_id] = refreshed
                        data.delivery_outbox[refreshed.envelope_id] = refreshed
                        persisted.append(refreshed)
                        continue
                    persisted.append(existing)
                    continue
                record = DeliveryOutboxRecord(
                    envelope_id=envelope.envelope_id,
                    envelope_type=envelope.envelope_type,
                    correlation_id=envelope.correlation_id,
                    session_id=envelope.session_id,
                    project_id=envelope.project_id,
                    native_thread_id=envelope.native_thread_id,
                    policy_version=envelope.policy_version,
                    fact_snapshot_version=envelope.fact_snapshot_version,
                    idempotency_key=envelope.idempotency_key,
                    audit_ref=envelope.audit_ref,
                    created_at=envelope.created_at,
                    updated_at=envelope.created_at,
                    outbox_seq=data.next_outbox_seq,
                    envelope_payload=envelope.model_dump(mode="json"),
                )
                data.next_outbox_seq += 1
                data.decision_outbox[record.envelope_id] = record
                data.delivery_outbox[record.envelope_id] = record
                persisted.append(record)
            self._write(data)
        return persisted

    def get_delivery_record(self, envelope_id: str) -> DeliveryOutboxRecord | None:
        with self._guard_io():
            data = self._read()
            return data.delivery_outbox.get(envelope_id)

    def update_delivery_record(self, record: DeliveryOutboxRecord) -> DeliveryOutboxRecord:
        with self._guard_io():
            data = self._read()
            data.decision_outbox[record.envelope_id] = record
            data.delivery_outbox[record.envelope_id] = record
            data.next_outbox_seq = max(data.next_outbox_seq, record.outbox_seq + 1)
            self._write(data)
        return record

    def reserve_outbox_seq(self) -> int:
        with self._guard_io():
            data = self._read()
            outbox_seq = data.next_outbox_seq
            data.next_outbox_seq += 1
            self._write(data)
        return outbox_seq

    def snapshot_rows(self) -> list[DeliveryOutboxRecord]:
        with self._guard_io():
            return list(self._read().delivery_outbox.values())

    def list_records(self) -> list[DeliveryOutboxRecord]:
        with self._guard_io():
            data = self._read()
        return list(data.delivery_outbox.values())

    def list_pending_delivery_records(self, *, session_id: str | None = None) -> list[DeliveryOutboxRecord]:
        with self._guard_io():
            data = self._read()
        records = list(data.delivery_outbox.values())
        pending = [
            record
            for record in records
            if record.delivery_status in {"pending", "retrying"}
            and (session_id is None or record.session_id == session_id)
        ]
        return sorted(
            pending,
            key=lambda record: (
                record.session_id,
                _fact_snapshot_order(record.fact_snapshot_version),
                record.outbox_seq,
            ),
        )

    def requeue_transport_failures(
        self,
        *,
        reason: str,
        updated_at: str,
    ) -> list[DeliveryOutboxRecord]:
        requeued: list[DeliveryOutboxRecord] = []
        with self._guard_io():
            data = self._read()
            for envelope_id, record in list(data.delivery_outbox.items()):
                if record.delivery_status != "delivery_failed":
                    continue
                failure_code = str(record.failure_code or "")
                if not self._is_requeueable_transport_failure(failure_code):
                    continue
                notes = list(record.operator_notes)
                notes.append(
                    "delivery_requeued "
                    f"reason={reason} previous_failure_code={failure_code or 'unknown'}"
                )
                updated = record.model_copy(
                    update={
                        "delivery_status": "pending",
                        "delivery_attempt": 0,
                        "failure_code": None,
                        "next_retry_at": None,
                        "operator_notes": notes,
                        "updated_at": updated_at,
                    }
                )
                data.delivery_outbox[envelope_id] = updated
                data.decision_outbox[envelope_id] = updated
                requeued.append(updated)
            if requeued:
                self._write(data)
        return requeued

    def supersede_records(
        self,
        *,
        envelope_reasons: dict[str, str],
        updated_at: str,
    ) -> list[DeliveryOutboxRecord]:
        superseded: list[DeliveryOutboxRecord] = []
        if not envelope_reasons:
            return superseded
        with self._guard_io():
            data = self._read()
            for envelope_id, reason in envelope_reasons.items():
                record = data.delivery_outbox.get(envelope_id)
                if record is None:
                    continue
                if record.delivery_status in {"delivered", "superseded"}:
                    continue
                notes = list(record.operator_notes)
                notes.append(f"delivery_superseded reason={reason}")
                updated = record.model_copy(
                    update={
                        "delivery_status": "superseded",
                        "failure_code": None,
                        "next_retry_at": None,
                        "operator_notes": notes,
                        "updated_at": updated_at,
                    }
                )
                data.decision_outbox[envelope_id] = updated
                data.delivery_outbox[envelope_id] = updated
                superseded.append(updated)
            if superseded:
                self._write(data)
        return superseded

    @staticmethod
    def _is_requeueable_transport_failure(failure_code: str) -> bool:
        if failure_code in {
            "transport_error",
            "transport_timeout",
            "transport_configuration_error",
        }:
            return True
        return failure_code.startswith("upstream_")

    @staticmethod
    def _refresh_existing_record(
        existing: DeliveryOutboxRecord,
        envelope: DecisionEnvelope | NotificationEnvelope | ApprovalEnvelope,
    ) -> DeliveryOutboxRecord | None:
        incoming_snapshot = _fact_snapshot_order(envelope.fact_snapshot_version)
        existing_snapshot = _fact_snapshot_order(existing.fact_snapshot_version)
        incoming_payload = envelope.model_dump(mode="json")
        if incoming_snapshot < existing_snapshot:
            return None
        if (
            existing.envelope_type == "approval"
            and existing.delivery_status in {"delivered", "superseded"}
        ):
            return None
        if (
            incoming_snapshot == existing_snapshot
            and existing.idempotency_key == envelope.idempotency_key
            and existing.envelope_payload == incoming_payload
        ):
            return None
        notes = list(existing.operator_notes)
        notes.append(
            "delivery_payload_refreshed "
            f"previous_snapshot={existing.fact_snapshot_version} "
            f"new_snapshot={envelope.fact_snapshot_version}"
        )
        return existing.model_copy(
            update={
                "envelope_type": envelope.envelope_type,
                "correlation_id": envelope.correlation_id,
                "session_id": envelope.session_id,
                "project_id": envelope.project_id,
                "native_thread_id": envelope.native_thread_id,
                "policy_version": envelope.policy_version,
                "fact_snapshot_version": envelope.fact_snapshot_version,
                "idempotency_key": envelope.idempotency_key,
                "audit_ref": envelope.audit_ref,
                "created_at": envelope.created_at,
                "updated_at": envelope.created_at,
                "delivery_status": "pending",
                "delivery_attempt": 0,
                "receipt_id": None,
                "next_retry_at": None,
                "failure_code": None,
                "operator_notes": notes,
                "envelope_payload": incoming_payload,
            }
        )
