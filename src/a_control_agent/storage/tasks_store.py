from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Any


class TaskRecord(dict[str, Any]):
    """单条任务记录（与 PRD §6.3 字段对齐的最小子集）。"""


class TaskStore:
    """文件型 JSON 持久化：project_id → 任务快照。"""

    def __init__(self, path: Path) -> None:
        self._path = path
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

    def get(self, project_id: str) -> TaskRecord | None:
        with self._lock:
            data = self._read()
            row = data.get(project_id)
            return TaskRecord(row) if row else None

    def upsert_from_create(self, project_id: str, body: dict[str, Any]) -> TaskRecord:
        with self._lock:
            data = self._read()
            thread_id = f"thr_{uuid.uuid4().hex[:16]}"
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
            }
            data[project_id] = rec
            self._write(data)
            return TaskRecord(rec)
