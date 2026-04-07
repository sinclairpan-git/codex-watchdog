from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from watchdog.contracts.session_spine.enums import ActionCode
from watchdog.contracts.session_spine.models import WatchdogAction, WatchdogActionResult
from watchdog.services.a_client.client import AControlAgentClient
from watchdog.services.actions.executor import execute_registered_action_for_decision
from watchdog.services.policy.decisions import CanonicalDecisionRecord
from watchdog.services.policy.rules import DECISION_REQUIRE_USER_DECISION
from watchdog.services.session_spine.actions import execute_watchdog_action
from watchdog.settings import Settings
from watchdog.storage.action_receipts import ActionReceiptStore


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _requested_action_args(decision: CanonicalDecisionRecord) -> dict[str, Any]:
    evidence = decision.evidence if isinstance(decision.evidence, dict) else {}
    requested_action_args = evidence.get("requested_action_args")
    if isinstance(requested_action_args, dict):
        return dict(requested_action_args)
    decision_evidence = evidence.get("decision")
    if isinstance(decision_evidence, dict):
        action_arguments = decision_evidence.get("action_arguments")
        if isinstance(action_arguments, dict):
            return dict(action_arguments)
    return {}


class CanonicalApprovalRecord(BaseModel):
    approval_id: str
    envelope_id: str
    approval_kind: str
    requested_action: str
    requested_action_args: dict[str, Any] = Field(default_factory=dict)
    approval_token: str
    decision_options: list[str] = Field(default_factory=list)
    policy_version: str
    fact_snapshot_version: str
    idempotency_key: str
    project_id: str
    session_id: str
    thread_id: str
    native_thread_id: str | None = None
    status: str
    created_at: str
    decided_at: str | None = None
    decided_by: str | None = None
    operator_notes: list[str] = Field(default_factory=list)
    decision: CanonicalDecisionRecord


class CanonicalApprovalResponseRecord(BaseModel):
    response_id: str
    envelope_id: str
    approval_id: str
    response_action: str
    client_request_id: str
    idempotency_key: str
    project_id: str
    approval_status: str
    operator: str
    note: str = ""
    created_at: str
    operator_notes: list[str] = Field(default_factory=list)
    approval_result: WatchdogActionResult | None = None
    execution_result: WatchdogActionResult | None = None


class _JsonModelStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._write({})

    def _read(self) -> dict[str, dict[str, Any]]:
        raw = self._path.read_text(encoding="utf-8")
        data = json.loads(raw) if raw.strip() else {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)


class CanonicalApprovalStore(_JsonModelStore):
    def get(self, envelope_id: str) -> CanonicalApprovalRecord | None:
        with self._lock:
            row = self._read().get(envelope_id)
        if not isinstance(row, dict):
            return None
        return CanonicalApprovalRecord.model_validate(row)

    def put(self, record: CanonicalApprovalRecord) -> CanonicalApprovalRecord:
        with self._lock:
            data = self._read()
            existing = data.get(record.envelope_id)
            if isinstance(existing, dict):
                return CanonicalApprovalRecord.model_validate(existing)
            data[record.envelope_id] = record.model_dump(mode="json")
            self._write(data)
        return record

    def update(self, record: CanonicalApprovalRecord) -> CanonicalApprovalRecord:
        with self._lock:
            data = self._read()
            data[record.envelope_id] = record.model_dump(mode="json")
            self._write(data)
        return record


class ApprovalResponseStore(_JsonModelStore):
    def get(self, idempotency_key: str) -> CanonicalApprovalResponseRecord | None:
        with self._lock:
            row = self._read().get(idempotency_key)
        if not isinstance(row, dict):
            return None
        return CanonicalApprovalResponseRecord.model_validate(row)

    def put(self, record: CanonicalApprovalResponseRecord) -> CanonicalApprovalResponseRecord:
        with self._lock:
            data = self._read()
            existing = data.get(record.idempotency_key)
            if isinstance(existing, dict):
                return CanonicalApprovalResponseRecord.model_validate(existing)
            data[record.idempotency_key] = record.model_dump(mode="json")
            self._write(data)
        return record


def build_response_idempotency_key(
    *,
    envelope_id: str,
    response_action: str,
    client_request_id: str,
) -> str:
    return "|".join([envelope_id, response_action, client_request_id])


def build_canonical_approval_record(
    decision: CanonicalDecisionRecord,
) -> CanonicalApprovalRecord:
    if decision.decision_result != DECISION_REQUIRE_USER_DECISION:
        raise ValueError("canonical approval requires require_user_decision")
    digest = _short_hash(decision.decision_key)
    approval_id = decision.approval_id or f"approval:{digest}"
    envelope_id = f"approval-envelope:{_short_hash(f'{decision.decision_key}|approval')}"
    approval_token = f"approval-token:{digest}"
    return CanonicalApprovalRecord(
        approval_id=approval_id,
        envelope_id=envelope_id,
        approval_kind="canonical_user_decision",
        requested_action=decision.action_ref,
        requested_action_args=_requested_action_args(decision),
        approval_token=approval_token,
        decision_options=["approve", "reject", "execute_action"],
        policy_version=decision.policy_version,
        fact_snapshot_version=decision.fact_snapshot_version,
        idempotency_key=f"{decision.idempotency_key}|approval",
        project_id=decision.project_id,
        session_id=decision.session_id,
        thread_id=decision.thread_id,
        native_thread_id=decision.native_thread_id,
        status="pending",
        created_at=_utc_now_iso(),
        operator_notes=[
            f"approval pending requested_action={decision.action_ref}",
            f"policy={decision.policy_version} snapshot={decision.fact_snapshot_version}",
        ],
        decision=decision,
    )


def materialize_canonical_approval(
    decision: CanonicalDecisionRecord,
    *,
    approval_store: CanonicalApprovalStore,
    delivery_outbox_store: object | None = None,
) -> CanonicalApprovalRecord:
    record = approval_store.put(build_canonical_approval_record(decision))
    if delivery_outbox_store is not None:
        from watchdog.services.delivery.envelopes import build_envelopes_for_decision

        delivery_outbox_store.enqueue_envelopes(build_envelopes_for_decision(record.decision))
    return record


def _approval_action_result(
    approval: CanonicalApprovalRecord,
    *,
    response_action: str,
    operator: str,
    note: str,
    settings: Settings,
    client: AControlAgentClient,
    receipt_store: ActionReceiptStore,
) -> WatchdogActionResult:
    if response_action not in {"approve", "reject"}:
        raise ValueError("response_action must be approve or reject")
    action_code = (
        ActionCode.APPROVE_APPROVAL if response_action == "approve" else ActionCode.REJECT_APPROVAL
    )
    action = WatchdogAction(
        action_code=action_code,
        project_id=approval.project_id,
        operator=operator,
        idempotency_key=f"{approval.idempotency_key}|{response_action}",
        arguments={"approval_id": approval.approval_id},
        note=note,
    )
    return execute_watchdog_action(
        action,
        settings=settings,
        client=client,
        receipt_store=receipt_store,
    )


def _transition_approval(
    approval: CanonicalApprovalRecord,
    *,
    status: str,
    operator: str,
    response_action: str,
) -> CanonicalApprovalRecord:
    notes = list(approval.operator_notes)
    notes.append(f"response={response_action} status={status} operator={operator}")
    return approval.model_copy(
        update={
            "status": status,
            "decided_at": _utc_now_iso(),
            "decided_by": operator,
            "operator_notes": notes,
        }
    )


def respond_to_canonical_approval(
    *,
    envelope_id: str,
    response_action: str,
    client_request_id: str,
    operator: str,
    note: str,
    approval_store: CanonicalApprovalStore,
    response_store: ApprovalResponseStore,
    settings: Settings,
    client: AControlAgentClient,
    receipt_store: ActionReceiptStore,
    delivery_outbox_store: object | None = None,
) -> CanonicalApprovalResponseRecord:
    if response_action not in {"approve", "reject", "execute_action"}:
        raise ValueError("response_action must be approve, reject, or execute_action")
    response_key = build_response_idempotency_key(
        envelope_id=envelope_id,
        response_action=response_action,
        client_request_id=client_request_id,
    )
    existing = response_store.get(response_key)
    if existing is not None:
        return existing
    approval = approval_store.get(envelope_id)
    if approval is None:
        raise KeyError(f"unknown approval envelope: {envelope_id}")
    if approval.status == "rejected" and response_action in {"approve", "execute_action"}:
        raise ValueError("rejected approval cannot be approved or executed")
    if approval.status == "approved" and response_action == "reject":
        raise ValueError("approved approval cannot be rejected")

    approval_result: WatchdogActionResult | None = None
    execution_result: WatchdogActionResult | None = None
    next_status = approval.status

    if response_action == "reject":
        approval_result = _approval_action_result(
            approval,
            response_action="reject",
            operator=operator,
            note=note,
            settings=settings,
            client=client,
            receipt_store=receipt_store,
        )
        next_status = "rejected"
    else:
        if approval.status != "approved":
            approval_result = _approval_action_result(
                approval,
                response_action="approve",
                operator=operator,
                note=note,
                settings=settings,
                client=client,
                receipt_store=receipt_store,
            )
        next_status = "approved"
        execution_result = execute_registered_action_for_decision(
            approval.decision,
            settings=settings,
            client=client,
            receipt_store=receipt_store,
            operator=operator,
        )

    updated_approval = _transition_approval(
        approval,
        status=next_status,
        operator=operator,
        response_action=response_action,
    )
    approval_store.update(updated_approval)

    operator_notes = [
        f"response={response_action} operator={operator}",
        f"approval_status={next_status}",
    ]
    if execution_result is not None:
        operator_notes.append(
            f"execution={execution_result.action_status} effect={execution_result.effect}"
        )
    response = CanonicalApprovalResponseRecord(
        response_id=f"approval-response:{_short_hash(response_key)}",
        envelope_id=envelope_id,
        approval_id=updated_approval.approval_id,
        response_action=response_action,
        client_request_id=client_request_id,
        idempotency_key=response_key,
        project_id=updated_approval.project_id,
        approval_status=next_status,
        operator=operator,
        note=note,
        created_at=_utc_now_iso(),
        operator_notes=operator_notes,
        approval_result=approval_result,
        execution_result=execution_result,
    )
    persisted_response = response_store.put(response)
    if delivery_outbox_store is not None:
        from watchdog.services.delivery.envelopes import build_envelopes_for_approval_response

        delivery_outbox_store.enqueue_envelopes(
            build_envelopes_for_approval_response(updated_approval, persisted_response)
        )
    return persisted_response
