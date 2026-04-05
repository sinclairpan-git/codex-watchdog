from __future__ import annotations

from watchdog.contracts.session_spine.enums import ReplyCode, ReplyKind
from watchdog.contracts.session_spine.models import ReplyModel
from watchdog.services.session_spine.service import (
    ApprovalInboxReadBundle,
    SessionDirectoryReadBundle,
    SessionReadBundle,
)


def build_session_reply(
    bundle: SessionReadBundle,
    *,
    intent_code: str = "get_session",
) -> ReplyModel:
    return ReplyModel(
        reply_kind=ReplyKind.SESSION,
        reply_code=ReplyCode.SESSION_PROJECTION,
        intent_code=intent_code,
        message=bundle.session.headline,
        session=bundle.session,
        facts=bundle.facts,
    )


def build_session_directory_reply(bundle: SessionDirectoryReadBundle) -> ReplyModel:
    return ReplyModel(
        reply_kind=ReplyKind.SESSION,
        reply_code=ReplyCode.SESSION_DIRECTORY,
        intent_code="list_sessions",
        message=f"{len(bundle.sessions)} session(s)",
        sessions=bundle.sessions,
    )


def build_progress_reply(bundle: SessionReadBundle) -> ReplyModel:
    return ReplyModel(
        reply_kind=ReplyKind.SESSION,
        reply_code=ReplyCode.TASK_PROGRESS_VIEW,
        intent_code="get_progress",
        message=bundle.progress.summary or bundle.session.headline,
        progress=bundle.progress,
        facts=bundle.facts,
    )


def build_approval_queue_reply(bundle: SessionReadBundle) -> ReplyModel:
    return ReplyModel(
        reply_kind=ReplyKind.APPROVALS,
        reply_code=ReplyCode.APPROVAL_QUEUE,
        intent_code="list_pending_approvals",
        message=f"{len(bundle.approval_queue)} pending approval(s)",
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
        message=message,
        session=bundle.session,
        progress=bundle.progress,
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
        message=message,
        session=bundle.session,
        progress=bundle.progress,
        facts=bundle.facts,
    )
