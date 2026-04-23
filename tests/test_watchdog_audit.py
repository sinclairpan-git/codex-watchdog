from __future__ import annotations

from pathlib import Path

from _watchdog_audit_fixtures import seed_audit_chain
from watchdog.services.session_service import SessionService, SessionServiceStore
from watchdog.services.audit.service import CanonicalAuditQuery, query_canonical_audit


def test_canonical_audit_query_collects_linked_records_by_session_id(tmp_path: Path) -> None:
    ids = seed_audit_chain(tmp_path)

    view = query_canonical_audit(
        tmp_path,
        CanonicalAuditQuery(session_id=ids["session_id"]),
    )

    assert view.filters.session_id == ids["session_id"]
    assert [record.decision_id for record in view.decisions] == [ids["decision_id"]]
    assert [record.approval_id for record in view.approvals] == [ids["approval_id"]]
    assert [record.response_id for record in view.responses] == [ids["response_id"]]
    assert [record.envelope_id for record in view.deliveries] == [
        ids["approval_envelope_id"],
        ids["approval_result_envelope_id"],
    ]
    assert [record.receipt_key for record in view.action_receipts] == [
        ids["approval_receipt_key"],
        ids["execution_receipt_key"],
    ]


def test_canonical_audit_query_resolves_receipt_id_back_to_response_chain(tmp_path: Path) -> None:
    ids = seed_audit_chain(tmp_path)

    view = query_canonical_audit(
        tmp_path,
        CanonicalAuditQuery(receipt_id=ids["receipt_id"]),
    )

    assert view.filters.receipt_id == ids["receipt_id"]
    assert [record.envelope_id for record in view.deliveries] == [ids["approval_result_envelope_id"]]
    assert [record.response_id for record in view.responses] == [ids["response_id"]]
    assert [record.approval_id for record in view.approvals] == [ids["approval_id"]]
    assert [record.decision_id for record in view.decisions] == [ids["decision_id"]]


def test_canonical_audit_query_includes_session_service_events_for_session_scope(
    tmp_path: Path,
) -> None:
    ids = seed_audit_chain(tmp_path)
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    session_service.record_event(
        event_type="approval_requested",
        project_id="repo-a",
        session_id=ids["session_id"],
        correlation_id=f"corr:approval:{ids['approval_id']}",
        causation_id=ids["decision_id"],
        related_ids={
            "approval_id": ids["approval_id"],
            "decision_id": ids["decision_id"],
        },
        payload={"requested_action": "execute_recovery"},
        occurred_at="2026-04-07T00:00:01Z",
    )
    session_service.record_event(
        event_type="notification_receipt_recorded",
        project_id="repo-a",
        session_id=ids["session_id"],
        correlation_id=f"corr:notification:{ids['approval_result_envelope_id']}:receipt:{ids['receipt_id']}",
        causation_id=ids["approval_result_envelope_id"],
        related_ids={
            "approval_id": ids["approval_id"],
            "envelope_id": ids["approval_result_envelope_id"],
            "receipt_id": ids["receipt_id"],
        },
        payload={
            "delivery_status": "delivered",
            "receipt_id": ids["receipt_id"],
        },
        occurred_at="2026-04-07T00:00:06Z",
    )

    view = query_canonical_audit(
        tmp_path,
        CanonicalAuditQuery(session_id=ids["session_id"]),
    )

    assert [record.event_type for record in view.session_events] == [
        "approval_requested",
        "notification_receipt_recorded",
    ]
    assert view.session_events[0].related_ids["decision_id"] == ids["decision_id"]
    assert view.session_events[1].related_ids["receipt_id"] == ids["receipt_id"]
