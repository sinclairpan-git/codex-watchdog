from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from watchdog.contracts.session_spine.models import (
    ApprovalProjection,
    FactRecord,
    SessionProjection,
    TaskProgressView,
)
from watchdog.services.a_client.client import AControlAgentClient
from watchdog.services.session_spine.facts import build_fact_records
from watchdog.services.session_spine.projection import (
    build_approval_projections,
    build_session_projection,
    build_task_progress_view,
)


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


def _load_approvals_or_raise(
    client: AControlAgentClient,
    project_id: str,
) -> list[dict[str, Any]]:
    try:
        items = client.list_approvals(status="pending")
    except (httpx.RequestError, RuntimeError, OSError) as exc:
        raise SessionSpineUpstreamError(dict(CONTROL_LINK_ERROR)) from exc
    return [
        dict(item)
        for item in items
        if str(item.get("project_id") or "") == project_id
    ]


def build_session_read_bundle(
    client: AControlAgentClient,
    project_id: str,
) -> SessionReadBundle:
    task = _load_task_or_raise(client, project_id)
    approvals = _load_approvals_or_raise(client, project_id)
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
