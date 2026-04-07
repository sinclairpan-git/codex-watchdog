from __future__ import annotations

from pathlib import Path

from _watchdog_audit_fixtures import seed_audit_chain
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
