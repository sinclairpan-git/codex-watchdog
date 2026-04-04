from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, Request

from a_control_agent.envelope import err, ok
from watchdog.api.deps import require_token
from watchdog.services.a_client.client import AControlAgentClient
from watchdog.settings import Settings

router = APIRouter(prefix="/watchdog", tags=["recover"])


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_client(request: Request) -> AControlAgentClient:
    return request.app.state.a_client


@router.post("/tasks/{project_id}/recover")
def recover(
    project_id: str,
    request: Request,
    settings: Settings = Depends(get_settings),
    client: AControlAgentClient = Depends(get_client),
    _: None = Depends(require_token),
) -> dict[str, Any]:
    """拉取 A 任务；若 context_pressure 为 critical 则触发 handoff。"""
    rid = request.headers.get("x-request-id")
    try:
        body = client.get_envelope(project_id)
    except httpx.RequestError:
        return err(
            rid,
            {
                "code": "CONTROL_LINK_ERROR",
                "message": "无法连接 A-Control-Agent",
            },
        )
    except (RuntimeError, OSError):
        return err(
            rid,
            {
                "code": "CONTROL_LINK_ERROR",
                "message": "无法连接 A-Control-Agent",
            },
        )
    if not body.get("success"):
        return err(rid, body.get("error") or {"code": "A_AGENT_ERROR", "message": "unknown"})
    task = body.get("data")
    if not isinstance(task, dict):
        return err(rid, {"code": "CONTROL_LINK_ERROR", "message": "数据格式异常"})

    if task.get("context_pressure") != "critical":
        return ok(
            rid,
            {"project_id": project_id, "action": "noop", "context_pressure": task.get("context_pressure")},
        )

    url = f"{settings.a_agent_base_url.rstrip('/')}/api/v1/tasks/{project_id}/handoff"
    try:
        with httpx.Client(timeout=settings.http_timeout_s) as h:
            r = h.post(
                url,
                json={"reason": "context_critical"},
                headers={"Authorization": f"Bearer {settings.a_agent_token}"},
            )
            r.raise_for_status()
            hj = r.json()
    except httpx.RequestError:
        return err(
            rid,
            {"code": "CONTROL_LINK_ERROR", "message": "handoff 调用失败"},
        )
    except httpx.HTTPError:
        return err(
            rid,
            {"code": "CONTROL_LINK_ERROR", "message": "handoff HTTP 错误"},
        )

    if isinstance(hj, dict) and hj.get("success"):
        data_out: dict[str, Any] = {
            "project_id": project_id,
            "action": "handoff_triggered",
            "result": hj.get("data"),
        }
        if settings.recover_auto_resume:
            resume_url = f"{settings.a_agent_base_url.rstrip('/')}/api/v1/tasks/{project_id}/resume"
            try:
                with httpx.Client(timeout=settings.http_timeout_s) as h2:
                    rr = h2.post(
                        resume_url,
                        json={
                            "mode": "resume_or_new_thread",
                            "handoff_summary": "",
                        },
                        headers={"Authorization": f"Bearer {settings.a_agent_token}"},
                    )
                    rr.raise_for_status()
                    rj = rr.json()
                data_out["action"] = "handoff_and_resume"
                data_out["resume"] = rj.get("data") if isinstance(rj, dict) else rj
            except (httpx.RequestError, httpx.HTTPError, ValueError):
                data_out["resume_error"] = "resume_call_failed"
        return ok(rid, data_out)
    return err(rid, hj.get("error") if isinstance(hj, dict) else {"code": "HANDOFF_FAILED"})
