from __future__ import annotations

from watchdog.contracts.session_spine.enums import ReplyCode, ReplyKind
from watchdog.contracts.session_spine.models import ReplyModel, SessionEvent
from watchdog.services.session_spine.service import (
    ApprovalInboxReadBundle,
    SessionDirectoryReadBundle,
    SessionReadBundle,
    WorkspaceActivityReadBundle,
)


def _display_thread_id(thread_id: str | None) -> str:
    normalized = str(thread_id or "").strip()
    if normalized.startswith("session:"):
        return normalized.removeprefix("session:")
    return normalized


def _render_recovery_summary(progress) -> str | None:
    outcome = str(progress.recovery_outcome or "").strip()
    status = str(progress.recovery_status or "").strip()
    child_session_id = _display_thread_id(progress.recovery_child_session_id)
    if outcome == "same_thread_resume":
        return "原线程续跑"
    if outcome == "new_child_session":
        if child_session_id:
            return f"新子会话 {child_session_id}"
        return "新子会话"
    if outcome == "resume_failed":
        if status:
            return f"恢复失败({status})"
        return "恢复失败"
    if outcome:
        if status:
            return f"{outcome}({status})"
        return outcome
    if status:
        return status
    return None


def _render_decision_summary(progress) -> str | None:
    reason = str(progress.decision_degrade_reason or "").strip()
    schema_ref = str(progress.provider_output_schema_ref or "").strip()
    if reason == "provider_output_invalid":
        if schema_ref:
            return f"provider降级({schema_ref})"
        return "provider降级"
    if reason and schema_ref:
        return f"{reason}({schema_ref})"
    if reason:
        return reason
    if schema_ref:
        return schema_ref
    return None


def _render_goal_summary(progress) -> str | None:
    goal = str(progress.current_phase_goal or "").strip()
    if goal:
        return goal
    last_instruction = str(progress.last_user_instruction or "").strip()
    return last_instruction or None


def _render_recovery_suppression_summary(progress) -> str | None:
    reason = str(progress.recovery_suppression_reason or "").strip()
    if reason == "reentry_without_newer_progress":
        return "等待新进展"
    if reason == "recovery_in_flight":
        return "恢复进行中"
    if reason == "cooldown_window_active":
        return "恢复冷却中"
    return reason or None


def _append_progress_annotations(
    message: str,
    progress,
    *,
    include_goal_summary: bool = False,
) -> str:
    enriched = message
    goal_summary = _render_goal_summary(progress) if include_goal_summary else None
    if goal_summary:
        enriched = f"{enriched} | 当前目标={goal_summary}"
    recovery_summary = _render_recovery_summary(progress)
    if recovery_summary:
        enriched = f"{enriched} | 恢复={recovery_summary}"
    suppression_summary = _render_recovery_suppression_summary(progress)
    if suppression_summary:
        enriched = f"{enriched} | 恢复抑制={suppression_summary}"
    decision_summary = _render_decision_summary(progress)
    if decision_summary:
        enriched = f"{enriched} | 决策={decision_summary}"
    return enriched


def _build_session_directory_message(bundle: SessionDirectoryReadBundle) -> str:
    count = len(bundle.progresses) if bundle.progresses else len(bundle.sessions)
    lines = [f"多项目进展（{count}）"]
    if bundle.progresses:
        for progress in bundle.progresses:
            line = (
                f"- {progress.project_id} | {progress.activity_phase} | {progress.summary} "
                f"| 上下文={progress.context_pressure}"
            )
            line = _append_progress_annotations(
                line,
                progress,
                include_goal_summary=True,
            )
            lines.append(line)
        return "\n".join(lines)
    for session in bundle.sessions:
        lines.append(
            f"- {session.project_id} | {session.activity_phase} | {session.headline}"
        )
    return "\n".join(lines)


def build_session_reply(
    bundle: SessionReadBundle,
    *,
    intent_code: str = "get_session",
) -> ReplyModel:
    return ReplyModel(
        reply_kind=ReplyKind.SESSION,
        reply_code=ReplyCode.SESSION_PROJECTION,
        intent_code=intent_code,
        message=_append_progress_annotations(
            bundle.session.headline,
            bundle.progress,
            include_goal_summary=True,
        ),
        session=bundle.session,
        progress=bundle.progress,
        snapshot=bundle.snapshot,
        facts=bundle.facts,
    )


def build_session_directory_reply(bundle: SessionDirectoryReadBundle) -> ReplyModel:
    return ReplyModel(
        reply_kind=ReplyKind.SESSION,
        reply_code=ReplyCode.SESSION_DIRECTORY,
        intent_code="list_sessions",
        message=_build_session_directory_message(bundle),
        sessions=bundle.sessions,
        progresses=bundle.progresses,
        resident_expert_coverage=bundle.resident_expert_coverage,
    )


def build_session_event_snapshot_reply(events: list[SessionEvent]) -> ReplyModel:
    return ReplyModel(
        reply_kind=ReplyKind.EVENTS,
        reply_code=ReplyCode.SESSION_EVENT_SNAPSHOT,
        intent_code="list_session_events",
        message=f"{len(events)} event(s)",
        events=events,
    )


def build_progress_reply(bundle: SessionReadBundle) -> ReplyModel:
    return ReplyModel(
        reply_kind=ReplyKind.SESSION,
        reply_code=ReplyCode.TASK_PROGRESS_VIEW,
        intent_code="get_progress",
        message=_append_progress_annotations(
            bundle.progress.summary or bundle.session.headline,
            bundle.progress,
            include_goal_summary=True,
        ),
        progress=bundle.progress,
        snapshot=bundle.snapshot,
        facts=bundle.facts,
    )


def build_session_facts_reply(bundle: SessionReadBundle) -> ReplyModel:
    return ReplyModel(
        reply_kind=ReplyKind.FACTS,
        reply_code=ReplyCode.SESSION_FACTS,
        intent_code="list_session_facts",
        message=f"{len(bundle.facts)} fact(s)",
        snapshot=bundle.snapshot,
        facts=bundle.facts,
    )


def build_workspace_activity_reply(bundle: WorkspaceActivityReadBundle) -> ReplyModel:
    activity = bundle.workspace_activity
    if not activity.cwd_exists:
        message = "workspace directory unavailable"
    elif activity.recent_change_count > 0:
        message = (
            f"{activity.recent_change_count} recent workspace change(s) "
            f"in last {activity.recent_window_minutes} min"
        )
    else:
        message = f"no workspace changes detected in last {activity.recent_window_minutes} min"
    return ReplyModel(
        reply_kind=ReplyKind.SESSION,
        reply_code=ReplyCode.WORKSPACE_ACTIVITY_VIEW,
        intent_code="get_workspace_activity",
        message=message,
        session=bundle.session,
        workspace_activity=activity,
        facts=bundle.facts,
    )


def build_approval_queue_reply(bundle: SessionReadBundle) -> ReplyModel:
    return ReplyModel(
        reply_kind=ReplyKind.APPROVALS,
        reply_code=ReplyCode.APPROVAL_QUEUE,
        intent_code="list_pending_approvals",
        message=f"{len(bundle.approval_queue)} pending approval(s)",
        snapshot=bundle.snapshot,
        approvals=bundle.approval_queue,
        facts=bundle.facts,
    )


def build_approval_inbox_reply(bundle: ApprovalInboxReadBundle) -> ReplyModel:
    return ReplyModel(
        reply_kind=ReplyKind.APPROVALS,
        reply_code=ReplyCode.APPROVAL_INBOX,
        intent_code="list_approval_inbox",
        message=f"{len(bundle.approval_inbox)} pending approval(s)",
        approvals=bundle.approval_inbox,
    )


def build_stuck_explanation_reply(bundle: SessionReadBundle) -> ReplyModel:
    stuck_facts = [
        fact.summary
        for fact in bundle.facts
        if fact.fact_code in {"stuck_no_progress", "repeat_failure", "context_critical"}
    ]
    message = "; ".join(stuck_facts) if stuck_facts else "no current stuck signals"
    return ReplyModel(
        reply_kind=ReplyKind.EXPLANATION,
        reply_code=ReplyCode.STUCK_EXPLANATION,
        intent_code="why_stuck",
        message=_append_progress_annotations(
            message,
            bundle.progress,
            include_goal_summary=True,
        ),
        session=bundle.session,
        progress=bundle.progress,
        snapshot=bundle.snapshot,
        facts=bundle.facts,
    )


def build_blocker_explanation_reply(bundle: SessionReadBundle) -> ReplyModel:
    blocker_facts = [
        fact.summary
        for fact in bundle.facts
        if fact.fact_kind in {"blocker", "availability"} or fact.fact_code == "control_link_error"
    ]
    message = "; ".join(blocker_facts) if blocker_facts else "no current blockers"
    return ReplyModel(
        reply_kind=ReplyKind.EXPLANATION,
        reply_code=ReplyCode.BLOCKER_EXPLANATION,
        intent_code="explain_blocker",
        message=_append_progress_annotations(
            message,
            bundle.progress,
            include_goal_summary=True,
        ),
        session=bundle.session,
        progress=bundle.progress,
        snapshot=bundle.snapshot,
        facts=bundle.facts,
    )
