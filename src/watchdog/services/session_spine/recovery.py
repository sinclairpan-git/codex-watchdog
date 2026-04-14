from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from watchdog.contracts.session_spine.models import FactRecord
from watchdog.services.a_client.client import AControlAgentClient
from watchdog.services.future_worker.service import FutureWorkerExecutionService
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
    _supersede_stale_interactions_for_recovery(
        project_id=project_id,
        session_service=service,
        data_dir=settings.data_dir,
        recovery_transaction_id=recorded.recovery_transaction_id,
        source_packet_id=recorded.source_packet_id,
    )
    _supersede_parent_future_workers_for_recovery(
        project_id=project_id,
        parent_session_id=recorded.parent_session_id,
        session_service=service,
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


def _supersede_stale_interactions_for_recovery(
    *,
    project_id: str,
    session_service: SessionService,
    data_dir: str,
    recovery_transaction_id: str,
    source_packet_id: str,
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
        old_context_id = str(record.envelope_payload.get("interaction_context_id") or "").strip()
        new_context_id = f"{old_context_id}:recovery"
        new_envelope_id = f"{record.envelope_id}:recovery"
        session_service.record_event(
            event_type="interaction_context_superseded",
            project_id=record.project_id,
            session_id=record.session_id,
            correlation_id=f"corr:recovery-interaction:{family_id}",
            causation_id=recovery_transaction_id,
            related_ids={
                "interaction_context_id": old_context_id,
                "interaction_family_id": family_id,
                "recovery_transaction_id": recovery_transaction_id,
                "source_packet_id": source_packet_id,
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
        store.update_delivery_record(
            record.model_copy(
                update={
                    "envelope_id": new_envelope_id,
                    "correlation_id": f"{record.correlation_id}:recovery",
                    "idempotency_key": f"{record.idempotency_key}:recovery",
                    "audit_ref": f"{record.audit_ref}:recovery",
                    "created_at": now,
                    "updated_at": now,
                    "outbox_seq": record.outbox_seq + 1,
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
