from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from a_control_agent.envelope import ok
from watchdog.api.deps import require_token
from watchdog.contracts.session_spine.enums import ActionCode, ActionStatus
from watchdog.services.approvals.service import CanonicalApprovalRecord, CanonicalApprovalStore
from watchdog.services.delivery.store import DeliveryOutboxStore
from watchdog.services.brain.release_gate import normalize_runtime_gate_reason
from watchdog.services.policy.decisions import PolicyDecisionStore
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


def _release_gate_blockers(decisions) -> list[OpsReleaseGateBlocker]:
    blockers: list[OpsReleaseGateBlocker] = []
    for record in decisions:
        evidence = record.evidence if isinstance(record.evidence, dict) else {}
        verdict = evidence.get("release_gate_verdict")
        if not isinstance(verdict, dict) or str(verdict.get("status")) == "pass":
            continue
        bundle = (
            evidence.get("release_gate_evidence_bundle")
            if isinstance(evidence.get("release_gate_evidence_bundle"), dict)
            else {}
        )
        certification = (
            bundle.get("certification_packet_corpus")
            if isinstance(bundle.get("certification_packet_corpus"), dict)
            else {}
        )
        ledger = (
            bundle.get("shadow_decision_ledger")
            if isinstance(bundle.get("shadow_decision_ledger"), dict)
            else {}
        )
        reason = normalize_runtime_gate_reason(
            str(verdict.get("degrade_reason") or "") or "unknown"
        )
        blockers.append(
            OpsReleaseGateBlocker(
                decision_id=record.decision_id,
                project_id=record.project_id,
                session_id=record.session_id,
                reason=reason,
                report_id=str(verdict.get("report_id") or "") or None,
                report_hash=str(verdict.get("report_hash") or "") or None,
                input_hash=str(verdict.get("input_hash") or "") or None,
                report_ref=str(bundle.get("release_gate_report_ref") or "") or None,
                certification_packet_corpus_ref=(
                    str(certification.get("artifact_ref") or "") or None
                ),
                shadow_decision_ledger_ref=str(ledger.get("artifact_ref") or "") or None,
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
        last_event = ordered_events[-1]
        status = _FUTURE_WORKER_STATUS_BY_EVENT_TYPE.get(last_event.event_type)
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
) -> OpsSummary:
    now = now or datetime.now(UTC)

    decisions = PolicyDecisionStore(data_dir / "policy_decisions.json").list_records()
    approvals = CanonicalApprovalStore(data_dir / "canonical_approvals.json").list_records()
    deliveries = DeliveryOutboxStore(data_dir / "delivery_outbox.json").list_records()
    receipt_items = ActionReceiptStore(data_dir / "action_receipts.json").list_items()

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
    release_gate_blockers = _release_gate_blockers(decisions)
    future_workers = _future_worker_statuses(data_dir=data_dir)
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
    if recovery_failed:
        alerts.append(
            OpsAlert(
                alert_code="recovery_failed",
                severity="critical",
                count=recovery_failed,
                summary="recovery execution produced non-completed receipts",
            )
        )

    alerts.sort(key=lambda item: item.alert_code)
    return OpsSummary(
        status="degraded" if alerts else "ok",
        active_alerts=len(alerts),
        alerts=alerts,
        release_gate_blockers=release_gate_blockers,
        future_workers=future_workers,
    )


@router.get("/alerts")
def get_ops_alerts(
    request: Request,
    _: None = Depends(require_token),
) -> dict[str, object]:
    summary = build_ops_summary(
        data_dir=Path(request.app.state.settings.data_dir),
        settings=request.app.state.settings,
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
