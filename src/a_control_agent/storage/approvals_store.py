from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from a_control_agent.audit import append_jsonl
from a_control_agent.risk.classifier import auto_approve_allowed, classify_risk


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ApprovalsStore:
    def __init__(self, path: Path, *, audit_path: Path | None = None) -> None:
        self._path = path
        self._audit_path = audit_path or path.parent / "approvals_audit.jsonl"
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._write({})

    def _read(self) -> dict[str, Any]:
        raw = self._path.read_text(encoding="utf-8")
        return json.loads(raw) if raw.strip() else {}

    def _write(self, data: dict[str, Any]) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def list_by_status(self, status: str | None) -> list[dict[str, Any]]:
        with self._lock:
            data = self._read()
        rows = list(data.values())
        if status:
            rows = [r for r in rows if r.get("status") == status]
        rows.sort(key=lambda r: r.get("requested_at", ""), reverse=True)
        return rows

    def get(self, approval_id: str) -> dict[str, Any] | None:
        with self._lock:
            data = self._read()
        return data.get(approval_id)

    def create_request(
        self,
        *,
        project_id: str,
        thread_id: str,
        command: str,
        reason: str,
        alternative: str = "",
        bridge_request_id: str | None = None,
    ) -> dict[str, Any]:
        risk = classify_risk(command)
        aid = f"appr_{uuid.uuid4().hex[:12]}"
        now = _now_iso()
        rec: dict[str, Any] = {
            "approval_id": aid,
            "project_id": project_id,
            "thread_id": thread_id,
            "risk_level": risk,
            "command": command,
            "reason": reason,
            "alternative": alternative,
            "bridge_request_id": bridge_request_id,
            "requested_at": now,
            "status": "pending",
            "decided_at": None,
            "decided_by": None,
            "callback_status": None,
            "callback_error": None,
        }
        if auto_approve_allowed(risk):
            rec["status"] = "approved"
            rec["decided_at"] = now
            rec["decided_by"] = "policy-auto"
        with self._lock:
            data = self._read()
            data[aid] = rec
            self._write(data)
        append_jsonl(
            self._audit_path,
            {
                "ts": now,
                "approval_id": aid,
                "action": "approval_created",
                "risk_level": risk,
                "auto": rec["decided_by"] == "policy-auto",
            },
        )
        return rec

    def mark_callback_deferred(
        self,
        approval_id: str,
        *,
        error: str = "",
    ) -> dict[str, Any] | None:
        return self._update_callback_status(
            approval_id,
            status="deferred",
            error=error,
        )

    def mark_callback_delivered(self, approval_id: str) -> dict[str, Any] | None:
        return self._update_callback_status(
            approval_id,
            status="delivered",
            error="",
        )

    def _update_callback_status(
        self,
        approval_id: str,
        *,
        status: str,
        error: str,
    ) -> dict[str, Any] | None:
        with self._lock:
            data = self._read()
            rec = data.get(approval_id)
            if rec is None:
                return None
            rec["callback_status"] = status
            rec["callback_error"] = error or None
            rec["callback_updated_at"] = _now_iso()
            data[approval_id] = rec
            self._write(data)
        append_jsonl(
            self._audit_path,
            {
                "ts": _now_iso(),
                "approval_id": approval_id,
                "action": "approval_callback_status_updated",
                "callback_status": status,
                "callback_error": error or None,
            },
        )
        return rec

    def apply_decision(
        self,
        approval_id: str,
        *,
        decision: str,
        operator: str,
        note: str = "",
    ) -> dict[str, Any] | None:
        with self._lock:
            data = self._read()
            rec = data.get(approval_id)
            if rec is None:
                return None
            if rec.get("status") != "pending":
                return None
            now = _now_iso()
            if decision == "approve":
                rec["status"] = "approved"
            elif decision == "reject":
                rec["status"] = "rejected"
            else:
                return None
            rec["decided_at"] = now
            rec["decided_by"] = operator
            if note:
                rec["decision_note"] = note
            data[approval_id] = rec
            self._write(data)
        append_jsonl(
            self._audit_path,
            {
                "ts": now,
                "approval_id": approval_id,
                "action": "approval_decided",
                "decision": decision,
                "operator": operator,
            },
        )
        return rec
