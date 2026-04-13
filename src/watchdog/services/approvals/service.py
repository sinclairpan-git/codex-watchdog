from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from typing import Callable

from pydantic import BaseModel, Field

from watchdog.contracts.session_spine.enums import ActionCode
from watchdog.contracts.session_spine.models import WatchdogAction, WatchdogActionResult
from watchdog.services.a_client.client import AControlAgentClient
from watchdog.services.actions.executor import execute_registered_action_for_decision
from watchdog.services.policy.decisions import CanonicalDecisionRecord
from watchdog.services.policy.rules import DECISION_REQUIRE_USER_DECISION
from watchdog.services.session_service.service import SessionService
from watchdog.services.session_spine.actions import execute_watchdog_action
from watchdog.settings import Settings
from watchdog.storage.action_receipts import ActionReceiptStore


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _fact_snapshot_order(value: str) -> tuple[int, str]:
    match = re.fullmatch(r"fact-v(\d+)", value)
    if match is None:
        return (2**31 - 1, value)
    return (int(match.group(1)), value)


def _timestamp_order(value: str | None) -> tuple[int, str]:
    if not value:
        return (0, "")
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return (0, str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (1, parsed.astimezone(timezone.utc).isoformat())


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


def requested_action_args_from_decision(decision: CanonicalDecisionRecord) -> dict[str, Any]:
    return _requested_action_args(decision)


def _approval_identity_seed(decision: CanonicalDecisionRecord) -> str:
    if decision.approval_id:
        return f"approval_id|{decision.approval_id}"
    return "|".join(
        [
            decision.session_id,
            decision.project_id,
            decision.policy_version,
            decision.decision_result,
            decision.action_ref,
        ]
    )


def build_canonical_approval_identifiers(
    decision: CanonicalDecisionRecord,
) -> tuple[str, str, str]:
    seed = _approval_identity_seed(decision)
    digest = _short_hash(seed)
    approval_id = decision.approval_id or f"approval:{digest}"
    envelope_id = f"approval-envelope:{_short_hash(f'{seed}|approval')}"
    approval_token = f"approval-token:{digest}"
    return approval_id, envelope_id, approval_token


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
            existing_record = self._find_existing_record_for_put(data, record)
            if existing_record is not None:
                if not self._should_refresh_pending_record(existing_record, record):
                    return existing_record
                record = self._refresh_pending_record(existing_record, record)
            data[record.envelope_id] = record.model_dump(mode="json")
            self._write(data)
        return record

    def update(self, record: CanonicalApprovalRecord) -> CanonicalApprovalRecord:
        with self._lock:
            data = self._read()
            data[record.envelope_id] = record.model_dump(mode="json")
            self._write(data)
        return record

    def list_records(self) -> list[CanonicalApprovalRecord]:
        with self._lock:
            data = self._read()
        return [CanonicalApprovalRecord.model_validate(row) for row in data.values()]

    def supersede_pending_records(
        self,
        *,
        session_id: str,
        fact_snapshot_version: str,
        reason: str,
        project_id: str | None = None,
        decided_by: str = "policy-supersede",
    ) -> list[CanonicalApprovalRecord]:
        threshold = _fact_snapshot_order(fact_snapshot_version)
        updated_records: list[CanonicalApprovalRecord] = []
        with self._lock:
            data = self._read()
            changed = False
            for envelope_id, row in data.items():
                if not isinstance(row, dict):
                    continue
                record = CanonicalApprovalRecord.model_validate(row)
                if record.status != "pending":
                    continue
                if record.session_id != session_id:
                    continue
                if project_id is not None and record.project_id != project_id:
                    continue
                if _fact_snapshot_order(record.fact_snapshot_version) > threshold:
                    continue
                notes = list(record.operator_notes)
                notes.append(reason)
                updated = record.model_copy(
                    update={
                        "status": "superseded",
                        "decided_at": _utc_now_iso(),
                        "decided_by": decided_by,
                        "operator_notes": notes,
                    }
                )
                data[envelope_id] = updated.model_dump(mode="json")
                updated_records.append(updated)
                changed = True
            if changed:
                self._write(data)
        return updated_records

    def reconcile_pending_records_against_decisions(
        self,
        decisions: list[CanonicalDecisionRecord],
        *,
        decided_by: str = "policy-reconcile",
    ) -> list[CanonicalApprovalRecord]:
        latest_superseding_decisions: dict[tuple[str, str], CanonicalDecisionRecord] = {}
        for decision in decisions:
            if decision.decision_result == DECISION_REQUIRE_USER_DECISION:
                continue
            key = (decision.session_id, decision.project_id)
            existing = latest_superseding_decisions.get(key)
            if existing is not None and (
                _fact_snapshot_order(existing.fact_snapshot_version)
                >= _fact_snapshot_order(decision.fact_snapshot_version)
            ):
                continue
            latest_superseding_decisions[key] = decision
        if not latest_superseding_decisions:
            return []

        updated_records: list[CanonicalApprovalRecord] = []
        with self._lock:
            data = self._read()
            changed = False
            for envelope_id, row in data.items():
                if not isinstance(row, dict):
                    continue
                record = CanonicalApprovalRecord.model_validate(row)
                if record.status != "pending":
                    continue
                decision = latest_superseding_decisions.get((record.session_id, record.project_id))
                if decision is None:
                    continue
                if (
                    _fact_snapshot_order(record.fact_snapshot_version)
                    > _fact_snapshot_order(decision.fact_snapshot_version)
                ):
                    continue
                notes = list(record.operator_notes)
                notes.append(
                    "approval_superseded_by_historical_decision "
                    f"decision_id={decision.decision_id} "
                    f"result={decision.decision_result} "
                    f"action={decision.action_ref} "
                    f"snapshot={decision.fact_snapshot_version}"
                )
                updated = record.model_copy(
                    update={
                        "status": "superseded",
                        "decided_at": _utc_now_iso(),
                        "decided_by": decided_by,
                        "operator_notes": notes,
                    }
                )
                data[envelope_id] = updated.model_dump(mode="json")
                updated_records.append(updated)
                changed = True
            if changed:
                self._write(data)
        return updated_records

    def reconcile_duplicate_pending_records_by_approval_id(
        self,
        *,
        decided_by: str = "policy-approval-id-reconcile",
    ) -> list[CanonicalApprovalRecord]:
        updated_records: list[CanonicalApprovalRecord] = []
        with self._lock:
            data = self._read()
            pending_by_approval_id: dict[str, list[CanonicalApprovalRecord]] = {}
            for row in data.values():
                if not isinstance(row, dict):
                    continue
                record = CanonicalApprovalRecord.model_validate(row)
                if record.status != "pending":
                    continue
                pending_by_approval_id.setdefault(record.approval_id, []).append(record)

            changed = False
            for records in pending_by_approval_id.values():
                if len(records) < 2:
                    continue
                ordered = sorted(records, key=self._pending_record_order)
                kept = ordered[-1]
                for duplicate in ordered[:-1]:
                    notes = list(duplicate.operator_notes)
                    notes.append(
                        "approval_superseded_by_duplicate_approval_id "
                        f"approval_id={duplicate.approval_id} "
                        f"kept_envelope_id={kept.envelope_id} "
                        f"kept_snapshot={kept.fact_snapshot_version}"
                    )
                    updated = duplicate.model_copy(
                        update={
                            "status": "superseded",
                            "decided_at": _utc_now_iso(),
                            "decided_by": decided_by,
                            "operator_notes": notes,
                        }
                    )
                    data[duplicate.envelope_id] = updated.model_dump(mode="json")
                    updated_records.append(updated)
                    changed = True
            if changed:
                self._write(data)
        return updated_records

    @staticmethod
    def _should_refresh_pending_record(
        existing: CanonicalApprovalRecord,
        incoming: CanonicalApprovalRecord,
    ) -> bool:
        if existing.status != "pending" or incoming.status != "pending":
            return False
        existing_snapshot = _fact_snapshot_order(existing.fact_snapshot_version)
        incoming_snapshot = _fact_snapshot_order(incoming.fact_snapshot_version)
        if incoming_snapshot < existing_snapshot:
            return False
        if incoming_snapshot > existing_snapshot:
            return True
        return incoming.model_dump(mode="json") != existing.model_dump(mode="json")

    @staticmethod
    def _refresh_pending_record(
        existing: CanonicalApprovalRecord,
        incoming: CanonicalApprovalRecord,
    ) -> CanonicalApprovalRecord:
        notes = list(existing.operator_notes)
        notes.extend(incoming.operator_notes)
        notes.append(
            "approval_refreshed "
            f"previous_snapshot={existing.fact_snapshot_version} "
            f"new_snapshot={incoming.fact_snapshot_version}"
        )
        return incoming.model_copy(
            update={
                "approval_id": existing.approval_id,
                "envelope_id": existing.envelope_id,
                "approval_token": existing.approval_token,
                "created_at": existing.created_at,
                "operator_notes": notes,
            }
        )

    @staticmethod
    def _pending_record_order(record: CanonicalApprovalRecord) -> tuple[tuple[int, str], tuple[int, str], str]:
        return (
            _fact_snapshot_order(record.fact_snapshot_version),
            _timestamp_order(record.created_at),
            record.envelope_id,
        )

    @classmethod
    def _find_existing_record_for_put(
        cls,
        data: dict[str, dict[str, Any]],
        incoming: CanonicalApprovalRecord,
    ) -> CanonicalApprovalRecord | None:
        existing = data.get(incoming.envelope_id)
        if isinstance(existing, dict):
            return CanonicalApprovalRecord.model_validate(existing)
        pending_matches: list[CanonicalApprovalRecord] = []
        for row in data.values():
            if not isinstance(row, dict):
                continue
            record = CanonicalApprovalRecord.model_validate(row)
            if record.approval_id != incoming.approval_id:
                continue
            if record.status != "pending":
                continue
            pending_matches.append(record)
        if not pending_matches:
            return None
        return max(pending_matches, key=cls._pending_record_order)


class ApprovalResponseStore(_JsonModelStore):
    def get(self, idempotency_key: str) -> CanonicalApprovalResponseRecord | None:
        with self._lock:
            row = self._read().get(idempotency_key)
        if not isinstance(row, dict):
            return None
        return CanonicalApprovalResponseRecord.model_validate(row)

    def create_or_get(
        self,
        idempotency_key: str,
        factory: Callable[[], CanonicalApprovalResponseRecord],
    ) -> CanonicalApprovalResponseRecord:
        # Serialize idempotent response creation so concurrent retries cannot
        # duplicate approval or action side effects before the response is stored.
        with self._lock:
            data = self._read()
            existing = data.get(idempotency_key)
            if isinstance(existing, dict):
                return CanonicalApprovalResponseRecord.model_validate(existing)
            record = factory()
            data[idempotency_key] = record.model_dump(mode="json")
            self._write(data)
        return record

    def put(self, record: CanonicalApprovalResponseRecord) -> CanonicalApprovalResponseRecord:
        with self._lock:
            data = self._read()
            existing = data.get(record.idempotency_key)
            if isinstance(existing, dict):
                return CanonicalApprovalResponseRecord.model_validate(existing)
            data[record.idempotency_key] = record.model_dump(mode="json")
            self._write(data)
        return record

    def list_records(self) -> list[CanonicalApprovalResponseRecord]:
        with self._lock:
            data = self._read()
        return [CanonicalApprovalResponseRecord.model_validate(row) for row in data.values()]


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
    approval_id, envelope_id, approval_token = build_canonical_approval_identifiers(decision)
    return CanonicalApprovalRecord(
        approval_id=approval_id,
        envelope_id=envelope_id,
        approval_kind="canonical_user_decision",
        requested_action=decision.action_ref,
        requested_action_args=requested_action_args_from_decision(decision),
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
    session_service: SessionService | None = None,
) -> CanonicalApprovalRecord:
    record = approval_store.put(build_canonical_approval_record(decision))
    if session_service is not None:
        session_service.record_event(
            event_type="approval_requested",
            project_id=record.project_id,
            session_id=record.session_id,
            correlation_id=f"corr:approval:{record.approval_id}",
            causation_id=record.decision.decision_id,
            related_ids={
                "approval_id": record.approval_id,
                "decision_id": record.decision.decision_id,
            },
            payload={
                "requested_action": record.requested_action,
                "decision_options": list(record.decision_options),
                "fact_snapshot_version": record.fact_snapshot_version,
                "policy_version": record.policy_version,
            },
        )
    if delivery_outbox_store is not None:
        from watchdog.services.delivery.envelopes import build_approval_envelope_for_record

        delivery_outbox_store.enqueue_envelopes([build_approval_envelope_for_record(record)])
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
    session_service: SessionService | None = None,
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
        session_service=session_service,
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
    session_service: SessionService | None = None,
) -> CanonicalApprovalResponseRecord:
    if response_action not in {"approve", "reject", "execute_action"}:
        raise ValueError("response_action must be approve, reject, or execute_action")
    response_key = build_response_idempotency_key(
        envelope_id=envelope_id,
        response_action=response_action,
        client_request_id=client_request_id,
    )
    def _build_response() -> CanonicalApprovalResponseRecord:
        approval = approval_store.get(envelope_id)
        if approval is None:
            raise KeyError(f"unknown approval envelope: {envelope_id}")
        if approval.status == "superseded":
            raise ValueError("superseded approval cannot be approved, rejected, or executed")
        if approval.status == "rejected" and response_action in {"approve", "execute_action"}:
            raise ValueError("rejected approval cannot be approved or executed")
        if approval.status == "approved" and response_action == "reject":
            raise ValueError("approved approval cannot be rejected")

        approval_result: WatchdogActionResult | None = None
        execution_result: WatchdogActionResult | None = None
        next_status = approval.status
        response_id = f"approval-response:{_short_hash(response_key)}"

        if response_action == "reject":
            approval_result = _approval_action_result(
                approval,
                response_action="reject",
                operator=operator,
                note=note,
                settings=settings,
                client=client,
                receipt_store=receipt_store,
                session_service=session_service,
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
                    session_service=session_service,
                )
            next_status = "approved"
            execution_result = execute_registered_action_for_decision(
                approval.decision,
                settings=settings,
                client=client,
                receipt_store=receipt_store,
                session_service=session_service,
                operator=operator,
            )

        updated_approval = _transition_approval(
            approval,
            status=next_status,
            operator=operator,
            response_action=response_action,
        )
        approval_store.update(updated_approval)
        if session_service is not None:
            session_service.record_event(
                event_type=(
                    "approval_approved" if next_status == "approved" else "approval_rejected"
                ),
                project_id=updated_approval.project_id,
                session_id=updated_approval.session_id,
                correlation_id=f"corr:approval:{updated_approval.approval_id}",
                causation_id=updated_approval.decision.decision_id,
                related_ids={
                    "approval_id": updated_approval.approval_id,
                    "decision_id": updated_approval.decision.decision_id,
                    "response_id": response_id,
                },
                payload={
                    "response_action": response_action,
                    "approval_status": next_status,
                    "operator": operator,
                    "note": note,
                },
            )
            override_payload = {
                "response_action": response_action,
                "approval_status": next_status,
                "operator": operator,
                "note": note,
                "requested_action": updated_approval.requested_action,
            }
            if execution_result is not None:
                override_payload["execution_status"] = execution_result.action_status
                override_payload["execution_effect"] = execution_result.effect
            session_service.record_event(
                event_type="human_override_recorded",
                project_id=updated_approval.project_id,
                session_id=updated_approval.session_id,
                correlation_id=f"corr:override:{response_id}",
                causation_id=response_id,
                related_ids={
                    "approval_id": updated_approval.approval_id,
                    "decision_id": updated_approval.decision.decision_id,
                    "response_id": response_id,
                    "envelope_id": updated_approval.envelope_id,
                },
                payload=override_payload,
            )

        operator_notes = [
            f"response={response_action} operator={operator}",
            f"approval_status={next_status}",
        ]
        if execution_result is not None:
            operator_notes.append(
                f"execution={execution_result.action_status} effect={execution_result.effect}"
            )
        response = CanonicalApprovalResponseRecord(
            response_id=response_id,
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
        if delivery_outbox_store is not None:
            from watchdog.services.delivery.envelopes import (
                build_envelopes_for_approval_response,
            )

            delivery_outbox_store.enqueue_envelopes(
                build_envelopes_for_approval_response(updated_approval, response)
            )
        return response

    return response_store.create_or_get(response_key, _build_response)
