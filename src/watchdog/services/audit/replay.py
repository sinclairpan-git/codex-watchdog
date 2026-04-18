from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from .service import CanonicalAuditQuery, query_canonical_audit


class ReplayResidentExpertConsultationExpert(BaseModel):
    expert_id: str
    status: str
    runtime_handle: str | None = None
    last_seen_at: str | None = None
    last_consulted_at: str | None = None
    last_consultation_ref: str | None = None


class ReplayResidentExpertConsultation(BaseModel):
    consultation_ref: str
    consulted_at: str
    coverage_status: str | None = None
    degraded_expert_ids: list[str] = Field(default_factory=list)
    experts: list[ReplayResidentExpertConsultationExpert] = Field(default_factory=list)


class ReplayTimelineEvent(BaseModel):
    event_kind: str
    ref_id: str
    occurred_at: str
    summary: str
    session_id: str | None = None
    decision_id: str | None = None
    approval_id: str | None = None
    envelope_id: str | None = None
    receipt_id: str | None = None
    resident_expert_consultation: ReplayResidentExpertConsultation | None = None


class CanonicalReplayTrace(BaseModel):
    filters: CanonicalAuditQuery
    timeline: list[ReplayTimelineEvent] = Field(default_factory=list)


_EVENT_PRIORITY = {
    "decision": 0,
    "resident_expert_consultation": 1,
    "approval": 2,
    "delivery": 3,
    "response": 4,
    "action_receipt": 5,
}


def _materialize_resident_expert_consultation(record) -> ReplayResidentExpertConsultation | None:
    evidence = record.evidence if isinstance(record.evidence, dict) else {}
    raw_bundle = evidence.get("resident_expert_consultation")
    if not isinstance(raw_bundle, dict):
        return None
    consultation_ref = str(raw_bundle.get("consultation_ref") or "").strip() or record.decision_id
    consulted_at = str(raw_bundle.get("consulted_at") or "").strip() or record.created_at
    raw_experts = raw_bundle.get("experts")
    experts = (
        [
            ReplayResidentExpertConsultationExpert.model_validate(item)
            for item in raw_experts
            if isinstance(item, dict)
        ]
        if isinstance(raw_experts, list)
        else []
    )
    degraded_expert_ids = raw_bundle.get("degraded_expert_ids")
    return ReplayResidentExpertConsultation(
        consultation_ref=consultation_ref,
        consulted_at=consulted_at,
        coverage_status=str(raw_bundle.get("coverage_status") or "").strip() or None,
        degraded_expert_ids=(
            [str(item) for item in degraded_expert_ids if isinstance(item, str)]
            if isinstance(degraded_expert_ids, list)
            else []
        ),
        experts=experts,
    )


def replay_canonical_audit(data_dir: Path, query: CanonicalAuditQuery) -> CanonicalReplayTrace:
    audit = query_canonical_audit(data_dir, query)
    timeline: list[ReplayTimelineEvent] = []

    for record in audit.decisions:
        timeline.append(
            ReplayTimelineEvent(
                event_kind="decision",
                ref_id=record.decision_id,
                occurred_at=record.created_at,
                summary=f"decision {record.decision_result}",
                session_id=record.session_id,
                decision_id=record.decision_id,
                approval_id=record.approval_id,
            )
        )
        consultation = _materialize_resident_expert_consultation(record)
        if consultation is not None:
            timeline.append(
                ReplayTimelineEvent(
                    event_kind="resident_expert_consultation",
                    ref_id=consultation.consultation_ref,
                    occurred_at=consultation.consulted_at,
                    summary=(
                        "resident expert consultation "
                        f"{consultation.coverage_status or 'recorded'}"
                    ),
                    session_id=record.session_id,
                    decision_id=record.decision_id,
                    approval_id=record.approval_id,
                    resident_expert_consultation=consultation,
                )
            )
    for record in audit.approvals:
        timeline.append(
            ReplayTimelineEvent(
                event_kind="approval",
                ref_id=record.approval_id,
                occurred_at=record.created_at,
                summary=f"approval {record.status}",
                session_id=record.session_id,
                decision_id=record.decision.decision_id,
                approval_id=record.approval_id,
                envelope_id=record.envelope_id,
            )
        )
    for record in audit.deliveries:
        timeline.append(
            ReplayTimelineEvent(
                event_kind="delivery",
                ref_id=record.envelope_id,
                occurred_at=record.created_at,
                summary=f"delivery {record.delivery_status}",
                session_id=record.session_id,
                envelope_id=record.envelope_id,
                receipt_id=record.receipt_id,
            )
        )
    for record in audit.responses:
        timeline.append(
            ReplayTimelineEvent(
                event_kind="response",
                ref_id=record.response_id,
                occurred_at=record.created_at,
                summary=f"response {record.response_action}",
                approval_id=record.approval_id,
                envelope_id=record.envelope_id,
            )
        )
    for entry in audit.action_receipts:
        occurred_at = entry.result.facts[0].observed_at if entry.result.facts else ""
        timeline.append(
            ReplayTimelineEvent(
                event_kind="action_receipt",
                ref_id=entry.receipt_key,
                occurred_at=occurred_at,
                summary=f"action receipt {entry.result.action_code}",
                approval_id=entry.result.approval_id,
            )
        )

    timeline.sort(key=lambda item: (item.occurred_at, _EVENT_PRIORITY[item.event_kind], item.ref_id))
    return CanonicalReplayTrace(filters=query, timeline=timeline)
