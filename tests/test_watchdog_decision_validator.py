from __future__ import annotations

from watchdog.services.brain.validator import (
    DecisionValidator,
    validate_managed_action_arguments,
)
from watchdog.services.goal_contract.models import GoalContractReadiness


def test_managed_action_args_contract_accepts_continue_session_fields() -> None:
    contract = validate_managed_action_arguments(
        action_ref="continue_session",
        action_arguments={
            "message": "继续推进 provider 切换并补 smoke。",
            "reason_code": "brain_auto_continue",
            "stuck_level": 1,
        },
    )

    assert contract.model_dump(mode="json") == {
        "status": "pass",
        "action_ref": "continue_session",
        "allowed_keys": ["message", "reason_code", "stuck_level"],
        "required_keys": [],
        "missing_required_keys": [],
        "rejected_keys": [],
        "invalid_fields": {},
    }
    verdict = DecisionValidator().validate(
        brain_intent="propose_execute",
        action_ref="continue_session",
        action_arguments={
            "message": "继续推进 provider 切换并补 smoke。",
            "reason_code": "brain_auto_continue",
            "stuck_level": 1,
        },
        goal_contract_readiness=GoalContractReadiness(
            mode="autonomous_ready",
            missing_fields=[],
        ),
    )

    assert verdict.model_dump(mode="json") == {
        "status": "pass",
        "reason": "schema_and_risk_ok",
    }


def test_decision_validator_rejects_unknown_continue_session_argument_key() -> None:
    contract = validate_managed_action_arguments(
        action_ref="continue_session",
        action_arguments={
            "message": "继续",
            "reason_code": "brain_auto_continue",
            "stuck_level": 1,
            "approval_id": "appr_001",
        },
    )

    assert contract.model_dump(mode="json") == {
        "status": "blocked",
        "action_ref": "continue_session",
        "allowed_keys": ["message", "reason_code", "stuck_level"],
        "required_keys": [],
        "missing_required_keys": [],
        "rejected_keys": ["approval_id"],
        "invalid_fields": {},
    }
    verdict = DecisionValidator().validate(
        brain_intent="propose_execute",
        action_ref="continue_session",
        action_arguments={
            "message": "继续",
            "reason_code": "brain_auto_continue",
            "stuck_level": 1,
            "approval_id": "appr_001",
        },
    )

    assert verdict.model_dump(mode="json") == {
        "status": "degraded",
        "reason": "action_args_invalid",
    }


def test_decision_validator_rejects_out_of_range_stuck_level() -> None:
    contract = validate_managed_action_arguments(
        action_ref="continue_session",
        action_arguments={
            "message": "继续",
            "reason_code": "brain_auto_continue",
            "stuck_level": 7,
        },
    )

    assert contract.model_dump(mode="json") == {
        "status": "blocked",
        "action_ref": "continue_session",
        "allowed_keys": ["message", "reason_code", "stuck_level"],
        "required_keys": [],
        "missing_required_keys": [],
        "rejected_keys": [],
        "invalid_fields": {
            "stuck_level": "must be an integer in 0..4",
        },
    }
    verdict = DecisionValidator().validate(
        brain_intent="propose_execute",
        action_ref="continue_session",
        action_arguments={
            "message": "继续",
            "reason_code": "brain_auto_continue",
            "stuck_level": 7,
        },
    )

    assert verdict.model_dump(mode="json") == {
        "status": "degraded",
        "reason": "action_args_invalid",
    }


def test_decision_validator_rejects_execute_recovery_args_from_provider() -> None:
    contract = validate_managed_action_arguments(
        action_ref="execute_recovery",
        action_arguments={"mode": "safe"},
    )

    assert contract.model_dump(mode="json") == {
        "status": "blocked",
        "action_ref": "execute_recovery",
        "allowed_keys": [],
        "required_keys": [],
        "missing_required_keys": [],
        "rejected_keys": ["mode"],
        "invalid_fields": {},
    }
    verdict = DecisionValidator().validate(
        brain_intent="propose_recovery",
        action_ref="execute_recovery",
        action_arguments={"mode": "safe"},
    )

    assert verdict.model_dump(mode="json") == {
        "status": "degraded",
        "reason": "action_args_invalid",
    }
