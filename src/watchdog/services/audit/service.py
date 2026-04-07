from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from watchdog.contracts.session_spine.models import WatchdogActionResult
from watchdog.services.approvals.service import (
    ApprovalResponseStore,
    CanonicalApprovalRecord,
    CanonicalApprovalResponseRecord,
    CanonicalApprovalStore,
)
from watchdog.services.delivery.store import DeliveryOutboxRecord, DeliveryOutboxStore
from watchdog.services.policy.decisions import CanonicalDecisionRecord, PolicyDecisionStore
from watchdog.storage.action_receipts import ActionReceiptStore


class CanonicalAuditQuery(BaseModel):
    session_id: str | None = None
    decision_id: str | None = None
    approval_id: str | None = None
    envelope_id: str | None = None
    receipt_id: str | None = None

    def has_filters(self) -> bool:
        return any(
            [
                self.session_id,
                self.decision_id,
                self.approval_id,
                self.envelope_id,
                self.receipt_id,
            ]
        )


class ActionReceiptEntry(BaseModel):
    receipt_key: str
    result: WatchdogActionResult


class CanonicalAuditView(BaseModel):
    filters: CanonicalAuditQuery
    decisions: list[CanonicalDecisionRecord] = Field(default_factory=list)
    approvals: list[CanonicalApprovalRecord] = Field(default_factory=list)
    responses: list[CanonicalApprovalResponseRecord] = Field(default_factory=list)
    deliveries: list[DeliveryOutboxRecord] = Field(default_factory=list)
    action_receipts: list[ActionReceiptEntry] = Field(default_factory=list)


def _delivery_sort_key(record: DeliveryOutboxRecord) -> tuple[str, int, str]:
    return (record.created_at, record.outbox_seq, record.envelope_id)


def _receipt_observed_at(entry: ActionReceiptEntry) -> str:
    if entry.result.facts:
        return entry.result.facts[0].observed_at
    return ""


def _load_decisions(data_dir: Path) -> list[CanonicalDecisionRecord]:
    return PolicyDecisionStore(data_dir / "policy_decisions.json").list_records()


def _load_approvals(data_dir: Path) -> list[CanonicalApprovalRecord]:
    return CanonicalApprovalStore(data_dir / "canonical_approvals.json").list_records()


def _load_responses(data_dir: Path) -> list[CanonicalApprovalResponseRecord]:
    return ApprovalResponseStore(data_dir / "approval_responses.json").list_records()


def _load_deliveries(data_dir: Path) -> list[DeliveryOutboxRecord]:
    return DeliveryOutboxStore(data_dir / "delivery_outbox.json").list_records()


def _load_receipts(data_dir: Path) -> list[ActionReceiptEntry]:
    return [
        ActionReceiptEntry(receipt_key=receipt_key, result=result)
        for receipt_key, result in ActionReceiptStore(data_dir / "action_receipts.json").list_items()
    ]


def query_canonical_audit(data_dir: Path, query: CanonicalAuditQuery) -> CanonicalAuditView:
    decisions = _load_decisions(data_dir)
    approvals = _load_approvals(data_dir)
    responses = _load_responses(data_dir)
    deliveries = _load_deliveries(data_dir)
    receipts = _load_receipts(data_dir)

    decision_map = {record.decision_id: record for record in decisions}
    approval_map = {record.approval_id: record for record in approvals}
    approval_by_envelope = {record.envelope_id: record for record in approvals}
    response_map = {record.response_id: record for record in responses}

    matched_decision_ids: set[str] = set()
    matched_approval_ids: set[str] = set()
    matched_response_ids: set[str] = set()
    matched_envelope_ids: set[str] = set()
    matched_receipt_keys: set[str] = set()
    session_scope: set[str] = set()
    idempotency_scope: set[str] = set()

    def add_decision(record: CanonicalDecisionRecord) -> None:
        matched_decision_ids.add(record.decision_id)
        session_scope.add(record.session_id)
        idempotency_scope.add(record.idempotency_key)
        if record.approval_id:
            matched_approval_ids.add(record.approval_id)

    def add_approval(record: CanonicalApprovalRecord) -> None:
        matched_approval_ids.add(record.approval_id)
        matched_envelope_ids.add(record.envelope_id)
        session_scope.add(record.session_id)
        idempotency_scope.add(record.idempotency_key)
        add_decision(record.decision)

    def add_response(record: CanonicalApprovalResponseRecord) -> None:
        matched_response_ids.add(record.response_id)
        matched_approval_ids.add(record.approval_id)
        matched_envelope_ids.add(record.envelope_id)
        if record.approval_result is not None:
            idempotency_scope.add(record.approval_result.idempotency_key)
        if record.execution_result is not None:
            idempotency_scope.add(record.execution_result.idempotency_key)

    def add_delivery(record: DeliveryOutboxRecord) -> None:
        matched_envelope_ids.add(record.envelope_id)
        session_scope.add(record.session_id)
        if record.audit_ref in decision_map:
            add_decision(decision_map[record.audit_ref])
        if record.audit_ref in response_map:
            add_response(response_map[record.audit_ref])
        if record.envelope_id in approval_by_envelope:
            add_approval(approval_by_envelope[record.envelope_id])
        elif record.correlation_id in approval_map:
            add_approval(approval_map[record.correlation_id])

    if not query.has_filters():
        for record in decisions:
            add_decision(record)
    if query.session_id:
        session_scope.add(query.session_id)
        for record in decisions:
            if record.session_id == query.session_id:
                add_decision(record)
        for record in approvals:
            if record.session_id == query.session_id:
                add_approval(record)
        for record in deliveries:
            if record.session_id == query.session_id:
                add_delivery(record)
    if query.decision_id and query.decision_id in decision_map:
        add_decision(decision_map[query.decision_id])
    if query.approval_id and query.approval_id in approval_map:
        add_approval(approval_map[query.approval_id])
    if query.envelope_id:
        if query.envelope_id in approval_by_envelope:
            add_approval(approval_by_envelope[query.envelope_id])
        for record in deliveries:
            if record.envelope_id == query.envelope_id:
                add_delivery(record)
        for record in responses:
            if record.envelope_id == query.envelope_id:
                add_response(record)
    if query.receipt_id:
        for record in deliveries:
            if record.receipt_id == query.receipt_id:
                add_delivery(record)

    changed = True
    while changed:
        changed = False
        before = (
            len(matched_decision_ids),
            len(matched_approval_ids),
            len(matched_response_ids),
            len(matched_envelope_ids),
            len(matched_receipt_keys),
            len(session_scope),
            len(idempotency_scope),
        )

        for record in approvals:
            if (
                record.approval_id in matched_approval_ids
                or record.envelope_id in matched_envelope_ids
                or (query.session_id and record.session_id in session_scope)
            ):
                add_approval(record)

        for record in responses:
            if record.approval_id in matched_approval_ids or record.envelope_id in matched_envelope_ids:
                add_response(record)

        for record in deliveries:
            if (
                record.envelope_id in matched_envelope_ids
                or record.audit_ref in matched_decision_ids
                or record.audit_ref in matched_response_ids
                or record.correlation_id in matched_approval_ids
                or (query.session_id and record.session_id in session_scope)
                or (query.receipt_id and record.receipt_id == query.receipt_id)
            ):
                add_delivery(record)

        for entry in receipts:
            result = entry.result
            if result.approval_id and result.approval_id in matched_approval_ids:
                matched_receipt_keys.add(entry.receipt_key)
                continue
            if result.idempotency_key in idempotency_scope:
                matched_receipt_keys.add(entry.receipt_key)

        changed = before != (
            len(matched_decision_ids),
            len(matched_approval_ids),
            len(matched_response_ids),
            len(matched_envelope_ids),
            len(matched_receipt_keys),
            len(session_scope),
            len(idempotency_scope),
        )

    matched_decisions = sorted(
        [record for record in decisions if record.decision_id in matched_decision_ids],
        key=lambda record: (record.created_at, record.decision_id),
    )
    matched_approvals = sorted(
        [record for record in approvals if record.approval_id in matched_approval_ids],
        key=lambda record: (record.created_at, record.approval_id),
    )
    matched_responses = sorted(
        [record for record in responses if record.response_id in matched_response_ids],
        key=lambda record: (record.created_at, record.response_id),
    )
    matched_deliveries = sorted(
        [
            record
            for record in deliveries
            if record.envelope_id in matched_envelope_ids
            and (query.receipt_id is None or record.receipt_id == query.receipt_id)
        ],
        key=_delivery_sort_key,
    )
    matched_receipts = sorted(
        [entry for entry in receipts if entry.receipt_key in matched_receipt_keys],
        key=lambda entry: (_receipt_observed_at(entry), entry.receipt_key),
    )
    return CanonicalAuditView(
        filters=query,
        decisions=matched_decisions,
        approvals=matched_approvals,
        responses=matched_responses,
        deliveries=matched_deliveries,
        action_receipts=matched_receipts,
    )
