from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from a_control_agent.envelope import ok
from watchdog.api.deps import require_token
from watchdog.contracts.session_spine.enums import ActionCode, ActionStatus
from watchdog.services.brain.release_gate import normalize_runtime_gate_reason
from watchdog.services.brain.release_gate_read_contract import (
    read_release_gate_decision_evidence,
)
from watchdog.services.approvals.service import CanonicalApprovalRecord, CanonicalApprovalStore
from watchdog.services.delivery.store import DeliveryOutboxRecord, DeliveryOutboxStore
from watchdog.services.policy.decisions import PolicyDecisionStore
from watchdog.services.resident_experts.service import ResidentExpertRuntimeService
from watchdog.services.session_service.service import SessionService
from watchdog.settings import Settings
from watchdog.storage.action_receipts import ActionReceiptStore

router = APIRouter(prefix="/watchdog/ops", tags=["watchdog"])

_NON_ALERTING_DELIVERY_FAILURE_CODES = {
    "suppressed_local_manual_activity",
    "stale_progress_summary",
    "stale_auto_execute_notification",
}

_RUNTIME_GATE_ALERT_RULES = {
    "runtime_gate_missing",
    "release_gate_degraded",
    "validator_gate_degraded",
}

_FUTURE_WORKER_EVENT_TYPES = {
    "future_worker_requested",
    "future_worker_started",
    "future_worker_heartbeat",
    "future_worker_summary_published",
    "future_worker_completed",
    "future_worker_failed",
    "future_worker_cancelled",
    "future_worker_transition_rejected",
    "future_worker_result_consumed",
    "future_worker_result_rejected",
}

_FUTURE_WORKER_STATUS_BY_EVENT_TYPE = {
    "future_worker_requested": "requested",
    "future_worker_started": "running",
    "future_worker_heartbeat": "running",
    "future_worker_summary_published": "running",
    "future_worker_completed": "completed",
    "future_worker_failed": "failed",
    "future_worker_cancelled": "cancelled",
    "future_worker_result_consumed": "consumed",
    "future_worker_result_rejected": "rejected",
}


def _fact_snapshot_order(value: str) -> tuple[int, str]:
    match = re.fullmatch(r"fact-v(\d+)", value)
    if match is None:
        return (2**31 - 1, value)
    return (int(match.group(1)), value)


class OpsAlert(BaseModel):
    alert_code: str
    severity: str
    count: int
    summary: str


class OpsReleaseGateBlocker(BaseModel):
    decision_id: str
    project_id: str
    session_id: str
    reason: str
    report_id: str | None = None
    report_hash: str | None = None
    input_hash: str | None = None
    report_ref: str | None = None
    certification_packet_corpus_ref: str | None = None
    shadow_decision_ledger_ref: str | None = None
    label_manifest_ref: str | None = None
    generated_by: str | None = None
    report_approved_by: str | None = None


class OpsFutureWorkerStatus(BaseModel):
    project_id: str
    session_id: str
    worker_task_ref: str
    status: str
    last_event_type: str
    occurred_at: str
    decision_trace_ref: str | None = None
    blocking_reason: str | None = None


class OpsSummary(BaseModel):
    status: str
    active_alerts: int
    alerts: list[OpsAlert] = Field(default_factory=list)
    release_gate_blockers: list[OpsReleaseGateBlocker] = Field(default_factory=list)
    future_workers: list[OpsFutureWorkerStatus] = Field(default_factory=list)


class OpsResidentExpertStatus(BaseModel):
    expert_id: str
    name: str
    display_name_zh_cn: str
    layer: str
    independence: str
    role_summary: str
    consult_before: list[str] = Field(default_factory=list)
    focus_areas: list[str] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list)
    expected_output: list[str] = Field(default_factory=list)
    charter_source_ref: str
    charter_version_hash: str
    status: str
    runtime_handle_bound: bool = False
    oversight_ready: bool = False
    runtime_handle: str | None = None
    last_seen_at: str | None = None
    last_consulted_at: str | None = None
    last_consultation_ref: str | None = None


class OpsResidentExpertConsultRequest(BaseModel):
    expert_ids: list[str] = Field(default_factory=list)
    consultation_ref: str | None = None
    observed_runtime_handles: dict[str, str] = Field(default_factory=dict)
    consulted_at: str | None = None


class OpsResidentExpertRuntimeHandleBinding(BaseModel):
    expert_id: str
    runtime_handle: str
    observed_at: str | None = None


class OpsResidentExpertRuntimeHandleBindingRequest(BaseModel):
    bindings: list[OpsResidentExpertRuntimeHandleBinding] = Field(default_factory=list)


class OpsResidentExpertDecisionAuditExpert(BaseModel):
    expert_id: str
    status: str
    runtime_handle: str | None = None
    last_seen_at: str | None = None
    last_consulted_at: str | None = None
    last_consultation_ref: str | None = None


class OpsResidentExpertDecisionAuditRow(BaseModel):
    decision_id: str
    project_id: str
    session_id: str
    action_ref: str
    decision_result: str
    created_at: str
    consultation_status: str
    consultation_ref: str | None = None
    consulted_at: str | None = None
    experts: list[OpsResidentExpertDecisionAuditExpert] = Field(default_factory=list)


class OpsDeliveryRequeueReceipt(BaseModel):
    accepted: bool = True
    requeued: int
    reason: str
    updated_at: str
    envelope_ids: list[str] = Field(default_factory=list)


def _iso_z(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso8601(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _is_older_than(value: str | None, *, now: datetime, threshold_seconds: float) -> bool:
    parsed = _parse_iso8601(value)
    if parsed is None:
        return False
    return (now - parsed).total_seconds() >= threshold_seconds


def _is_recent_enough(value: str | None, *, now: datetime, threshold_seconds: float) -> bool:
    if threshold_seconds <= 0:
        return True
    parsed = _parse_iso8601(value)
    if parsed is None:
        return True
    return (now - parsed).total_seconds() < threshold_seconds


def _latest_timestamp(values: list[str | None]) -> datetime | None:
    parsed = [item for item in (_parse_iso8601(value) for value in values) if item is not None]
    if not parsed:
        return None
    return max(parsed)


def _approval_recency_key(record: CanonicalApprovalRecord) -> tuple[tuple[int, str], datetime, str]:
    created_at = _parse_iso8601(record.created_at) or datetime.min.replace(tzinfo=UTC)
    return (_fact_snapshot_order(record.fact_snapshot_version), created_at, record.approval_id)


def _latest_approval_records(
    approvals: list[CanonicalApprovalRecord],
) -> list[CanonicalApprovalRecord]:
    latest_by_session: dict[tuple[str, str], CanonicalApprovalRecord] = {}
    for record in approvals:
        key = (record.session_id, record.project_id)
        existing = latest_by_session.get(key)
        if existing is None or _approval_recency_key(record) > _approval_recency_key(existing):
            latest_by_session[key] = record
    return list(latest_by_session.values())


def _latest_approval_row_by_session(
    approval_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    latest_by_session: dict[tuple[str, str], dict[str, object]] = {}
    for row in approval_rows:
        session_id = str(row.get("session_id") or "").strip()
        project_id = str(row.get("project_id") or "").strip()
        if not session_id or not project_id:
            continue
        key = (session_id, project_id)
        existing = latest_by_session.get(key)
        created_at = _parse_iso8601(str(row.get("created_at") or ""))
        recency = (
            _fact_snapshot_order(str(row.get("fact_snapshot_version") or "")),
            created_at or datetime.min.replace(tzinfo=UTC),
            str(row.get("approval_id") or ""),
        )
        if existing is None:
            latest_by_session[key] = row
            continue
        existing_created_at = _parse_iso8601(str(existing.get("created_at") or ""))
        existing_recency = (
            _fact_snapshot_order(str(existing.get("fact_snapshot_version") or "")),
            existing_created_at or datetime.min.replace(tzinfo=UTC),
            str(existing.get("approval_id") or ""),
        )
        if recency > existing_recency:
            latest_by_session[key] = row
    return list(latest_by_session.values())


def _runtime_gate_reason_counts(decisions) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in decisions:
        if not any(rule in _RUNTIME_GATE_ALERT_RULES for rule in record.matched_policy_rules):
            continue
        reasons = record.uncertainty_reasons or []
        reason = next(
            (
                str(item).strip()
                for item in reasons
                if str(item).strip()
            ),
            "",
        )
        normalized = normalize_runtime_gate_reason(reason)
        counts[normalized] = counts.get(normalized, 0) + 1
    return counts


def _provider_degrade_reason_counts(decisions) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in decisions:
        evidence = record.evidence if isinstance(record.evidence, dict) else None
        if evidence is None:
            continue
        trace = evidence.get("decision_trace")
        if not isinstance(trace, dict):
            continue
        reason = str(trace.get("degrade_reason") or "").strip()
        if not reason:
            continue
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def get_resident_expert_runtime_service(request: Request) -> ResidentExpertRuntimeService:
    return request.app.state.resident_expert_runtime_service


def _resident_expert_decision_audit_rows(
    decisions,
    *,
    decision_id: str | None = None,
    project_id: str | None = None,
    session_id: str | None = None,
) -> list[OpsResidentExpertDecisionAuditRow]:
    rows: list[OpsResidentExpertDecisionAuditRow] = []
    for record in decisions:
        if decision_id and record.decision_id != decision_id:
            continue
        if project_id and record.project_id != project_id:
            continue
        if session_id and record.session_id != session_id:
            continue
        evidence = record.evidence if isinstance(record.evidence, dict) else {}
        consultation = evidence.get("resident_expert_consultation")
        consultation_bundle = consultation if isinstance(consultation, dict) else None
        experts: list[OpsResidentExpertDecisionAuditExpert] = []
        if consultation_bundle is not None:
            raw_experts = consultation_bundle.get("experts")
            if isinstance(raw_experts, list):
                experts = [
                    OpsResidentExpertDecisionAuditExpert.model_validate(item)
                    for item in raw_experts
                    if isinstance(item, dict)
                ]
        rows.append(
            OpsResidentExpertDecisionAuditRow(
                decision_id=record.decision_id,
                project_id=record.project_id,
                session_id=record.session_id,
                action_ref=record.action_ref,
                decision_result=record.decision_result,
                created_at=record.created_at,
                consultation_status="recorded" if consultation_bundle is not None else "missing",
                consultation_ref=(
                    str(consultation_bundle.get("consultation_ref") or "").strip() or None
                    if consultation_bundle is not None
                    else None
                ),
                consulted_at=(
                    str(consultation_bundle.get("consulted_at") or "").strip() or None
                    if consultation_bundle is not None
                    else None
                ),
                experts=experts,
            )
        )
    rows.sort(
        key=lambda item: (
            _parse_iso8601(item.consulted_at or item.created_at) or datetime.min.replace(tzinfo=UTC),
            item.decision_id,
        ),
        reverse=True,
    )
    return rows


def _release_gate_blockers(decisions) -> list[OpsReleaseGateBlocker]:
    blockers: list[OpsReleaseGateBlocker] = []
    for record in decisions:
        release_gate = read_release_gate_decision_evidence(
            record.evidence if isinstance(record.evidence, dict) else None
        )
        verdict = release_gate.verdict
        if verdict is None or verdict.status == "pass":
            continue
        bundle = release_gate.evidence_bundle
        reason = normalize_runtime_gate_reason(verdict.degrade_reason or "unknown")
        blockers.append(
            OpsReleaseGateBlocker(
                decision_id=record.decision_id,
                project_id=record.project_id,
                session_id=record.session_id,
                reason=reason,
                report_id=verdict.report_id,
                report_hash=verdict.report_hash,
                input_hash=verdict.input_hash,
                report_ref=(
                    bundle.release_gate_report_ref
                    if bundle is not None
                    else None
                ),
                certification_packet_corpus_ref=(
                    bundle.certification_packet_corpus.artifact_ref
                    if bundle is not None
                    else None
                ),
                shadow_decision_ledger_ref=(
                    bundle.shadow_decision_ledger.artifact_ref
                    if bundle is not None
                    else None
                ),
                label_manifest_ref=(
                    bundle.label_manifest_ref
                    if bundle is not None
                    else None
                ),
                generated_by=bundle.generated_by if bundle is not None else None,
                report_approved_by=(
                    bundle.report_approved_by
                    if bundle is not None
                    else None
                ),
            )
        )
    blockers.sort(key=lambda item: (item.reason, item.project_id, item.decision_id))
    return blockers


def _session_event_order(event) -> tuple[int, datetime, str]:
    occurred_at = _parse_iso8601(event.occurred_at) or datetime.min.replace(tzinfo=UTC)
    return (event.log_seq or 0, occurred_at, event.event_id)


def _future_worker_decision_trace_ref(events) -> str | None:
    for event in events:
        decision_trace_ref = event.related_ids.get("decision_trace_ref")
        if decision_trace_ref:
            return decision_trace_ref
    for event in reversed(events):
        decision_trace_ref = event.payload.get("decision_trace_ref")
        if isinstance(decision_trace_ref, str) and decision_trace_ref:
            return decision_trace_ref
    return None


def _future_worker_blocking_reason(event) -> str | None:
    reason = event.payload.get("reason")
    if isinstance(reason, str) and reason:
        return reason
    return None


def _record_notification_requeued(
    service: SessionService,
    record: DeliveryOutboxRecord,
    *,
    reason: str,
    previous_failure_code: str | None,
) -> None:
    payload = dict(record.envelope_payload)
    if payload.get("envelope_type") != "notification":
        return
    mirrored: dict[str, Any] = {
        "outbox_seq": record.outbox_seq,
        "delivery_status": record.delivery_status,
        "delivery_attempt": record.delivery_attempt,
        "reason": reason,
    }
    if previous_failure_code:
        mirrored["failure_code"] = previous_failure_code
    next_retry_at = record.next_retry_at
    if next_retry_at is not None:
        mirrored["next_retry_at"] = next_retry_at
    for field in (
        "event_id",
        "notification_kind",
        "severity",
        "title",
        "summary",
        "occurred_at",
        "decision_result",
        "action_name",
        "interaction_context_id",
        "interaction_family_id",
        "actor_id",
        "channel_kind",
        "action_window_expires_at",
    ):
        value = payload.get(field)
        if value is not None:
            mirrored[field] = value
    service.record_event(
        event_type="notification_requeued",
        project_id=record.project_id,
        session_id=record.session_id,
        occurred_at=record.updated_at,
        correlation_id=f"corr:notification:{record.envelope_id}:requeue:{reason}",
        causation_id=str(payload.get("event_id") or record.envelope_id),
        related_ids={
            "envelope_id": record.envelope_id,
            **(
                {"notification_event_id": payload["event_id"]}
                if isinstance(payload.get("event_id"), str) and payload.get("event_id")
                else {}
            ),
            **(
                {"notification_kind": payload["notification_kind"]}
                if isinstance(payload.get("notification_kind"), str)
                and payload.get("notification_kind")
                else {}
            ),
            **(
                {"interaction_context_id": payload["interaction_context_id"]}
                if isinstance(payload.get("interaction_context_id"), str)
                and payload.get("interaction_context_id")
                else {}
            ),
            **(
                {"interaction_family_id": payload["interaction_family_id"]}
                if isinstance(payload.get("interaction_family_id"), str)
                and payload.get("interaction_family_id")
                else {}
            ),
            **(
                {"actor_id": payload["actor_id"]}
                if isinstance(payload.get("actor_id"), str) and payload.get("actor_id")
                else {}
            ),
        },
        payload=mirrored,
    )


def _future_worker_statuses(*, data_dir: Path) -> list[OpsFutureWorkerStatus]:
    session_service = SessionService.from_data_dir(data_dir)
    grouped_events: dict[tuple[str, str, str], list[object]] = {}
    for event in session_service.list_events():
        if event.event_type not in _FUTURE_WORKER_EVENT_TYPES:
            continue
        worker_task_ref = event.related_ids.get("worker_task_ref")
        if not worker_task_ref:
            continue
        key = (event.project_id, event.session_id, worker_task_ref)
        grouped_events.setdefault(key, []).append(event)

    statuses: list[OpsFutureWorkerStatus] = []
    for (project_id, session_id, worker_task_ref), events in grouped_events.items():
        ordered_events = sorted(events, key=_session_event_order)
        state_events = [
            event
            for event in ordered_events
            if event.event_type in _FUTURE_WORKER_STATUS_BY_EVENT_TYPE
        ]
        if not state_events:
            continue
        last_event = ordered_events[-1]
        last_state_event = state_events[-1]
        status = _FUTURE_WORKER_STATUS_BY_EVENT_TYPE.get(last_state_event.event_type)
        if status is None:
            continue
        statuses.append(
            OpsFutureWorkerStatus(
                project_id=project_id,
                session_id=session_id,
                worker_task_ref=worker_task_ref,
                status=status,
                last_event_type=last_event.event_type,
                occurred_at=last_event.occurred_at,
                decision_trace_ref=_future_worker_decision_trace_ref(ordered_events),
                blocking_reason=_future_worker_blocking_reason(last_event),
            )
        )

    statuses.sort(key=lambda item: (item.worker_task_ref, item.session_id, item.project_id))
    return statuses


def build_ops_summary(
    *,
    data_dir: Path,
    settings: Settings,
    now: datetime | None = None,
    decision_store: PolicyDecisionStore | None = None,
    approval_store: CanonicalApprovalStore | None = None,
    delivery_store: DeliveryOutboxStore | None = None,
    receipt_store: ActionReceiptStore | None = None,
) -> OpsSummary:
    now = now or datetime.now(UTC)

    decision_store = decision_store or PolicyDecisionStore(data_dir / "policy_decisions.json")
    approval_store = approval_store or CanonicalApprovalStore(data_dir / "canonical_approvals.json")
    delivery_store = delivery_store or DeliveryOutboxStore(data_dir / "delivery_outbox.json")
    receipt_store = receipt_store or ActionReceiptStore(data_dir / "action_receipts.json")

    decisions = decision_store.list_records()
    approvals = approval_store.list_records()
    deliveries = delivery_store.list_records()
    receipt_items = receipt_store.list_items()

    blocked_too_long = sum(
        1
        for record in decisions
        if record.decision_result == "block_and_alert"
        and _is_older_than(
            record.created_at,
            now=now,
            threshold_seconds=settings.ops_blocked_too_long_seconds,
        )
    )
    approval_pending_too_long = sum(
        1
        for record in _latest_approval_records(approvals)
        if record.status == "pending"
        and _is_older_than(
            record.created_at,
            now=now,
            threshold_seconds=settings.ops_approval_pending_too_long_seconds,
        )
    )
    delivery_failed = sum(
        1
        for record in deliveries
        if record.delivery_status == "delivery_failed"
        and str(record.failure_code or "") not in _NON_ALERTING_DELIVERY_FAILURE_CODES
        and _is_recent_enough(
            record.updated_at or record.created_at,
            now=now,
            threshold_seconds=settings.ops_delivery_failed_alert_window_seconds,
        )
    )
    mapping_incomplete = sum(
        1 for record in decisions if "mapping_incomplete" in record.uncertainty_reasons
    )
    runtime_gate_reason_counts = _runtime_gate_reason_counts(decisions)
    provider_degrade_reason_counts = _provider_degrade_reason_counts(decisions)
    release_gate_blockers = _release_gate_blockers(decisions)
    future_workers = _future_worker_statuses(data_dir=data_dir)
    resident_expert_views = ResidentExpertRuntimeService.from_data_dir(
        data_dir,
        stale_after_seconds=settings.resident_expert_stale_after_seconds,
    ).list_runtime_views(now=now)
    resident_expert_stale = sum(1 for view in resident_expert_views if view.status == "stale")
    recovery_failed = sum(
        1
        for _, result in receipt_items
        if result.action_code == ActionCode.EXECUTE_RECOVERY
        and result.action_status not in {ActionStatus.COMPLETED, ActionStatus.NOOP}
    )

    alerts: list[OpsAlert] = []
    if approval_pending_too_long:
        alerts.append(
            OpsAlert(
                alert_code="approval_pending_too_long",
                severity="warning",
                count=approval_pending_too_long,
                summary="pending approvals exceeded operator SLA",
            )
        )
    if blocked_too_long:
        alerts.append(
            OpsAlert(
                alert_code="blocked_too_long",
                severity="critical",
                count=blocked_too_long,
                summary="blocked decisions remain unresolved beyond threshold",
            )
        )
    if delivery_failed:
        alerts.append(
            OpsAlert(
                alert_code="delivery_failed",
                severity="critical",
                count=delivery_failed,
                summary="delivery outbox contains permanently failed envelopes",
            )
        )
    if mapping_incomplete:
        alerts.append(
            OpsAlert(
                alert_code="mapping_incomplete",
                severity="warning",
                count=mapping_incomplete,
                summary="mapping gaps are blocking or degrading decision quality",
            )
        )
    for reason, count in sorted(runtime_gate_reason_counts.items()):
        alerts.append(
            OpsAlert(
                alert_code=f"runtime_gate_{reason}",
                severity="warning",
                count=count,
                summary=f"runtime gate degradation: {reason}",
            )
        )
    for reason, count in sorted(provider_degrade_reason_counts.items()):
        alerts.append(
            OpsAlert(
                alert_code=reason,
                severity="warning",
                count=count,
                summary=f"brain provider degradation: {reason}",
            )
        )
    if recovery_failed:
        alerts.append(
            OpsAlert(
                alert_code="recovery_failed",
                severity="critical",
                count=recovery_failed,
                summary="recovery execution produced non-completed receipts",
            )
        )
    if resident_expert_stale:
        alerts.append(
            OpsAlert(
                alert_code="resident_expert_stale",
                severity="warning",
                count=resident_expert_stale,
                summary="resident expert runtime handles are stale",
            )
        )

    alerts.sort(key=lambda item: item.alert_code)
    return OpsSummary(
        status="degraded" if alerts or release_gate_blockers else "ok",
        active_alerts=len(alerts),
        alerts=alerts,
        release_gate_blockers=release_gate_blockers,
        future_workers=future_workers,
    )


def build_ops_health_summary(
    *,
    data_dir: Path,
    settings: Settings,
    now: datetime | None = None,
    decision_store: PolicyDecisionStore | None = None,
    approval_store: CanonicalApprovalStore | None = None,
    delivery_store: DeliveryOutboxStore | None = None,
    receipt_store: ActionReceiptStore | None = None,
) -> dict[str, int | str]:
    now = now or datetime.now(UTC)
    decision_store = decision_store or PolicyDecisionStore(data_dir / "policy_decisions.json")
    approval_store = approval_store or CanonicalApprovalStore(data_dir / "canonical_approvals.json")
    delivery_store = delivery_store or DeliveryOutboxStore(data_dir / "delivery_outbox.json")
    receipt_store = receipt_store or ActionReceiptStore(data_dir / "action_receipts.json")

    decision_rows = decision_store.snapshot_rows()
    approval_rows = approval_store.snapshot_rows()
    delivery_rows = delivery_store.snapshot_rows()
    receipt_rows = receipt_store.snapshot_rows()

    blocked_too_long = sum(
        1
        for row in decision_rows
        if str(row.get("decision_result") or "") == "block_and_alert"
        and _is_older_than(
            str(row.get("created_at") or ""),
            now=now,
            threshold_seconds=settings.ops_blocked_too_long_seconds,
        )
    )
    approval_pending_too_long = sum(
        1
        for row in _latest_approval_row_by_session(approval_rows)
        if str(row.get("status") or "") == "pending"
        and _is_older_than(
            str(row.get("created_at") or ""),
            now=now,
            threshold_seconds=settings.ops_approval_pending_too_long_seconds,
        )
    )
    delivery_failed = sum(
        1
        for row in delivery_rows
        if row.delivery_status == "delivery_failed"
        and str(row.failure_code or "") not in _NON_ALERTING_DELIVERY_FAILURE_CODES
        and _is_recent_enough(
            row.updated_at or row.created_at,
            now=now,
            threshold_seconds=settings.ops_delivery_failed_alert_window_seconds,
        )
    )
    mapping_incomplete = sum(
        1
        for row in decision_rows
        if "mapping_incomplete" in list(row.get("uncertainty_reasons") or [])
    )
    runtime_gate_reason_counts: dict[str, int] = {}
    release_gate_blockers = 0
    resident_expert_stale = sum(
        1
        for view in ResidentExpertRuntimeService.from_data_dir(
            data_dir,
            stale_after_seconds=settings.resident_expert_stale_after_seconds,
        ).list_runtime_views(now=now)
        if view.status == "stale"
    )
    for row in decision_rows:
        matched_policy_rules = list(row.get("matched_policy_rules") or [])
        if any(rule in _RUNTIME_GATE_ALERT_RULES for rule in matched_policy_rules):
            reasons = [
                str(item).strip()
                for item in list(row.get("uncertainty_reasons") or [])
                if str(item).strip()
            ]
            normalized = normalize_runtime_gate_reason(reasons[0] if reasons else "")
            runtime_gate_reason_counts[normalized] = runtime_gate_reason_counts.get(normalized, 0) + 1
        release_gate = read_release_gate_decision_evidence(
            row.get("evidence") if isinstance(row.get("evidence"), dict) else None
        )
        verdict = release_gate.verdict
        if verdict is not None and verdict.status != "pass":
            release_gate_blockers += 1
    recovery_failed = sum(
        1
        for _, row in receipt_rows
        if str(row.get("action_code") or "") == ActionCode.EXECUTE_RECOVERY
        and str(row.get("action_status") or "")
        not in {ActionStatus.COMPLETED, ActionStatus.NOOP}
    )

    active_alerts = sum(
        1
        for value in (
            approval_pending_too_long,
            blocked_too_long,
            delivery_failed,
            mapping_incomplete,
            recovery_failed,
            resident_expert_stale,
        )
        if value
    ) + sum(1 for count in runtime_gate_reason_counts.values() if count)

    return {
        "status": "degraded" if active_alerts or release_gate_blockers else "ok",
        "active_alerts": active_alerts,
        "release_gate_blockers": release_gate_blockers,
    }


@router.get("/alerts")
def get_ops_alerts(
    request: Request,
    _: None = Depends(require_token),
) -> dict[str, object]:
    summary = build_ops_summary(
        data_dir=Path(request.app.state.settings.data_dir),
        settings=request.app.state.settings,
        decision_store=request.app.state.policy_decision_store,
        approval_store=request.app.state.canonical_approval_store,
        delivery_store=request.app.state.delivery_outbox_store,
        receipt_store=request.app.state.action_receipt_store,
    )
    return ok(
        request.headers.get("x-request-id"),
        {
            "status": summary.status,
            "active_alerts": summary.active_alerts,
            "alerts": [item.model_dump(mode="json") for item in summary.alerts],
            "release_gate_blockers": [
                item.model_dump(mode="json") for item in summary.release_gate_blockers
            ],
            "future_workers": [
                item.model_dump(mode="json") for item in summary.future_workers
            ],
        },
    )


@router.get("/resident-experts")
def get_resident_experts(
    request: Request,
    _: None = Depends(require_token),
    resident_expert_runtime_service: ResidentExpertRuntimeService = Depends(
        get_resident_expert_runtime_service
    ),
) -> dict[str, object]:
    return ok(
        request.headers.get("x-request-id"),
        {
            "experts": [
                OpsResidentExpertStatus.model_validate(
                    view.model_dump(mode="json")
                ).model_dump(mode="json")
                for view in resident_expert_runtime_service.list_runtime_views(now=datetime.now(UTC))
            ]
        },
    )


@router.post("/resident-experts/consult")
def post_resident_experts_consult(
    request: Request,
    payload: OpsResidentExpertConsultRequest,
    _: None = Depends(require_token),
    resident_expert_runtime_service: ResidentExpertRuntimeService = Depends(
        get_resident_expert_runtime_service
    ),
) -> dict[str, object]:
    response_now = _parse_iso8601(payload.consulted_at) or datetime.now(UTC)
    resident_expert_runtime_service.consult_or_restore(
        expert_ids=payload.expert_ids or None,
        consultation_ref=payload.consultation_ref,
        observed_runtime_handles=payload.observed_runtime_handles,
        consulted_at=payload.consulted_at,
    )
    return ok(
        request.headers.get("x-request-id"),
        {
            "experts": [
                OpsResidentExpertStatus.model_validate(
                    view.model_dump(mode="json")
                ).model_dump(mode="json")
                for view in resident_expert_runtime_service.list_runtime_views(now=response_now)
            ]
        },
    )


@router.post("/resident-experts/runtime-handles")
def post_resident_expert_runtime_handles(
    request: Request,
    payload: OpsResidentExpertRuntimeHandleBindingRequest,
    _: None = Depends(require_token),
    resident_expert_runtime_service: ResidentExpertRuntimeService = Depends(
        get_resident_expert_runtime_service
    ),
) -> dict[str, object]:
    for binding in payload.bindings:
        try:
            resident_expert_runtime_service.bind_runtime_handle(
                expert_id=binding.expert_id,
                runtime_handle=binding.runtime_handle,
                observed_at=binding.observed_at,
            )
        except KeyError as exc:
            detail = exc.args[0] if exc.args else str(exc)
            raise HTTPException(status_code=404, detail=str(detail)) from exc
    response_now = _latest_timestamp([binding.observed_at for binding in payload.bindings])
    return ok(
        request.headers.get("x-request-id"),
        {
            "experts": [
                OpsResidentExpertStatus.model_validate(
                    view.model_dump(mode="json")
                ).model_dump(mode="json")
                for view in resident_expert_runtime_service.list_runtime_views(now=response_now)
            ]
        },
    )


@router.get("/resident-experts/decision-audit")
def get_resident_expert_decision_audit(
    request: Request,
    decision_id: str | None = None,
    project_id: str | None = None,
    session_id: str | None = None,
    _: None = Depends(require_token),
) -> dict[str, object]:
    rows = _resident_expert_decision_audit_rows(
        request.app.state.policy_decision_store.list_records(),
        decision_id=decision_id,
        project_id=project_id,
        session_id=session_id,
    )
    return ok(
        request.headers.get("x-request-id"),
        {
            "decisions": [row.model_dump(mode="json") for row in rows],
        },
    )


@router.post("/delivery/requeue-transport-failures")
def post_ops_requeue_transport_failures(
    request: Request,
    _: None = Depends(require_token),
) -> dict[str, object]:
    updated_at = _iso_z(datetime.now(UTC))
    reason = "manual_transport_recovered"
    delivery_store = request.app.state.delivery_outbox_store
    failed_codes = {
        record.envelope_id: str(record.failure_code or "").strip() or None
        for record in delivery_store.list_records()
        if record.delivery_status == "delivery_failed"
    }
    requeued = delivery_store.requeue_transport_failures(
        reason=reason,
        updated_at=updated_at,
    )
    for record in requeued:
        _record_notification_requeued(
            request.app.state.session_service,
            record,
            reason=reason,
            previous_failure_code=failed_codes.get(record.envelope_id),
        )
    return ok(
        request.headers.get("x-request-id"),
        OpsDeliveryRequeueReceipt(
            requeued=len(requeued),
            reason=reason,
            updated_at=updated_at,
            envelope_ids=[record.envelope_id for record in requeued],
        ).model_dump(mode="json"),
    )
