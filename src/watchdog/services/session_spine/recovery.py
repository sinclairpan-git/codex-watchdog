from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from watchdog.contracts.session_spine.models import FactRecord
from watchdog.services.a_client.client import AControlAgentClient
from watchdog.services.goal_contract.service import GoalContractService
from watchdog.services.session_service.service import SessionService
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
    session_service: SessionService | None = None,
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
        outcome = RecoveryExecutionOutcome(
            project_id=project_id,
            context_pressure=context_pressure,
            action="handoff_triggered",
            facts=facts,
            handoff=handoff,
        )
        _record_recovery_truth(
            project_id=project_id,
            task=task,
            outcome=outcome,
            settings=settings,
            session_service=session_service,
        )
        return outcome

    try:
        resume_body = client.trigger_resume(
            project_id,
            mode="resume_or_new_thread",
            handoff_summary="",
        )
    except (httpx.RequestError, RuntimeError, OSError):
        outcome = RecoveryExecutionOutcome(
            project_id=project_id,
            context_pressure=context_pressure,
            action="handoff_triggered",
            facts=facts,
            handoff=handoff,
            resume_error="resume_call_failed",
        )
        _record_recovery_truth(
            project_id=project_id,
            task=task,
            outcome=outcome,
            settings=settings,
            session_service=session_service,
        )
        return outcome

    if not resume_body.get("success"):
        outcome = RecoveryExecutionOutcome(
            project_id=project_id,
            context_pressure=context_pressure,
            action="handoff_triggered",
            facts=facts,
            handoff=handoff,
            resume_error="resume_call_failed",
        )
        _record_recovery_truth(
            project_id=project_id,
            task=task,
            outcome=outcome,
            settings=settings,
            session_service=session_service,
        )
        return outcome

    resume = resume_body.get("data")
    if not isinstance(resume, dict):
        outcome = RecoveryExecutionOutcome(
            project_id=project_id,
            context_pressure=context_pressure,
            action="handoff_triggered",
            facts=facts,
            handoff=handoff,
            resume_error="resume_call_failed",
        )
        _record_recovery_truth(
            project_id=project_id,
            task=task,
            outcome=outcome,
            settings=settings,
            session_service=session_service,
        )
        return outcome

    outcome = RecoveryExecutionOutcome(
        project_id=project_id,
        context_pressure=context_pressure,
        action="handoff_and_resume",
        facts=facts,
        handoff=handoff,
        resume=dict(resume),
    )
    _record_recovery_truth(
        project_id=project_id,
        task=task,
        outcome=outcome,
        settings=settings,
        session_service=session_service,
    )
    return outcome


def _record_recovery_truth(
    *,
    project_id: str,
    task: dict[str, Any],
    outcome: RecoveryExecutionOutcome,
    settings: Settings,
    session_service: SessionService | None,
) -> None:
    if outcome.handoff is None:
        return
    service = session_service or SessionService.from_data_dir(settings.data_dir)
    goal_contract_version = str(
        outcome.handoff.get("goal_contract_version")
        or (outcome.resume or {}).get("goal_contract_version")
        or "goal-contract:unknown"
    ).strip() or "goal-contract:unknown"
    source_packet_id = str(
        outcome.handoff.get("source_packet_id")
        or (outcome.resume or {}).get("source_packet_id")
        or ""
    ).strip() or None
    recorded = service.record_recovery_execution(
        project_id=project_id,
        parent_session_id=f"session:{project_id}",
        parent_native_thread_id=str(task.get("thread_id") or "").strip() or None,
        recovery_reason="context_critical",
        failure_family="context_pressure",
        failure_signature=outcome.context_pressure,
        handoff=outcome.handoff,
        resume=outcome.resume,
        resume_error=outcome.resume_error,
        goal_contract_version=goal_contract_version,
        source_packet_id=source_packet_id,
    )
    if (
        recorded.child_session_id is None
        or goal_contract_version == "goal-contract:unknown"
    ):
        return
    goal_contracts = GoalContractService(service)
    if goal_contracts.get_current_contract(
        project_id=project_id,
        session_id=recorded.parent_session_id,
    ) is None:
        return
    goal_contracts.adopt_contract_for_child_session(
        project_id=project_id,
        parent_session_id=recorded.parent_session_id,
        child_session_id=recorded.child_session_id,
        expected_version=goal_contract_version,
        recovery_transaction_id=recorded.recovery_transaction_id,
        source_packet_id=recorded.source_packet_id,
    )
