from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from a_control_agent.repo_activity import summarize_workspace_activity
from watchdog.contracts.session_spine.enums import (
    ActionStatus,
    Effect,
    ReplyCode,
    SupervisionReasonCode,
)
from watchdog.contracts.session_spine.models import (
    SupervisionEvaluation,
    WatchdogAction,
    WatchdogActionResult,
)
from watchdog.services.action_executor.steer import SOFT_STEER_MESSAGE, post_steer
from watchdog.services.a_client.client import AControlAgentClient
from watchdog.services.audit import append_watchdog_audit
from watchdog.services.session_spine.facts import build_fact_records
from watchdog.services.session_spine.service import (
    CONTROL_LINK_ERROR,
    SessionSpineUpstreamError,
)
from watchdog.services.status_analyzer.stuck import StuckThresholds, evaluate_stuck
from watchdog.settings import Settings


def _repo_recent_change_count(task: dict[str, Any]) -> int | None:
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


def _map_reason_code(raw_reason: Any) -> SupervisionReasonCode:
    try:
        return SupervisionReasonCode(str(raw_reason))
    except ValueError:
        return SupervisionReasonCode.WITHIN_THRESHOLD


def build_supervision_evaluation(
    *,
    project_id: str,
    task: dict[str, Any],
    thread_id: str | None = None,
    native_thread_id: str | None = None,
    repo_recent_change_count: int | None = None,
    thresholds: StuckThresholds | None = None,
    now: datetime | None = None,
) -> SupervisionEvaluation:
    thresholds = thresholds or StuckThresholds()
    now = now or datetime.now(timezone.utc)
    current_stuck_level = int(task.get("stuck_level", 0) or 0)
    evaluation = evaluate_stuck(
        task,
        now=now,
        thresholds=thresholds,
        repo_recent_change_count=repo_recent_change_count,
    )
    next_stuck_level = int(evaluation.get("next_stuck_level", current_stuck_level) or current_stuck_level)
    return SupervisionEvaluation(
        project_id=project_id,
        thread_id=thread_id or f"session:{project_id}",
        native_thread_id=native_thread_id or str(task.get("thread_id") or "") or None,
        evaluated_at=now.isoformat(),
        reason_code=_map_reason_code(evaluation.get("reason")),
        detail=str(evaluation.get("detail") or ""),
        current_stuck_level=current_stuck_level,
        next_stuck_level=next_stuck_level,
        repo_recent_change_count=int(repo_recent_change_count or 0),
        threshold_minutes=thresholds.soft_steer_after_minutes,
        should_steer=bool(evaluation.get("should_steer")),
        steer_sent=False,
    )


def _append_steer_audit(
    *,
    settings: Settings,
    project_id: str,
    evaluation: SupervisionEvaluation,
) -> None:
    append_watchdog_audit(
        Path(settings.data_dir),
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "project_id": project_id,
            "action": "steer_injected",
            "reason": str(evaluation.reason_code),
            "payload": {
                "thread_id": evaluation.native_thread_id,
                "detail": evaluation.detail,
            },
        },
    )


def _steer_error(message: str) -> SessionSpineUpstreamError:
    error = dict(CONTROL_LINK_ERROR)
    error["message"] = message
    return SessionSpineUpstreamError(error)


def _load_task_or_raise(
    client: AControlAgentClient,
    project_id: str,
) -> dict[str, Any]:
    try:
        body = client.get_envelope(project_id)
    except (httpx.RequestError, RuntimeError, OSError) as exc:
        raise _steer_error("无法连接 A-Control-Agent 或链路异常；请检查网络与 A 侧服务状态。") from exc
    if not body.get("success"):
        error = body.get("error")
        if isinstance(error, dict):
            raise SessionSpineUpstreamError(dict(error))
        raise _steer_error("无法连接 A-Control-Agent 或链路异常；请检查网络与 A 侧服务状态。")
    data = body.get("data")
    if isinstance(data, dict):
        return dict(data)
    raise _steer_error("A 侧返回数据格式异常")


def execute_supervision_evaluation(
    action: WatchdogAction,
    *,
    settings: Settings,
    client: AControlAgentClient,
) -> WatchdogActionResult:
    task = _load_task_or_raise(client, action.project_id)
    facts = build_fact_records(project_id=action.project_id, task=task, approvals=[])
    repo_recent_change_count = _repo_recent_change_count(task)
    evaluation = build_supervision_evaluation(
        project_id=action.project_id,
        task=task,
        repo_recent_change_count=repo_recent_change_count,
    )

    effect = Effect.NOOP
    message = "supervision evaluation completed"
    if evaluation.should_steer:
        try:
            steer_body = post_steer(
                settings.a_agent_base_url,
                settings.a_agent_token,
                action.project_id,
                message=SOFT_STEER_MESSAGE,
                reason=str(evaluation.reason_code),
                stuck_level=evaluation.next_stuck_level,
                timeout=settings.http_timeout_s,
            )
        except (httpx.HTTPError, RuntimeError) as exc:
            raise _steer_error("steer 调用失败：无法连接 A-Control-Agent") from exc
        if not steer_body.get("success"):
            error = steer_body.get("error")
            if isinstance(error, dict):
                raise SessionSpineUpstreamError(dict(error))
            raise _steer_error("A 侧拒绝 steer")
        evaluation = evaluation.model_copy(update={"steer_sent": True})
        effect = Effect.STEER_POSTED
        message = "supervision evaluation completed; steer posted"
        _append_steer_audit(settings=settings, project_id=action.project_id, evaluation=evaluation)

    return WatchdogActionResult(
        action_code=action.action_code,
        project_id=action.project_id,
        approval_id=None,
        idempotency_key=action.idempotency_key,
        action_status=ActionStatus.COMPLETED,
        effect=effect,
        reply_code=ReplyCode.SUPERVISION_EVALUATION,
        message=message,
        facts=facts,
        supervision_evaluation=evaluation,
    )
