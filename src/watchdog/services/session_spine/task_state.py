from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _normalized(value: Any) -> str:
    return str(value or "").strip().lower()


def _parse_iso8601(value: Any) -> datetime | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _max_timestamp(*values: datetime | None) -> datetime | None:
    candidates = [value for value in values if value is not None]
    if not candidates:
        return None
    return max(candidates)


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

DEFAULT_ACTIVE_SESSION_STALE_AFTER_SECONDS = 3 * 24 * 60 * 60

_SESSION_DISCONNECT_ERROR_FRAGMENTS = (
    "broken pipe",
    "current working directory missing",
    "cwd missing",
    "no such file or directory",
    "session closed",
    "connection reset by peer",
)

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


def derive_project_execution_state_liveness_override(
    task: dict[str, Any] | None,
    *,
    project_execution_state: str,
    now: datetime | None = None,
    stale_after_seconds: float = DEFAULT_ACTIVE_SESSION_STALE_AFTER_SECONDS,
) -> str:
    normalized_state = _normalized(project_execution_state)
    if not isinstance(task, dict):
        return normalized_state or "unknown"
    if normalized_state in _NON_ACTIVE_PROJECT_EXECUTION_STATES:
        return normalized_state

    task_status = normalize_task_status(task)
    if task_status in {"completed", "failed", "paused"}:
        return normalized_state or "unknown"

    claims_live_session = bool(str(task.get("native_thread_id") or task.get("thread_id") or "").strip())
    if not claims_live_session and normalized_state not in {"active", "unknown", ""}:
        return normalized_state

    workspace_cwd_exists = task.get("workspace_cwd_exists")
    if claims_live_session and workspace_cwd_exists is False:
        return "paused"

    current = now or datetime.now(UTC)
    manual_activity_at = _max_timestamp(
        _parse_iso8601(task.get("last_local_manual_activity_at")),
        _parse_iso8601(task.get("last_substantive_user_input_at")),
    )
    progress_at = _parse_iso8601(task.get("last_progress_at"))
    workspace_latest_mtime_at = _parse_iso8601(task.get("workspace_latest_mtime_iso"))
    workspace_recent_change_count = int(task.get("workspace_recent_change_count", 0) or 0)
    latest_activity_at = _max_timestamp(manual_activity_at, progress_at)
    runtime_task_missing = bool(task.get("runtime_task_missing"))

    if runtime_task_missing:
        return "paused"

    if (
        claims_live_session
        and workspace_latest_mtime_at is not None
        and progress_at is not None
        and workspace_recent_change_count <= 0
        and progress_at > workspace_latest_mtime_at
        and (progress_at - workspace_latest_mtime_at).total_seconds() > stale_after_seconds
        and (
            manual_activity_at is None
            or manual_activity_at <= workspace_latest_mtime_at
            or (current - manual_activity_at).total_seconds() > stale_after_seconds
        )
    ):
        return "paused"

    if latest_activity_at is not None:
        idle_seconds = max((current - latest_activity_at).total_seconds(), 0.0)
        if normalized_state == "active" and idle_seconds > stale_after_seconds:
            return "paused"

    manual_idle_seconds = None
    if manual_activity_at is not None:
        manual_idle_seconds = max((current - manual_activity_at).total_seconds(), 0.0)

    last_error_signature = _normalized(task.get("last_error_signature"))
    if (
        claims_live_session
        and any(fragment in last_error_signature for fragment in _SESSION_DISCONNECT_ERROR_FRAGMENTS)
        and (manual_idle_seconds is None or manual_idle_seconds > stale_after_seconds)
    ):
        # Do not let stale runtime progress timestamps keep a disconnected session active.
        return "paused"

    return normalized_state or "unknown"


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
        if source_status in {
            "created",
            "running",
            "waiting_for_direction",
            "waiting_for_approval",
            "stuck",
        }:
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
