from __future__ import annotations

from typing import Any


def _normalized(value: Any) -> str:
    return str(value or "").strip().lower()


CANONICAL_TASK_STATUSES = {
    "created",
    "running",
    "waiting_for_direction",
    "waiting_for_approval",
    "stuck",
    "handoff_in_progress",
    "resuming",
    "paused",
    "completed",
    "failed",
}

CANONICAL_PROJECT_EXECUTION_STATES = {
    "active",
    "paused",
    "stopped",
    "branch_transition_in_progress",
    "completed",
    "archived",
    "closed",
    "unknown",
}

_NON_ACTIVE_PROJECT_EXECUTION_STATES = {
    "paused",
    "stopped",
    "branch_transition_in_progress",
    "completed",
    "archived",
    "closed",
}

CANONICAL_TASK_PHASES = {
    "planning",
    "code_reading",
    "editing_source",
    "editing_tests",
    "running_tests",
    "debugging",
    "summarizing",
    "handoff",
}

_LEGACY_PHASE_MAP = {
    "approval": "planning",
    "coding": "editing_source",
    "done": "summarizing",
    "recovery": "handoff",
}


def normalize_task_status(task: dict[str, Any] | None) -> str:
    if not isinstance(task, dict):
        return "created"
    status = _normalized(task.get("status"))
    phase = _normalized(task.get("phase"))
    pending_approval = bool(task.get("pending_approval"))

    if pending_approval:
        return "waiting_for_approval"
    if status in CANONICAL_TASK_STATUSES:
        return status
    if status in {"done", "complete"}:
        return "completed"
    if status in {"error", "failed", "resume_failed"}:
        return "failed"
    if pending_approval or status == "approval":
        return "waiting_for_approval"
    if status in {"waiting_human", "awaiting_human_direction"}:
        return "waiting_for_direction"
    if phase == "done":
        return "completed"
    return status or "created"


def normalize_task_phase(task: dict[str, Any] | None) -> str:
    if not isinstance(task, dict):
        return "planning"
    phase = _normalized(task.get("phase"))
    if phase in CANONICAL_TASK_PHASES:
        return phase
    return _LEGACY_PHASE_MAP.get(phase, phase or "planning")


def is_canonical_task_status(value: Any) -> bool:
    return _normalized(value) in CANONICAL_TASK_STATUSES


def is_canonical_task_phase(value: Any) -> bool:
    return _normalized(value) in CANONICAL_TASK_PHASES


def normalize_project_execution_state(task: dict[str, Any] | None) -> str:
    if not isinstance(task, dict):
        return "unknown"
    for key in ("project_execution_state", "execution_state", "project_status"):
        value = _normalized(task.get(key))
        if not value:
            continue
        if value in {"execute", "decompose", "design", "refine", "init", "initialized", "running"}:
            return "active"
        if value in {"complete", "completed"}:
            return "completed"
        if value in {"close", "closed"}:
            return "closed"
        if value in {"stop", "stopped"}:
            return "stopped"
        if value in CANONICAL_PROJECT_EXECUTION_STATES:
            return value
    return "unknown"


def is_non_active_project_execution_state(value: Any) -> bool:
    return _normalized(value) in _NON_ACTIVE_PROJECT_EXECUTION_STATES


def validate_action_transition(
    action: str,
    *,
    task: dict[str, Any] | None,
    has_human_guidance: bool = False,
    has_approval: bool = False,
    has_continuation: bool = False,
) -> dict[str, Any]:
    source_status = normalize_task_status(task)
    normalized_action = _normalized(action)

    def _reject() -> dict[str, Any]:
        return {
            "allowed": False,
            "target_status": source_status,
            "reason_code": "rejected_invalid_state",
        }

    if normalized_action == "continue":
        if source_status == "waiting_for_approval" and not has_approval:
            return _reject()
        if source_status == "waiting_for_direction" and not has_human_guidance:
            return _reject()
        if source_status in {"created", "running", "waiting_for_direction", "waiting_for_approval"}:
            return {
                "allowed": True,
                "target_status": "running",
                "reason_code": "continue",
            }
        return _reject()

    if normalized_action == "pause":
        if source_status in {
            "created",
            "running",
            "waiting_for_direction",
            "waiting_for_approval",
            "stuck",
            "resuming",
        }:
            return {"allowed": True, "target_status": "paused", "reason_code": "pause"}
        return _reject()

    if normalized_action == "resume":
        if source_status == "paused":
            return {"allowed": True, "target_status": "resuming", "reason_code": "resume"}
        if source_status == "handoff_in_progress" and has_continuation:
            return {"allowed": True, "target_status": "resuming", "reason_code": "resume"}
        return _reject()

    if normalized_action == "summarize":
        return {"allowed": True, "target_status": source_status, "reason_code": "summarize"}

    if normalized_action == "force_handoff":
        if source_status in {
            "running",
            "waiting_for_direction",
            "waiting_for_approval",
            "stuck",
            "paused",
        }:
            return {
                "allowed": True,
                "target_status": "handoff_in_progress",
                "reason_code": "force_handoff",
            }
        return _reject()

    if normalized_action == "retry_with_conservative_path":
        if source_status in {"running", "stuck"}:
            return {
                "allowed": True,
                "target_status": "running",
                "reason_code": "retry_with_conservative_path",
            }
        return _reject()

    return _reject()


def is_terminal_task(task: dict[str, Any] | None) -> bool:
    status = normalize_task_status(task)
    if status in {"completed", "failed"}:
        return True
    if not isinstance(task, dict):
        return False
    phase = _normalized(task.get("phase"))
    if phase != "done":
        return False
    if bool(task.get("pending_approval")):
        return False
    return True
