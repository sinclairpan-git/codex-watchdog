from __future__ import annotations

from datetime import UTC, datetime, timezone
from typing import Any

from watchdog.contracts.session_spine.models import FactRecord
from watchdog.services.session_spine.approval_visibility import is_actionable_approval
from watchdog.services.session_spine.task_state import (
    is_non_active_project_execution_state,
    is_terminal_task,
    normalize_project_execution_state,
    normalize_task_status,
)


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


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _auto_recovery_suppressed(task: dict[str, Any] | None) -> bool:
    return normalize_task_status(task) in {
        "handoff_in_progress",
        "resuming",
        "paused",
        "waiting_for_direction",
    }


def _recent_local_activity_supersedes_stuck_signal(task: dict[str, Any] | None) -> bool:
    if not isinstance(task, dict):
        return False
    manual_activity_at = _parse_iso(task.get("last_local_manual_activity_at"))
    if manual_activity_at is None:
        return False
    last_progress_at = _parse_iso(task.get("last_progress_at"))
    if last_progress_at is None:
        return True
    return manual_activity_at > last_progress_at


def build_fact_records(
    *,
    project_id: str,
    task: dict[str, Any] | None,
    approvals: list[dict[str, Any]],
    link_error: str | None = None,
) -> list[FactRecord]:
    observed_at = _task_value(task, "last_progress_at", None)
    if observed_at is None and approvals:
        observed_at = approvals[0].get("requested_at") or approvals[0].get("created_at")
    if observed_at in (None, ""):
        observed_at = _now_iso()
    observed_at = str(observed_at)
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

    pending_approvals = [approval for approval in approvals if is_actionable_approval(approval)]
    if is_terminal_task(task) and not pending_approvals:
        return [
            _build_fact(
                project_id,
                fact_code="task_completed",
                fact_kind="advisory",
                severity="info",
                summary="session completed",
                detail="session reached a terminal completed state",
                source="watchdog_projection",
                observed_at=observed_at,
            )
        ]
    if pending_approvals:
        related_ids: dict[str, Any] = {
            "approval_id": str(pending_approvals[0].get("approval_id") or "")
        }
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

    project_execution_state = normalize_project_execution_state(task)
    if bool(_task_value(task, "authoritative_project_execution_state_missing", False)):
        facts.append(
            _build_fact(
                project_id,
                fact_code="project_state_unavailable",
                fact_kind="blocker",
                severity="warning",
                summary="authoritative project state unavailable",
                detail=(
                    "autonomous continuation is blocked because authoritative "
                    "project execution state could not be resolved"
                ),
                source="watchdog_projection",
                observed_at=observed_at,
            )
        )
        return facts
    if is_non_active_project_execution_state(project_execution_state):
        facts.append(
            _build_fact(
                project_id,
                fact_code="project_not_active",
                fact_kind="blocker",
                severity="info",
                summary="project is not active",
                detail=(
                    "autonomous continuation is blocked because "
                    f"project_execution_state={project_execution_state}"
                ),
                source="watchdog_projection",
                observed_at=observed_at,
                related_ids={"project_execution_state": project_execution_state},
            )
        )
        return facts

    if _auto_recovery_suppressed(task):
        return facts

    if (
        int(_task_value(task, "stuck_level", 0)) >= 2
        and not _recent_local_activity_supersedes_stuck_signal(task)
    ):
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
