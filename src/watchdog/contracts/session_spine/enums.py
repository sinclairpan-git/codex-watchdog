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
    EVENTS = "events"
    APPROVALS = "approvals"
    FACTS = "facts"
    EXPLANATION = "explanation"
    ACTION_RESULT = "action_result"


class ReplyCode(str, Enum):
    SESSION_PROJECTION = "session_projection"
    SESSION_DIRECTORY = "session_directory"
    SESSION_EVENT_SNAPSHOT = "session_event_snapshot"
    SESSION_FACTS = "session_facts"
    TASK_PROGRESS_VIEW = "task_progress_view"
    WORKSPACE_ACTIVITY_VIEW = "workspace_activity_view"
    APPROVAL_QUEUE = "approval_queue"
    APPROVAL_INBOX = "approval_inbox"
    APPROVAL_RESULT = "approval_result"
    ACTION_RESULT = "action_result"
    SUPERVISION_EVALUATION = "supervision_evaluation"
    ACTION_RECEIPT = "action_receipt"
    ACTION_RECEIPT_NOT_FOUND = "action_receipt_not_found"
    STUCK_EXPLANATION = "stuck_explanation"
    BLOCKER_EXPLANATION = "blocker_explanation"
    RECOVERY_AVAILABILITY = "recovery_availability"
    RECOVERY_EXECUTION_RESULT = "recovery_execution_result"
    ACTION_NOT_AVAILABLE = "action_not_available"
    CONTROL_LINK_ERROR = "control_link_error"
    UNSUPPORTED_INTENT = "unsupported_intent"


class EventKind(str, Enum):
    LIFECYCLE = "lifecycle"
    GUIDANCE = "guidance"
    RECOVERY = "recovery"
    APPROVAL = "approval"
    OBSERVATION = "observation"


class EventCode(str, Enum):
    SESSION_CREATED = "session_created"
    NATIVE_THREAD_BOUND = "native_thread_bound"
    GUIDANCE_POSTED = "guidance_posted"
    HANDOFF_REQUESTED = "handoff_requested"
    SESSION_RESUMED = "session_resumed"
    APPROVAL_RESOLVED = "approval_resolved"
    SESSION_UPDATED = "session_updated"


class ActionCode(str, Enum):
    CONTINUE_SESSION = "continue_session"
    PAUSE_SESSION = "pause_session"
    RESUME_SESSION = "resume_session"
    SUMMARIZE_SESSION = "summarize_session"
    FORCE_HANDOFF = "force_handoff"
    RETRY_WITH_CONSERVATIVE_PATH = "retry_with_conservative_path"
    POST_OPERATOR_GUIDANCE = "post_operator_guidance"
    APPROVE_APPROVAL = "approve_approval"
    REJECT_APPROVAL = "reject_approval"
    REQUEST_RECOVERY = "request_recovery"
    EXECUTE_RECOVERY = "execute_recovery"
    EVALUATE_SUPERVISION = "evaluate_supervision"


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
    SESSION_PAUSED = "session_paused"
    SESSION_RESUMED = "session_resumed"
    SUMMARY_GENERATED = "summary_generated"
    CONSERVATIVE_RETRY_REQUESTED = "conservative_retry_requested"
    APPROVAL_DECIDED = "approval_decided"
    HANDOFF_TRIGGERED = "handoff_triggered"
    HANDOFF_AND_RESUME = "handoff_and_resume"


class SupervisionReasonCode(str, Enum):
    FILESYSTEM_ACTIVITY_RECENT = "filesystem_activity_recent"
    NO_LAST_PROGRESS_AT = "no_last_progress_at"
    TERMINAL_STATE = "terminal_state"
    WITHIN_THRESHOLD = "within_threshold"
    STUCK_SOFT = "stuck_soft"
