from __future__ import annotations

from watchdog.contracts.session_spine.enums import ReplyCode, ReplyKind
from watchdog.contracts.session_spine.models import ReplyModel, WatchdogActionResult
from watchdog.services.session_spine.replies import (
    build_approval_queue_reply as build_approval_queue_read_reply,
)
from watchdog.services.session_spine.replies import (
    build_blocker_explanation_reply as build_blocker_explanation_read_reply,
)
from watchdog.services.session_spine.replies import build_progress_reply as build_progress_read_reply
from watchdog.services.session_spine.replies import build_session_reply as build_session_read_reply
from watchdog.services.session_spine.replies import (
    build_stuck_explanation_reply as build_stuck_explanation_read_reply,
)
from watchdog.services.session_spine.service import SessionReadBundle


def build_session_reply(bundle: SessionReadBundle) -> ReplyModel:
    return build_session_read_reply(bundle)


def build_progress_reply(bundle: SessionReadBundle) -> ReplyModel:
    return build_progress_read_reply(bundle)


def build_approval_queue_reply(bundle: SessionReadBundle) -> ReplyModel:
    return build_approval_queue_read_reply(bundle)


def build_stuck_explanation_reply(bundle: SessionReadBundle) -> ReplyModel:
    return build_stuck_explanation_read_reply(bundle)


def build_blocker_explanation_reply(bundle: SessionReadBundle) -> ReplyModel:
    return build_blocker_explanation_read_reply(bundle)


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
