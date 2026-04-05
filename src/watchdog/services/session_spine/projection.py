from __future__ import annotations

from typing import Any

from watchdog.contracts.session_spine.enums import AttentionState, SessionState
from watchdog.contracts.session_spine.models import (
    ApprovalProjection,
    FactRecord,
    SessionProjection,
    TaskProgressView,
    WorkspaceActivityView,
)


def stable_thread_id_for_project(project_id: str) -> str:
    return f"session:{project_id}"


def _task_value(task: dict[str, Any] | None, key: str, default: Any) -> Any:
    if not isinstance(task, dict):
        return default
    value = task.get(key)
    if value in (None, ""):
        return default
    return value


def build_approval_projections(
    *,
    project_id: str,
    native_thread_id: str | None,
    approvals: list[dict[str, Any]],
) -> list[ApprovalProjection]:
    projections: list[ApprovalProjection] = []
    for approval in approvals:
        projections.append(
            ApprovalProjection(
                approval_id=str(approval.get("approval_id") or ""),
                project_id=project_id,
                thread_id=stable_thread_id_for_project(project_id),
                native_thread_id=native_thread_id or str(approval.get("thread_id") or "") or None,
                risk_level=str(approval.get("risk_level") or "") or None,
                command=str(approval.get("command") or ""),
                reason=str(approval.get("reason") or ""),
                alternative=str(approval.get("alternative") or ""),
                status=str(approval.get("status") or ""),
                requested_at=str(approval.get("requested_at") or ""),
                decided_at=str(approval.get("decided_at") or "") or None,
                decided_by=str(approval.get("decided_by") or "") or None,
            )
        )
    return projections


def build_approval_inbox_projections(
    *,
    approvals: list[dict[str, Any]],
) -> list[ApprovalProjection]:
    projections: list[ApprovalProjection] = []
    for approval in approvals:
        project_id = str(approval.get("project_id") or "")
        projections.append(
            ApprovalProjection(
                approval_id=str(approval.get("approval_id") or ""),
                project_id=project_id,
                thread_id=stable_thread_id_for_project(project_id),
                native_thread_id=str(approval.get("thread_id") or "") or None,
                risk_level=str(approval.get("risk_level") or "") or None,
                command=str(approval.get("command") or ""),
                reason=str(approval.get("reason") or ""),
                alternative=str(approval.get("alternative") or ""),
                status=str(approval.get("status") or ""),
                requested_at=str(approval.get("requested_at") or ""),
                decided_at=str(approval.get("decided_at") or "") or None,
                decided_by=str(approval.get("decided_by") or "") or None,
            )
        )
    return projections


def build_task_progress_view(
    *,
    project_id: str,
    task: dict[str, Any] | None,
    facts: list[FactRecord],
) -> TaskProgressView:
    stable_thread_id = stable_thread_id_for_project(project_id)
    return TaskProgressView(
        project_id=project_id,
        thread_id=stable_thread_id,
        native_thread_id=str(_task_value(task, "thread_id", "")) or None,
        activity_phase=str(_task_value(task, "phase", "unknown")),
        summary=str(_task_value(task, "last_summary", "")),
        files_touched=[
            str(path)
            for path in _task_value(task, "files_touched", [])
            if isinstance(path, str) and path
        ],
        context_pressure=str(_task_value(task, "context_pressure", "unknown")),
        stuck_level=int(_task_value(task, "stuck_level", 0)),
        primary_fact_codes=[fact.fact_code for fact in facts],
        blocker_fact_codes=[fact.fact_code for fact in facts if fact.fact_kind == "blocker"],
        last_progress_at=str(_task_value(task, "last_progress_at", "")) or None,
    )


def build_workspace_activity_view(
    *,
    project_id: str,
    task: dict[str, Any] | None,
    activity: dict[str, Any],
) -> WorkspaceActivityView:
    stable_thread_id = stable_thread_id_for_project(project_id)
    return WorkspaceActivityView(
        project_id=project_id,
        thread_id=stable_thread_id,
        native_thread_id=str(_task_value(task, "thread_id", "")) or None,
        recent_window_minutes=int(activity.get("recent_window_minutes") or 15),
        cwd_exists=bool(activity.get("cwd_exists")),
        files_scanned=int(activity.get("files_scanned") or 0),
        latest_mtime_iso=str(activity.get("latest_mtime_iso") or "") or None,
        recent_change_count=int(activity.get("recent_change_count") or 0),
    )


def _build_available_intents(
    *,
    has_task: bool,
    pending_approval_count: int,
    fact_codes: set[str],
) -> list[str]:
    intents = ["get_session"]
    if has_task:
        intents.append("continue_session")
    if pending_approval_count > 0:
        intents.extend(
            [
                "list_pending_approvals",
                "approve_approval",
                "reject_approval",
            ]
        )
    if fact_codes.intersection({"stuck_no_progress", "repeat_failure", "context_critical"}):
        intents.extend(["why_stuck", "explain_blocker", "request_recovery"])
        if "context_critical" in fact_codes:
            intents.append("execute_recovery")
    elif fact_codes.intersection({"approval_pending", "awaiting_human_direction"}):
        intents.extend(["why_stuck", "explain_blocker"])
    return intents


def build_session_projection(
    *,
    project_id: str,
    task: dict[str, Any] | None,
    approvals: list[dict[str, Any]],
    facts: list[FactRecord],
) -> SessionProjection:
    stable_thread_id = stable_thread_id_for_project(project_id)
    fact_codes = {fact.fact_code for fact in facts}
    pending_approval_count = sum(
        1 for approval in approvals if str(approval.get("status") or "").lower() == "pending"
    )

    session_state = SessionState.ACTIVE
    attention_state = AttentionState.NORMAL
    headline = str(_task_value(task, "last_summary", "session active"))

    if "control_link_error" in fact_codes:
        session_state = SessionState.UNAVAILABLE
        attention_state = AttentionState.UNREACHABLE
        headline = "control link unavailable"
    elif fact_codes.intersection({"approval_pending", "awaiting_human_direction"}):
        session_state = SessionState.AWAITING_APPROVAL
        attention_state = AttentionState.NEEDS_HUMAN
        headline = str(_task_value(task, "last_summary", "waiting for approval"))
    elif fact_codes.intersection({"stuck_no_progress", "repeat_failure", "context_critical"}):
        session_state = SessionState.BLOCKED
        attention_state = AttentionState.CRITICAL
        headline = str(_task_value(task, "last_summary", "session blocked"))

    return SessionProjection(
        project_id=project_id,
        thread_id=stable_thread_id,
        native_thread_id=str(_task_value(task, "thread_id", "")) or None,
        session_state=session_state,
        activity_phase=str(_task_value(task, "phase", "unknown")),
        attention_state=attention_state,
        headline=headline,
        pending_approval_count=pending_approval_count,
        available_intents=_build_available_intents(
            has_task=isinstance(task, dict),
            pending_approval_count=pending_approval_count,
            fact_codes=fact_codes,
        ),
    )
