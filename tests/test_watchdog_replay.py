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
