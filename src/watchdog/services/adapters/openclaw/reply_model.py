from __future__ import annotations

from watchdog.contracts.session_spine.enums import ReplyCode, ReplyKind
from watchdog.contracts.session_spine.models import ReplyModel, WatchdogActionResult
from watchdog.services.session_spine.replies import (
    build_approval_inbox_reply as build_approval_inbox_read_reply,
)
from watchdog.services.session_spine.replies import (
    build_approval_queue_reply as build_approval_queue_read_reply,
)
from watchdog.services.session_spine.replies import (
    build_blocker_explanation_reply as build_blocker_explanation_read_reply,
)
from watchdog.services.session_spine.replies import (
    build_session_facts_reply as build_session_facts_read_reply,
)
from watchdog.services.session_spine.replies import (
    build_session_event_snapshot_reply as build_session_event_snapshot_read_reply,
)
from watchdog.services.session_spine.replies import build_progress_reply as build_progress_read_reply
from watchdog.services.session_spine.replies import (
    build_session_directory_reply as build_session_directory_read_reply,
)
from watchdog.services.session_spine.replies import build_session_reply as build_session_read_reply
from watchdog.services.session_spine.replies import (
    build_stuck_explanation_reply as build_stuck_explanation_read_reply,
)
from watchdog.services.session_spine.replies import (
    build_workspace_activity_reply as build_workspace_activity_read_reply,
)
from watchdog.services.session_spine.service import (
    ApprovalInboxReadBundle,
    SessionDirectoryReadBundle,
    SessionReadBundle,
    WorkspaceActivityReadBundle,
)
from watchdog.contracts.session_spine.models import SessionEvent


def _render_action_hint(*, intent_code: str, available_intents: list[str]) -> str | None:
    intents = set(available_intents)
    hints: list[str] = []

    if "list_pending_approvals" in intents and intent_code != "list_pending_approvals":
        hints.append("审批列表")

    if "approve_approval" in intents:
        if "reject_approval" in intents:
            hints.append("回复同意/拒绝")
        else:
            hints.append("回复同意")

    if "explain_blocker" in intents and intent_code != "explain_blocker":
        hints.append("卡在哪里")

    if "why_stuck" in intents and intent_code != "why_stuck" and "卡在哪里" not in hints:
        hints.append("为什么卡住")

    if not hints:
        return None
    return "、".join(hints)


def _with_action_hint(reply: ReplyModel, *, available_intents: list[str]) -> ReplyModel:
    hint = _render_action_hint(intent_code=reply.intent_code, available_intents=available_intents)
    if not hint or " | 下一步=" in reply.message:
        return reply
    return reply.model_copy(update={"message": f"{reply.message} | 下一步={hint}"})


def _with_directory_action_hints(reply: ReplyModel, *, bundle: SessionDirectoryReadBundle) -> ReplyModel:
    if not reply.message or " | 下一步=" in reply.message:
        return reply

    session_intents = {
        session.project_id: session.available_intents for session in bundle.sessions
    }
    lines = reply.message.splitlines()
    if not lines:
        return reply

    enriched_lines = [lines[0]]
    progress_lines = lines[1:]
    for index, line in enumerate(progress_lines):
        if index >= len(bundle.progresses):
            enriched_lines.append(line)
            continue
        progress = bundle.progresses[index]
        hint = _render_action_hint(
            intent_code=reply.intent_code,
            available_intents=session_intents.get(progress.project_id, []),
        )
        if hint and " | 下一步=" not in line:
            line = f"{line} | 下一步={hint}"
        enriched_lines.append(line)
    return reply.model_copy(update={"message": "\n".join(enriched_lines)})


def build_session_reply(
    bundle: SessionReadBundle,
    *,
    intent_code: str = "get_session",
) -> ReplyModel:
    return _with_action_hint(
        build_session_read_reply(bundle, intent_code=intent_code),
        available_intents=bundle.session.available_intents,
    )


def build_session_directory_reply(bundle: SessionDirectoryReadBundle) -> ReplyModel:
    return _with_directory_action_hints(
        build_session_directory_read_reply(bundle),
        bundle=bundle,
    )


def build_session_event_snapshot_reply(events: list[SessionEvent]) -> ReplyModel:
    return build_session_event_snapshot_read_reply(events)


def build_progress_reply(bundle: SessionReadBundle) -> ReplyModel:
    return _with_action_hint(
        build_progress_read_reply(bundle),
        available_intents=bundle.session.available_intents,
    )


def build_session_facts_reply(bundle: SessionReadBundle) -> ReplyModel:
    return build_session_facts_read_reply(bundle)


def build_workspace_activity_reply(bundle: WorkspaceActivityReadBundle) -> ReplyModel:
    return build_workspace_activity_read_reply(bundle)


def build_approval_queue_reply(bundle: SessionReadBundle) -> ReplyModel:
    return _with_action_hint(
        build_approval_queue_read_reply(bundle),
        available_intents=bundle.session.available_intents,
    )


def build_approval_inbox_reply(bundle: ApprovalInboxReadBundle) -> ReplyModel:
    return build_approval_inbox_read_reply(bundle)


def build_stuck_explanation_reply(bundle: SessionReadBundle) -> ReplyModel:
    return _with_action_hint(
        build_stuck_explanation_read_reply(bundle),
        available_intents=bundle.session.available_intents,
    )


def build_blocker_explanation_reply(bundle: SessionReadBundle) -> ReplyModel:
    return _with_action_hint(
        build_blocker_explanation_read_reply(bundle),
        available_intents=bundle.session.available_intents,
    )


def build_action_reply(intent_code: str, result: WatchdogActionResult) -> ReplyModel:
    reply_kind = ReplyKind.ACTION_RESULT
    if result.reply_code == ReplyCode.RECOVERY_AVAILABILITY:
        reply_kind = ReplyKind.EXPLANATION
    return ReplyModel(
        reply_kind=reply_kind,
        reply_code=result.reply_code or ReplyCode.ACTION_RESULT,
        intent_code=intent_code,
        message=result.message,
        action_result=result,
        facts=result.facts,
    )


def build_control_link_error_reply(intent_code: str, message: str) -> ReplyModel:
    return ReplyModel(
        reply_kind=ReplyKind.EXPLANATION,
        reply_code=ReplyCode.CONTROL_LINK_ERROR,
        intent_code=intent_code,
        message=message,
    )


def build_action_not_available_reply(intent_code: str, message: str) -> ReplyModel:
    return ReplyModel(
        reply_kind=ReplyKind.ACTION_RESULT,
        reply_code=ReplyCode.ACTION_NOT_AVAILABLE,
        intent_code=intent_code,
        message=message,
    )


def build_unsupported_intent_reply(intent_code: str) -> ReplyModel:
    return ReplyModel(
        reply_kind=ReplyKind.EXPLANATION,
        reply_code=ReplyCode.UNSUPPORTED_INTENT,
        intent_code=intent_code,
        message=f"unsupported intent: {intent_code}",
    )
