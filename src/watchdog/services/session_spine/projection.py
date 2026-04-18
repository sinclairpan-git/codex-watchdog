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
from watchdog.services.session_service.models import SessionEventRecord
from watchdog.services.session_spine.approval_visibility import (
    actionable_approval_count,
    has_rejectable_approval,
)
from watchdog.services.session_spine.task_state import is_terminal_task


def stable_thread_id_for_project(project_id: str) -> str:
    return f"session:{project_id}"


_SESSION_SERVICE_FACT_SPECS: dict[str, dict[str, str]] = {
    "memory_unavailable_degraded": {
        "fact_kind": "risk",
        "severity": "warning",
        "summary": "memory unavailable in degraded mode",
    },
    "memory_conflict_detected": {
        "fact_kind": "risk",
        "severity": "warning",
        "summary": "memory conflict detected",
    },
    "human_override_recorded": {
        "fact_kind": "action",
        "severity": "info",
        "summary": "human override recorded",
    },
    "notification_announced": {
        "fact_kind": "advisory",
        "severity": "info",
        "summary": "notification announced",
    },
    "notification_delivery_succeeded": {
        "fact_kind": "action",
        "severity": "info",
        "summary": "notification delivered",
    },
    "notification_delivery_failed": {
        "fact_kind": "risk",
        "severity": "warning",
        "summary": "notification delivery failed",
    },
    "notification_requeued": {
        "fact_kind": "advisory",
        "severity": "warning",
        "summary": "notification requeued",
    },
    "notification_receipt_recorded": {
        "fact_kind": "action",
        "severity": "info",
        "summary": "notification receipt recorded",
    },
    "interaction_context_superseded": {
        "fact_kind": "advisory",
        "severity": "warning",
        "summary": "interaction context superseded",
    },
    "interaction_window_expired": {
        "fact_kind": "risk",
        "severity": "warning",
        "summary": "interaction window expired",
    },
}


def _task_value(task: dict[str, Any] | None, key: str, default: Any) -> Any:
    if not isinstance(task, dict):
        return default
    value = task.get(key)
    if value in (None, ""):
        return default
    return value


def _approval_text(approval: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = approval.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _approval_nested_text(approval: dict[str, Any], *keys: str) -> str:
    direct = _approval_text(approval, *keys)
    if direct:
        return direct
    decision = approval.get("decision")
    if not isinstance(decision, dict):
        return ""
    return _approval_text(decision, *keys)


def _approval_native_thread_id(approval: dict[str, Any]) -> str | None:
    native_thread_id = _approval_text(approval, "native_thread_id")
    if native_thread_id:
        return native_thread_id
    thread_id = _approval_text(approval, "thread_id")
    if thread_id.startswith("session:"):
        return None
    return thread_id or None


def _event_sort_key(event: SessionEventRecord) -> tuple[str, int, str, str]:
    return (
        "0" if event.log_seq is not None else "1",
        event.log_seq or 0,
        event.occurred_at,
        event.event_id,
    )


def _session_event_detail(event: SessionEventRecord) -> str:
    payload = event.payload
    event_type = event.event_type
    if event_type == "memory_unavailable_degraded":
        fallback_mode = str(payload.get("fallback_mode") or "").strip()
        degradation_reason = str(payload.get("degradation_reason") or "").strip()
        return (
            f"fallback_mode={fallback_mode or 'unknown'} "
            f"reason={degradation_reason or 'unknown'}"
        )
    if event_type == "memory_conflict_detected":
        conflict_reason = str(payload.get("conflict_reason") or "").strip()
        resolution = str(payload.get("resolution") or "").strip()
        return (
            f"conflict_reason={conflict_reason or 'unknown'} "
            f"resolution={resolution or 'unknown'}"
        )
    if event_type == "human_override_recorded":
        response_action = str(payload.get("response_action") or "").strip()
        approval_status = str(payload.get("approval_status") or "").strip()
        execution_effect = str(payload.get("execution_effect") or "").strip()
        return (
            f"response_action={response_action or 'unknown'} "
            f"approval_status={approval_status or 'unknown'} "
            f"execution_effect={execution_effect or 'unknown'}"
        )
    if event_type.startswith("notification_"):
        delivery_status = str(payload.get("delivery_status") or "").strip()
        receipt_id = str(payload.get("receipt_id") or "").strip()
        return (
            f"delivery_status={delivery_status or 'unknown'} "
            f"receipt_id={receipt_id or 'unknown'}"
        )
    if event_type == "interaction_context_superseded":
        active_context = str(payload.get("active_interaction_context_id") or "").strip()
        return f"active_interaction_context_id={active_context or 'unknown'}"
    if event_type == "interaction_window_expired":
        expired_at = str(payload.get("expired_at") or "").strip()
        return f"expired_at={expired_at or 'unknown'}"
    return event.event_type


def build_session_service_fact_records(
    *,
    project_id: str,
    events: list[SessionEventRecord],
) -> list[FactRecord]:
    latest_by_type: dict[str, SessionEventRecord] = {}
    for event in sorted(events, key=_event_sort_key):
        if event.project_id != project_id:
            continue
        if event.event_type not in _SESSION_SERVICE_FACT_SPECS:
            continue
        latest_by_type[event.event_type] = event

    facts: list[FactRecord] = []
    for event in sorted(latest_by_type.values(), key=_event_sort_key):
        spec = _SESSION_SERVICE_FACT_SPECS[event.event_type]
        facts.append(
            FactRecord(
                fact_id=f"{project_id}:{event.event_type}:{event.event_id}",
                fact_code=event.event_type,
                fact_kind=spec["fact_kind"],
                severity=spec["severity"],
                summary=spec["summary"],
                detail=_session_event_detail(event),
                source="session_service",
                observed_at=event.occurred_at,
                related_ids=dict(event.related_ids),
            )
        )
    return facts


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
                native_thread_id=native_thread_id or _approval_native_thread_id(approval),
                risk_level=_approval_nested_text(approval, "risk_level", "risk_class") or None,
                command=_approval_nested_text(approval, "command", "requested_action"),
                reason=_approval_nested_text(approval, "reason", "summary", "decision_reason"),
                alternative=_approval_nested_text(approval, "alternative"),
                status=str(approval.get("status") or ""),
                requested_at=_approval_text(approval, "requested_at", "created_at"),
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
                native_thread_id=_approval_native_thread_id(approval),
                risk_level=_approval_nested_text(approval, "risk_level", "risk_class") or None,
                command=_approval_nested_text(approval, "command", "requested_action"),
                reason=_approval_nested_text(approval, "reason", "summary", "decision_reason"),
                alternative=_approval_nested_text(approval, "alternative"),
                status=str(approval.get("status") or ""),
                requested_at=_approval_text(approval, "requested_at", "created_at"),
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
    recovery: dict[str, Any] | None = None,
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
        recovery_outcome=str((recovery or {}).get("recovery_outcome") or "") or None,
        recovery_status=str((recovery or {}).get("recovery_status") or "") or None,
        recovery_updated_at=str((recovery or {}).get("recovery_updated_at") or "") or None,
        recovery_child_session_id=str((recovery or {}).get("recovery_child_session_id") or "") or None,
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
    is_terminal: bool,
    pending_approval_count: int,
    can_reject_approval: bool,
    fact_codes: set[str],
) -> list[str]:
    intents = ["get_session"]
    if has_task and not is_terminal:
        intents.append("continue_session")
    if pending_approval_count > 0:
        intents.extend(["list_pending_approvals", "approve_approval"])
        if can_reject_approval:
            intents.append("reject_approval")
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
    pending_approval_count = actionable_approval_count(approvals)
    can_reject_approval = has_rejectable_approval(approvals)
    terminal = "task_completed" in fact_codes or (
        pending_approval_count == 0 and is_terminal_task(task)
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
            is_terminal=terminal,
            pending_approval_count=pending_approval_count,
            can_reject_approval=can_reject_approval,
            fact_codes=fact_codes,
        ),
    )
