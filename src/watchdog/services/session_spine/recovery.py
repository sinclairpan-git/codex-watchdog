from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from watchdog.contracts.session_spine.models import FactRecord
from watchdog.services.a_client.client import AControlAgentClient
from watchdog.services.session_spine.facts import build_fact_records
from watchdog.services.session_spine.service import (
    CONTROL_LINK_ERROR,
    SessionSpineUpstreamError,
)
from watchdog.settings import Settings


@dataclass(frozen=True, slots=True)
class RecoveryExecutionOutcome:
    project_id: str
    context_pressure: str
    action: str
    facts: list[FactRecord] = field(default_factory=list)
    handoff: dict[str, Any] | None = None
    resume: dict[str, Any] | None = None
    resume_error: str | None = None


def _control_link_error(message: str) -> SessionSpineUpstreamError:
    error = dict(CONTROL_LINK_ERROR)
    error["message"] = message
    return SessionSpineUpstreamError(error)


def _extract_success_data(
    body: dict[str, Any],
    *,
    default_message: str,
) -> dict[str, Any]:
    if body.get("success"):
        data = body.get("data")
        if isinstance(data, dict):
            return dict(data)
        raise _control_link_error(default_message)
    error = body.get("error")
    if isinstance(error, dict):
        raise SessionSpineUpstreamError(dict(error))
    raise _control_link_error(default_message)


def _load_task_or_raise(
    client: AControlAgentClient,
    project_id: str,
) -> dict[str, Any]:
    try:
        body = client.get_envelope(project_id)
    except (httpx.RequestError, RuntimeError, OSError) as exc:
        raise _control_link_error("无法连接 A-Control-Agent") from exc
    if not body.get("success"):
        error = body.get("error")
        if isinstance(error, dict):
            raise SessionSpineUpstreamError(dict(error))
        raise _control_link_error("无法连接 A-Control-Agent")
    data = body.get("data")
    if isinstance(data, dict):
        return dict(data)
    raise _control_link_error("数据格式异常")


def perform_recovery_execution(
    project_id: str,
    *,
    settings: Settings,
    client: AControlAgentClient,
) -> RecoveryExecutionOutcome:
    task = _load_task_or_raise(client, project_id)
    facts = build_fact_records(project_id=project_id, task=task, approvals=[])
    context_pressure = str(task.get("context_pressure") or "unknown")
    if context_pressure != "critical":
        return RecoveryExecutionOutcome(
            project_id=project_id,
            context_pressure=context_pressure,
            action="noop",
            facts=facts,
        )

    try:
        handoff = _extract_success_data(
            client.trigger_handoff(project_id, reason="context_critical"),
            default_message="handoff 调用失败",
        )
    except (httpx.RequestError, RuntimeError, OSError) as exc:
        raise _control_link_error("handoff 调用失败") from exc

    if not settings.recover_auto_resume:
        return RecoveryExecutionOutcome(
            project_id=project_id,
            context_pressure=context_pressure,
            action="handoff_triggered",
            facts=facts,
            handoff=handoff,
        )

    try:
        resume_body = client.trigger_resume(
            project_id,
            mode="resume_or_new_thread",
            handoff_summary="",
        )
    except (httpx.RequestError, RuntimeError, OSError):
        return RecoveryExecutionOutcome(
            project_id=project_id,
            context_pressure=context_pressure,
            action="handoff_triggered",
            facts=facts,
            handoff=handoff,
            resume_error="resume_call_failed",
        )

    if not resume_body.get("success"):
        return RecoveryExecutionOutcome(
            project_id=project_id,
            context_pressure=context_pressure,
            action="handoff_triggered",
            facts=facts,
            handoff=handoff,
            resume_error="resume_call_failed",
        )

    resume = resume_body.get("data")
    if not isinstance(resume, dict):
        return RecoveryExecutionOutcome(
            project_id=project_id,
            context_pressure=context_pressure,
            action="handoff_triggered",
            facts=facts,
            handoff=handoff,
            resume_error="resume_call_failed",
        )

    return RecoveryExecutionOutcome(
        project_id=project_id,
        context_pressure=context_pressure,
        action="handoff_and_resume",
        facts=facts,
        handoff=handoff,
        resume=dict(resume),
    )
