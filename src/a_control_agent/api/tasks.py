from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from a_control_agent.api.deps import require_token
from a_control_agent.envelope import err, ok
from a_control_agent.repo_activity import summarize_workspace_activity
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


@router.get("/{project_id}/workspace-activity")
def workspace_activity(
    project_id: str,
    request: Request,
    store: TaskStore = Depends(get_store),
    recent_minutes: int = Query(default=15, ge=1, le=24 * 60),
    _: None = Depends(require_token),
) -> dict[str, Any]:
    """基于任务 cwd 的文件 mtime 摘要（不执行 shell）。"""
    rec = store.get(project_id)
    if rec is None:
        return err(
            request.headers.get("x-request-id"),
            {"code": "NOT_FOUND", "message": f"unknown project_id: {project_id}"},
        )
    cwd = rec.get("cwd") or ""
    summary = summarize_workspace_activity(
        Path(str(cwd)),
        recent_minutes=recent_minutes,
    )
    return ok(
        request.headers.get("x-request-id"),
        {"project_id": project_id, "activity": summary},
    )


@router.post("/{project_id}/steer")
def steer_task(
    project_id: str,
    request: Request,
    body: dict[str, Any],
    store: TaskStore = Depends(get_store),
    _: None = Depends(require_token),
) -> dict[str, Any]:
    message = body.get("message")
    source = body.get("source", "watchdog")
    reason = body.get("reason", "policy")
    sl_raw = body.get("stuck_level")
    stuck_level: int | None = None
    if sl_raw is not None:
        try:
            stuck_level = int(sl_raw)
        except (TypeError, ValueError):
            return err(
                request.headers.get("x-request-id"),
                {"code": "INVALID_ARGUMENT", "message": "stuck_level must be int"},
            )
        if stuck_level < 0 or stuck_level > 4:
            return err(
                request.headers.get("x-request-id"),
                {"code": "INVALID_ARGUMENT", "message": "stuck_level must be 0..4"},
            )
    if not message or not isinstance(message, str):
        return err(
            request.headers.get("x-request-id"),
            {"code": "INVALID_ARGUMENT", "message": "message required"},
        )
    rec = store.apply_steer(
        project_id,
        message=message,
        source=str(source),
        reason=str(reason),
        stuck_level=stuck_level,
    )
    if rec is None:
        return err(
            request.headers.get("x-request-id"),
            {"code": "NOT_FOUND", "message": f"unknown project_id: {project_id}"},
        )
    return ok(
        request.headers.get("x-request-id"),
        {"project_id": rec["project_id"], "status": rec.get("status", "running")},
    )
