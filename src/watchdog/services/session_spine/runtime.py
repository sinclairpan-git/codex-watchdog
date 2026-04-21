from __future__ import annotations

import httpx
from typing import Any

from watchdog.services.a_client.client import AControlAgentClient
from watchdog.services.session_spine.service import (
    _build_session_read_bundle,
    _load_approvals_or_raise,
)
from watchdog.services.session_spine.store import SessionSpineStore


class SessionSpineRuntime:
    def __init__(
        self,
        *,
        client: AControlAgentClient,
        store: SessionSpineStore,
    ) -> None:
        self._client = client
        self._store = store

    def refresh_all(self) -> None:
        try:
            tasks = self._client.list_tasks()
        except (httpx.RequestError, RuntimeError, OSError):
            return
        try:
            approvals = _load_approvals_or_raise(self._client)
        except RuntimeError:
            approvals = None

        approvals_by_project: dict[str, list[dict[str, Any]]] | None = {}
        if approvals is None:
            approvals_by_project = None
        else:
            for approval in approvals:
                project_id = str(approval.get("project_id") or "")
                if not project_id:
                    continue
                approvals_by_project.setdefault(project_id, []).append(dict(approval))

        for task in tasks:
            if not isinstance(task, dict):
                continue
            project_id = str(task.get("project_id") or "")
            if not project_id:
                continue
            self.refresh_project(
                project_id,
                task=task,
                approvals=(
                    approvals_by_project.get(project_id, [])
                    if approvals_by_project is not None
                    else None
                ),
            )

    def refresh_project(
        self,
        project_id: str,
        *,
        task: dict[str, Any] | None = None,
        approvals: list[dict[str, Any]] | None = None,
    ) -> None:
        if task is None:
            try:
                body = self._client.get_envelope(project_id)
            except (httpx.RequestError, RuntimeError, OSError):
                return
            if not body.get("success"):
                return
            data = body.get("data")
            if not isinstance(data, dict):
                return
            task = data

        if approvals is None:
            try:
                approvals = _load_approvals_or_raise(self._client, project_id)
            except RuntimeError:
                approvals = []

        bundle = _build_session_read_bundle(
            project_id=project_id,
            task=task,
            approvals=approvals,
        )
        self._store.put(
            project_id=project_id,
            session=bundle.session,
            progress=bundle.progress,
            facts=bundle.facts,
            approval_queue=bundle.approval_queue,
            last_local_manual_activity_at=(
                str(task.get("last_local_manual_activity_at") or "") or None
            ),
        )
