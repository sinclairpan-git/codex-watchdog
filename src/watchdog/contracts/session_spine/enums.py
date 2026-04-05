from __future__ import annotations

from enum import Enum


class SessionState(str, Enum):
    ACTIVE = "active"
    AWAITING_APPROVAL = "awaiting_approval"
    BLOCKED = "blocked"
    UNAVAILABLE = "unavailable"


class AttentionState(str, Enum):
    NORMAL = "normal"
    NEEDS_HUMAN = "needs_human"
    CRITICAL = "critical"
    UNREACHABLE = "unreachable"


class ReplyKind(str, Enum):
    SESSION = "session"
    APPROVALS = "approvals"
    EXPLANATION = "explanation"
    ACTION_RESULT = "action_result"


class ReplyCode(str, Enum):
    SESSION_PROJECTION = "session_projection"
    TASK_PROGRESS_VIEW = "task_progress_view"
    APPROVAL_QUEUE = "approval_queue"
    APPROVAL_RESULT = "approval_result"
    ACTION_RESULT = "action_result"
    STUCK_EXPLANATION = "stuck_explanation"
    BLOCKER_EXPLANATION = "blocker_explanation"
    RECOVERY_AVAILABILITY = "recovery_availability"
    ACTION_NOT_AVAILABLE = "action_not_available"
    CONTROL_LINK_ERROR = "control_link_error"
    UNSUPPORTED_INTENT = "unsupported_intent"


class ActionCode(str, Enum):
    CONTINUE_SESSION = "continue_session"
    APPROVE_APPROVAL = "approve_approval"
    REJECT_APPROVAL = "reject_approval"
    REQUEST_RECOVERY = "request_recovery"


class ActionStatus(str, Enum):
    COMPLETED = "completed"
    BLOCKED = "blocked"
    NOOP = "noop"
    REJECTED = "rejected"
    NOT_AVAILABLE = "not_available"
    ERROR = "error"


class Effect(str, Enum):
    NOOP = "noop"
    ADVISORY_ONLY = "advisory_only"
    STEER_POSTED = "steer_posted"
    APPROVAL_DECIDED = "approval_decided"
