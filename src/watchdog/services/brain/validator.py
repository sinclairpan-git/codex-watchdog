from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from watchdog.services.goal_contract.models import GoalContractReadiness


class DecisionValidationVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(min_length=1)
    reason: str | None = None


class DecisionValidator:
    def validate(
        self,
        *,
        brain_intent: str,
        goal_contract_readiness: GoalContractReadiness | None = None,
        memory_conflict_detected: bool = False,
        memory_unavailable: bool = False,
        status: str | None = None,
        reason: str | None = None,
    ) -> DecisionValidationVerdict:
        if status is not None:
            return DecisionValidationVerdict(status=status, reason=reason)
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
