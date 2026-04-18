from __future__ import annotations

import fcntl
import hashlib
import json
import os
import threading
import uuid
from contextlib import contextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from watchdog.services.session_spine.store import PersistedSessionRecord

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


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decision_id_for_key(decision_key: str) -> str:
    digest = hashlib.sha256(decision_key.encode("utf-8")).hexdigest()[:16]
    return f"decision:{digest}"


def brain_intent_to_runtime_disposition(brain_intent: str) -> str:
    mapping = {
        "propose_execute": "auto_execute_and_notify",
        "require_approval": "require_user_decision",
        "propose_recovery": "auto_execute_and_notify",
        "candidate_closure": "require_user_decision",
        "suggest_only": "block_and_alert",
        "observe_only": "block_and_alert",
        "reject": "block_and_alert",
    }
    return mapping[brain_intent]


def build_decision_key(
    *,
    session_id: str,
    fact_snapshot_version: str,
    policy_version: str,
    decision_result: str,
    brain_intent: str | None,
    action_ref: str,
    approval_id: str | None,
) -> str:
    return "|".join(
        [
            session_id,
            fact_snapshot_version,
            policy_version,
            decision_result,
            brain_intent or "",
            action_ref,
            approval_id or "",
        ]
    )


def _build_operator_notes(
    *,
    session_id: str,
    fact_snapshot_version: str,
    policy_version: str,
    decision_result: str,
    risk_class: str,
    action_ref: str,
    matched_policy_rules: list[str],
    uncertainty_reasons: list[str],
    why_not_escalated: str | None,
    why_escalated: str | None,
) -> list[str]:
    notes = [
        f"decision={decision_result} risk={risk_class} action={action_ref}",
        f"snapshot={fact_snapshot_version} policy={policy_version} session={session_id}",
    ]
    if matched_policy_rules:
        notes.append(f"rules={','.join(matched_policy_rules)}")
    if uncertainty_reasons:
        notes.append(f"uncertainty={','.join(uncertainty_reasons)}")
    if why_not_escalated:
        notes.append(f"why_not_escalated={why_not_escalated}")
    if why_escalated:
        notes.append(f"why_escalated={why_escalated}")
    return notes


class CanonicalDecisionRecord(BaseModel):
    decision_id: str
    decision_key: str
    session_id: str
    project_id: str
    thread_id: str
    native_thread_id: str | None = None
    approval_id: str | None = None
    action_ref: str
    trigger: str = "resident_supervision"
    brain_intent: str | None = None
    runtime_disposition: str | None = None
    decision_result: str
    risk_class: str
    decision_reason: str
    matched_policy_rules: list[str] = Field(default_factory=list)
    why_not_escalated: str | None = None
    why_escalated: str | None = None
    uncertainty_reasons: list[str] = Field(default_factory=list)
    policy_version: str
    fact_snapshot_version: str
    idempotency_key: str
    created_at: str
    operator_notes: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)


def build_canonical_decision_record(
    *,
    persisted_record: PersistedSessionRecord,
    decision_result: str,
    brain_intent: str | None = None,
    risk_class: str,
    action_ref: str,
    matched_policy_rules: list[str],
    decision_reason: str,
    why_not_escalated: str | None,
    why_escalated: str | None,
    uncertainty_reasons: list[str],
    policy_version: str,
    trigger: str = "resident_supervision",
    extra_evidence: dict[str, Any] | None = None,
) -> CanonicalDecisionRecord:
    approval_id = (
        persisted_record.approval_queue[0].approval_id if persisted_record.approval_queue else None
    )
    session_id = persisted_record.thread_id
    decision_key = build_decision_key(
        session_id=session_id,
        fact_snapshot_version=persisted_record.fact_snapshot_version,
        policy_version=policy_version,
        decision_result=decision_result,
        brain_intent=brain_intent,
        action_ref=action_ref,
        approval_id=approval_id,
    )
    runtime_disposition = decision_result
    operator_notes = _build_operator_notes(
        session_id=session_id,
        fact_snapshot_version=persisted_record.fact_snapshot_version,
        policy_version=policy_version,
        decision_result=decision_result,
        risk_class=risk_class,
        action_ref=action_ref,
        matched_policy_rules=list(matched_policy_rules),
        uncertainty_reasons=list(uncertainty_reasons),
        why_not_escalated=why_not_escalated,
        why_escalated=why_escalated,
    )
    evidence = {
        "facts": [fact.model_dump(mode="json") for fact in persisted_record.facts],
        "matched_policy_rules": list(matched_policy_rules),
        "risk_class": risk_class,
        "decision_reason": decision_reason,
        "why_not_escalated": why_not_escalated,
        "why_escalated": why_escalated,
        "decision": {
            "brain_intent": brain_intent,
            "runtime_disposition": runtime_disposition,
            "decision_result": decision_result,
            "decision_reason": decision_reason,
            "why_not_escalated": why_not_escalated,
            "why_escalated": why_escalated,
            "uncertainty_reasons": list(uncertainty_reasons),
            "action_ref": action_ref,
            "approval_id": approval_id,
        },
        "target": {
            "session_id": session_id,
            "project_id": persisted_record.project_id,
            "thread_id": persisted_record.thread_id,
            "native_thread_id": persisted_record.native_thread_id,
            "approval_id": approval_id,
        },
        "policy_version": policy_version,
        "fact_snapshot_version": persisted_record.fact_snapshot_version,
        "idempotency_key": decision_key,
        "operator_notes": operator_notes,
    }
    if extra_evidence:
        evidence.update(extra_evidence)

    return CanonicalDecisionRecord(
        decision_id=_decision_id_for_key(decision_key),
        decision_key=decision_key,
        session_id=session_id,
        project_id=persisted_record.project_id,
        thread_id=persisted_record.thread_id,
        native_thread_id=persisted_record.native_thread_id,
        approval_id=approval_id,
        action_ref=action_ref,
        trigger=trigger,
        brain_intent=brain_intent,
        runtime_disposition=runtime_disposition,
        decision_result=decision_result,
        risk_class=risk_class,
        decision_reason=decision_reason,
        matched_policy_rules=list(matched_policy_rules),
        why_not_escalated=why_not_escalated,
        why_escalated=why_escalated,
        uncertainty_reasons=list(uncertainty_reasons),
        policy_version=policy_version,
        fact_snapshot_version=persisted_record.fact_snapshot_version,
        idempotency_key=decision_key,
        created_at=_utc_now_iso(),
        operator_notes=operator_notes,
        evidence=evidence,
    )


def build_brain_intent_decision_record(
    *,
    persisted_record: PersistedSessionRecord,
    brain_intent: str,
    risk_class: str,
    action_ref: str,
    matched_policy_rules: list[str],
    decision_reason: str,
    why_not_escalated: str | None,
    why_escalated: str | None,
    uncertainty_reasons: list[str],
    policy_version: str,
    trigger: str = "resident_supervision",
    extra_evidence: dict[str, Any] | None = None,
) -> CanonicalDecisionRecord:
    return build_canonical_decision_record(
        persisted_record=persisted_record,
        decision_result=brain_intent_to_runtime_disposition(brain_intent),
        brain_intent=brain_intent,
        risk_class=risk_class,
        action_ref=action_ref,
        matched_policy_rules=matched_policy_rules,
        decision_reason=decision_reason,
        why_not_escalated=why_not_escalated,
        why_escalated=why_escalated,
        uncertainty_reasons=uncertainty_reasons,
        policy_version=policy_version,
        trigger=trigger,
        extra_evidence=extra_evidence,
    )


class PolicyDecisionStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = _path_lock(path)
        self._lock_path = path.with_name(f".{path.name}.lock")
        self._cache: dict[str, dict[str, Any]] | None = None
        self._cache_signature: tuple[int, int] | None = None
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._guard_io():
            if not self._path.exists():
                self._write({})

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

    def _read(self) -> dict[str, dict[str, Any]]:
        signature = self._file_signature()
        if self._cache is not None and signature == self._cache_signature:
            return self._cache
        raw = self._path.read_text(encoding="utf-8")
        data = json.loads(raw) if raw.strip() else {}
        normalized = data if isinstance(data, dict) else {}
        self._cache = normalized
        self._cache_signature = self._file_signature()
        return normalized

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        tmp = self._path.with_name(f"{self._path.name}.{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self._path)
            self._cache = data
            self._cache_signature = self._file_signature()
        finally:
            with suppress(FileNotFoundError):
                tmp.unlink()

    def _file_signature(self) -> tuple[int, int] | None:
        with suppress(FileNotFoundError):
            stat = self._path.stat()
            return (stat.st_mtime_ns, stat.st_size)
        return None

    def get(self, decision_key: str) -> CanonicalDecisionRecord | None:
        with self._guard_io():
            row = self._read().get(decision_key)
        if not isinstance(row, dict):
            return None
        return CanonicalDecisionRecord.model_validate(row)

    def snapshot_rows(self) -> list[dict[str, Any]]:
        with self._guard_io():
            return list(self._read().values())

    def put(self, record: CanonicalDecisionRecord) -> CanonicalDecisionRecord:
        with self._guard_io():
            data = self._read()
            existing = data.get(record.decision_key)
            if isinstance(existing, dict):
                return CanonicalDecisionRecord.model_validate(existing)
            data[record.decision_key] = record.model_dump(mode="json")
            self._write(data)
        return record

    def update(self, record: CanonicalDecisionRecord) -> CanonicalDecisionRecord:
        with self._guard_io():
            data = self._read()
            data[record.decision_key] = record.model_dump(mode="json")
            self._write(data)
        return record

    def list_records(self) -> list[CanonicalDecisionRecord]:
        with self._guard_io():
            data = self._read()
        return [CanonicalDecisionRecord.model_validate(row) for row in data.values()]
