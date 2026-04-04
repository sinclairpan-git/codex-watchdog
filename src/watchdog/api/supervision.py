from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import httpx

from a_control_agent.repo_activity import summarize_workspace_activity
from fastapi import APIRouter, Depends, Request

from a_control_agent.envelope import err, ok
from watchdog.api.deps import require_token
from watchdog.services.action_executor.steer import SOFT_STEER_MESSAGE, post_steer
from watchdog.services.audit import append_watchdog_audit
from watchdog.services.a_client.client import AControlAgentClient
from watchdog.services.status_analyzer.stuck import evaluate_stuck
from watchdog.settings import Settings

router = APIRouter(prefix="/watchdog", tags=["supervision"])


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_client(request: Request) -> AControlAgentClient:
    return request.app.state.a_client


@router.post("/tasks/{project_id}/evaluate")
def evaluate_task(
    project_id: str,
    request: Request,
    settings: Settings = Depends(get_settings),
    client: AControlAgentClient = Depends(get_client),
    _: None = Depends(require_token),
) -> dict[str, object]:
    """拉取 A 侧任务 → stuck 分析 → 满足阈值则注入 soft steer。"""
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

    task = body.get("data")
    if not isinstance(task, dict):
        return err(
            rid,
            {"code": "CONTROL_LINK_ERROR", "message": "A 侧返回数据格式异常"},
        )

    repo_n: int | None = None
    cwd = task.get("cwd")
    if isinstance(cwd, str) and cwd.strip():
        try:
            repo_n = int(
                summarize_workspace_activity(Path(cwd), recent_minutes=15).get(
                    "recent_change_count", 0
                )
            )
        except OSError:
            repo_n = None
    ev = evaluate_stuck(task, repo_recent_change_count=repo_n)
    steer_sent = False
    if ev.get("should_steer"):
        try:
            nsl = ev.get("next_stuck_level")
            sl = int(nsl) if isinstance(nsl, int) else None
            steer_body = post_steer(
                settings.a_agent_base_url,
                settings.a_agent_token,
                project_id,
                message=SOFT_STEER_MESSAGE,
                reason=str(ev.get("reason", "stuck_soft")),
                stuck_level=sl,
            )
            if not steer_body.get("success"):
                return err(
                    rid,
                    steer_body.get("error")
                    or {"code": "STEER_FAILED", "message": "A 侧拒绝 steer"},
                )
            steer_sent = True
        except httpx.HTTPError:
            return err(
                rid,
                {
                    "code": "CONTROL_LINK_ERROR",
                    "message": "steer 调用失败：无法连接 A-Control-Agent",
                },
            )
        append_watchdog_audit(
            Path(settings.data_dir),
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "project_id": project_id,
                "action": "steer_injected",
                "reason": str(ev.get("reason")),
                "payload": {"detail": ev.get("detail")},
            },
        )

    return ok(
        rid,
        {
            "project_id": project_id,
            "evaluation": ev,
            "steer_sent": steer_sent,
        },
    )
