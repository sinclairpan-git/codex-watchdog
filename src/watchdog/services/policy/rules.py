from __future__ import annotations

POLICY_VERSION = "policy-v1"

DECISION_AUTO_EXECUTE_AND_NOTIFY = "auto_execute_and_notify"
DECISION_REQUIRE_USER_DECISION = "require_user_decision"
DECISION_BLOCK_AND_ALERT = "block_and_alert"

RISK_CLASS_NONE = "none"
RISK_CLASS_HUMAN_GATE = "human_gate"
RISK_CLASS_HARD_BLOCK = "hard_block"

CONTROLLED_UNCERTAINTY_REASONS = {
    "evidence_missing",
    "fact_conflict",
    "policy_conflict",
    "action_unregistered",
    "risk_unexplainable",
    "mapping_incomplete",
    "idempotency_uncertain",
}

HUMAN_GATE_FACT_CODES = {
    "approval_pending",
    "awaiting_human_direction",
}

REGISTERED_ACTION_REFS = {
    "continue_session",
    "execute_recovery",
    "post_operator_guidance",
}

EXPLICIT_USER_DECISION_ACTION_REFS = {
    "execute_recovery",
}
