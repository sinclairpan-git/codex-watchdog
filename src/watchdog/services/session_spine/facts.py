from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from watchdog.contracts.session_spine.models import FactRecord


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _task_value(task: dict[str, Any] | None, key: str, default: Any) -> Any:
    if not isinstance(task, dict):
        return default
    value = task.get(key)
    if value in (None, ""):
        return default
    return value


def _build_fact(
    project_id: str,
    *,
    fact_code: str,
    fact_kind: str,
    severity: str,
    summary: str,
    detail: str,
    source: str,
    observed_at: str,
    related_ids: dict[str, Any] | None = None,
) -> FactRecord:
    return FactRecord(
        fact_id=f"{project_id}:{fact_code}",
        fact_code=fact_code,
        fact_kind=fact_kind,
        severity=severity,
        summary=summary,
        detail=detail,
        source=source,
        observed_at=observed_at,
        related_ids=related_ids or {},
    )


def build_fact_records(
    *,
    project_id: str,
    task: dict[str, Any] | None,
    approvals: list[dict[str, Any]],
    link_error: str | None = None,
) -> list[FactRecord]:
    observed_at = str(
        _task_value(task, "last_progress_at", None)
        or approvals[0].get("requested_at")
        if approvals
        else None
        or _now_iso()
    )
    facts: list[FactRecord] = []

    if link_error:
        return [
            _build_fact(
                project_id,
                fact_code="control_link_error",
                fact_kind="availability",
                severity="unreachable",
                summary="control link unavailable",
                detail=str(link_error),
                source="watchdog_control_link",
                observed_at=observed_at,
            )
        ]

    pending_approvals = [
        approval
        for approval in approvals
        if str(approval.get("status") or "").lower() == "pending"
    ]
    if bool(_task_value(task, "pending_approval", False)) or pending_approvals:
        related_ids: dict[str, Any] = {}
        if pending_approvals:
            related_ids["approval_id"] = str(pending_approvals[0].get("approval_id") or "")
        facts.append(
            _build_fact(
                project_id,
                fact_code="approval_pending",
                fact_kind="blocker",
                severity="needs_human",
                summary="approval required",
                detail="session is waiting for an approval decision",
                source="approval_store",
                observed_at=observed_at,
                related_ids=related_ids,
            )
        )
        facts.append(
            _build_fact(
                project_id,
                fact_code="awaiting_human_direction",
                fact_kind="blocker",
                severity="needs_human",
                summary="awaiting operator direction",
                detail="human input is required before the session can continue",
                source="watchdog_projection",
                observed_at=observed_at,
            )
        )

    if int(_task_value(task, "stuck_level", 0)) >= 2:
        facts.append(
            _build_fact(
                project_id,
                fact_code="stuck_no_progress",
                fact_kind="blocker",
                severity="warning",
                summary="session appears stuck",
                detail="no meaningful progress has been observed within the watchdog threshold",
                source="status_analyzer",
                observed_at=observed_at,
            )
        )

    if int(_task_value(task, "failure_count", 0)) >= 3:
        facts.append(
            _build_fact(
                project_id,
                fact_code="repeat_failure",
                fact_kind="blocker",
                severity="warning",
                summary="repeated failures detected",
                detail="the same failure pattern has repeated multiple times",
                source="status_analyzer",
                observed_at=observed_at,
            )
        )

    if str(_task_value(task, "context_pressure", "low")) == "critical":
        facts.append(
            _build_fact(
                project_id,
                fact_code="context_critical",
                fact_kind="risk",
                severity="critical",
                summary="context pressure is critical",
                detail="remaining context is too constrained for safe continuation",
                source="watchdog_projection",
                observed_at=observed_at,
            )
        )

    if any(fact.fact_code in {"stuck_no_progress", "repeat_failure", "context_critical"} for fact in facts):
        facts.append(
            _build_fact(
                project_id,
                fact_code="recovery_available",
                fact_kind="advisory",
                severity="info",
                summary="recovery may be requested",
                detail=(
                    "watchdog can explain recovery availability; request_recovery remains "
                    "advisory-only, while execute_recovery performs the explicit recovery action"
                ),
                source="watchdog_projection",
                observed_at=observed_at,
            )
        )

    return facts
