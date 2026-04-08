from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from a_control_agent.envelope import ok
from watchdog.api.deps import require_token
from watchdog.contracts.session_spine.enums import ActionCode, ActionStatus
from watchdog.services.approvals.service import CanonicalApprovalStore
from watchdog.services.delivery.store import DeliveryOutboxStore
from watchdog.services.policy.decisions import PolicyDecisionStore
from watchdog.settings import Settings
from watchdog.storage.action_receipts import ActionReceiptStore

router = APIRouter(prefix="/watchdog/ops", tags=["watchdog"])

_NON_ALERTING_DELIVERY_FAILURE_CODES = {
    "suppressed_local_manual_activity",
    "stale_progress_summary",
    "stale_auto_execute_notification",
}


class OpsAlert(BaseModel):
    alert_code: str
    severity: str
    count: int
    summary: str


class OpsSummary(BaseModel):
    status: str
    active_alerts: int
    alerts: list[OpsAlert] = Field(default_factory=list)


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
        for record in approvals
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
        },
    )
