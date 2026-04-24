from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from a_control_agent.audit import append_jsonl
from a_control_agent.api.deps import require_token
from a_control_agent.envelope import err, ok
from a_control_agent.repo_activity import summarize_workspace_activity
from a_control_agent.settings import Settings
from a_control_agent.storage.tasks_store import TaskStore
from watchdog.services.session_spine.task_state import (
    is_canonical_task_phase,
    is_canonical_task_status,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])
_CANONICAL_CONTEXT_PRESSURES = {"low", "medium", "high", "critical"}


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_store(request: Request) -> TaskStore:
    return request.app.state.task_store


def get_bridge(request: Request) -> Any:
    return getattr(request.app.state, "codex_bridge", None)


def _encode_sse(event: dict[str, Any]) -> str:
    event_id = str(event.get("event_id") or "")
    event_type = str(event.get("event_type") or "message")
    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    lines: list[str] = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event_type}")
    for line in payload.splitlines() or [payload]:
        lines.append(f"data: {line}")
    return "\n".join(lines) + "\n\n"


@router.get("")
def list_tasks(
    request: Request,
    store: TaskStore = Depends(get_store),
    _: None = Depends(require_token),
) -> dict[str, Any]:
    tasks = [dict(rec) for rec in store.list_tasks(active_only=True)]
    return ok(request.headers.get("x-request-id"), {"tasks": tasks})


@router.get("/by-thread/{thread_id}")
def get_task_by_thread(
    thread_id: str,
    request: Request,
    store: TaskStore = Depends(get_store),
    _: None = Depends(require_token),
) -> dict[str, Any]:
    rec = store.get_by_thread(thread_id)
    if rec is None:
        return err(
            request.headers.get("x-request-id"),
            {"code": "NOT_FOUND", "message": f"unknown thread_id: {thread_id}"},
        )
    return ok(request.headers.get("x-request-id"), dict(rec))


@router.post("/native-threads")
def register_native_thread(
    request: Request,
    body: dict[str, Any],
    store: TaskStore = Depends(get_store),
    _: None = Depends(require_token),
) -> dict[str, Any]:
    thread_id = body.get("thread_id")
    project_id = body.get("project_id")
    cwd = body.get("cwd")
    if not isinstance(thread_id, str) or not thread_id.strip():
        return err(
            request.headers.get("x-request-id"),
            {"code": "INVALID_ARGUMENT", "message": "thread_id required"},
        )
    if not (
        isinstance(project_id, str)
        and project_id.strip()
        or isinstance(cwd, str)
        and cwd.strip()
    ):
        return err(
            request.headers.get("x-request-id"),
            {"code": "INVALID_ARGUMENT", "message": "project_id or cwd required"},
        )
    raw_pending_approval = body.get("pending_approval")
    if raw_pending_approval is not None and not isinstance(raw_pending_approval, bool):
        return err(
            request.headers.get("x-request-id"),
            {"code": "INVALID_ARGUMENT", "message": "pending_approval must be bool"},
        )
    rec = store.upsert_native_thread(dict(body))
    return ok(
        request.headers.get("x-request-id"),
        {
            "project_id": rec["project_id"],
            "thread_id": rec["thread_id"],
            "status": rec["status"],
            "phase": rec["phase"],
        },
    )


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
    raw_status = body.get("status")
    if raw_status not in (None, "") and not is_canonical_task_status(raw_status):
        return err(
            request.headers.get("x-request-id"),
            {"code": "INVALID_ARGUMENT", "message": "status must be canonical"},
        )
    raw_phase = body.get("phase")
    if raw_phase not in (None, "") and not is_canonical_task_phase(raw_phase):
        return err(
            request.headers.get("x-request-id"),
            {"code": "INVALID_ARGUMENT", "message": "phase must be canonical"},
        )
    raw_context_pressure = body.get("context_pressure")
    if raw_context_pressure not in (None, "") and str(raw_context_pressure) not in _CANONICAL_CONTEXT_PRESSURES:
        return err(
            request.headers.get("x-request-id"),
            {"code": "INVALID_ARGUMENT", "message": "context_pressure must be canonical"},
        )
    raw_stuck_level = body.get("stuck_level")
    if raw_stuck_level not in (None, ""):
        try:
            stuck_level = int(raw_stuck_level)
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
    raw_pending_approval = body.get("pending_approval")
    if raw_pending_approval is not None and not isinstance(raw_pending_approval, bool):
        return err(
            request.headers.get("x-request-id"),
            {"code": "INVALID_ARGUMENT", "message": "pending_approval must be bool"},
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


@router.get("/{project_id}/events")
async def task_events(
    project_id: str,
    request: Request,
    follow: bool = Query(default=True),
    poll_interval: float = Query(default=0.5, ge=0.1, le=10.0),
    store: TaskStore = Depends(get_store),
    _: None = Depends(require_token),
) -> Any:
    rec = store.get(project_id)
    if rec is None:
        return err(
            request.headers.get("x-request-id"),
            {"code": "NOT_FOUND", "message": f"unknown project_id: {project_id}"},
        )

    async def stream() -> Any:
        emitted: set[str] = set()
        while True:
            for event in store.list_events(project_id):
                event_id = str(event.get("event_id") or "")
                if event_id and event_id in emitted:
                    continue
                if event_id:
                    emitted.add(event_id)
                yield _encode_sse(event)
            if not follow:
                break
            await asyncio.sleep(poll_interval)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


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
async def steer_task(
    project_id: str,
    request: Request,
    body: dict[str, Any],
    settings: Settings = Depends(get_settings),
    store: TaskStore = Depends(get_store),
    bridge: Any = Depends(get_bridge),
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
    current = store.get(project_id)
    if current is None:
        return err(
            request.headers.get("x-request-id"),
            {"code": "NOT_FOUND", "message": f"unknown project_id: {project_id}"},
        )
    thread_id = str(current.get("thread_id") or "")
    service_input_delivered = False
    if bridge is not None and thread_id:
        try:
            if bridge.active_turn_id(thread_id):
                await bridge.steer_turn(thread_id, message=message)
            else:
                await bridge.start_turn(thread_id, prompt=message)
            service_input_delivered = True
        except Exception as exc:
            append_jsonl(
                Path(settings.data_dir) / "audit.jsonl",
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "project_id": project_id,
                    "action": "steer_failed",
                    "reason": str(reason),
                    "source": "a_control_agent",
                    "payload": {
                        "message": str(message)[:500],
                        "steer_source": str(source),
                        "error": str(exc),
                    },
                },
            )
            return err(
                request.headers.get("x-request-id"),
                {"code": "CONTROL_LINK_ERROR", "message": str(exc)},
                {
                    "project_id": project_id,
                    "status": str(current.get("status") or "running"),
                },
            )

    rec = store.apply_steer(
        project_id,
        message=message,
        source=str(source),
        reason=str(reason),
        stuck_level=stuck_level,
        service_input_delivered=service_input_delivered,
    )
    return ok(
        request.headers.get("x-request-id"),
        {"project_id": rec["project_id"], "status": rec.get("status", "running")},
    )
