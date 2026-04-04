from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response, StreamingResponse

from a_control_agent.envelope import err
from watchdog.api.deps import require_token
from watchdog.services.a_client.client import AControlAgentClient

router = APIRouter(prefix="/watchdog", tags=["watchdog"])


def get_client(request: Request) -> AControlAgentClient:
    return request.app.state.a_client


@router.get("/tasks/{project_id}/events")
def task_events_proxy(
    project_id: str,
    request: Request,
    follow: bool = Query(default=True),
    poll_interval: float = Query(default=0.5, ge=0.1, le=10.0),
    client: AControlAgentClient = Depends(get_client),
    _: None = Depends(require_token),
) -> Any:
    rid = request.headers.get("x-request-id")
    try:
        snapshot = client.get_events_snapshot(project_id, poll_interval=poll_interval)
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

    if isinstance(snapshot, dict):
        if not snapshot.get("success"):
            return err(rid, snapshot.get("error") or {"code": "A_AGENT_ERROR", "message": "unknown"})
        return err(rid, {"code": "CONTROL_LINK_ERROR", "message": "A 侧事件流返回格式异常"})

    body, _content_type = snapshot
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
    }
    if not follow:
        return Response(content=body, media_type="text/event-stream", headers=headers)

    def stream() -> Any:
        yield from client.iter_events(project_id, poll_interval=poll_interval)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers=headers,
    )
