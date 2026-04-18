from __future__ import annotations

from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field

from watchdog.services.goal_contract.models import GoalContractReadiness
from watchdog.services.policy.rules import MANAGED_AGENT_ACTION_ARGUMENT_CONTRACTS


class DecisionValidationVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(min_length=1)
    reason: str | None = None


class ManagedActionArgumentsContractVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(min_length=1)
    action_ref: str | None = None
    allowed_keys: list[str] = Field(default_factory=list)
    required_keys: list[str] = Field(default_factory=list)
    missing_required_keys: list[str] = Field(default_factory=list)
    rejected_keys: list[str] = Field(default_factory=list)
    invalid_fields: dict[str, str] = Field(default_factory=dict)


def _invalid_text_field(value: object) -> bool:
    return not isinstance(value, str) or not value.strip()


def validate_managed_action_arguments(
    *,
    action_ref: str | None,
    action_arguments: Mapping[str, Any] | None,
) -> ManagedActionArgumentsContractVerdict:
    contract = (
        MANAGED_AGENT_ACTION_ARGUMENT_CONTRACTS.get(action_ref)
        if action_ref is not None
        else None
    )
    if contract is None:
        return ManagedActionArgumentsContractVerdict(
            status="unregistered_action",
            action_ref=action_ref,
        )

    allowed_keys = list(contract["allowed_keys"])
    required_keys = list(contract["required_keys"])
    payload = dict(action_arguments or {})
    rejected_keys = sorted(key for key in payload if key not in allowed_keys)
    missing_required_keys = [key for key in required_keys if key not in payload]
    invalid_fields: dict[str, str] = {}

    for key in allowed_keys:
        if key not in payload:
            continue
        value = payload[key]
        if key in {"message", "reason_code"} and _invalid_text_field(value):
            invalid_fields[key] = "must be a non-empty string"
        elif key == "stuck_level":
            if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 4:
                invalid_fields[key] = "must be an integer in 0..4"

    status = (
        "blocked"
        if rejected_keys or missing_required_keys or invalid_fields
        else "pass"
    )
    return ManagedActionArgumentsContractVerdict(
        status=status,
        action_ref=action_ref,
        allowed_keys=allowed_keys,
        required_keys=required_keys,
        missing_required_keys=missing_required_keys,
        rejected_keys=rejected_keys,
        invalid_fields=invalid_fields,
    )


class DecisionValidator:
    def validate(
        self,
        *,
        brain_intent: str,
        action_ref: str | None = None,
        action_arguments: Mapping[str, Any] | None = None,
        goal_contract_readiness: GoalContractReadiness | None = None,
        memory_conflict_detected: bool = False,
        memory_unavailable: bool = False,
        status: str | None = None,
        reason: str | None = None,
    ) -> DecisionValidationVerdict:
        if status is not None:
            return DecisionValidationVerdict(status=status, reason=reason)
        action_args_contract = validate_managed_action_arguments(
            action_ref=action_ref,
            action_arguments=action_arguments,
        )
        if action_ref is not None and action_args_contract.status != "pass":
            return DecisionValidationVerdict(
                status="degraded",
                reason="action_args_invalid",
            )
        if brain_intent != "propose_execute":
            return DecisionValidationVerdict(
                status="pass",
                reason="non_executing_intent",
            )
        if memory_conflict_detected:
            return DecisionValidationVerdict(
                status="degraded",
                reason="memory_conflict",
            )
        if memory_unavailable:
            return DecisionValidationVerdict(
                status="degraded",
                reason="memory_unavailable",
            )
        if (
            goal_contract_readiness is not None
            and goal_contract_readiness.mode != "autonomous_ready"
        ):
            return DecisionValidationVerdict(
                status="degraded",
                reason="goal_contract_not_ready",
            )
        return DecisionValidationVerdict(
            status="pass",
            reason="schema_and_risk_ok",
        )
