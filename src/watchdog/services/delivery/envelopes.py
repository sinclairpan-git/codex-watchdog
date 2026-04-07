from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from watchdog.services.approvals.service import (
    CanonicalApprovalRecord,
    CanonicalApprovalResponseRecord,
)
from watchdog.services.policy.decisions import CanonicalDecisionRecord
from watchdog.services.policy.rules import (
    DECISION_AUTO_EXECUTE_AND_NOTIFY,
    DECISION_BLOCK_AND_ALERT,
    DECISION_REQUIRE_USER_DECISION,
)


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _envelope_id(decision_key: str, envelope_type: str, suffix: str = "") -> str:
    seed = "|".join(part for part in [decision_key, envelope_type, suffix] if part)
    return f"{envelope_type}-envelope:{_short_hash(seed)}"


def _facts_from_decision(decision: CanonicalDecisionRecord) -> list[dict[str, Any]]:
    facts = decision.evidence.get("facts")
    if isinstance(facts, list):
        return [dict(fact) for fact in facts if isinstance(fact, dict)]
    return []


def _matched_rules(decision: CanonicalDecisionRecord) -> list[str]:
    return list(decision.matched_policy_rules)


def _recommended_actions(decision: CanonicalDecisionRecord) -> list[dict[str, str]]:
    return [
        {
            "action_code": decision.action_ref,
            "label": decision.action_ref.replace("_", " "),
            "action_ref": decision.action_ref,
        }
    ]


class EnvelopeBase(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    envelope_id: str
    envelope_type: str
    envelope_version: str = "v1"
    correlation_id: str
    session_id: str
    project_id: str
    native_thread_id: str | None = None
    policy_version: str
    fact_snapshot_version: str
    idempotency_key: str
    audit_ref: str
    created_at: str


class DecisionEnvelope(EnvelopeBase):
    envelope_type: str = "decision"
    decision_id: str
    decision_result: str
    execution_state: str = "queued"
    action_name: str
    action_args: dict[str, Any] = Field(default_factory=dict)
    approval_id: str | None = None
    risk_class: str
    decision_reason: str
    facts: list[dict[str, Any]] = Field(default_factory=list)
    matched_policy_rules: list[str] = Field(default_factory=list)
    why_not_escalated: str | None = None
    completed_at: str | None = None


class NotificationEnvelope(EnvelopeBase):
    envelope_type: str = "notification"
    event_id: str
    severity: str
    notification_kind: str
    title: str
    summary: str
    reason: str
    facts: list[dict[str, Any]] = Field(default_factory=list)
    recommended_actions: list[dict[str, str]] = Field(default_factory=list)


class ApprovalEnvelope(EnvelopeBase):
    envelope_type: str = "approval"
    approval_id: str
    approval_kind: str
    requested_action: str
    requested_action_args: dict[str, Any] = Field(default_factory=dict)
    risk_class: str
    title: str
    summary: str
    decision_options: list[str] = Field(default_factory=lambda: ["approve", "reject", "execute_action"])
    facts: list[dict[str, Any]] = Field(default_factory=list)
    matched_policy_rules: list[str] = Field(default_factory=list)
    why_escalated: str | None = None
    approval_token: str
    callback_action_ref: str = "/api/v1/watchdog/openclaw/responses"


def _build_decision_envelope(decision: CanonicalDecisionRecord) -> DecisionEnvelope:
    return DecisionEnvelope(
        envelope_id=_envelope_id(decision.decision_key, "decision"),
        correlation_id=decision.decision_id,
        session_id=decision.session_id,
        project_id=decision.project_id,
        native_thread_id=decision.native_thread_id,
        policy_version=decision.policy_version,
        fact_snapshot_version=decision.fact_snapshot_version,
        idempotency_key=decision.idempotency_key,
        audit_ref=decision.decision_id,
        created_at=decision.created_at,
        decision_id=decision.decision_id,
        decision_result=decision.decision_result,
        action_name=decision.action_ref,
        action_args={},
        approval_id=decision.approval_id,
        risk_class=decision.risk_class,
        decision_reason=decision.decision_reason,
        facts=_facts_from_decision(decision),
        matched_policy_rules=_matched_rules(decision),
        why_not_escalated=decision.why_not_escalated,
    )


def _build_decision_notification(decision: CanonicalDecisionRecord) -> NotificationEnvelope:
    return NotificationEnvelope(
        envelope_id=_envelope_id(decision.decision_key, "notification", "decision_result"),
        correlation_id=decision.decision_id,
        session_id=decision.session_id,
        project_id=decision.project_id,
        native_thread_id=decision.native_thread_id,
        policy_version=decision.policy_version,
        fact_snapshot_version=decision.fact_snapshot_version,
        idempotency_key=f"{decision.idempotency_key}|decision_result",
        audit_ref=decision.decision_id,
        created_at=decision.created_at,
        event_id=f"event:{_short_hash(decision.decision_id + '|decision_result')}",
        severity="critical" if decision.decision_result == DECISION_BLOCK_AND_ALERT else "info",
        notification_kind="decision_result",
        title=f"decision {decision.decision_result}",
        summary=decision.decision_reason,
        reason=decision.decision_reason,
        facts=_facts_from_decision(decision),
        recommended_actions=_recommended_actions(decision),
    )


def _build_approval_envelope(decision: CanonicalDecisionRecord) -> ApprovalEnvelope:
    digest = _short_hash(decision.decision_key)
    return ApprovalEnvelope(
        envelope_id=_envelope_id(decision.decision_key, "approval"),
        correlation_id=decision.decision_id,
        session_id=decision.session_id,
        project_id=decision.project_id,
        native_thread_id=decision.native_thread_id,
        policy_version=decision.policy_version,
        fact_snapshot_version=decision.fact_snapshot_version,
        idempotency_key=f"{decision.idempotency_key}|approval",
        audit_ref=decision.decision_id,
        created_at=decision.created_at,
        approval_id=decision.approval_id or f"approval:{digest}",
        approval_kind="canonical_user_decision",
        requested_action=decision.action_ref,
        requested_action_args={},
        risk_class=decision.risk_class,
        title=f"approval required for {decision.action_ref}",
        summary=decision.decision_reason,
        facts=_facts_from_decision(decision),
        matched_policy_rules=_matched_rules(decision),
        why_escalated=decision.why_escalated,
        approval_token=f"approval-token:{digest}",
    )


def build_envelopes_for_decision(
    decision: CanonicalDecisionRecord,
) -> list[DecisionEnvelope | NotificationEnvelope | ApprovalEnvelope]:
    if decision.decision_result == DECISION_AUTO_EXECUTE_AND_NOTIFY:
        return [_build_decision_envelope(decision), _build_decision_notification(decision)]
    if decision.decision_result == DECISION_REQUIRE_USER_DECISION:
        return [_build_approval_envelope(decision)]
    if decision.decision_result == DECISION_BLOCK_AND_ALERT:
        return [_build_decision_notification(decision)]
    raise ValueError(f"unsupported decision_result for delivery: {decision.decision_result}")


def build_envelopes_for_approval_response(
    approval: CanonicalApprovalRecord,
    response: CanonicalApprovalResponseRecord,
) -> list[NotificationEnvelope]:
    decision = approval.decision
    return [
        NotificationEnvelope(
            envelope_id=_envelope_id(decision.decision_key, "notification", "approval_result"),
            correlation_id=approval.approval_id,
            session_id=approval.session_id,
            project_id=approval.project_id,
            native_thread_id=approval.native_thread_id,
            policy_version=approval.policy_version,
            fact_snapshot_version=approval.fact_snapshot_version,
            idempotency_key=response.idempotency_key,
            audit_ref=response.response_id,
            created_at=response.created_at,
            event_id=f"event:{_short_hash(response.response_id + '|approval_result')}",
            severity="critical" if response.approval_status == "rejected" else "info",
            notification_kind="approval_result",
            title=f"approval {response.approval_status}",
            summary=f"approval {response.approval_status} via {response.response_action}",
            reason=response.note or response.response_action,
            facts=_facts_from_decision(decision),
            recommended_actions=_recommended_actions(decision),
        )
    ]
