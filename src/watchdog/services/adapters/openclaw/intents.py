from __future__ import annotations

from watchdog.contracts.session_spine.enums import ActionCode

READ_INTENTS = {
    "list_sessions",
    "list_session_events",
    "get_session",
    "get_session_by_native_thread",
    "get_progress",
    "list_session_facts",
    "get_workspace_activity",
    "why_stuck",
    "explain_blocker",
    "list_pending_approvals",
    "list_approval_inbox",
}

GLOBAL_READ_INTENTS = {
    "list_sessions",
    "list_approval_inbox",
}

RECEIPT_INTENTS = {"get_action_receipt"}

WRITE_INTENT_TO_ACTION = {
    "continue_session": ActionCode.CONTINUE_SESSION,
    "pause_session": ActionCode.PAUSE_SESSION,
    "resume_session": ActionCode.RESUME_SESSION,
    "summarize_session": ActionCode.SUMMARIZE_SESSION,
    "force_handoff": ActionCode.FORCE_HANDOFF,
    "retry_with_conservative_path": ActionCode.RETRY_WITH_CONSERVATIVE_PATH,
    "post_operator_guidance": ActionCode.POST_OPERATOR_GUIDANCE,
    "request_recovery": ActionCode.REQUEST_RECOVERY,
    "execute_recovery": ActionCode.EXECUTE_RECOVERY,
    "evaluate_supervision": ActionCode.EVALUATE_SUPERVISION,
    "approve_approval": ActionCode.APPROVE_APPROVAL,
    "reject_approval": ActionCode.REJECT_APPROVAL,
}

ALL_SUPPORTED_INTENTS = READ_INTENTS.union(RECEIPT_INTENTS, WRITE_INTENT_TO_ACTION)

NATURAL_LANGUAGE_TO_INTENT = {
    "项目列表": "list_sessions",
    "会话列表": "list_sessions",
    "所有项目": "list_sessions",
    "所有项目进展": "list_sessions",
    "多项目进展": "list_sessions",
    "现在进展": "get_progress",
    "进展": "get_progress",
    "当前进展": "get_progress",
    "现在到哪了": "get_progress",
    "任务进展": "get_progress",
    "状态": "get_session",
    "当前状态": "get_session",
    "任务状态": "get_session",
    "事件流": "list_session_events",
    "会话事件": "list_session_events",
    "事件快照": "list_session_events",
    "为什么卡住": "why_stuck",
    "卡在哪里": "explain_blocker",
    "审批列表": "list_pending_approvals",
    "继续": "continue_session",
    "继续做": "continue_session",
    "暂停": "pause_session",
    "恢复": "resume_session",
    "总结": "summarize_session",
    "转人工": "force_handoff",
    "人工接管": "force_handoff",
    "转人工接管": "force_handoff",
    "保守重试": "retry_with_conservative_path",
    "progress": "get_progress",
    "status": "get_session",
    "session events": "list_session_events",
    "event stream": "list_session_events",
    "event snapshot": "list_session_events",
    "continue": "continue_session",
    "pause": "pause_session",
    "resume": "resume_session",
    "summarize": "summarize_session",
}


def resolve_message_to_intent(message: str) -> str | None:
    normalized = str(message or "").strip().lower()
    if not normalized:
        return None
    return NATURAL_LANGUAGE_TO_INTENT.get(normalized)
