from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

import httpx

from a_control_agent.repo_activity import summarize_workspace_activity
from fastapi import APIRouter, Depends, Request

from a_control_agent.envelope import err, ok
from watchdog.api.deps import require_token
from watchdog.contracts.session_spine.enums import ActionCode
from watchdog.contracts.session_spine.models import SupervisionEvaluation, WatchdogAction
from watchdog.services.action_executor.steer import SOFT_STEER_MESSAGE, post_steer
from watchdog.services.audit import append_watchdog_audit
from watchdog.services.runtime_client.client import CodexRuntimeClient
from watchdog.services.session_spine.projection import task_native_thread_id
from watchdog.services.session_spine.service import SessionSpineUpstreamError
from watchdog.services.session_spine.supervision import execute_supervision_evaluation
from watchdog.services.status_analyzer.stuck import evaluate_stuck
from watchdog.settings import Settings

router = APIRouter(prefix="/watchdog", tags=["supervision"])


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_client(request: Request) -> CodexRuntimeClient:
    return request.app.state.runtime_client


def _repo_recent_change_count(task: dict[str, object]) -> int | None:
    cwd = task.get("cwd")
    if isinstance(cwd, str) and cwd.strip():
        try:
            return int(
                summarize_workspace_activity(Path(cwd), recent_minutes=15).get(
                    "recent_change_count", 0
                )
            )
        except OSError:
            return None
    return None


def post_steer_thread(
    base_url: str,
    token: str,
    thread_id: str,
    project_id: str,
    *,
    message: str,
    reason: str,
    stuck_level: int | None = None,
    timeout: float = 10.0,
) -> dict[str, object]:
    _ = thread_id
    return post_steer(
        base_url,
        token,
        project_id,
        message=message,
        reason=reason,
        stuck_level=stuck_level,
        timeout=timeout,
    )


def _legacy_evaluation_payload(evaluation: SupervisionEvaluation) -> dict[str, object]:
    return {
        "should_steer": evaluation.should_steer,
        "reason": str(evaluation.reason_code),
        "next_stuck_level": evaluation.next_stuck_level,
        "detail": evaluation.detail,
    }


def run_background_supervision(settings: Settings, client: CodexRuntimeClient) -> None:
    try:
        tasks = client.list_tasks()
    except (httpx.RequestError, RuntimeError, OSError):
        return

    request_timeout = max(float(settings.http_timeout_s), 0.05)
    deadline = monotonic() + request_timeout

    for task in tasks:
        status = task.get("status")
        project_id = task.get("project_id")
        thread_id = task_native_thread_id(task)
        if status not in {
            "created",
            "running",
            "resuming",
            "waiting_human",
            "waiting_for_direction",
        }:
            continue
        if not isinstance(project_id, str) or not project_id:
            continue
        if not isinstance(thread_id, str) or not thread_id:
            fallback_thread_id = task.get("thread_id")
            if isinstance(fallback_thread_id, str) and fallback_thread_id:
                thread_id = fallback_thread_id
        if not isinstance(thread_id, str) or not thread_id:
            continue
        ev = evaluate_stuck(task, repo_recent_change_count=_repo_recent_change_count(task))
        if not ev.get("should_steer"):
            continue
        next_level = ev.get("next_stuck_level")
        stuck_level = int(next_level) if isinstance(next_level, int) else None
        remaining_timeout = deadline - monotonic()
        if remaining_timeout <= 0:
            break
        try:
            body = post_steer_thread(
                settings.codex_runtime_base_url,
                settings.codex_runtime_token,
                thread_id,
                project_id,
                message=SOFT_STEER_MESSAGE,
                reason=str(ev.get("reason", "stuck_soft")),
                stuck_level=stuck_level,
                timeout=remaining_timeout,
            )
        except (httpx.HTTPError, RuntimeError):
            continue
        if not isinstance(body, dict) or not body.get("success"):
            continue
        append_watchdog_audit(
            Path(settings.data_dir),
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "project_id": project_id,
                "action": "steer_injected",
                "reason": str(ev.get("reason")),
                "payload": {"thread_id": thread_id, "detail": ev.get("detail")},
            },
        )


@router.post("/tasks/{project_id}/evaluate")
def evaluate_task(
    project_id: str,
    request: Request,
    settings: Settings = Depends(get_settings),
    client: CodexRuntimeClient = Depends(get_client),
    _: None = Depends(require_token),
) -> dict[str, object]:
    """拉取 runtime 任务 → stuck 分析 → 满足阈值则注入 soft steer。"""
    rid = request.headers.get("x-request-id")

    action = WatchdogAction(
        action_code=ActionCode.EVALUATE_SUPERVISION,
        project_id=project_id,
        operator="watchdog_legacy",
        idempotency_key=rid or f"legacy-evaluate:{datetime.now(timezone.utc).isoformat()}",
        arguments={},
    )
    try:
        result = execute_supervision_evaluation(
            action,
            settings=settings,
            client=client,
        )
    except SessionSpineUpstreamError as exc:
        return err(rid, exc.error)
    evaluation = result.supervision_evaluation
    if evaluation is None:
        return err(rid, {"code": "CONTROL_LINK_ERROR", "message": "stable supervision result missing"})

    return ok(
        rid,
        {
            "project_id": project_id,
            "evaluation": _legacy_evaluation_payload(evaluation),
            "steer_sent": evaluation.steer_sent,
        },
    )
