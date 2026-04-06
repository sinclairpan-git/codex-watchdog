from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from watchdog.contracts.session_spine.models import (
    ApprovalProjection,
    FactRecord,
    SessionProjection,
    TaskProgressView,
    WorkspaceActivityView,
)
from watchdog.services.a_client.client import AControlAgentClient
from watchdog.services.session_spine.facts import build_fact_records
from watchdog.services.session_spine.projection import (
    build_approval_inbox_projections,
    build_approval_projections,
    build_session_projection,
    build_task_progress_view,
    build_workspace_activity_view,
)
from watchdog.services.session_spine.approval_visibility import is_actionable_approval


CONTROL_LINK_ERROR = {
    "code": "CONTROL_LINK_ERROR",
    "message": "无法连接 A-Control-Agent 或链路异常；请检查网络与 A 侧服务状态。",
}


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
    try:
        deferred_items = client.list_approvals(
            status="approved",
            project_id=project_id,
            decided_by="policy-auto",
            callback_status="deferred",
        )
    except (httpx.RequestError, RuntimeError, OSError) as exc:
        _ = exc
        deferred_items = []
    rows_by_id: dict[str, dict[str, Any]] = {}
    for item in [*pending_items, *deferred_items]:
        row = dict(item)
        if not is_actionable_approval(row):
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
    )


def build_session_read_bundle(
    client: AControlAgentClient,
    project_id: str,
) -> SessionReadBundle:
    task = _load_task_or_raise(client, project_id)
    approvals = _load_approvals_or_raise(client, project_id)
    return _build_session_read_bundle(
        project_id=project_id,
        task=task,
        approvals=approvals,
    )


def build_session_read_bundle_by_native_thread(
    client: AControlAgentClient,
    native_thread_id: str,
) -> SessionReadBundle:
    task = _load_task_by_native_thread_or_raise(client, native_thread_id)
    project_id = str(task.get("project_id") or "")
    if not project_id:
        raise SessionSpineUpstreamError(
            {"code": "CONTROL_LINK_ERROR", "message": "A 侧返回数据格式异常"}
        )
    approvals = _load_approvals_or_raise(client, project_id)
    return _build_session_read_bundle(
        project_id=project_id,
        task=task,
        approvals=approvals,
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
) -> ApprovalInboxReadBundle:
    approvals = _load_approvals_or_raise(client, project_id)
    return ApprovalInboxReadBundle(
        project_id=project_id,
        approvals=approvals,
        approval_inbox=build_approval_inbox_projections(approvals=approvals),
    )


def build_session_directory_bundle(
    client: AControlAgentClient,
) -> SessionDirectoryReadBundle:
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
