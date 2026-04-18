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

MANAGED_AGENT_ACTION_BOUNDARY = {
    "continue_session": {
        "capability": "session_control",
        "allowed_brain_intents": (
            "propose_execute",
            "require_approval",
            "suggest_only",
            "observe_only",
        ),
        "auto_execute_allowed_intents": ("propose_execute",),
    },
    "execute_recovery": {
        "capability": "session_recovery",
        "allowed_brain_intents": ("propose_recovery",),
        "auto_execute_allowed_intents": ("propose_recovery",),
    },
    "post_operator_guidance": {
        "capability": "operator_guidance",
        "allowed_brain_intents": ("candidate_closure",),
        "auto_execute_allowed_intents": (),
    },
}

MANAGED_AGENT_ACTION_ARGUMENT_CONTRACTS = {
    "continue_session": {
        "allowed_keys": (
            "message",
            "reason_code",
            "stuck_level",
        ),
        "required_keys": (),
    },
    "execute_recovery": {
        "allowed_keys": (),
        "required_keys": (),
    },
    "post_operator_guidance": {
        "allowed_keys": (
            "message",
            "reason_code",
            "stuck_level",
        ),
        "required_keys": ("message",),
    },
}
