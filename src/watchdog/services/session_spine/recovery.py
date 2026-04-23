from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from watchdog.services.memory_hub.models import ContextQualitySnapshot
from watchdog.services.memory_hub.service import MemoryHubService
from watchdog.contracts.session_spine.models import FactRecord
from watchdog.services.runtime_client.client import CodexRuntimeClient
from watchdog.services.future_worker.service import FutureWorkerExecutionService
from watchdog.services.goal_contract.service import GoalContractService
from watchdog.services.session_service.service import SessionService
from watchdog.services.session_spine.continuation_packet import (
    build_recovery_continuation_packet,
)
from watchdog.services.session_spine.facts import build_fact_records
from watchdog.services.session_spine.projection import (
    stable_thread_id_for_project,
    task_native_thread_id,
)
from watchdog.services.session_spine.service import (
    CONTROL_LINK_ERROR,
    SessionSpineUpstreamError,
    _load_approvals_or_raise,
    _task_with_authoritative_project_execution_state,
)
from watchdog.services.session_spine.store import SessionSpineStore
from watchdog.services.session_spine.task_state import normalize_task_status
from watchdog.services.session_spine.task_state import (
    is_non_active_project_execution_state,
    normalize_project_execution_state,
)
from watchdog.settings import Settings

_SAME_THREAD_RESUME = "same_thread_resume"
_NEW_CHILD_SESSION = "new_child_session"


def _load_persisted_session_record(
    *,
    project_id: str,
    settings: Settings,
):
    store_path = Path(settings.data_dir) / "session_spine.json"
    if not store_path.exists():
        return None
    try:
        return SessionSpineStore(store_path).get(project_id)
    except Exception:
        return None


def _recovery_audit_context(
    *,
    project_id: str,
    task: dict[str, Any],
    settings: Settings,
) -> dict[str, str | None]:
    persisted = _load_persisted_session_record(project_id=project_id, settings=settings)
    continuation_identity = (
        f"{project_id}:{stable_thread_id_for_project(project_id)}:"
        f"{task_native_thread_id(task) or 'none'}:recover_current_branch"
    )
    authoritative_snapshot_version = (
        str(getattr(persisted, "fact_snapshot_version", "") or "").strip() or None
    )
    snapshot_epoch = None
    if persisted is not None:
        snapshot_epoch = f"session-seq:{persisted.session_seq}"
    route_key = (
        f"{continuation_identity}:{authoritative_snapshot_version}"
        if authoritative_snapshot_version is not None
        else None
    )
    return {
        "continuation_identity": continuation_identity,
        "route_key": route_key,
        "authoritative_snapshot_version": authoritative_snapshot_version,
        "snapshot_epoch": snapshot_epoch,
    }


def _build_recovery_packet(
    *,
    project_id: str,
    task: dict[str, Any],
    settings: Settings,
    session_service: SessionService | None,
    audit_context: dict[str, str | None],
) -> dict[str, Any]:
    service = session_service or SessionService.from_data_dir(settings.data_dir)
    goal_contracts = GoalContractService(service)
    contract = goal_contracts.get_current_contract(
        project_id=project_id,
        session_id=stable_thread_id_for_project(project_id),
    )
    goal_contract_version = str(
        getattr(contract, "version", "")
        or task.get("goal_contract_version")
        or "goal-contract:unknown"
    ).strip() or "goal-contract:unknown"
    project_total_goal = (
        str(getattr(contract, "original_goal", "") or "").strip()
        or str(task.get("task_prompt") or "").strip()
        or project_id
    )
    branch_goal = (
        str(getattr(contract, "current_phase_goal", "") or "").strip()
        or str(getattr(contract, "active_goal", "") or "").strip()
        or str(task.get("current_phase_goal") or "").strip()
        or str(task.get("task_title") or "").strip()
        or project_total_goal
    )
    remaining_tasks = [
        str(item or "").strip()
        for item in getattr(contract, "completion_signals", []) or []
        if str(item or "").strip()
    ]
    packet = build_recovery_continuation_packet(
        project_id=project_id,
        task=task,
        continuation_identity=str(audit_context["continuation_identity"] or ""),
        route_key=str(audit_context["route_key"] or "") or None,
        project_total_goal=project_total_goal,
        branch_goal=branch_goal,
        remaining_tasks=remaining_tasks,
        goal_contract_version=goal_contract_version,
        decision_source="recovery_guard",
        authoritative_snapshot_version=str(audit_context["authoritative_snapshot_version"] or "") or None,
        snapshot_epoch=str(audit_context["snapshot_epoch"] or "") or None,
        target_session_id=stable_thread_id_for_project(project_id),
        target_thread_id=task_native_thread_id(task) or stable_thread_id_for_project(project_id),
    )
    return packet.model_dump(mode="json", exclude_none=True)


def _resume_native_thread_id(resume: dict[str, Any] | None) -> str | None:
    if resume is None:
        return None
    native_thread_id = str(resume.get("native_thread_id") or "").strip()
    if native_thread_id:
        return native_thread_id
    thread_id = str(resume.get("thread_id") or "").strip()
    if thread_id.startswith("session:"):
        return None
    return thread_id or None


def _resume_session_id(resume: dict[str, Any] | None) -> str | None:
    if resume is None:
        return None
    for key in ("session_id", "child_session_id"):
        value = str(resume.get(key) or "").strip()
        if value:
            return value
    return None


def _resume_session_thread_id(resume: dict[str, Any] | None) -> str | None:
    if resume is None:
        return None
    thread_id = str(resume.get("thread_id") or "").strip()
    if thread_id.startswith("session:"):
        return thread_id
    return None


@dataclass(frozen=True, slots=True)
class RecoveryExecutionOutcome:
    project_id: str
    context_pressure: str
    action: str
    noop_reason: str | None = None
    facts: list[FactRecord] = field(default_factory=list)
    handoff: dict[str, Any] | None = None
    resume: dict[str, Any] | None = None
    resume_outcome: str | None = None
    resume_error: str | None = None
    memory_advisory_context: dict[str, Any] | None = None


def _record_recovery_suppressed(
    *,
    project_id: str,
    task: dict[str, Any],
    task_status: str,
    context_pressure: str,
    suppression_reason: str,
    project_execution_state: str | None,
    session_service: SessionService | None,
    settings: Settings,
) -> None:
    service = session_service or SessionService.from_data_dir(settings.data_dir)
    audit_context = _recovery_audit_context(
        project_id=project_id,
        task=task,
        settings=settings,
    )
    occurred_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    correlation_id = (
        f"corr:recovery-suppressed:{project_id}:{task_status or 'unknown'}:{occurred_at}"
    )
    related_ids = {
        "native_thread_id": task_native_thread_id(task) or "",
    }
    service.record_event(
        event_type="recovery_execution_suppressed",
        project_id=project_id,
        session_id=stable_thread_id_for_project(project_id),
        correlation_id=correlation_id,
        related_ids=related_ids,
        occurred_at=occurred_at,
        payload={
            "suppression_reason": suppression_reason,
            "task_status": task_status,
            "context_pressure": context_pressure,
            "last_progress_at": str(task.get("last_progress_at") or ""),
            **(
                {"project_execution_state": project_execution_state}
                if project_execution_state not in (None, "", "unknown")
                else {}
            ),
        },
    )
    service.record_continuation_gate_verdict(
        project_id=project_id,
        session_id=stable_thread_id_for_project(project_id),
        gate_kind="recovery_execution",
        gate_status="suppressed",
        decision_source="recovery_guard",
        decision_class="recover_current_branch",
        action_ref="execute_recovery",
        authoritative_snapshot_version=audit_context["authoritative_snapshot_version"],
        snapshot_epoch=audit_context["snapshot_epoch"],
        suppression_reason=suppression_reason,
        continuation_identity=audit_context["continuation_identity"],
        route_key=audit_context["route_key"],
        causation_id=None,
        correlation_id=correlation_id,
        occurred_at=occurred_at,
    )
    if suppression_reason in {
        "project_not_active",
        "project_state_unavailable",
        "pending_approval",
        "task_terminal",
    }:
        service.record_continuation_identity_state(
            project_id=project_id,
            session_id=stable_thread_id_for_project(project_id),
            continuation_identity=str(audit_context["continuation_identity"] or ""),
            state="invalidated",
            decision_source="recovery_guard",
            decision_class="recover_current_branch",
            action_ref="execute_recovery",
            authoritative_snapshot_version=audit_context["authoritative_snapshot_version"],
            snapshot_epoch=audit_context["snapshot_epoch"],
            route_key=audit_context["route_key"],
            suppression_reason=suppression_reason,
            causation_id=None,
            correlation_id=correlation_id,
            occurred_at=occurred_at,
        )
        service.record_continuation_replay_invalidated(
            project_id=project_id,
            session_id=stable_thread_id_for_project(project_id),
            decision_source="recovery_guard",
            decision_class="recover_current_branch",
            authoritative_snapshot_version=audit_context["authoritative_snapshot_version"],
            snapshot_epoch=audit_context["snapshot_epoch"],
            continuation_identity=audit_context["continuation_identity"],
            route_key=audit_context["route_key"],
            invalidation_reason=suppression_reason,
            causation_id=None,
            correlation_id=correlation_id,
            occurred_at=occurred_at,
        )


def _record_recovery_dispatch_started(
    *,
    project_id: str,
    task: dict[str, Any],
    context_pressure: str,
    settings: Settings,
    session_service: SessionService | None,
) -> None:
    service = session_service or SessionService.from_data_dir(settings.data_dir)
    audit_context = _recovery_audit_context(
        project_id=project_id,
        task=task,
        settings=settings,
    )
    occurred_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    correlation_id = (
        "corr:recovery-dispatch:"
        f"{project_id}:{audit_context['continuation_identity'] or 'none'}:"
        f"{audit_context['authoritative_snapshot_version'] or 'unknown'}:"
        f"{str(task.get('last_progress_at') or '')}"
    )
    related_ids = {
        "native_thread_id": task_native_thread_id(task) or "",
    }
    if audit_context["continuation_identity"]:
        related_ids["continuation_identity"] = str(audit_context["continuation_identity"])
    if audit_context["route_key"]:
        related_ids["route_key"] = str(audit_context["route_key"])
    service.record_event_once(
        event_type="recovery_dispatch_started",
        project_id=project_id,
        session_id=stable_thread_id_for_project(project_id),
        correlation_id=correlation_id,
        related_ids=related_ids,
        occurred_at=occurred_at,
        payload={
            "decision_source": "recovery_guard",
            "decision_class": "recover_current_branch",
            "context_pressure": context_pressure,
            "authoritative_snapshot_version": audit_context["authoritative_snapshot_version"],
            "snapshot_epoch": audit_context["snapshot_epoch"],
            "recovery_reason": "context_critical",
            "failure_signature": context_pressure,
            "last_progress_at": str(task.get("last_progress_at") or ""),
        },
    )


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
    client: CodexRuntimeClient,
    project_id: str,
) -> dict[str, Any]:
    try:
        body = client.get_envelope(project_id)
    except (httpx.RequestError, RuntimeError, OSError) as exc:
        raise _control_link_error("无法连接 Codex runtime") from exc
    if not body.get("success"):
        error = body.get("error")
        if isinstance(error, dict):
            raise SessionSpineUpstreamError(dict(error))
        raise _control_link_error("无法连接 Codex runtime")
    data = body.get("data")
    if isinstance(data, dict):
        return dict(data)
    raise _control_link_error("数据格式异常")


def _memory_quality_snapshot() -> ContextQualitySnapshot:
    return ContextQualitySnapshot(
        key_fact_recall=0.8,
        irrelevant_summary_precision=0.8,
        token_budget_utilization=0.4,
        expansion_miss_rate=0.1,
    )


def _memory_source_ref(payload: dict[str, Any]) -> str | None:
    packet_inputs = payload.get("packet_inputs")
    if isinstance(packet_inputs, dict):
        refs = packet_inputs.get("refs")
        if isinstance(refs, list):
            for ref in refs:
                if not isinstance(ref, dict):
                    continue
                source_ref = str(ref.get("source_ref") or "").strip()
                if source_ref:
                    return source_ref
    skills = payload.get("skills")
    if isinstance(skills, list):
        for skill in skills:
            if not isinstance(skill, dict):
                continue
            source_ref = str(skill.get("source_ref") or "").strip()
            if source_ref:
                return source_ref
    return None


def _resolve_resume_outcome(
    *,
    task: dict[str, Any],
    resume: dict[str, Any] | None,
) -> str | None:
    if resume is None:
        return None
    explicit = str(resume.get("resume_outcome") or "").strip()
    if explicit in {_SAME_THREAD_RESUME, _NEW_CHILD_SESSION}:
        return explicit
    resumed_session_id = _resume_session_id(resume)
    parent_session_id = stable_thread_id_for_project(str(task.get("project_id") or ""))
    if resumed_session_id and parent_session_id and resumed_session_id != parent_session_id:
        return _NEW_CHILD_SESSION
    resumed_session_thread_id = _resume_session_thread_id(resume)
    if (
        resumed_session_thread_id
        and parent_session_id
        and resumed_session_thread_id != parent_session_id
    ):
        return _NEW_CHILD_SESSION
    resumed_thread_id = str(_resume_native_thread_id(resume) or "").strip()
    parent_thread_id = str(task_native_thread_id(task) or "").strip()
    if resumed_thread_id and parent_thread_id and resumed_thread_id != parent_thread_id:
        return _NEW_CHILD_SESSION
    return _SAME_THREAD_RESUME


def _session_truth(
    *,
    project_id: str,
    session_id: str,
    task: dict[str, Any],
    session_service: SessionService | None,
) -> dict[str, object]:
    truth: dict[str, object] = {
        "status": str(task.get("status") or ""),
        "activity_phase": str(task.get("phase") or ""),
    }
    if session_service is None:
        return truth
    contracts = GoalContractService(session_service)
    contract = contracts.get_current_contract(
        project_id=project_id,
        session_id=session_id,
    )
    if contract is not None and contract.current_phase_goal:
        truth["current_phase_goal"] = contract.current_phase_goal
    return truth


def _build_memory_advisory_context(
    *,
    project_id: str,
    task: dict[str, Any],
    settings: Settings,
    session_service: SessionService | None,
    memory_hub_service: MemoryHubService | None,
) -> dict[str, Any] | None:
    session_id = stable_thread_id_for_project(project_id)
    service = memory_hub_service or MemoryHubService.from_data_dir(settings.data_dir)
    try:
        payload = service.build_runtime_advisory_context(
            query=f"resume {project_id}",
            project_id=project_id,
            session_id=session_id,
            limit=4,
            quality=_memory_quality_snapshot(),
            session_truth=_session_truth(
                project_id=project_id,
                session_id=session_id,
                task=task,
                session_service=session_service,
            ),
        )
    except Exception:
        if session_service is not None:
            session_service.record_memory_unavailable_degraded(
                project_id=project_id,
                session_id=session_id,
                memory_scope="project",
                fallback_mode="session_service_runtime_snapshot",
                degradation_reason="memory_hub_unreachable",
            )
        return None
    degradation = payload.get("degradation")
    if (
        session_service is not None
        and isinstance(degradation, dict)
        and str(degradation.get("reason_code") or "") == "memory_conflict_detected"
    ):
        session_service.record_memory_conflict_detected(
            project_id=project_id,
            session_id=session_id,
            memory_scope="project",
            conflict_reason="runtime_advisory_conflict",
            resolution=str(degradation.get("resolution") or "session_service_truth"),
            source_ref=_memory_source_ref(payload),
        )
    return payload


def perform_recovery_execution(
    project_id: str,
    *,
    settings: Settings,
    client: CodexRuntimeClient,
    session_service: SessionService | None = None,
    memory_hub_service: MemoryHubService | None = None,
) -> RecoveryExecutionOutcome:
    task = _task_with_authoritative_project_execution_state(
        _load_task_or_raise(client, project_id)
    )
    approvals = _load_approvals_or_raise(client, project_id)
    facts = build_fact_records(project_id=project_id, task=task, approvals=approvals)
    fact_codes = {fact.fact_code for fact in facts}
    context_pressure = str(task.get("context_pressure") or "unknown")
    task_status = normalize_task_status(task)
    project_execution_state = normalize_project_execution_state(task)
    memory_advisory_context = _build_memory_advisory_context(
        project_id=project_id,
        task=task,
        settings=settings,
        session_service=session_service,
        memory_hub_service=memory_hub_service,
    )
    if "project_state_unavailable" in fact_codes:
        _record_recovery_suppressed(
            project_id=project_id,
            task=task,
            task_status=task_status,
            context_pressure=context_pressure,
            suppression_reason="project_state_unavailable",
            project_execution_state=project_execution_state,
            session_service=session_service,
            settings=settings,
        )
        return RecoveryExecutionOutcome(
            project_id=project_id,
            context_pressure=context_pressure,
            action="noop",
            noop_reason="project_state_unavailable",
            facts=facts,
            memory_advisory_context=memory_advisory_context,
        )
    if is_non_active_project_execution_state(project_execution_state):
        _record_recovery_suppressed(
            project_id=project_id,
            task=task,
            task_status=task_status,
            context_pressure=context_pressure,
            suppression_reason="project_not_active",
            project_execution_state=project_execution_state,
            session_service=session_service,
            settings=settings,
        )
        return RecoveryExecutionOutcome(
            project_id=project_id,
            context_pressure=context_pressure,
            action="noop",
            noop_reason="project_not_active",
            facts=facts,
            memory_advisory_context=memory_advisory_context,
        )
    if approvals or bool(task.get("pending_approval")):
        _record_recovery_suppressed(
            project_id=project_id,
            task=task,
            task_status=task_status,
            context_pressure=context_pressure,
            suppression_reason="pending_approval",
            project_execution_state=project_execution_state,
            session_service=session_service,
            settings=settings,
        )
        return RecoveryExecutionOutcome(
            project_id=project_id,
            context_pressure=context_pressure,
            action="noop",
            noop_reason="pending_approval",
            facts=facts,
            memory_advisory_context=memory_advisory_context,
        )
    if task_status in {"handoff_in_progress", "resuming"}:
        _record_recovery_suppressed(
            project_id=project_id,
            task=task,
            task_status=task_status,
            context_pressure=context_pressure,
            suppression_reason="recovery_in_flight",
            project_execution_state=project_execution_state,
            session_service=session_service,
            settings=settings,
        )
        return RecoveryExecutionOutcome(
            project_id=project_id,
            context_pressure=context_pressure,
            action="noop",
            noop_reason="recovery_in_flight",
            facts=facts,
            memory_advisory_context=memory_advisory_context,
        )
    task_suppression_reasons = {
        "paused": "paused",
        "waiting_for_direction": "waiting_for_direction",
        "waiting_for_approval": "pending_approval",
        "completed": "task_terminal",
        "failed": "task_terminal",
    }
    if task_status in task_suppression_reasons:
        _record_recovery_suppressed(
            project_id=project_id,
            task=task,
            task_status=task_status,
            context_pressure=context_pressure,
            suppression_reason=task_suppression_reasons[task_status],
            project_execution_state=project_execution_state,
            session_service=session_service,
            settings=settings,
        )
        return RecoveryExecutionOutcome(
            project_id=project_id,
            context_pressure=context_pressure,
            action="noop",
            noop_reason=task_suppression_reasons[task_status],
            facts=facts,
            memory_advisory_context=memory_advisory_context,
        )
    if context_pressure != "critical":
        return RecoveryExecutionOutcome(
            project_id=project_id,
            context_pressure=context_pressure,
            action="noop",
            noop_reason="context_not_critical",
            facts=facts,
            memory_advisory_context=memory_advisory_context,
        )

    _record_recovery_dispatch_started(
        project_id=project_id,
        task=task,
        context_pressure=context_pressure,
        settings=settings,
        session_service=session_service,
    )
    audit_context = _recovery_audit_context(
        project_id=project_id,
        task=task,
        settings=settings,
    )
    continuation_packet = _build_recovery_packet(
        project_id=project_id,
        task=task,
        settings=settings,
        session_service=session_service,
        audit_context=audit_context,
    )
    try:
        handoff = _extract_success_data(
            client.trigger_handoff(
                project_id,
                reason="context_critical",
                continuation_packet=continuation_packet,
            ),
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
            memory_advisory_context=memory_advisory_context,
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
            continuation_packet=continuation_packet,
        )
    except (httpx.RequestError, RuntimeError, OSError):
        outcome = RecoveryExecutionOutcome(
            project_id=project_id,
            context_pressure=context_pressure,
            action="handoff_triggered",
            facts=facts,
            handoff=handoff,
            resume_error="resume_call_failed",
            memory_advisory_context=memory_advisory_context,
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
            memory_advisory_context=memory_advisory_context,
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
            memory_advisory_context=memory_advisory_context,
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
        resume_outcome=_resolve_resume_outcome(task=task, resume=resume),
        memory_advisory_context=memory_advisory_context,
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
    audit_context = _recovery_audit_context(
        project_id=project_id,
        task=task,
        settings=settings,
    )
    goal_contract_version = _resolve_recovery_goal_contract_version(
        handoff=outcome.handoff,
        resume=outcome.resume,
    )
    source_packet_id = str(
        outcome.handoff.get("source_packet_id")
        or (outcome.resume or {}).get("source_packet_id")
        or ""
    ).strip() or None
    recorded = service.record_recovery_execution(
        project_id=project_id,
        parent_session_id=stable_thread_id_for_project(project_id),
        parent_native_thread_id=task_native_thread_id(task),
        recovery_reason="context_critical",
        failure_family="context_pressure",
        failure_signature=outcome.context_pressure,
        handoff=outcome.handoff,
        resume=outcome.resume,
        resume_outcome=outcome.resume_outcome,
        resume_error=outcome.resume_error,
        goal_contract_version=goal_contract_version,
        source_packet_id=source_packet_id,
        continuation_identity=audit_context["continuation_identity"],
        route_key=audit_context["route_key"],
        authoritative_snapshot_version=audit_context["authoritative_snapshot_version"],
        snapshot_epoch=audit_context["snapshot_epoch"],
    )
    _supersede_stale_interactions_for_recovery(
        project_id=project_id,
        session_service=service,
        data_dir=settings.data_dir,
        recovery_transaction_id=recorded.recovery_transaction_id,
        source_packet_id=recorded.source_packet_id,
        child_session_id=recorded.child_session_id,
        child_native_thread_id=_resume_native_thread_id(outcome.resume),
    )
    if recorded.child_session_id is None:
        return
    _supersede_parent_future_workers_for_recovery(
        project_id=project_id,
        parent_session_id=recorded.parent_session_id,
        session_service=service,
    )
    if goal_contract_version == "goal-contract:unknown":
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
        child_native_thread_id=_resume_native_thread_id(outcome.resume),
        expected_version=goal_contract_version,
        recovery_transaction_id=recorded.recovery_transaction_id,
        source_packet_id=recorded.source_packet_id,
    )


def _resolve_recovery_goal_contract_version(
    *,
    handoff: dict[str, Any],
    resume: dict[str, Any] | None,
) -> str:
    for payload in (handoff, resume or {}):
        if not isinstance(payload, dict):
            continue
        continuation_packet = payload.get("continuation_packet")
        if isinstance(continuation_packet, dict):
            source_refs = continuation_packet.get("source_refs")
            if isinstance(source_refs, dict):
                packet_goal_contract_version = str(
                    source_refs.get("goal_contract_version") or ""
                ).strip()
                if packet_goal_contract_version:
                    return packet_goal_contract_version
        top_level = str(payload.get("goal_contract_version") or "").strip()
        if top_level:
            return top_level
    return "goal-contract:unknown"


def _is_reissuable_recovery_interaction(record: Any) -> bool:
    return str(getattr(record, "delivery_status", "") or "").strip() not in {
        "superseded",
        "delivery_failed",
    }


def _supersede_stale_interactions_for_recovery(
    *,
    project_id: str,
    session_service: SessionService,
    data_dir: str,
    recovery_transaction_id: str,
    source_packet_id: str,
    child_session_id: str | None = None,
    child_native_thread_id: str | None = None,
) -> None:
    from watchdog.services.delivery.store import DeliveryOutboxStore

    store = DeliveryOutboxStore(Path(data_dir) / "delivery_outbox.json")
    records = store.list_records()
    latest_by_family = {}
    for record in records:
        if record.project_id != project_id:
            continue
        family_id = str(record.envelope_payload.get("interaction_family_id") or "").strip()
        context_id = str(record.envelope_payload.get("interaction_context_id") or "").strip()
        if not family_id or not context_id:
            continue
        current = latest_by_family.get(family_id)
        if current is None or record.outbox_seq > current.outbox_seq:
            latest_by_family[family_id] = record

    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    for family_id, record in latest_by_family.items():
        if not _is_reissuable_recovery_interaction(record):
            continue
        old_context_id = str(record.envelope_payload.get("interaction_context_id") or "").strip()
        new_context_id = f"{old_context_id}:recovery"
        new_envelope_id = f"{record.envelope_id}:recovery"
        effective_native_thread_id = child_native_thread_id or record.effective_native_thread_id
        session_service.record_event(
            event_type="interaction_context_superseded",
            project_id=record.project_id,
            session_id=record.session_id,
            correlation_id=(
                f"corr:recovery-interaction:{family_id}:{recovery_transaction_id}:{new_context_id}"
            ),
            causation_id=recovery_transaction_id,
            related_ids={
                "interaction_context_id": old_context_id,
                "interaction_family_id": family_id,
                "recovery_transaction_id": recovery_transaction_id,
                "source_packet_id": source_packet_id,
                **(
                    {"native_thread_id": record.effective_native_thread_id}
                    if record.effective_native_thread_id
                    else {}
                ),
            },
            occurred_at=now,
            payload={
                "active_interaction_context_id": new_context_id,
                "active_envelope_id": new_envelope_id,
                "channel_kind": str(record.envelope_payload.get("channel_kind") or "dm"),
            },
        )
        store.update_delivery_record(
            record.model_copy(
                update={
                    "delivery_status": "superseded",
                    "updated_at": now,
                    "operator_notes": [
                        *record.operator_notes,
                        "delivery_superseded reason=recovery_continuation",
                    ],
                }
            )
        )
        fresh_outbox_seq = store.reserve_outbox_seq()
        store.update_delivery_record(
            record.model_copy(
                update={
                    "envelope_id": new_envelope_id,
                    "correlation_id": f"{record.correlation_id}:recovery",
                    "session_id": child_session_id or record.session_id,
                    "native_thread_id": effective_native_thread_id,
                    "idempotency_key": f"{record.idempotency_key}:recovery",
                    "audit_ref": f"{record.audit_ref}:recovery",
                    "created_at": now,
                    "updated_at": now,
                    "outbox_seq": fresh_outbox_seq,
                    "delivery_status": "pending",
                    "delivery_attempt": 0,
                    "receipt_id": None,
                    "failure_code": None,
                    "next_retry_at": None,
                    "operator_notes": [
                        *record.operator_notes,
                        "delivery_reissued_by_recovery",
                    ],
                    "envelope_payload": {
                        **record.envelope_payload,
                        "envelope_id": new_envelope_id,
                        "correlation_id": f"{record.correlation_id}:recovery",
                        "session_id": child_session_id or record.session_id,
                        "native_thread_id": effective_native_thread_id,
                        "idempotency_key": f"{record.idempotency_key}:recovery",
                        "audit_ref": f"{record.audit_ref}:recovery",
                        "created_at": now,
                        "interaction_context_id": new_context_id,
                    },
                }
            )
        )


def _supersede_parent_future_workers_for_recovery(
    *,
    project_id: str,
    parent_session_id: str,
    session_service: SessionService,
) -> None:
    future_worker_service = FutureWorkerExecutionService(session_service)
    grouped_events: dict[str, list[dict[str, Any] | Any]] = {}
    for event in session_service.list_events(session_id=parent_session_id):
        worker_task_ref = str(event.related_ids.get("worker_task_ref") or "").strip()
        if not worker_task_ref or not event.event_type.startswith("future_worker_"):
            continue
        grouped_events.setdefault(worker_task_ref, []).append(event)

    for worker_task_ref, events in grouped_events.items():
        latest_event = max(events, key=lambda event: event.log_seq or 0)
        if latest_event.event_type in {
            "future_worker_requested",
            "future_worker_started",
            "future_worker_heartbeat",
            "future_worker_summary_published",
        }:
            future_worker_service.record_cancelled(
                worker_task_ref=worker_task_ref,
                project_id=project_id,
                parent_session_id=parent_session_id,
                occurred_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace(
                    "+00:00",
                    "Z",
                ),
                reason="recovery_superseded_by_child_session",
            )
            continue
        if latest_event.event_type == "future_worker_completed":
            future_worker_service.reject_result(
                worker_task_ref=worker_task_ref,
                project_id=project_id,
                parent_session_id=parent_session_id,
                occurred_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace(
                    "+00:00",
                    "Z",
                ),
                reason="recovery_superseded_by_child_session",
            )
