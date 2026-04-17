from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from watchdog.services.approvals.service import (
    CanonicalApprovalRecord,
    CanonicalApprovalResponseRecord,
    build_canonical_approval_identifiers,
    requested_action_args_from_decision,
)
from watchdog.services.policy.decisions import CanonicalDecisionRecord
from watchdog.services.policy.rules import POLICY_VERSION
from watchdog.services.policy.rules import (
    DECISION_AUTO_EXECUTE_AND_NOTIFY,
    DECISION_BLOCK_AND_ALERT,
    DECISION_REQUIRE_USER_DECISION,
    RISK_CLASS_HARD_BLOCK,
    RISK_CLASS_HUMAN_GATE,
    RISK_CLASS_NONE,
)
from watchdog.services.session_spine.store import PersistedSessionRecord


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


def _canonical_timestamp(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _compatibility_risk_level(risk_class: str) -> str:
    return {
        RISK_CLASS_NONE: "L0",
        RISK_CLASS_HUMAN_GATE: "L2",
        RISK_CLASS_HARD_BLOCK: "L3",
    }.get(risk_class, risk_class)


def _compatibility_command(action_ref: str, action_args: dict[str, Any]) -> str:
    if not action_args:
        return action_ref
    return " ".join(
        [
            action_ref,
            json.dumps(
                action_args,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
        ]
    )


def _progress_summary_severity(record: PersistedSessionRecord) -> str:
    fact_codes = {fact.fact_code for fact in record.facts}
    if "context_critical" in fact_codes or "control_link_error" in fact_codes:
        return "critical"
    if fact_codes.intersection({"approval_pending", "awaiting_human_direction", "stuck_no_progress", "repeat_failure"}):
        return "warning"
    return "info"


def progress_summary_fingerprint(record: PersistedSessionRecord) -> str:
    payload = {
        "project_id": record.project_id,
        "session_state": record.session.session_state,
        "attention_state": record.session.attention_state,
        "activity_phase": record.progress.activity_phase,
        "summary": record.progress.summary,
        "files_touched": list(record.progress.files_touched),
        "context_pressure": record.progress.context_pressure,
        "stuck_level": record.progress.stuck_level,
        "last_progress_at": record.progress.last_progress_at,
        "pending_approval_count": record.session.pending_approval_count,
    }
    return _short_hash(repr(payload))


def build_progress_summary_envelope(
    record: PersistedSessionRecord,
    *,
    created_at: str,
    progress_fingerprint: str | None = None,
) -> NotificationEnvelope:
    fingerprint = progress_fingerprint or progress_summary_fingerprint(record)
    occurred_at = _canonical_timestamp(record.progress.last_progress_at)
    summary = record.progress.summary or record.session.headline
    files = list(record.progress.files_touched)[:3]
    reason_parts = [
        f"phase={record.progress.activity_phase}",
        f"context={record.progress.context_pressure}",
        f"stuck={record.progress.stuck_level}",
    ]
    if files:
        reason_parts.append(f"files={', '.join(files)}")
    return NotificationEnvelope(
        envelope_id=_envelope_id(
            f"{record.thread_id}|{record.fact_snapshot_version}|{fingerprint}",
            "notification",
            "progress_summary",
        ),
        correlation_id=f"progress-summary:{record.project_id}:{fingerprint}",
        session_id=record.thread_id,
        project_id=record.project_id,
        native_thread_id=record.native_thread_id,
        policy_version=POLICY_VERSION,
        fact_snapshot_version=record.fact_snapshot_version,
        idempotency_key=f"{record.thread_id}|{record.fact_snapshot_version}|progress_summary|{fingerprint}",
        audit_ref=f"progress-summary:{record.project_id}:{record.fact_snapshot_version}",
        created_at=created_at,
        event_id=f"event:{_short_hash(record.project_id + '|progress_summary|' + fingerprint)}",
        severity=_progress_summary_severity(record),
        notification_kind="progress_summary",
        occurred_at=occurred_at,
        title=f"progress update for {record.project_id}",
        summary=summary,
        reason="; ".join(reason_parts),
        facts=[fact.model_dump(mode="json") for fact in record.facts],
        recommended_actions=[],
    )


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
    interaction_context_id: str | None = None
    interaction_family_id: str | None = None
    actor_id: str | None = None
    channel_kind: str | None = None
    action_window_expires_at: str | None = None
    receive_id: str | None = None
    receive_id_type: str | None = None


class DecisionEnvelope(EnvelopeBase):
    envelope_type: str = "decision"
    occurred_at: str | None = None
    decision_id: str
    decision_result: str
    execution_state: str = "queued"
    action_name: str
    action_args: dict[str, Any] = Field(default_factory=dict)
    approval_id: str | None = None
    risk_class: str
    risk_level: str | None = None
    command: str = ""
    title: str = ""
    summary: str = ""
    reason: str = ""
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
    occurred_at: str | None = None
    decision_result: str | None = None
    action_name: str | None = None
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
    risk_level: str | None = None
    command: str = ""
    reason: str = ""
    alternative: str = ""
    status: str = "pending"
    requested_at: str
    title: str
    summary: str
    decision_options: list[str] = Field(default_factory=lambda: ["approve", "reject", "execute_action"])
    facts: list[dict[str, Any]] = Field(default_factory=list)
    matched_policy_rules: list[str] = Field(default_factory=list)
    why_escalated: str | None = None
    approval_token: str
    callback_action_ref: str = "/api/v1/watchdog/openclaw/responses"


def _build_decision_envelope(decision: CanonicalDecisionRecord) -> DecisionEnvelope:
    occurred_at = _canonical_timestamp(decision.created_at)
    action_args = requested_action_args_from_decision(decision)
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
        created_at=occurred_at or decision.created_at,
        occurred_at=occurred_at,
        decision_id=decision.decision_id,
        decision_result=decision.decision_result,
        action_name=decision.action_ref,
        action_args=action_args,
        approval_id=decision.approval_id,
        risk_class=decision.risk_class,
        risk_level=_compatibility_risk_level(decision.risk_class),
        command=_compatibility_command(decision.action_ref, action_args),
        title=f"decision {decision.decision_result}",
        summary=decision.decision_reason,
        reason=decision.decision_reason,
        decision_reason=decision.decision_reason,
        facts=_facts_from_decision(decision),
        matched_policy_rules=_matched_rules(decision),
        why_not_escalated=decision.why_not_escalated,
    )


def _build_decision_notification(decision: CanonicalDecisionRecord) -> NotificationEnvelope:
    occurred_at = _canonical_timestamp(decision.created_at)
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
        created_at=occurred_at or decision.created_at,
        event_id=f"event:{_short_hash(decision.decision_id + '|decision_result')}",
        severity="critical" if decision.decision_result == DECISION_BLOCK_AND_ALERT else "info",
        notification_kind="decision_result",
        occurred_at=occurred_at,
        decision_result=decision.decision_result,
        action_name=decision.action_ref,
        title=f"decision {decision.decision_result}",
        summary=decision.decision_reason,
        reason=decision.decision_reason,
        facts=_facts_from_decision(decision),
        recommended_actions=_recommended_actions(decision),
    )


def _build_approval_envelope(decision: CanonicalDecisionRecord) -> ApprovalEnvelope:
    occurred_at = _canonical_timestamp(decision.created_at)
    approval_id, envelope_id, approval_token = build_canonical_approval_identifiers(decision)
    requested_action_args = requested_action_args_from_decision(decision)
    return ApprovalEnvelope(
        envelope_id=envelope_id,
        correlation_id=decision.decision_id,
        session_id=decision.session_id,
        project_id=decision.project_id,
        native_thread_id=decision.native_thread_id,
        policy_version=decision.policy_version,
        fact_snapshot_version=decision.fact_snapshot_version,
        idempotency_key=f"{decision.idempotency_key}|approval",
        audit_ref=decision.decision_id,
        created_at=occurred_at or decision.created_at,
        approval_id=approval_id,
        approval_kind="canonical_user_decision",
        requested_action=decision.action_ref,
        requested_action_args=requested_action_args,
        risk_class=decision.risk_class,
        risk_level=_compatibility_risk_level(decision.risk_class),
        command=_compatibility_command(decision.action_ref, requested_action_args),
        reason=decision.decision_reason,
        alternative="",
        status="pending",
        requested_at=occurred_at or decision.created_at,
        title=f"approval required for {decision.action_ref}",
        summary=decision.decision_reason,
        facts=_facts_from_decision(decision),
        matched_policy_rules=_matched_rules(decision),
        why_escalated=decision.why_escalated,
        approval_token=approval_token,
    )


def build_approval_envelope_for_record(approval: CanonicalApprovalRecord) -> ApprovalEnvelope:
    decision = approval.decision
    occurred_at = _canonical_timestamp(decision.created_at)
    requested_action_args = dict(approval.requested_action_args)
    return ApprovalEnvelope(
        envelope_id=approval.envelope_id,
        correlation_id=decision.decision_id,
        session_id=approval.session_id,
        project_id=approval.project_id,
        native_thread_id=approval.native_thread_id,
        policy_version=approval.policy_version,
        fact_snapshot_version=approval.fact_snapshot_version,
        idempotency_key=approval.idempotency_key,
        audit_ref=decision.decision_id,
        created_at=occurred_at or decision.created_at,
        approval_id=approval.approval_id,
        approval_kind=approval.approval_kind,
        requested_action=approval.requested_action,
        requested_action_args=requested_action_args,
        risk_class=decision.risk_class,
        risk_level=_compatibility_risk_level(decision.risk_class),
        command=_compatibility_command(approval.requested_action, requested_action_args),
        reason=decision.decision_reason,
        alternative="",
        status=approval.status,
        requested_at=occurred_at or decision.created_at,
        title=f"approval required for {approval.requested_action}",
        summary=decision.decision_reason,
        facts=_facts_from_decision(decision),
        matched_policy_rules=_matched_rules(decision),
        why_escalated=decision.why_escalated,
        approval_token=approval.approval_token,
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
    occurred_at = _canonical_timestamp(response.created_at)
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
            created_at=occurred_at or response.created_at,
            event_id=f"event:{_short_hash(response.response_id + '|approval_result')}",
            severity="critical" if response.approval_status == "rejected" else "info",
            notification_kind="approval_result",
            occurred_at=occurred_at,
            title=f"approval {response.approval_status}",
            summary=f"approval {response.approval_status} via {response.response_action}",
            reason=response.note or response.response_action,
            facts=_facts_from_decision(decision),
            recommended_actions=_recommended_actions(decision),
        )
    ]
