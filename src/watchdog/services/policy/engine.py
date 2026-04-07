from __future__ import annotations

from watchdog.services.policy.decisions import (
    CanonicalDecisionRecord,
    build_canonical_decision_record,
)
from watchdog.services.policy.rules import (
    CONTROLLED_UNCERTAINTY_REASONS,
    DECISION_AUTO_EXECUTE_AND_NOTIFY,
    DECISION_BLOCK_AND_ALERT,
    DECISION_REQUIRE_USER_DECISION,
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
    policy_version: str = POLICY_VERSION,
) -> CanonicalDecisionRecord:
    fact_codes = [fact.fact_code for fact in persisted_record.facts]
    uncertainty_reasons = [
        fact_code for fact_code in fact_codes if fact_code in CONTROLLED_UNCERTAINTY_REASONS
    ]

    if any(fact_code in HUMAN_GATE_FACT_CODES for fact_code in fact_codes):
        return build_canonical_decision_record(
            persisted_record=persisted_record,
            decision_result=DECISION_REQUIRE_USER_DECISION,
            risk_class=RISK_CLASS_HUMAN_GATE,
            action_ref=action_ref,
            matched_policy_rules=["human_gate"],
            decision_reason="session requires explicit human decision",
            why_not_escalated=None,
            why_escalated="human_gate matched persisted facts",
            uncertainty_reasons=[],
            policy_version=policy_version,
            trigger=trigger,
        )

    if uncertainty_reasons:
        return build_canonical_decision_record(
            persisted_record=persisted_record,
            decision_result=DECISION_BLOCK_AND_ALERT,
            risk_class=RISK_CLASS_HARD_BLOCK,
            action_ref=action_ref,
            matched_policy_rules=["controlled_uncertainty"],
            decision_reason="controlled uncertainty blocks autonomous execution",
            why_not_escalated=None,
            why_escalated="controlled uncertainty requires block",
            uncertainty_reasons=uncertainty_reasons,
            policy_version=policy_version,
            trigger=trigger,
        )

    if action_ref not in REGISTERED_ACTION_REFS:
        return build_canonical_decision_record(
            persisted_record=persisted_record,
            decision_result=DECISION_BLOCK_AND_ALERT,
            risk_class=RISK_CLASS_HARD_BLOCK,
            action_ref=action_ref,
            matched_policy_rules=["action_registration"],
            decision_reason="action policy is not registered",
            why_not_escalated=None,
            why_escalated="unregistered action cannot be auto executed",
            uncertainty_reasons=["action_unregistered"],
            policy_version=policy_version,
            trigger=trigger,
        )

    return build_canonical_decision_record(
        persisted_record=persisted_record,
        decision_result=DECISION_AUTO_EXECUTE_AND_NOTIFY,
        risk_class=RISK_CLASS_NONE,
        action_ref=action_ref,
        matched_policy_rules=["registered_action"],
        decision_reason="registered action and complete evidence",
        why_not_escalated="policy_allows_auto_execution",
        why_escalated=None,
        uncertainty_reasons=[],
        policy_version=policy_version,
        trigger=trigger,
    )
