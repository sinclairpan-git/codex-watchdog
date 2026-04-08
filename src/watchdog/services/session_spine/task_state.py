from __future__ import annotations

from typing import Any


def _normalized(value: Any) -> str:
    return str(value or "").strip().lower()


def is_terminal_task(task: dict[str, Any] | None) -> bool:
    if not isinstance(task, dict):
        return False
    status = _normalized(task.get("status"))
    phase = _normalized(task.get("phase"))
    if status == "completed":
        return True
    if phase != "done":
        return False
    if bool(task.get("pending_approval")):
        return False
    return True
