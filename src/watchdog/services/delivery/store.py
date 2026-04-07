from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from watchdog.services.delivery.envelopes import ApprovalEnvelope, DecisionEnvelope, NotificationEnvelope


def _fact_snapshot_order(value: str) -> tuple[int, str]:
    match = re.fullmatch(r"fact-v(\d+)", value)
    if match is None:
        return (2**31 - 1, value)
    return (int(match.group(1)), value)


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
    outbox_seq: int
    delivery_status: str = "pending"
    delivery_attempt: int = 0
    receipt_id: str | None = None
    next_retry_at: str | None = None
    failure_code: str | None = None
    operator_notes: list[str] = Field(default_factory=list)
    envelope_payload: dict[str, Any] = Field(default_factory=dict)


class _DeliveryStoreFile(BaseModel):
    next_outbox_seq: int = 1
    decision_outbox: dict[str, DeliveryOutboxRecord] = Field(default_factory=dict)
    delivery_outbox: dict[str, DeliveryOutboxRecord] = Field(default_factory=dict)


class DeliveryOutboxStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._write(_DeliveryStoreFile())

    def _read(self) -> _DeliveryStoreFile:
        raw = self._path.read_text(encoding="utf-8")
        if not raw.strip():
            return _DeliveryStoreFile()
        return _DeliveryStoreFile.model_validate_json(raw)

    def _write(self, data: _DeliveryStoreFile) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(data.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def enqueue_envelopes(
        self,
        envelopes: list[DecisionEnvelope | NotificationEnvelope | ApprovalEnvelope],
    ) -> list[DeliveryOutboxRecord]:
        persisted: list[DeliveryOutboxRecord] = []
        with self._lock:
            data = self._read()
            for envelope in envelopes:
                existing = data.delivery_outbox.get(envelope.envelope_id)
                if existing is not None:
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
        with self._lock:
            data = self._read()
            return data.delivery_outbox.get(envelope_id)

    def update_delivery_record(self, record: DeliveryOutboxRecord) -> DeliveryOutboxRecord:
        with self._lock:
            data = self._read()
            data.delivery_outbox[record.envelope_id] = record
            self._write(data)
        return record

    def list_records(self) -> list[DeliveryOutboxRecord]:
        with self._lock:
            data = self._read()
        return list(data.delivery_outbox.values())

    def list_pending_delivery_records(self, *, session_id: str | None = None) -> list[DeliveryOutboxRecord]:
        with self._lock:
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
