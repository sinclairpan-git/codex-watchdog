from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from watchdog.contracts.session_spine.models import (
    ApprovalProjection,
    FactRecord,
    SessionProjection,
    SnapshotReadSemantics,
    TaskProgressView,
    WorkspaceActivityView,
)
from watchdog.services.policy.decisions import (
    CanonicalDecisionRecord,
    PolicyDecisionStore,
)
from watchdog.services.policy.engine import evaluate_persisted_session_policy
from watchdog.services.a_client.client import AControlAgentClient
from watchdog.services.session_spine.facts import build_fact_records
from watchdog.services.session_spine.projection import (
    build_approval_inbox_projections,
    build_approval_projections,
    build_session_projection,
    build_task_progress_view,
    build_workspace_activity_view,
)
from watchdog.services.session_spine.store import PersistedSessionRecord, SessionSpineStore
from watchdog.services.session_spine.approval_visibility import (
    is_actionable_approval,
    is_deferred_policy_auto_approval,
)


CONTROL_LINK_ERROR = {
    "code": "CONTROL_LINK_ERROR",
    "message": "无法连接 A-Control-Agent 或链路异常；请检查网络与 A 侧服务状态。",
}
PERSISTED_SESSION_SPINE_REQUIRED_ERROR = {
    "code": "PERSISTED_SESSION_SPINE_REQUIRED",
    "message": "缺少 canonical persisted session spine；请先刷新 resident session spine。",
}
PERSISTED_SPINE_READ_SOURCE = "persisted_spine"
LIVE_QUERY_FALLBACK_READ_SOURCE = "live_query_fallback"
DEFAULT_SESSION_SPINE_FRESHNESS_WINDOW_SECONDS = 60.0


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
            str(row.get("requested_at") or "") == "",
            str(row.get("requested_at") or ""),
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
) -> SessionReadBundle:
    facts = build_fact_records(project_id=project_id, task=task, approvals=approvals)
    native_thread_id = str(task.get("thread_id") or "") or None
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
        ),
        approval_queue=build_approval_projections(
            project_id=project_id,
            native_thread_id=native_thread_id,
            approvals=approvals,
        ),
        snapshot=None,
    )


def _build_session_read_bundle_from_persisted_record(
    record: PersistedSessionRecord,
    *,
    freshness_window_seconds: float,
) -> SessionReadBundle:
    return SessionReadBundle(
        project_id=record.project_id,
        task=None,
        approvals=[],
        facts=list(record.facts),
        session=record.session,
        progress=record.progress,
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
    store: SessionSpineStore | None = None,
    freshness_window_seconds: float = DEFAULT_SESSION_SPINE_FRESHNESS_WINDOW_SECONDS,
) -> SessionReadBundle:
    if store is not None:
        record = store.get(project_id)
        if record is not None:
            return _build_session_read_bundle_from_persisted_record(
                record,
                freshness_window_seconds=freshness_window_seconds,
            )
    task = _load_task_or_raise(client, project_id)
    approvals = _load_approvals_or_raise(client, project_id)
    bundle = _build_session_read_bundle(
        project_id=project_id,
        task=task,
        approvals=approvals,
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
    store: SessionSpineStore | None = None,
    freshness_window_seconds: float = DEFAULT_SESSION_SPINE_FRESHNESS_WINDOW_SECONDS,
) -> SessionReadBundle:
    if store is not None:
        record = store.get_by_native_thread(native_thread_id)
        if record is not None:
            return _build_session_read_bundle_from_persisted_record(
                record,
                freshness_window_seconds=freshness_window_seconds,
            )
    task = _load_task_by_native_thread_or_raise(client, native_thread_id)
    project_id = str(task.get("project_id") or "")
    if not project_id:
        raise SessionSpineUpstreamError(
            {"code": "CONTROL_LINK_ERROR", "message": "A 侧返回数据格式异常"}
        )
    approvals = _load_approvals_or_raise(client, project_id)
    bundle = _build_session_read_bundle(
        project_id=project_id,
        task=task,
        approvals=approvals,
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
    store: SessionSpineStore | None = None,
) -> ApprovalInboxReadBundle:
    if store is not None:
        persisted = [
            approval
            for record in store.list_records()
            for approval in record.approval_queue
            if project_id is None or approval.project_id == project_id
        ]
        if persisted:
            return ApprovalInboxReadBundle(
                project_id=project_id,
                approvals=[approval.model_dump(mode="json") for approval in persisted],
                approval_inbox=persisted,
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
    store: SessionSpineStore | None = None,
) -> SessionDirectoryReadBundle:
    if store is not None:
        persisted = store.list_records()
        if persisted:
            return SessionDirectoryReadBundle(
                tasks=[],
                approvals=[],
                sessions=[record.session for record in persisted],
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
    for project_id, task in tasks_by_project.items():
        project_approvals = [
            row for row in approvals if str(row.get("project_id") or "") == project_id
        ]
        facts = build_fact_records(project_id=project_id, task=task, approvals=project_approvals)
        sessions.append(
            build_session_projection(
                project_id=project_id,
                task=task,
                approvals=project_approvals,
                facts=facts,
            )
        )

    return SessionDirectoryReadBundle(
        tasks=list(tasks_by_project.values()),
        approvals=approvals,
        sessions=sessions,
    )
