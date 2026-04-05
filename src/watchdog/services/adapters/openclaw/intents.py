from __future__ import annotations

from watchdog.contracts.session_spine.enums import ActionCode

READ_INTENTS = {
    "get_session",
    "get_progress",
    "why_stuck",
    "explain_blocker",
    "list_pending_approvals",
}

WRITE_INTENT_TO_ACTION = {
    "continue_session": ActionCode.CONTINUE_SESSION,
    "request_recovery": ActionCode.REQUEST_RECOVERY,
    "execute_recovery": ActionCode.EXECUTE_RECOVERY,
    "approve_approval": ActionCode.APPROVE_APPROVAL,
    "reject_approval": ActionCode.REJECT_APPROVAL,
}

ALL_SUPPORTED_INTENTS = READ_INTENTS.union(WRITE_INTENT_TO_ACTION)
