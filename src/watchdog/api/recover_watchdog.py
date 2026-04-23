from __future__ import annotations

from typing import Any

import httpx  # noqa: F401
from fastapi import APIRouter, Depends, Request

from a_control_agent.envelope import err, ok
from watchdog.api.deps import require_token
from watchdog.services.runtime_client.client import CodexRuntimeClient
from watchdog.services.session_spine.recovery import perform_recovery_execution
from watchdog.services.session_spine.service import SessionSpineUpstreamError
from watchdog.settings import Settings

router = APIRouter(prefix="/watchdog", tags=["recover"])


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_client(request: Request) -> CodexRuntimeClient:
    return request.app.state.runtime_client


@router.post("/tasks/{project_id}/recover")
def recover(
    project_id: str,
    request: Request,
    settings: Settings = Depends(get_settings),
    client: CodexRuntimeClient = Depends(get_client),
    _: None = Depends(require_token),
) -> dict[str, Any]:
    """兼容旧 recover route，内部复用 stable recovery execution 内核。"""
    rid = request.headers.get("x-request-id")
    try:
        outcome = perform_recovery_execution(
            project_id,
            settings=settings,
            client=client,
            session_service=request.app.state.session_service,
        )
    except SessionSpineUpstreamError as exc:
        return err(rid, exc.error)

    data_out: dict[str, Any] = {
        "project_id": project_id,
        "action": outcome.action,
        "context_pressure": outcome.context_pressure,
    }
    if outcome.handoff is not None:
        data_out["result"] = outcome.handoff
    if outcome.resume is not None:
        data_out["resume"] = outcome.resume
    if outcome.resume_error:
        data_out["resume_error"] = outcome.resume_error
    return ok(rid, data_out)
