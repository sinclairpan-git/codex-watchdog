from __future__ import annotations

from typing import Any, Mapping

from watchdog.services.goal_contract.models import GoalContractReadiness
from watchdog.services.brain.release_gate_read_contract import (
    ReleaseGateDecisionReadSnapshot,
    read_release_gate_decision_evidence,
)
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
    validator_verdict: dict[str, Any] | None = None,
    release_gate_verdict: dict[str, Any] | None = None,
    policy_version: str = POLICY_VERSION,
    goal_contract_readiness: GoalContractReadiness | None = None,
) -> CanonicalDecisionRecord:
    fact_codes = [fact.fact_code for fact in persisted_record.facts]
    uncertainty_reasons = [
        fact_code for fact_code in fact_codes if fact_code in CONTROLLED_UNCERTAINTY_REASONS
    ]
    extra_evidence = _goal_contract_evidence(
        goal_contract_readiness,
        validator_verdict=validator_verdict,
        release_gate_verdict=release_gate_verdict,
    )

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

    if brain_intent == "observe_only":
        return build_canonical_decision_record(
            persisted_record=persisted_record,
            decision_result=DECISION_BLOCK_AND_ALERT,
            brain_intent=brain_intent,
            risk_class=RISK_CLASS_HARD_BLOCK,
            action_ref=action_ref,
            matched_policy_rules=["brain_observe_only"],
            decision_reason="brain observed state without proposing execution",
            why_not_escalated=None,
            why_escalated="brain intent is observe_only",
            uncertainty_reasons=[],
            policy_version=policy_version,
            trigger=trigger,
            extra_evidence=extra_evidence,
        )

    runtime_gate_override = _runtime_gate_override(
        persisted_record=persisted_record,
        action_ref=action_ref,
        trigger=trigger,
        brain_intent=brain_intent,
        policy_version=policy_version,
        validator_verdict=validator_verdict,
        release_gate_verdict=release_gate_verdict,
        extra_evidence=extra_evidence,
    )
    if runtime_gate_override is not None:
        return runtime_gate_override

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
    *,
    validator_verdict: dict[str, Any] | None = None,
    release_gate_verdict: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    evidence: dict[str, Any] = {}
    release_gate = read_release_gate_decision_evidence(release_gate_verdict)
    if readiness is None:
        if validator_verdict is not None:
            evidence["validator_verdict"] = dict(validator_verdict)
        if release_gate.verdict is not None:
            evidence["release_gate_verdict"] = release_gate.verdict.model_dump(mode="json")
        if release_gate.evidence_bundle is not None:
            evidence["release_gate_evidence_bundle"] = release_gate.evidence_bundle.model_dump(
                mode="json"
            )
        return evidence or None
    evidence["goal_contract_readiness"] = readiness.model_dump(mode="json")
    if validator_verdict is not None:
        evidence["validator_verdict"] = dict(validator_verdict)
    if release_gate.verdict is not None:
        evidence["release_gate_verdict"] = release_gate.verdict.model_dump(mode="json")
    if release_gate.evidence_bundle is not None:
        evidence["release_gate_evidence_bundle"] = release_gate.evidence_bundle.model_dump(
            mode="json"
        )
    return evidence


def _runtime_gate_override(
    *,
    persisted_record: PersistedSessionRecord,
    action_ref: str,
    trigger: str,
    brain_intent: str | None,
    policy_version: str,
    validator_verdict: dict[str, Any] | None,
    release_gate_verdict: Mapping[str, Any] | None,
    extra_evidence: dict[str, Any] | None,
) -> CanonicalDecisionRecord | None:
    if brain_intent != "propose_execute":
        return None
    if not _verdict_is_pass(validator_verdict):
        matched_rule = (
            "runtime_gate_missing" if validator_verdict is None else "validator_gate_degraded"
        )
        degrade_reason = _verdict_reason(validator_verdict, fallback="validator_missing")
        return build_canonical_decision_record(
            persisted_record=persisted_record,
            decision_result=DECISION_BLOCK_AND_ALERT,
            brain_intent=brain_intent,
            risk_class=RISK_CLASS_HARD_BLOCK,
            action_ref=action_ref,
            matched_policy_rules=[matched_rule],
            decision_reason="validator gate blocks autonomous execution",
            why_not_escalated=None,
            why_escalated=f"validator verdict is not pass: {degrade_reason}",
            uncertainty_reasons=[degrade_reason],
            policy_version=policy_version,
            trigger=trigger,
            extra_evidence=extra_evidence,
        )
    release_gate = read_release_gate_decision_evidence(release_gate_verdict)
    if not _release_gate_snapshot_is_pass(release_gate):
        matched_rule = (
            "runtime_gate_missing"
            if not _release_gate_snapshot_has_gate_evidence(release_gate)
            else "release_gate_degraded"
        )
        degrade_reason = _release_gate_snapshot_reason(
            release_gate,
            fallback="release_gate_missing",
        )
        decision_result = DECISION_REQUIRE_USER_DECISION if degrade_reason == "approval_stale" else DECISION_BLOCK_AND_ALERT
        risk_class = RISK_CLASS_HUMAN_GATE if degrade_reason == "approval_stale" else RISK_CLASS_HARD_BLOCK
        decision_reason = (
            "release gate requires fresh approval before autonomous execution"
            if degrade_reason == "approval_stale"
            else "release gate blocks autonomous execution"
        )
        return build_canonical_decision_record(
            persisted_record=persisted_record,
            decision_result=decision_result,
            brain_intent=brain_intent,
            risk_class=risk_class,
            action_ref=action_ref,
            matched_policy_rules=[matched_rule],
            decision_reason=decision_reason,
            why_not_escalated=None,
            why_escalated=f"release gate verdict is not pass: {degrade_reason}",
            uncertainty_reasons=[degrade_reason],
            policy_version=policy_version,
            trigger=trigger,
            extra_evidence=extra_evidence,
        )
    return None


def _verdict_is_pass(verdict: dict[str, Any] | None) -> bool:
    return isinstance(verdict, dict) and verdict.get("status") == "pass"


def _verdict_reason(verdict: dict[str, Any] | None, *, fallback: str) -> str:
    if not isinstance(verdict, dict):
        return fallback
    return str(verdict.get("degrade_reason") or verdict.get("reason") or fallback)


def _release_gate_snapshot_requires_bundle(
    snapshot: ReleaseGateDecisionReadSnapshot,
) -> bool:
    return snapshot.verdict is not None and snapshot.verdict.report_id != "report:resident_default"


def _release_gate_snapshot_is_pass(snapshot: ReleaseGateDecisionReadSnapshot) -> bool:
    if snapshot.verdict is None or snapshot.verdict.status != "pass":
        return False
    if _release_gate_snapshot_requires_bundle(snapshot) and snapshot.evidence_bundle is None:
        return False
    return True


def _release_gate_snapshot_has_gate_evidence(
    snapshot: ReleaseGateDecisionReadSnapshot,
) -> bool:
    return (
        snapshot.verdict is not None
        or snapshot.has_verdict_payload
        or snapshot.has_evidence_bundle_payload
    )


def _release_gate_snapshot_reason(
    snapshot: ReleaseGateDecisionReadSnapshot,
    *,
    fallback: str,
) -> str:
    if snapshot.verdict is None:
        return fallback
    if snapshot.verdict.status != "pass":
        return snapshot.verdict.degrade_reason or fallback
    if _release_gate_snapshot_requires_bundle(snapshot) and snapshot.evidence_bundle is None:
        return fallback
    return fallback
