from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from watchdog.services.session_spine.store import PersistedSessionRecord


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decision_id_for_key(decision_key: str) -> str:
    digest = hashlib.sha256(decision_key.encode("utf-8")).hexdigest()[:16]
    return f"decision:{digest}"


def build_decision_key(
    *,
    session_id: str,
    fact_snapshot_version: str,
    policy_version: str,
    decision_result: str,
    action_ref: str,
    approval_id: str | None,
) -> str:
    return "|".join(
        [
            session_id,
            fact_snapshot_version,
            policy_version,
            decision_result,
            action_ref,
            approval_id or "",
        ]
    )


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
    evidence: dict[str, Any] = Field(default_factory=dict)


def build_canonical_decision_record(
    *,
    persisted_record: PersistedSessionRecord,
    decision_result: str,
    risk_class: str,
    action_ref: str,
    matched_policy_rules: list[str],
    decision_reason: str,
    why_not_escalated: str | None,
    why_escalated: str | None,
    uncertainty_reasons: list[str],
    policy_version: str,
    trigger: str = "resident_supervision",
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
        action_ref=action_ref,
        approval_id=approval_id,
    )
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
        evidence={
            "facts": [fact.model_dump(mode="json") for fact in persisted_record.facts],
            "matched_policy_rules": list(matched_policy_rules),
            "risk_class": risk_class,
            "decision": {
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
        },
    )


class PolicyDecisionStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._write({})

    def _read(self) -> dict[str, dict[str, Any]]:
        raw = self._path.read_text(encoding="utf-8")
        data = json.loads(raw) if raw.strip() else {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def get(self, decision_key: str) -> CanonicalDecisionRecord | None:
        with self._lock:
            row = self._read().get(decision_key)
        if not isinstance(row, dict):
            return None
        return CanonicalDecisionRecord.model_validate(row)

    def put(self, record: CanonicalDecisionRecord) -> CanonicalDecisionRecord:
        with self._lock:
            data = self._read()
            existing = data.get(record.decision_key)
            if isinstance(existing, dict):
                return CanonicalDecisionRecord.model_validate(existing)
            data[record.decision_key] = record.model_dump(mode="json")
            self._write(data)
        return record

    def list_records(self) -> list[CanonicalDecisionRecord]:
        with self._lock:
            data = self._read()
        return [CanonicalDecisionRecord.model_validate(row) for row in data.values()]
