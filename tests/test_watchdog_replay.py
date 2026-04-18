from __future__ import annotations

from pathlib import Path

from _watchdog_audit_fixtures import seed_audit_chain
from watchdog.services.audit.replay import replay_canonical_audit
from watchdog.services.audit.service import CanonicalAuditQuery


def test_replay_canonical_audit_orders_linked_chain_for_decision_id(tmp_path: Path) -> None:
    ids = seed_audit_chain(tmp_path)

    trace = replay_canonical_audit(
        tmp_path,
        CanonicalAuditQuery(decision_id=ids["decision_id"]),
    )

    assert [event.event_kind for event in trace.timeline] == [
        "decision",
        "approval",
        "delivery",
        "response",
        "action_receipt",
        "action_receipt",
        "delivery",
    ]
    assert trace.timeline[0].decision_id == ids["decision_id"]
    assert trace.timeline[-1].receipt_id == ids["receipt_id"]


def test_replay_canonical_audit_can_start_from_receipt_id(tmp_path: Path) -> None:
    ids = seed_audit_chain(tmp_path)

    trace = replay_canonical_audit(
        tmp_path,
        CanonicalAuditQuery(receipt_id=ids["receipt_id"]),
    )

    assert trace.filters.receipt_id == ids["receipt_id"]
    assert [event.event_kind for event in trace.timeline] == [
        "decision",
        "approval",
        "response",
        "action_receipt",
        "action_receipt",
        "delivery",
    ]
    assert trace.timeline[-1].envelope_id == ids["approval_result_envelope_id"]


def test_replay_canonical_audit_materializes_resident_expert_consultation_event(
    tmp_path: Path,
) -> None:
    ids = seed_audit_chain(tmp_path, with_resident_expert_consultation=True)

    trace = replay_canonical_audit(
        tmp_path,
        CanonicalAuditQuery(decision_id=ids["decision_id"]),
    )

    assert [event.event_kind for event in trace.timeline] == [
        "decision",
        "resident_expert_consultation",
        "approval",
        "delivery",
        "response",
        "action_receipt",
        "action_receipt",
        "delivery",
    ]
    consultation = trace.timeline[1]
    assert consultation.ref_id == ids["decision_id"]
    assert consultation.session_id == ids["session_id"]
    assert consultation.decision_id == ids["decision_id"]
    assert consultation.summary == "resident expert consultation degraded"
    assert consultation.resident_expert_consultation is not None
    assert consultation.resident_expert_consultation.model_dump(mode="json") == {
        "consultation_ref": ids["decision_id"],
        "consulted_at": "2026-04-07T00:00:00Z",
        "coverage_status": "degraded",
        "degraded_expert_ids": ["hermes-agent-expert"],
        "experts": [
            {
                "expert_id": "managed-agent-expert",
                "status": "available",
                "runtime_handle": "agent:managed:1",
                "last_seen_at": "2026-04-06T23:59:30Z",
                "last_consulted_at": "2026-04-07T00:00:00Z",
                "last_consultation_ref": ids["decision_id"],
            },
            {
                "expert_id": "hermes-agent-expert",
                "status": "stale",
                "runtime_handle": "agent:hermes:1",
                "last_seen_at": "2026-04-06T23:55:00Z",
                "last_consulted_at": "2026-04-07T00:00:00Z",
                "last_consultation_ref": ids["decision_id"],
            },
        ],
    }
