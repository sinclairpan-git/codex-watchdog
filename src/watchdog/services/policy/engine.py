from __future__ import annotations

from typing import Any

from watchdog.services.goal_contract.models import GoalContractReadiness
from watchdog.services.policy.decisions import (
    CanonicalDecisionRecord,
    build_canonical_decision_record,
)
from watchdog.services.policy.rules import (
    CONTROLLED_UNCERTAINTY_REASONS,
    DECISION_AUTO_EXECUTE_AND_NOTIFY,
    DECISION_BLOCK_AND_ALERT,
    DECISION_REQUIRE_USER_DECISION,
    EXPLICIT_USER_DECISION_ACTION_REFS,
    HUMAN_GATE_FACT_CODES,
    POLICY_VERSION,
    REGISTERED_ACTION_REFS,
    RISK_CLASS_HARD_BLOCK,
    RISK_CLASS_HUMAN_GATE,
    RISK_CLASS_NONE,
)
from watchdog.services.session_spine.store import PersistedSessionRecord


def evaluate_persisted_session_policy(
    persisted_record: PersistedSessionRecord,
    *,
    action_ref: str,
    trigger: str,
    brain_intent: str | None = None,
    policy_version: str = POLICY_VERSION,
    goal_contract_readiness: GoalContractReadiness | None = None,
) -> CanonicalDecisionRecord:
    fact_codes = [fact.fact_code for fact in persisted_record.facts]
    uncertainty_reasons = [
        fact_code for fact_code in fact_codes if fact_code in CONTROLLED_UNCERTAINTY_REASONS
    ]
    extra_evidence = _goal_contract_evidence(goal_contract_readiness)

    if any(fact_code in HUMAN_GATE_FACT_CODES for fact_code in fact_codes):
        return build_canonical_decision_record(
            persisted_record=persisted_record,
            decision_result=DECISION_REQUIRE_USER_DECISION,
            brain_intent=brain_intent,
            risk_class=RISK_CLASS_HUMAN_GATE,
            action_ref=action_ref,
            matched_policy_rules=["human_gate"],
            decision_reason="session requires explicit human decision",
            why_not_escalated=None,
            why_escalated="human_gate matched persisted facts",
            uncertainty_reasons=[],
            policy_version=policy_version,
            trigger=trigger,
            extra_evidence=extra_evidence,
        )

    if uncertainty_reasons:
        return build_canonical_decision_record(
            persisted_record=persisted_record,
            decision_result=DECISION_BLOCK_AND_ALERT,
            brain_intent=brain_intent,
            risk_class=RISK_CLASS_HARD_BLOCK,
            action_ref=action_ref,
            matched_policy_rules=["controlled_uncertainty"],
            decision_reason="controlled uncertainty blocks autonomous execution",
            why_not_escalated=None,
            why_escalated="controlled uncertainty requires block",
            uncertainty_reasons=uncertainty_reasons,
            policy_version=policy_version,
            trigger=trigger,
            extra_evidence=extra_evidence,
        )

    if action_ref not in REGISTERED_ACTION_REFS:
        return build_canonical_decision_record(
            persisted_record=persisted_record,
            decision_result=DECISION_BLOCK_AND_ALERT,
            brain_intent=brain_intent,
            risk_class=RISK_CLASS_HARD_BLOCK,
            action_ref=action_ref,
            matched_policy_rules=["action_registration"],
            decision_reason="action policy is not registered",
            why_not_escalated=None,
            why_escalated="unregistered action cannot be auto executed",
            uncertainty_reasons=["action_unregistered"],
            policy_version=policy_version,
            trigger=trigger,
            extra_evidence=extra_evidence,
        )

    if action_ref in EXPLICIT_USER_DECISION_ACTION_REFS:
        return build_canonical_decision_record(
            persisted_record=persisted_record,
            decision_result=DECISION_REQUIRE_USER_DECISION,
            brain_intent=brain_intent,
            risk_class=RISK_CLASS_HUMAN_GATE,
            action_ref=action_ref,
            matched_policy_rules=["recovery_human_gate"],
            decision_reason="recovery execution requires explicit human decision",
            why_not_escalated=None,
            why_escalated="recovery execution requires explicit human decision",
            uncertainty_reasons=[],
            policy_version=policy_version,
            trigger=trigger,
            extra_evidence=extra_evidence,
        )

    if goal_contract_readiness is not None and goal_contract_readiness.mode != "autonomous_ready":
        missing_summary = ", ".join(goal_contract_readiness.missing_fields) or "goal_contract"
        return build_canonical_decision_record(
            persisted_record=persisted_record,
            decision_result=DECISION_REQUIRE_USER_DECISION,
            brain_intent=brain_intent,
            risk_class=RISK_CLASS_HUMAN_GATE,
            action_ref=action_ref,
            matched_policy_rules=["goal_contract_readiness_gate"],
            decision_reason="goal contract is incomplete for autonomous execution",
            why_not_escalated=None,
            why_escalated=f"goal contract is not autonomous_ready: {missing_summary}",
            uncertainty_reasons=[],
            policy_version=policy_version,
            trigger=trigger,
            extra_evidence=extra_evidence,
        )

    if brain_intent == "candidate_closure":
        return build_canonical_decision_record(
            persisted_record=persisted_record,
            decision_result=DECISION_REQUIRE_USER_DECISION,
            brain_intent=brain_intent,
            risk_class=RISK_CLASS_HUMAN_GATE,
            action_ref=action_ref,
            matched_policy_rules=["task_completion_candidate"],
            decision_reason="session completion requires explicit closure review",
            why_not_escalated=None,
            why_escalated="candidate closure requires explicit human confirmation",
            uncertainty_reasons=[],
            policy_version=policy_version,
            trigger=trigger,
            extra_evidence=extra_evidence,
        )

    if brain_intent == "require_approval":
        return build_canonical_decision_record(
            persisted_record=persisted_record,
            decision_result=DECISION_REQUIRE_USER_DECISION,
            brain_intent=brain_intent,
            risk_class=RISK_CLASS_HUMAN_GATE,
            action_ref=action_ref,
            matched_policy_rules=["brain_requires_approval"],
            decision_reason="brain requested explicit human approval",
            why_not_escalated=None,
            why_escalated="brain intent requires explicit human approval",
            uncertainty_reasons=[],
            policy_version=policy_version,
            trigger=trigger,
            extra_evidence=extra_evidence,
        )

    if brain_intent == "suggest_only":
        return build_canonical_decision_record(
            persisted_record=persisted_record,
            decision_result=DECISION_BLOCK_AND_ALERT,
            brain_intent=brain_intent,
            risk_class=RISK_CLASS_HARD_BLOCK,
            action_ref=action_ref,
            matched_policy_rules=["brain_suggest_only"],
            decision_reason="brain suggested a non-executing follow-up",
            why_not_escalated=None,
            why_escalated="brain intent is suggest_only",
            uncertainty_reasons=[],
            policy_version=policy_version,
            trigger=trigger,
            extra_evidence=extra_evidence,
        )

    return build_canonical_decision_record(
        persisted_record=persisted_record,
        decision_result=DECISION_AUTO_EXECUTE_AND_NOTIFY,
        brain_intent=brain_intent,
        risk_class=RISK_CLASS_NONE,
        action_ref=action_ref,
        matched_policy_rules=["registered_action"],
        decision_reason="registered action and complete evidence",
        why_not_escalated="policy_allows_auto_execution",
        why_escalated=None,
        uncertainty_reasons=[],
        policy_version=policy_version,
        trigger=trigger,
        extra_evidence=extra_evidence,
    )


def _goal_contract_evidence(
    readiness: GoalContractReadiness | None,
) -> dict[str, Any] | None:
    if readiness is None:
        return None
    return {"goal_contract_readiness": readiness.model_dump(mode="json")}
