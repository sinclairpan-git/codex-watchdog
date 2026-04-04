from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request

from a_control_agent.api.deps import require_token
from a_control_agent.audit import append_jsonl
from a_control_agent.envelope import err, ok
from a_control_agent.settings import Settings
from a_control_agent.storage.handoff_manager import write_handoff_file
from a_control_agent.storage.tasks_store import TaskStore

router = APIRouter(prefix="/tasks", tags=["recovery"])


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_store(request: Request) -> TaskStore:
    return request.app.state.task_store


@router.post("/{project_id}/handoff")
def handoff(
    project_id: str,
    request: Request,
    body: dict[str, Any],
    settings: Settings = Depends(get_settings),
    store: TaskStore = Depends(get_store),
    _: None = Depends(require_token),
) -> dict[str, Any]:
    reason = str(body.get("reason", "unspecified"))
    rec = store.get(project_id)
    if rec is None:
        return err(
            request.headers.get("x-request-id"),
            {"code": "NOT_FOUND", "message": project_id},
        )
    store.merge_update(project_id, {"status": "handoff_in_progress", "phase": "handoff"})
    rec2 = store.get(project_id)
    assert rec2 is not None
    handoffs_dir = Path(settings.data_dir) / "handoffs"
    hf_path, summary = write_handoff_file(handoffs_dir, project_id, reason, dict(rec2))
    now = datetime.now(timezone.utc).isoformat()
    append_jsonl(
        Path(settings.data_dir) / "audit.jsonl",
        {
            "ts": now,
            "project_id": project_id,
            "action": "handoff",
            "reason": reason,
            "source": "a_control_agent",
            "payload": {"handoff_file": hf_path},
        },
    )
    return ok(
        request.headers.get("x-request-id"),
        {"handoff_file": hf_path, "summary": summary},
    )


@router.post("/{project_id}/resume")
def resume(
    project_id: str,
    request: Request,
    body: dict[str, Any],
    settings: Settings = Depends(get_settings),
    store: TaskStore = Depends(get_store),
    _: None = Depends(require_token),
) -> dict[str, Any]:
    mode = str(body.get("mode", "resume_or_new_thread"))
    _summary = body.get("handoff_summary", "")
    rec = store.get(project_id)
    if rec is None:
        return err(
            request.headers.get("x-request-id"),
            {"code": "NOT_FOUND", "message": project_id},
        )
    store.merge_update(
        project_id,
        {
            "status": "resuming",
            "context_pressure": str(rec.get("context_pressure", "low")),
            "phase": str(rec.get("phase", "planning")),
        },
    )
    store.merge_update(
        project_id,
        {
            "status": "running",
            "context_pressure": "medium",
            "phase": str(rec.get("phase", "planning")),
        },
    )
    now = datetime.now(timezone.utc).isoformat()
    append_jsonl(
        Path(settings.data_dir) / "audit.jsonl",
        {
            "ts": now,
            "project_id": project_id,
            "action": "resume",
            "reason": mode,
            "source": "a_control_agent",
            "payload": {"handoff_summary_len": len(str(_summary))},
        },
    )
    rec3 = store.get(project_id)
    return ok(
        request.headers.get("x-request-id"),
        {
            "project_id": project_id,
            "status": rec3.get("status") if rec3 else "running",
            "mode": mode,
        },
    )
