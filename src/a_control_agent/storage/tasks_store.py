from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from a_control_agent.audit import append_jsonl


class TaskRecord(dict[str, Any]):
    """单条任务记录（与 PRD §6.3 字段对齐的最小子集）。"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskStore:
    """文件型 JSON 持久化：project_id → 任务快照。"""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._audit_path = path.parent / "audit.jsonl"
        self._events_path = path.parent / "task_events.jsonl"
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

    def count_projects(self) -> int:
        with self._lock:
            return len(self._read())

    def get(self, project_id: str) -> TaskRecord | None:
        with self._lock:
            data = self._read()
            row = data.get(project_id)
            return TaskRecord(row) if row else None

    def upsert_from_create(self, project_id: str, body: dict[str, Any]) -> TaskRecord:
        with self._lock:
            data = self._read()
            thread_id = f"thr_{uuid.uuid4().hex[:16]}"
            now = _now_iso()
            rec: dict[str, Any] = {
                "project_id": project_id,
                "thread_id": thread_id,
                "cwd": body.get("cwd", ""),
                "task_title": body.get("task_title", ""),
                "task_prompt": body.get("task_prompt", ""),
                "model": body.get("model", ""),
                "sandbox": body.get("sandbox", ""),
                "approval_policy": body.get("approval_policy", ""),
                "status": "running",
                "phase": "planning",
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_summary": "",
                "files_touched": [],
                "pending_approval": False,
                "approval_risk": None,
                "last_error_signature": None,
                "last_progress_at": now,
            }
            data[project_id] = rec
            self._write(data)
            return TaskRecord(rec)

    def apply_steer(
        self,
        project_id: str,
        *,
        message: str,
        source: str,
        reason: str,
        stuck_level: int | None = None,
    ) -> TaskRecord | None:
        with self._lock:
            data = self._read()
            rec = data.get(project_id)
            if rec is None:
                return None
            now = _now_iso()
            rec["last_summary"] = f"[steer:{reason}] {message}"[:4000]
            rec["last_progress_at"] = now
            if stuck_level is not None:
                rec["stuck_level"] = int(stuck_level)
            data[project_id] = rec
            self._write(data)

        ev = {
            "event_id": f"evt_{uuid.uuid4().hex[:12]}",
            "project_id": project_id,
            "thread_id": rec.get("thread_id", ""),
            "event_type": "steer",
            "event_source": source,
            "payload_json": {"message": message, "reason": reason},
            "ts": now,
        }
        append_jsonl(self._events_path, ev)
        append_jsonl(
            self._audit_path,
            {
                "ts": now,
                "project_id": project_id,
                "action": "steer_injected",
                "reason": reason,
                "source": "a_control_agent",
                "payload": {"message": message[:500], "steer_source": source},
            },
        )
        return TaskRecord(rec)

    def record_error_repeat(self, project_id: str, signature: str) -> TaskRecord | None:
        with self._lock:
            data = self._read()
            rec = data.get(project_id)
            if rec is None:
                return None
            prev = rec.get("last_error_signature")
            if prev == signature:
                rec["failure_count"] = int(rec.get("failure_count", 0)) + 1
            else:
                rec["failure_count"] = 1
            rec["last_error_signature"] = signature
            now = _now_iso()
            rec["last_progress_at"] = now
            data[project_id] = rec
            self._write(data)

        append_jsonl(
            self._audit_path,
            {
                "ts": _now_iso(),
                "project_id": project_id,
                "action": "loop_escalation",
                "reason": "error_repeat",
                "source": "a_control_agent",
                "payload": {"signature": signature, "failure_count": rec["failure_count"]},
            },
        )
        return TaskRecord(rec)

    def merge_update(self, project_id: str, fields: dict[str, Any]) -> TaskRecord | None:
        with self._lock:
            data = self._read()
            rec = data.get(project_id)
            if rec is None:
                return None
            rec.update(fields)
            rec["last_progress_at"] = _now_iso()
            data[project_id] = rec
            self._write(data)
            return TaskRecord(rec)
