from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from a_control_agent.api.deps import require_token
from a_control_agent.envelope import err, ok
from a_control_agent.settings import Settings
from a_control_agent.storage.tasks_store import TaskStore

router = APIRouter(prefix="/tasks", tags=["tasks"])


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_store(request: Request) -> TaskStore:
    return request.app.state.task_store


@router.post("")
def create_task(
    request: Request,
    body: dict[str, Any],
    settings: Settings = Depends(get_settings),
    store: TaskStore = Depends(get_store),
    _: None = Depends(require_token),
) -> dict[str, Any]:
    project_id = body.get("project_id")
    if not project_id or not isinstance(project_id, str):
        return err(
            request.headers.get("x-request-id"),
            {"code": "INVALID_ARGUMENT", "message": "project_id required"},
        )
    rec = store.upsert_from_create(project_id, body)
    return ok(
        request.headers.get("x-request-id"),
        {
            "project_id": rec["project_id"],
            "thread_id": rec["thread_id"],
            "status": rec["status"],
        },
    )


@router.get("/{project_id}")
def get_task(
    project_id: str,
    request: Request,
    store: TaskStore = Depends(get_store),
    _: None = Depends(require_token),
) -> dict[str, Any]:
    rec = store.get(project_id)
    if rec is None:
        return err(
            request.headers.get("x-request-id"),
            {"code": "NOT_FOUND", "message": f"unknown project_id: {project_id}"},
        )
    return ok(request.headers.get("x-request-id"), dict(rec))
