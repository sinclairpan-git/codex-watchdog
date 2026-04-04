from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, Request

from a_control_agent.envelope import err, ok
from watchdog.api.deps import require_token
from watchdog.services.a_client.client import AControlAgentClient
router = APIRouter(prefix="/watchdog", tags=["watchdog"])


def get_client(request: Request) -> AControlAgentClient:
    return request.app.state.a_client


def _to_progress(task: dict[str, object]) -> dict[str, object]:
    return {
        "status": task.get("status"),
        "phase": task.get("phase"),
        "last_summary": task.get("last_summary"),
        "files_touched": task.get("files_touched"),
        "blockers": [],
        "pending_approval": task.get("pending_approval"),
        "context_pressure": task.get("context_pressure"),
        "last_progress_at": task.get("last_progress_at"),
    }


@router.get("/tasks/{project_id}/progress")
def get_progress(
    project_id: str,
    request: Request,
    client: AControlAgentClient = Depends(get_client),
    _: None = Depends(require_token),
) -> dict[str, object]:
    rid = request.headers.get("x-request-id")
    try:
        body = client.get_envelope(project_id)
    except httpx.RequestError:
        return err(
            rid,
            {
                "code": "CONTROL_LINK_ERROR",
                "message": "无法连接 A-Control-Agent 或链路异常；请检查网络与 A 侧服务状态。",
            },
        )
    except (RuntimeError, OSError):
        return err(
            rid,
            {
                "code": "CONTROL_LINK_ERROR",
                "message": "无法连接 A-Control-Agent 或链路异常；请检查网络与 A 侧服务状态。",
            },
        )

    if not body.get("success"):
        return err(rid, body.get("error") or {"code": "A_AGENT_ERROR", "message": "unknown"})

    data = body.get("data")
    if not isinstance(data, dict):
        return err(
            rid,
            {"code": "CONTROL_LINK_ERROR", "message": "A 侧返回数据格式异常"},
        )
    return ok(rid, _to_progress(data))
