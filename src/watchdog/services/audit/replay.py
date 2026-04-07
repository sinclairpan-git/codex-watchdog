from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from .service import CanonicalAuditQuery, query_canonical_audit


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


class CanonicalReplayTrace(BaseModel):
    filters: CanonicalAuditQuery
    timeline: list[ReplayTimelineEvent] = Field(default_factory=list)


_EVENT_PRIORITY = {
    "decision": 0,
    "approval": 1,
    "delivery": 2,
    "response": 3,
    "action_receipt": 4,
}


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
