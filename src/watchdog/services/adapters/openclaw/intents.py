from __future__ import annotations

from watchdog.contracts.session_spine.enums import ActionCode

READ_INTENTS = {
    "list_sessions",
    "list_session_events",
    "get_session",
    "get_session_by_native_thread",
    "get_progress",
    "get_workspace_activity",
    "why_stuck",
    "explain_blocker",
    "list_pending_approvals",
    "list_approval_inbox",
}

RECEIPT_INTENTS = {"get_action_receipt"}

WRITE_INTENT_TO_ACTION = {
    "continue_session": ActionCode.CONTINUE_SESSION,
    "post_operator_guidance": ActionCode.POST_OPERATOR_GUIDANCE,
    "request_recovery": ActionCode.REQUEST_RECOVERY,
    "execute_recovery": ActionCode.EXECUTE_RECOVERY,
    "evaluate_supervision": ActionCode.EVALUATE_SUPERVISION,
    "approve_approval": ActionCode.APPROVE_APPROVAL,
    "reject_approval": ActionCode.REJECT_APPROVAL,
}

ALL_SUPPORTED_INTENTS = READ_INTENTS.union(RECEIPT_INTENTS, WRITE_INTENT_TO_ACTION)
