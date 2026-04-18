from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import httpx

from watchdog.contracts.session_spine.models import (
    ApprovalProjection,
    FactRecord,
    ResidentExpertCoverageView,
    SessionProjection,
    SnapshotReadSemantics,
    TaskProgressView,
    WorkspaceActivityView,
)
from watchdog.services.resident_experts.service import ResidentExpertRuntimeService
from watchdog.services.policy.decisions import (
    CanonicalDecisionRecord,
    PolicyDecisionStore,
)
from watchdog.services.policy.engine import evaluate_persisted_session_policy
from watchdog.services.a_client.client import AControlAgentClient
from watchdog.services.session_service.models import SessionEventRecord
from watchdog.services.session_service.service import SessionService
from watchdog.services.session_spine.facts import build_fact_records
from watchdog.services.session_spine.projection import (
    build_approval_inbox_projections,
    build_approval_projections,
    build_session_projection,
    build_session_service_fact_records,
    build_task_progress_view,
    build_workspace_activity_view,
    stable_thread_id_for_project,
)
from watchdog.services.session_spine.store import PersistedSessionRecord, SessionSpineStore
from watchdog.services.session_spine.approval_visibility import (
    is_actionable_approval,
    is_deferred_policy_auto_approval,
)

if TYPE_CHECKING:
    from watchdog.services.approvals.service import CanonicalApprovalStore


CONTROL_LINK_ERROR = {
    "code": "CONTROL_LINK_ERROR",
    "message": "无法连接 A-Control-Agent 或链路异常；请检查网络与 A 侧服务状态。",
}
PERSISTED_SESSION_SPINE_REQUIRED_ERROR = {
    "code": "PERSISTED_SESSION_SPINE_REQUIRED",
    "message": "缺少 canonical persisted session spine；请先刷新 resident session spine。",
}
PERSISTED_SPINE_READ_SOURCE = "persisted_spine"
SESSION_EVENTS_PROJECTION_READ_SOURCE = "session_events_projection"
LIVE_QUERY_FALLBACK_READ_SOURCE = "live_query_fallback"
DEFAULT_SESSION_SPINE_FRESHNESS_WINDOW_SECONDS = 60.0
SESSION_EVENT_APPROVAL_TYPES = frozenset(
    {
        "approval_requested",
        "approval_approved",
        "approval_rejected",
        "approval_expired",
    }
)
SESSION_EVENT_FACT_TYPES = frozenset(
    {
        "memory_unavailable_degraded",
        "memory_conflict_detected",
        "human_override_recorded",
        "notification_announced",
        "notification_delivery_succeeded",
        "notification_delivery_failed",
        "notification_requeued",
        "notification_receipt_recorded",
    }
)
SESSION_EVENT_PROJECTION_TYPES = SESSION_EVENT_APPROVAL_TYPES | SESSION_EVENT_FACT_TYPES


def _approval_sort_key(approval: ApprovalProjection) -> tuple[bool, str, str]:
    return (
        approval.requested_at == "",
        approval.requested_at,
        approval.approval_id,
    )


class SessionSpineUpstreamError(RuntimeError):
    def __init__(self, error: dict[str, Any]) -> None:
        super().__init__(str(error.get("code") or "upstream_error"))
        self.error = error


@dataclass(frozen=True, slots=True)
class SessionReadBundle:
    project_id: str
    task: dict[str, Any] | None
    approvals: list[dict[str, Any]]
    facts: list[FactRecord]
    session: SessionProjection
    progress: TaskProgressView
    approval_queue: list[ApprovalProjection]
    snapshot: SnapshotReadSemantics | None = None


@dataclass(frozen=True, slots=True)
class ApprovalInboxReadBundle:
    project_id: str | None
    approvals: list[dict[str, Any]]
    approval_inbox: list[ApprovalProjection]


@dataclass(frozen=True, slots=True)
class SessionDirectoryReadBundle:
    tasks: list[dict[str, Any]]
    approvals: list[dict[str, Any]]
    sessions: list[SessionProjection]
    progresses: list[TaskProgressView] = field(default_factory=list)
    resident_expert_coverage: ResidentExpertCoverageView | None = None


def _canonical_decision_sort_key(record: CanonicalDecisionRecord) -> tuple[str, str]:
    return (str(record.created_at or ""), record.decision_id)


def _build_decision_trace_projection(
    decision_store: PolicyDecisionStore | None,
    *,
    project_id: str,
    session_id: str | None = None,
    native_thread_id: str | None = None,
) -> dict[str, Any] | None:
    if decision_store is None:
        return None
    normalized_session_id = str(session_id or "").strip()
    normalized_native_thread_id = str(native_thread_id or "").strip()
    project_records = [
        record for record in decision_store.list_records() if record.project_id == project_id
    ]
    if not project_records:
        return None
    matched_records = [
        record
        for record in project_records
        if (
            normalized_session_id
            and record.session_id == normalized_session_id
            or normalized_native_thread_id
            and record.native_thread_id == normalized_native_thread_id
        )
    ]
    candidate_records = matched_records or project_records
    latest = max(candidate_records, key=_canonical_decision_sort_key)
    evidence = latest.evidence if isinstance(latest.evidence, dict) else {}
    trace = evidence.get("decision_trace")
    if not isinstance(trace, dict):
        return None
    return {
        "decision_trace_ref": str(trace.get("trace_id") or "") or None,
        "decision_degrade_reason": str(trace.get("degrade_reason") or "") or None,
        "provider_output_schema_ref": str(trace.get("provider_output_schema_ref") or "") or None,
    }


def _build_resident_expert_coverage_view(
    resident_expert_runtime_service: ResidentExpertRuntimeService | None,
) -> ResidentExpertCoverageView | None:
    if resident_expert_runtime_service is None:
        return None
    views = resident_expert_runtime_service.list_runtime_views(now=datetime.now(timezone.utc))
    if not views:
        return None
    if not any(
        view.runtime_handle_bound or view.last_consulted_at or view.last_consultation_ref
        for view in views
    ):
        return None

    latest_view = max(
        (
            view
            for view in views
            if view.last_consulted_at or view.last_consultation_ref
        ),
        key=lambda item: (
            _parse_iso8601(item.last_consulted_at) or datetime.min.replace(tzinfo=timezone.utc),
            item.expert_id,
        ),
        default=None,
    )
    degraded_expert_ids = [
        view.expert_id
        for view in views
        if view.status != "available"
    ]
    return ResidentExpertCoverageView(
        coverage_status="healthy" if not degraded_expert_ids else "degraded",
        available_expert_count=sum(1 for view in views if view.status == "available"),
        bound_expert_count=sum(1 for view in views if view.status == "bound"),
        restoring_expert_count=sum(1 for view in views if view.status == "restoring"),
        stale_expert_count=sum(1 for view in views if view.status == "stale"),
        unavailable_expert_count=sum(1 for view in views if view.status == "unavailable"),
        degraded_expert_ids=degraded_expert_ids,
        latest_consultation_ref=(
            str(latest_view.last_consultation_ref or "") or None
            if latest_view is not None
            else None
        ),
        latest_consulted_at=(
            str(latest_view.last_consulted_at or "") or None
            if latest_view is not None
            else None
        ),
    )


@dataclass(frozen=True, slots=True)
class WorkspaceActivityReadBundle:
    project_id: str
    task: dict[str, Any] | None
    approvals: list[dict[str, Any]]
    facts: list[FactRecord]
    session: SessionProjection
    workspace_activity: WorkspaceActivityView


def _parse_iso8601(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _build_snapshot_read_semantics_from_persisted_record(
    record: PersistedSessionRecord,
    *,
    freshness_window_seconds: float,
) -> SnapshotReadSemantics:
    last_refreshed = _parse_iso8601(record.last_refreshed_at)
    snapshot_age_seconds: float | None = None
    if last_refreshed is not None:
        snapshot_age_seconds = max(
            0.0,
            (datetime.now(timezone.utc) - last_refreshed).total_seconds(),
        )
    is_fresh = (
        snapshot_age_seconds is not None
        and snapshot_age_seconds <= max(freshness_window_seconds, 0.0)
    )
    return SnapshotReadSemantics(
        read_source=PERSISTED_SPINE_READ_SOURCE,
        is_persisted=True,
        is_fresh=is_fresh,
        is_stale=not is_fresh,
        last_refreshed_at=record.last_refreshed_at,
        snapshot_age_seconds=snapshot_age_seconds,
        session_seq=record.session_seq,
        fact_snapshot_version=record.fact_snapshot_version,
    )


def _build_snapshot_read_semantics_for_live_query() -> SnapshotReadSemantics:
    return SnapshotReadSemantics(
        read_source=LIVE_QUERY_FALLBACK_READ_SOURCE,
        is_persisted=False,
        is_fresh=True,
        is_stale=False,
    )


def _build_snapshot_read_semantics_for_session_events(
    last_observed_at: str | None = None,
) -> SnapshotReadSemantics:
    return SnapshotReadSemantics(
        read_source=SESSION_EVENTS_PROJECTION_READ_SOURCE,
        is_persisted=False,
        is_fresh=True,
        is_stale=False,
        last_refreshed_at=last_observed_at,
    )


def _session_event_sort_key(event: SessionEventRecord) -> tuple[str, int, str, str]:
    return (
        "0" if event.log_seq is not None else "1",
        event.log_seq or 0,
        event.occurred_at,
        event.event_id,
    )


def _list_project_session_events(
    session_service: SessionService,
    project_id: str,
) -> list[SessionEventRecord]:
    return sorted(
        session_service.list_events(session_id=stable_thread_id_for_project(project_id)),
        key=_session_event_sort_key,
    )


def _group_project_session_events(
    session_service: SessionService,
    *,
    relevant_types: set[str] | frozenset[str],
) -> dict[str, list[SessionEventRecord]]:
    grouped: dict[str, list[SessionEventRecord]] = {}
    for event in sorted(session_service.list_events(), key=_session_event_sort_key):
        if event.event_type not in relevant_types:
            continue
        if event.session_id != stable_thread_id_for_project(event.project_id):
            continue
        grouped.setdefault(event.project_id, []).append(event)
    return grouped


def _has_relevant_session_projection_events(events: list[SessionEventRecord]) -> bool:
    return any(event.event_type in SESSION_EVENT_PROJECTION_TYPES for event in events)


def _has_relevant_approval_projection_events(events: list[SessionEventRecord]) -> bool:
    return any(event.event_type in SESSION_EVENT_APPROVAL_TYPES for event in events)


def _build_approval_rows_from_session_events(
    events: list[SessionEventRecord],
) -> list[dict[str, Any]]:
    approvals_by_id: dict[str, dict[str, Any]] = {}
    for event in sorted(events, key=_session_event_sort_key):
        if event.event_type not in SESSION_EVENT_APPROVAL_TYPES:
            continue
        approval_id = str(event.related_ids.get("approval_id") or "")
        if not approval_id:
            continue
        if event.event_type == "approval_requested":
            requested_action = str(event.payload.get("requested_action") or "").strip()
            approvals_by_id[approval_id] = {
                "approval_id": approval_id,
                "project_id": event.project_id,
                "thread_id": stable_thread_id_for_project(event.project_id),
                "native_thread_id": (
                    str(
                        event.payload.get("native_thread_id")
                        or event.related_ids.get("native_thread_id")
                        or ""
                    ).strip()
                    or None
                ),
                "command": requested_action,
                "requested_action": requested_action,
                "reason": str(event.payload.get("reason") or event.payload.get("note") or ""),
                "alternative": str(event.payload.get("alternative") or ""),
                "status": "pending",
                "requested_at": event.occurred_at,
                "created_at": event.occurred_at,
                "risk_level": (
                    str(event.payload.get("risk_level") or event.payload.get("risk_class") or "")
                    or None
                ),
            }
            continue
        approvals_by_id.pop(approval_id, None)
    return sorted(
        approvals_by_id.values(),
        key=lambda row: (
            str(row.get("requested_at") or row.get("created_at") or "") == "",
            str(row.get("requested_at") or row.get("created_at") or ""),
            str(row.get("approval_id") or ""),
        ),
    )


def _latest_event_timestamp(events: list[SessionEventRecord]) -> str | None:
    if not events:
        return None
    return sorted(events, key=_session_event_sort_key)[-1].occurred_at


def _recovery_sort_key(record: Any) -> tuple[str, int, str, str]:
    return (
        "0" if getattr(record, "log_seq", None) is not None else "1",
        getattr(record, "log_seq", None) or 0,
        str(getattr(record, "updated_at", "")),
        str(getattr(record, "recovery_transaction_id", "")),
    )


def _build_recovery_projection(
    *,
    session_service: SessionService | None,
    project_id: str,
) -> dict[str, Any] | None:
    if session_service is None:
        return None
    records = session_service.list_recovery_transactions(
        parent_session_id=stable_thread_id_for_project(project_id),
    )
    if not records:
        return None
    latest = sorted(records, key=_recovery_sort_key)[-1]
    resume_outcome = str(latest.metadata.get("resume_outcome") or "").strip() or None
    if resume_outcome not in {"same_thread_resume", "new_child_session"}:
        resume_outcome = None
    if resume_outcome is None and latest.status in {"failed_retryable", "failed_manual"}:
        resume_outcome = "resume_failed"
    if resume_outcome is None and str(latest.metadata.get("resume_error") or "").strip():
        resume_outcome = "resume_failed"
    return {
        "recovery_outcome": resume_outcome,
        "recovery_status": latest.status,
        "recovery_updated_at": latest.updated_at,
        "recovery_child_session_id": latest.child_session_id,
    }


def _merge_fact_records(
    *collections: list[FactRecord],
) -> list[FactRecord]:
    merged: list[FactRecord] = []
    seen_codes: set[str] = set()
    for collection in collections:
        for fact in collection:
            if fact.fact_code in seen_codes:
                continue
            merged.append(fact)
            seen_codes.add(fact.fact_code)
    return merged


def _build_event_projection_task(
    *,
    project_id: str,
    approvals: list[dict[str, Any]],
    events: list[SessionEventRecord],
    persisted_record: PersistedSessionRecord | None = None,
    task: dict[str, Any] | None = None,
) -> dict[str, Any]:
    native_thread_id = str(
        (task or {}).get("thread_id")
        or (persisted_record.native_thread_id if persisted_record is not None else "")
        or ""
    ).strip()
    activity_phase = str(
        (task or {}).get("phase")
        or (
            persisted_record.progress.activity_phase
            if persisted_record is not None
            else "unknown"
        )
        or "unknown"
    )
    files_touched = list(
        (task or {}).get("files_touched")
        or (
            list(persisted_record.progress.files_touched)
            if persisted_record is not None
            else []
        )
    )
    last_progress_at = (
        _latest_event_timestamp(events)
        or str((task or {}).get("last_progress_at") or "").strip()
        or (
            persisted_record.progress.last_progress_at
            if persisted_record is not None
            else None
        )
    )
    summary = "waiting for approval" if approvals else "session active"
    return {
        "project_id": project_id,
        "thread_id": native_thread_id,
        "status": "waiting_human" if approvals else "running",
        "phase": activity_phase,
        "pending_approval": bool(approvals),
        "last_summary": summary,
        "files_touched": files_touched,
        "context_pressure": "low",
        "stuck_level": 0,
        "failure_count": 0,
        "last_progress_at": last_progress_at,
    }


def _build_session_read_bundle_from_session_events(
    *,
    project_id: str,
    events: list[SessionEventRecord],
    persisted_record: PersistedSessionRecord | None = None,
    task: dict[str, Any] | None = None,
    session_service: SessionService | None = None,
    decision_store: PolicyDecisionStore | None = None,
) -> SessionReadBundle:
    approvals = _build_approval_rows_from_session_events(events)
    projected_task = _build_event_projection_task(
        project_id=project_id,
        approvals=approvals,
        events=events,
        persisted_record=persisted_record,
        task=task,
    )
    approval_facts = build_fact_records(
        project_id=project_id,
        task=projected_task,
        approvals=approvals,
    )
    event_facts = build_session_service_fact_records(
        project_id=project_id,
        events=events,
    )
    facts = _merge_fact_records(approval_facts, event_facts)
    native_thread_id = str(projected_task.get("thread_id") or "") or None
    recovery = _build_recovery_projection(session_service=session_service, project_id=project_id)
    decision_trace = _build_decision_trace_projection(
        decision_store,
        project_id=project_id,
        session_id=stable_thread_id_for_project(project_id),
        native_thread_id=native_thread_id,
    )
    return SessionReadBundle(
        project_id=project_id,
        task=projected_task,
        approvals=approvals,
        facts=facts,
        session=build_session_projection(
            project_id=project_id,
            task=projected_task,
            approvals=approvals,
            facts=facts,
        ),
        progress=build_task_progress_view(
            project_id=project_id,
            task=projected_task,
            facts=facts,
            recovery=recovery,
            decision_trace=decision_trace,
        ),
        approval_queue=build_approval_projections(
            project_id=project_id,
            native_thread_id=native_thread_id,
            approvals=approvals,
        ),
        snapshot=_build_snapshot_read_semantics_for_session_events(
            _latest_event_timestamp(events),
        ),
    )


def _load_task_or_raise(
    client: AControlAgentClient,
    project_id: str,
) -> dict[str, Any] | None:
    try:
        body = client.get_envelope(project_id)
    except (httpx.RequestError, RuntimeError, OSError) as exc:
        raise SessionSpineUpstreamError(dict(CONTROL_LINK_ERROR)) from exc
    if not body.get("success"):
        error = body.get("error")
        if isinstance(error, dict):
            raise SessionSpineUpstreamError(dict(error))
        raise SessionSpineUpstreamError(dict(CONTROL_LINK_ERROR))
    data = body.get("data")
    if not isinstance(data, dict):
        raise SessionSpineUpstreamError(
            {"code": "CONTROL_LINK_ERROR", "message": "A 侧返回数据格式异常"}
        )
    return data


def _load_task_by_native_thread_or_raise(
    client: AControlAgentClient,
    native_thread_id: str,
) -> dict[str, Any] | None:
    try:
        body = client.get_envelope_by_thread(native_thread_id)
    except (httpx.RequestError, RuntimeError, OSError) as exc:
        raise SessionSpineUpstreamError(dict(CONTROL_LINK_ERROR)) from exc
    if not body.get("success"):
        error = body.get("error")
        if isinstance(error, dict):
            raise SessionSpineUpstreamError(dict(error))
        raise SessionSpineUpstreamError(dict(CONTROL_LINK_ERROR))
    data = body.get("data")
    if not isinstance(data, dict):
        raise SessionSpineUpstreamError(
            {"code": "CONTROL_LINK_ERROR", "message": "A 侧返回数据格式异常"}
        )
    return data


def _load_approvals_or_raise(
    client: AControlAgentClient,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    try:
        pending_items = client.list_approvals(status="pending", project_id=project_id)
    except (httpx.RequestError, RuntimeError, OSError) as exc:
        raise SessionSpineUpstreamError(dict(CONTROL_LINK_ERROR)) from exc
    deferred_items = _load_deferred_approvals_or_raise(client, project_id)
    rows_by_id: dict[str, dict[str, Any]] = {}
    for item in [*pending_items, *deferred_items]:
        row = dict(item)
        if not is_actionable_approval(row):
            continue
        if project_id is not None and str(row.get("project_id") or "") != project_id:
            continue
        approval_id = str(row.get("approval_id") or "")
        if approval_id:
            rows_by_id[approval_id] = row
    return sorted(
        rows_by_id.values(),
        key=lambda row: (
            str(row.get("requested_at") or row.get("created_at") or "") == "",
            str(row.get("requested_at") or row.get("created_at") or ""),
            str(row.get("approval_id") or ""),
        ),
    )


def _load_deferred_approvals_or_raise(
    client: AControlAgentClient,
    project_id: str | None,
) -> list[dict[str, Any]]:
    try:
        return client.list_approvals(
            status="approved",
            project_id=project_id,
            decided_by="policy-auto",
            callback_status="deferred",
        )
    except (httpx.RequestError, RuntimeError, OSError):
        try:
            approved_items = client.list_approvals(
                status="approved",
                project_id=project_id,
            )
        except (httpx.RequestError, RuntimeError, OSError) as exc:
            raise SessionSpineUpstreamError(dict(CONTROL_LINK_ERROR)) from exc
        return [
            dict(item)
            for item in approved_items
            if is_deferred_policy_auto_approval(dict(item))
        ]


def _load_tasks_or_raise(client: AControlAgentClient) -> list[dict[str, Any]]:
    try:
        return client.list_tasks()
    except (httpx.RequestError, RuntimeError, OSError) as exc:
        raise SessionSpineUpstreamError(dict(CONTROL_LINK_ERROR)) from exc


def _load_workspace_activity_or_raise(
    client: AControlAgentClient,
    project_id: str,
    *,
    recent_minutes: int,
) -> dict[str, Any]:
    try:
        body = client.get_workspace_activity_envelope(
            project_id,
            recent_minutes=recent_minutes,
        )
    except (httpx.RequestError, RuntimeError, OSError) as exc:
        raise SessionSpineUpstreamError(dict(CONTROL_LINK_ERROR)) from exc
    if not body.get("success"):
        error = body.get("error")
        if isinstance(error, dict):
            raise SessionSpineUpstreamError(dict(error))
        raise SessionSpineUpstreamError(dict(CONTROL_LINK_ERROR))
    data = body.get("data")
    if not isinstance(data, dict):
        raise SessionSpineUpstreamError(
            {"code": "CONTROL_LINK_ERROR", "message": "A 侧返回数据格式异常"}
        )
    activity = data.get("activity")
    if not isinstance(activity, dict):
        raise SessionSpineUpstreamError(
            {"code": "CONTROL_LINK_ERROR", "message": "A 侧返回数据格式异常"}
        )
    return dict(activity)


def _build_session_read_bundle(
    *,
    project_id: str,
    task: dict[str, Any] | None,
    approvals: list[dict[str, Any]],
    session_service: SessionService | None = None,
    decision_store: PolicyDecisionStore | None = None,
) -> SessionReadBundle:
    facts = build_fact_records(project_id=project_id, task=task, approvals=approvals)
    native_thread_id = str(task.get("thread_id") or "") or None
    recovery = _build_recovery_projection(session_service=session_service, project_id=project_id)
    decision_trace = _build_decision_trace_projection(
        decision_store,
        project_id=project_id,
        session_id=stable_thread_id_for_project(project_id),
        native_thread_id=native_thread_id,
    )
    return SessionReadBundle(
        project_id=project_id,
        task=task,
        approvals=approvals,
        facts=facts,
        session=build_session_projection(
            project_id=project_id,
            task=task,
            approvals=approvals,
            facts=facts,
        ),
        progress=build_task_progress_view(
            project_id=project_id,
            task=task,
            facts=facts,
            recovery=recovery,
            decision_trace=decision_trace,
        ),
        approval_queue=build_approval_projections(
            project_id=project_id,
            native_thread_id=native_thread_id,
            approvals=approvals,
        ),
        snapshot=None,
    )


def _approval_projection_to_row(approval: ApprovalProjection) -> dict[str, Any]:
    return {
        "approval_id": approval.approval_id,
        "project_id": approval.project_id,
        "native_thread_id": approval.native_thread_id,
        "command": approval.command,
        "reason": approval.reason,
        "alternative": approval.alternative,
        "status": approval.status,
        "requested_at": approval.requested_at,
        "decided_at": approval.decided_at,
        "decided_by": approval.decided_by,
        "risk_level": approval.risk_level,
    }


def _canonical_approval_to_row(approval: Any) -> dict[str, Any]:
    return {
        "approval_id": approval.approval_id,
        "project_id": approval.project_id,
        "thread_id": approval.thread_id,
        "native_thread_id": approval.native_thread_id,
        "command": approval.requested_action,
        "requested_action": approval.requested_action,
        "status": approval.status,
        "requested_at": approval.created_at,
        "created_at": approval.created_at,
        "decided_at": approval.decided_at,
        "decided_by": approval.decided_by,
        "decision": approval.decision.model_dump(mode="json"),
    }


def _list_actionable_canonical_approval_rows(
    approval_store: CanonicalApprovalStore | None,
    *,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    if approval_store is None:
        return []
    rows = [
        _canonical_approval_to_row(record)
        for record in approval_store.list_records()
        if project_id is None or record.project_id == project_id
    ]
    actionable = [row for row in rows if is_actionable_approval(row)]
    return sorted(
        actionable,
        key=lambda row: (
            str(row.get("requested_at") or row.get("created_at") or "") == "",
            str(row.get("requested_at") or row.get("created_at") or ""),
            str(row.get("approval_id") or ""),
        ),
    )


def _merge_approval_rows(
    persisted_approvals: list[ApprovalProjection],
    canonical_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows_by_id: dict[str, dict[str, Any]] = {}
    for approval in persisted_approvals:
        row = _approval_projection_to_row(approval)
        approval_id = str(row.get("approval_id") or "")
        if approval_id:
            rows_by_id[approval_id] = row
    for row in canonical_rows:
        approval_id = str(row.get("approval_id") or "")
        if approval_id and approval_id not in rows_by_id:
            rows_by_id[approval_id] = dict(row)
    return sorted(
        rows_by_id.values(),
        key=lambda row: (
            str(row.get("requested_at") or row.get("created_at") or "") == "",
            str(row.get("requested_at") or row.get("created_at") or ""),
            str(row.get("approval_id") or ""),
        ),
    )


def _task_from_persisted_record(
    record: PersistedSessionRecord,
    *,
    approvals: list[dict[str, Any]],
) -> dict[str, Any]:
    fact_codes = {fact.fact_code for fact in record.facts}
    status = "completed"
    if approvals:
        status = "waiting_human"
    elif record.session.session_state == "blocked":
        status = "running"
    return {
        "project_id": record.project_id,
        "thread_id": record.native_thread_id,
        "status": status,
        "phase": record.progress.activity_phase,
        "pending_approval": bool(approvals),
        "last_summary": record.progress.summary or record.session.headline,
        "files_touched": list(record.progress.files_touched),
        "context_pressure": record.progress.context_pressure,
        "stuck_level": record.progress.stuck_level,
        "failure_count": 3 if "repeat_failure" in fact_codes else 0,
        "last_progress_at": record.progress.last_progress_at,
    }


def _build_session_read_bundle_from_persisted_record(
    record: PersistedSessionRecord,
    *,
    approval_store: CanonicalApprovalStore | None = None,
    freshness_window_seconds: float,
    session_service: SessionService | None = None,
    decision_store: PolicyDecisionStore | None = None,
) -> SessionReadBundle:
    canonical_approvals = _list_actionable_canonical_approval_rows(
        approval_store,
        project_id=record.project_id,
    )
    if canonical_approvals:
        approvals = _merge_approval_rows(record.approval_queue, canonical_approvals)
        synthesized_task = _task_from_persisted_record(record, approvals=approvals)
        bundle = _build_session_read_bundle(
            project_id=record.project_id,
            task=synthesized_task,
            approvals=approvals,
            session_service=session_service,
            decision_store=decision_store,
        )
        return SessionReadBundle(
            project_id=bundle.project_id,
            task=bundle.task,
            approvals=bundle.approvals,
            facts=bundle.facts,
            session=bundle.session,
            progress=bundle.progress,
            approval_queue=bundle.approval_queue,
            snapshot=_build_snapshot_read_semantics_from_persisted_record(
                record,
                freshness_window_seconds=freshness_window_seconds,
            ),
        )
    recovery = _build_recovery_projection(
        session_service=session_service,
        project_id=record.project_id,
    )
    decision_trace = _build_decision_trace_projection(
        decision_store,
        project_id=record.project_id,
        session_id=record.thread_id,
        native_thread_id=record.native_thread_id,
    )
    return SessionReadBundle(
        project_id=record.project_id,
        task=None,
        approvals=[],
        facts=list(record.facts),
        session=record.session,
        progress=record.progress.model_copy(
            update={
                "recovery_outcome": (recovery or {}).get("recovery_outcome"),
                "recovery_status": (recovery or {}).get("recovery_status"),
                "recovery_updated_at": (recovery or {}).get("recovery_updated_at"),
                "recovery_child_session_id": (recovery or {}).get("recovery_child_session_id"),
                "decision_trace_ref": (decision_trace or {}).get("decision_trace_ref"),
                "decision_degrade_reason": (decision_trace or {}).get("decision_degrade_reason"),
                "provider_output_schema_ref": (decision_trace or {}).get(
                    "provider_output_schema_ref"
                ),
            }
        ),
        approval_queue=list(record.approval_queue),
        snapshot=_build_snapshot_read_semantics_from_persisted_record(
            record,
            freshness_window_seconds=freshness_window_seconds,
        ),
    )


def load_persisted_session_record_or_raise(
    project_id: str,
    *,
    store: SessionSpineStore,
) -> PersistedSessionRecord:
    record = store.get(project_id)
    if record is None:
        raise SessionSpineUpstreamError(dict(PERSISTED_SESSION_SPINE_REQUIRED_ERROR))
    return record


def evaluate_session_policy_from_persisted_spine(
    project_id: str,
    *,
    action_ref: str,
    trigger: str,
    store: SessionSpineStore,
    decision_store: PolicyDecisionStore | None = None,
    delivery_outbox_store: object | None = None,
) -> CanonicalDecisionRecord:
    record = load_persisted_session_record_or_raise(project_id, store=store)
    decision = evaluate_persisted_session_policy(
        record,
        action_ref=action_ref,
        trigger=trigger,
    )
    canonical_decision = decision_store.put(decision) if decision_store is not None else decision
    if delivery_outbox_store is not None:
        from watchdog.services.delivery.envelopes import build_envelopes_for_decision

        delivery_outbox_store.enqueue_envelopes(build_envelopes_for_decision(canonical_decision))
    return canonical_decision


def build_session_read_bundle(
    client: AControlAgentClient,
    project_id: str,
    *,
    session_service: SessionService | None = None,
    store: SessionSpineStore | None = None,
    approval_store: CanonicalApprovalStore | None = None,
    decision_store: PolicyDecisionStore | None = None,
    freshness_window_seconds: float = DEFAULT_SESSION_SPINE_FRESHNESS_WINDOW_SECONDS,
) -> SessionReadBundle:
    persisted_record = store.get(project_id) if store is not None else None
    if session_service is not None:
        session_events = _list_project_session_events(session_service, project_id)
        if _has_relevant_session_projection_events(session_events):
            return _build_session_read_bundle_from_session_events(
                project_id=project_id,
                events=session_events,
                persisted_record=persisted_record,
                session_service=session_service,
                decision_store=decision_store,
            )
    if store is not None:
        if persisted_record is not None:
            return _build_session_read_bundle_from_persisted_record(
                persisted_record,
                approval_store=approval_store,
                freshness_window_seconds=freshness_window_seconds,
                session_service=session_service,
                decision_store=decision_store,
            )
    task = _load_task_or_raise(client, project_id)
    approvals = _load_approvals_or_raise(client, project_id)
    bundle = _build_session_read_bundle(
        project_id=project_id,
        task=task,
        approvals=approvals,
        session_service=session_service,
        decision_store=decision_store,
    )
    return SessionReadBundle(
        project_id=bundle.project_id,
        task=bundle.task,
        approvals=bundle.approvals,
        facts=bundle.facts,
        session=bundle.session,
        progress=bundle.progress,
        approval_queue=bundle.approval_queue,
        snapshot=_build_snapshot_read_semantics_for_live_query(),
    )


def build_session_read_bundle_by_native_thread(
    client: AControlAgentClient,
    native_thread_id: str,
    *,
    session_service: SessionService | None = None,
    store: SessionSpineStore | None = None,
    approval_store: CanonicalApprovalStore | None = None,
    decision_store: PolicyDecisionStore | None = None,
    freshness_window_seconds: float = DEFAULT_SESSION_SPINE_FRESHNESS_WINDOW_SECONDS,
) -> SessionReadBundle:
    persisted_record = store.get_by_native_thread(native_thread_id) if store is not None else None
    if session_service is not None and persisted_record is not None:
        session_events = _list_project_session_events(session_service, persisted_record.project_id)
        if _has_relevant_session_projection_events(session_events):
            return _build_session_read_bundle_from_session_events(
                project_id=persisted_record.project_id,
                events=session_events,
                persisted_record=persisted_record,
                session_service=session_service,
                decision_store=decision_store,
            )
    if store is not None:
        if persisted_record is not None:
            return _build_session_read_bundle_from_persisted_record(
                persisted_record,
                approval_store=approval_store,
                freshness_window_seconds=freshness_window_seconds,
                session_service=session_service,
                decision_store=decision_store,
            )
    task = _load_task_by_native_thread_or_raise(client, native_thread_id)
    project_id = str(task.get("project_id") or "")
    if not project_id:
        raise SessionSpineUpstreamError(
            {"code": "CONTROL_LINK_ERROR", "message": "A 侧返回数据格式异常"}
        )
    if session_service is not None:
        session_events = _list_project_session_events(session_service, project_id)
        if _has_relevant_session_projection_events(session_events):
            return _build_session_read_bundle_from_session_events(
                project_id=project_id,
                events=session_events,
                task=task,
                session_service=session_service,
                decision_store=decision_store,
            )
    approvals = _load_approvals_or_raise(client, project_id)
    bundle = _build_session_read_bundle(
        project_id=project_id,
        task=task,
        approvals=approvals,
        session_service=session_service,
        decision_store=decision_store,
    )
    return SessionReadBundle(
        project_id=bundle.project_id,
        task=bundle.task,
        approvals=bundle.approvals,
        facts=bundle.facts,
        session=bundle.session,
        progress=bundle.progress,
        approval_queue=bundle.approval_queue,
        snapshot=_build_snapshot_read_semantics_for_live_query(),
    )


def build_workspace_activity_bundle(
    client: AControlAgentClient,
    project_id: str,
    *,
    recent_minutes: int = 15,
) -> WorkspaceActivityReadBundle:
    task = _load_task_or_raise(client, project_id)
    approvals = _load_approvals_or_raise(client, project_id)
    facts = build_fact_records(project_id=project_id, task=task, approvals=approvals)
    return WorkspaceActivityReadBundle(
        project_id=project_id,
        task=task,
        approvals=approvals,
        facts=facts,
        session=build_session_projection(
            project_id=project_id,
            task=task,
            approvals=approvals,
            facts=facts,
        ),
        workspace_activity=build_workspace_activity_view(
            project_id=project_id,
            task=task,
            activity=_load_workspace_activity_or_raise(
                client,
                project_id,
                recent_minutes=recent_minutes,
            ),
        ),
    )


def build_approval_inbox_bundle(
    client: AControlAgentClient,
    project_id: str | None = None,
    *,
    session_service: SessionService | None = None,
    store: SessionSpineStore | None = None,
    approval_store: CanonicalApprovalStore | None = None,
) -> ApprovalInboxReadBundle:
    if session_service is not None:
        if project_id is not None:
            session_events = _list_project_session_events(session_service, project_id)
            if _has_relevant_approval_projection_events(session_events):
                approvals = _build_approval_rows_from_session_events(session_events)
                return ApprovalInboxReadBundle(
                    project_id=project_id,
                    approvals=approvals,
                    approval_inbox=build_approval_inbox_projections(approvals=approvals),
                )
        else:
            grouped_events = _group_project_session_events(
                session_service,
                relevant_types=SESSION_EVENT_APPROVAL_TYPES,
            )
            if grouped_events:
                event_project_ids = set(grouped_events)
                event_approvals: list[dict[str, Any]] = []
                for events in grouped_events.values():
                    event_approvals.extend(_build_approval_rows_from_session_events(events))

                canonical_rows = [
                    row
                    for row in _list_actionable_canonical_approval_rows(approval_store)
                    if str(row.get("project_id") or "") not in event_project_ids
                ]
                persisted: list[ApprovalProjection] = []
                if store is not None:
                    persisted = sorted(
                        [
                            approval
                            for record in store.list_records()
                            for approval in record.approval_queue
                            if approval.project_id not in event_project_ids
                        ],
                        key=_approval_sort_key,
                    )
                fallback_rows = _merge_approval_rows(persisted, canonical_rows)
                merged_rows = sorted(
                    [*event_approvals, *fallback_rows],
                    key=lambda row: (
                        str(row.get("requested_at") or row.get("created_at") or "") == "",
                        str(row.get("requested_at") or row.get("created_at") or ""),
                        str(row.get("approval_id") or ""),
                    ),
                )
                return ApprovalInboxReadBundle(
                    project_id=None,
                    approvals=merged_rows,
                    approval_inbox=build_approval_inbox_projections(approvals=merged_rows),
                )
    canonical_rows = _list_actionable_canonical_approval_rows(
        approval_store,
        project_id=project_id,
    )
    if store is not None:
        persisted = sorted(
            [
            approval
            for record in store.list_records()
            for approval in record.approval_queue
            if project_id is None or approval.project_id == project_id
            ],
            key=_approval_sort_key,
        )
        if persisted or canonical_rows:
            merged = list(persisted)
            existing_ids = {approval.approval_id for approval in merged}
            merged.extend(
                projection
                for projection in build_approval_inbox_projections(approvals=canonical_rows)
                if projection.approval_id not in existing_ids
            )
            merged.sort(key=_approval_sort_key)
            return ApprovalInboxReadBundle(
                project_id=project_id,
                approvals=[approval.model_dump(mode="json") for approval in merged],
                approval_inbox=merged,
            )
    approvals = _load_approvals_or_raise(client, project_id)
    return ApprovalInboxReadBundle(
        project_id=project_id,
        approvals=approvals,
        approval_inbox=build_approval_inbox_projections(approvals=approvals),
    )


def build_session_directory_bundle(
    client: AControlAgentClient,
    *,
    session_service: SessionService | None = None,
    store: SessionSpineStore | None = None,
    approval_store: CanonicalApprovalStore | None = None,
    decision_store: PolicyDecisionStore | None = None,
    resident_expert_runtime_service: ResidentExpertRuntimeService | None = None,
) -> SessionDirectoryReadBundle:
    persisted_records = store.list_records() if store is not None else []
    persisted_by_project = {record.project_id: record for record in persisted_records}
    resident_expert_coverage = _build_resident_expert_coverage_view(
        resident_expert_runtime_service
    )
    if session_service is not None:
        grouped_events = _group_project_session_events(
            session_service,
            relevant_types=SESSION_EVENT_PROJECTION_TYPES,
        )
        if grouped_events:
            sessions: list[SessionProjection] = []
            progresses: list[TaskProgressView] = []
            ordered_project_ids = list(dict.fromkeys([*grouped_events.keys(), *persisted_by_project.keys()]))
            for current_project_id in ordered_project_ids:
                if current_project_id in grouped_events:
                    bundle = _build_session_read_bundle_from_session_events(
                        project_id=current_project_id,
                        events=grouped_events[current_project_id],
                        persisted_record=persisted_by_project.get(current_project_id),
                        session_service=session_service,
                        decision_store=decision_store,
                    )
                    sessions.append(bundle.session)
                    progresses.append(bundle.progress)
                    continue
                record = persisted_by_project.get(current_project_id)
                if record is None:
                    continue
                bundle = _build_session_read_bundle_from_persisted_record(
                    record,
                    approval_store=approval_store,
                    freshness_window_seconds=DEFAULT_SESSION_SPINE_FRESHNESS_WINDOW_SECONDS,
                    session_service=session_service,
                    decision_store=decision_store,
                )
                sessions.append(bundle.session)
                progresses.append(bundle.progress)
            if sessions:
                return SessionDirectoryReadBundle(
                    tasks=[],
                    approvals=[],
                    sessions=sessions,
                    progresses=progresses,
                    resident_expert_coverage=resident_expert_coverage,
                )
    if store is not None:
        if persisted_records:
            bundles = [
                _build_session_read_bundle_from_persisted_record(
                    record,
                    approval_store=approval_store,
                    freshness_window_seconds=DEFAULT_SESSION_SPINE_FRESHNESS_WINDOW_SECONDS,
                    session_service=session_service,
                    decision_store=decision_store,
                )
                for record in persisted_records
            ]
            return SessionDirectoryReadBundle(
                tasks=[],
                approvals=[],
                sessions=[bundle.session for bundle in bundles],
                progresses=[bundle.progress for bundle in bundles],
                resident_expert_coverage=resident_expert_coverage,
            )
    tasks = _load_tasks_or_raise(client)
    approvals = _load_approvals_or_raise(client)
    tasks_by_project: dict[str, dict[str, Any]] = {}
    for task in tasks:
        project_id = str(task.get("project_id") or "")
        if not project_id:
            continue
        if project_id in tasks_by_project:
            tasks_by_project.pop(project_id)
        tasks_by_project[project_id] = dict(task)

    sessions: list[SessionProjection] = []
    progresses: list[TaskProgressView] = []
    for project_id, task in tasks_by_project.items():
        project_approvals = [
            row for row in approvals if str(row.get("project_id") or "") == project_id
        ]
        bundle = _build_session_read_bundle(
            project_id=project_id,
            task=task,
            approvals=project_approvals,
            session_service=session_service,
            decision_store=decision_store,
        )
        sessions.append(bundle.session)
        progresses.append(bundle.progress)

    return SessionDirectoryReadBundle(
        tasks=list(tasks_by_project.values()),
        approvals=approvals,
        sessions=sessions,
        progresses=progresses,
        resident_expert_coverage=resident_expert_coverage,
    )
