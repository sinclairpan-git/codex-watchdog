from __future__ import annotations

from typing import Any

from watchdog.services.future_worker.models import (
    FutureWorkerExecutionRequest,
    FutureWorkerResultEnvelope,
)
from watchdog.services.session_service.service import SessionService

_WORKER_STATE_BY_EVENT_TYPE = {
    "future_worker_requested": "requested",
    "future_worker_started": "running",
    "future_worker_heartbeat": "running",
    "future_worker_summary_published": "running",
    "future_worker_completed": "completed",
    "future_worker_failed": "failed",
    "future_worker_cancelled": "cancelled",
    "future_worker_result_consumed": "consumed",
    "future_worker_result_rejected": "rejected",
}

_TERMINAL_WORKER_STATES = {"failed", "cancelled", "consumed", "rejected"}

_ALLOWED_NEXT_WORKER_EVENTS: dict[str | None, set[str]] = {
    None: {"future_worker_requested"},
    "requested": {
        "future_worker_started",
        "future_worker_heartbeat",
        "future_worker_failed",
        "future_worker_cancelled",
    },
    "running": {
        "future_worker_heartbeat",
        "future_worker_summary_published",
        "future_worker_completed",
        "future_worker_failed",
        "future_worker_cancelled",
    },
    "completed": {
        "future_worker_result_consumed",
        "future_worker_result_rejected",
    },
    "failed": set(),
    "cancelled": set(),
    "consumed": set(),
    "rejected": set(),
}


class FutureWorkerExecutionService:
    def __init__(self, session_service: SessionService) -> None:
        self._session_service = session_service

    @staticmethod
    def _correlation_id(worker_task_ref: str) -> str:
        return f"corr:future-worker:{worker_task_ref}"

    def request_worker(
        self,
        *,
        project_id: str,
        parent_session_id: str,
        worker_task_ref: str,
        decision_trace_ref: str,
        goal_contract_version: str,
        scope: str,
        allowed_hands: list[str],
        input_packet_refs: list[str],
        retrieval_handles: list[str],
        distilled_summary_ref: str,
        execution_budget_ref: str,
        occurred_at: str,
    ) -> FutureWorkerExecutionRequest:
        self._assert_transition_allowed(
            parent_session_id=parent_session_id,
            worker_task_ref=worker_task_ref,
            next_event_type="future_worker_requested",
        )
        request = FutureWorkerExecutionRequest(
            project_id=project_id,
            parent_session_id=parent_session_id,
            worker_task_ref=worker_task_ref,
            decision_trace_ref=decision_trace_ref,
            goal_contract_version=goal_contract_version,
            scope=scope,
            allowed_hands=list(allowed_hands),
            input_packet_refs=list(input_packet_refs),
            retrieval_handles=list(retrieval_handles),
            distilled_summary_ref=distilled_summary_ref,
            execution_budget_ref=execution_budget_ref,
        )
        self._record_lifecycle_event(
            event_type="future_worker_requested",
            project_id=project_id,
            parent_session_id=parent_session_id,
            worker_task_ref=worker_task_ref,
            occurred_at=occurred_at,
            related_ids={"decision_trace_ref": decision_trace_ref},
            payload=request.model_dump(mode="json"),
        )
        return request

    def record_started(
        self,
        *,
        worker_task_ref: str,
        project_id: str,
        parent_session_id: str,
        occurred_at: str,
        worker_runtime_contract: dict[str, Any] | None = None,
    ) -> None:
        self._require_request_event(
            parent_session_id=parent_session_id,
            worker_task_ref=worker_task_ref,
        )
        self._assert_transition_allowed(
            parent_session_id=parent_session_id,
            worker_task_ref=worker_task_ref,
            next_event_type="future_worker_started",
        )
        self._record_lifecycle_event(
            event_type="future_worker_started",
            project_id=project_id,
            parent_session_id=parent_session_id,
            worker_task_ref=worker_task_ref,
            occurred_at=occurred_at,
            payload={"worker_runtime_contract": dict(worker_runtime_contract or {})},
        )

    def record_summary_published(
        self,
        *,
        worker_task_ref: str,
        project_id: str,
        parent_session_id: str,
        summary_ref: str,
        occurred_at: str,
    ) -> None:
        self._require_request_event(
            parent_session_id=parent_session_id,
            worker_task_ref=worker_task_ref,
        )
        self._assert_transition_allowed(
            parent_session_id=parent_session_id,
            worker_task_ref=worker_task_ref,
            next_event_type="future_worker_summary_published",
        )
        self._record_lifecycle_event(
            event_type="future_worker_summary_published",
            project_id=project_id,
            parent_session_id=parent_session_id,
            worker_task_ref=worker_task_ref,
            occurred_at=occurred_at,
            related_ids={"summary_ref": summary_ref},
            payload={"summary_ref": summary_ref},
        )

    def record_heartbeat(
        self,
        *,
        worker_task_ref: str,
        project_id: str,
        parent_session_id: str,
        occurred_at: str,
        heartbeat: dict[str, Any],
    ) -> None:
        self._require_request_event(
            parent_session_id=parent_session_id,
            worker_task_ref=worker_task_ref,
        )
        self._assert_transition_allowed(
            parent_session_id=parent_session_id,
            worker_task_ref=worker_task_ref,
            next_event_type="future_worker_heartbeat",
        )
        self._record_lifecycle_event(
            event_type="future_worker_heartbeat",
            project_id=project_id,
            parent_session_id=parent_session_id,
            worker_task_ref=worker_task_ref,
            occurred_at=occurred_at,
            payload={"heartbeat": dict(heartbeat)},
        )

    def record_completed(
        self,
        *,
        worker_task_ref: str,
        project_id: str,
        parent_session_id: str,
        result_summary_ref: str,
        artifact_refs: list[str],
        input_contract_hash: str,
        result_hash: str,
        occurred_at: str,
    ) -> FutureWorkerResultEnvelope:
        request_event = self._require_request_event(
            parent_session_id=parent_session_id,
            worker_task_ref=worker_task_ref,
        )
        self._assert_transition_allowed(
            parent_session_id=parent_session_id,
            worker_task_ref=worker_task_ref,
            next_event_type="future_worker_completed",
        )
        started_event = self._require_started_event(
            parent_session_id=parent_session_id,
            worker_task_ref=worker_task_ref,
        )
        decision_trace_ref = request_event.related_ids.get("decision_trace_ref")
        if not decision_trace_ref:
            raise ValueError(f"missing decision trace for future worker {worker_task_ref}")
        worker_runtime_contract = started_event.payload.get("worker_runtime_contract")
        if not isinstance(worker_runtime_contract, dict) or not worker_runtime_contract:
            raise ValueError(f"missing worker runtime contract for future worker {worker_task_ref}")
        envelope = FutureWorkerResultEnvelope(
            worker_task_ref=worker_task_ref,
            parent_session_id=parent_session_id,
            decision_trace_ref=decision_trace_ref,
            result_summary_ref=result_summary_ref,
            artifact_refs=list(artifact_refs),
            input_contract_hash=input_contract_hash,
            result_hash=result_hash,
            produced_at=occurred_at,
            status="completed",
            worker_runtime_contract=worker_runtime_contract,
        )
        self._record_lifecycle_event(
            event_type="future_worker_completed",
            project_id=project_id,
            parent_session_id=parent_session_id,
            worker_task_ref=worker_task_ref,
            occurred_at=occurred_at,
            related_ids={"summary_ref": result_summary_ref},
            payload=envelope.model_dump(mode="json"),
        )
        return envelope

    def consume_result(
        self,
        *,
        worker_task_ref: str,
        project_id: str,
        parent_session_id: str,
        consumed_by_decision_id: str,
        occurred_at: str,
    ) -> None:
        self._require_request_event(
            parent_session_id=parent_session_id,
            worker_task_ref=worker_task_ref,
        )
        self._require_completed_event(
            parent_session_id=parent_session_id,
            worker_task_ref=worker_task_ref,
        )
        self._assert_transition_allowed(
            parent_session_id=parent_session_id,
            worker_task_ref=worker_task_ref,
            next_event_type="future_worker_result_consumed",
        )
        self._record_lifecycle_event(
            event_type="future_worker_result_consumed",
            project_id=project_id,
            parent_session_id=parent_session_id,
            worker_task_ref=worker_task_ref,
            occurred_at=occurred_at,
            related_ids={"decision_id": consumed_by_decision_id},
            payload={"consumed_by_decision_id": consumed_by_decision_id},
        )

    def record_failed(
        self,
        *,
        worker_task_ref: str,
        project_id: str,
        parent_session_id: str,
        occurred_at: str,
        reason: str,
    ) -> None:
        self._require_request_event(
            parent_session_id=parent_session_id,
            worker_task_ref=worker_task_ref,
        )
        self._assert_transition_allowed(
            parent_session_id=parent_session_id,
            worker_task_ref=worker_task_ref,
            next_event_type="future_worker_failed",
        )
        self._record_lifecycle_event(
            event_type="future_worker_failed",
            project_id=project_id,
            parent_session_id=parent_session_id,
            worker_task_ref=worker_task_ref,
            occurred_at=occurred_at,
            payload={"reason": reason},
        )

    def record_cancelled(
        self,
        *,
        worker_task_ref: str,
        project_id: str,
        parent_session_id: str,
        occurred_at: str,
        reason: str,
    ) -> None:
        self._require_request_event(
            parent_session_id=parent_session_id,
            worker_task_ref=worker_task_ref,
        )
        self._assert_transition_allowed(
            parent_session_id=parent_session_id,
            worker_task_ref=worker_task_ref,
            next_event_type="future_worker_cancelled",
        )
        self._record_lifecycle_event(
            event_type="future_worker_cancelled",
            project_id=project_id,
            parent_session_id=parent_session_id,
            worker_task_ref=worker_task_ref,
            occurred_at=occurred_at,
            payload={"reason": reason},
        )

    def reject_result(
        self,
        *,
        worker_task_ref: str,
        project_id: str,
        parent_session_id: str,
        reason: str,
        occurred_at: str,
    ) -> None:
        self._require_request_event(
            parent_session_id=parent_session_id,
            worker_task_ref=worker_task_ref,
        )
        self._require_completed_event(
            parent_session_id=parent_session_id,
            worker_task_ref=worker_task_ref,
        )
        self._assert_transition_allowed(
            parent_session_id=parent_session_id,
            worker_task_ref=worker_task_ref,
            next_event_type="future_worker_result_rejected",
        )
        self._record_lifecycle_event(
            event_type="future_worker_result_rejected",
            project_id=project_id,
            parent_session_id=parent_session_id,
            worker_task_ref=worker_task_ref,
            occurred_at=occurred_at,
            payload={"reason": reason},
        )

    def _worker_events(self, *, parent_session_id: str, worker_task_ref: str):
        events = self._session_service.list_events(session_id=parent_session_id)
        return [
            event
            for event in events
            if event.related_ids.get("worker_task_ref") == worker_task_ref
        ]

    def _current_worker_state(self, *, parent_session_id: str, worker_task_ref: str) -> str | None:
        for event in reversed(
            self._worker_events(
                parent_session_id=parent_session_id,
                worker_task_ref=worker_task_ref,
            )
        ):
            state = _WORKER_STATE_BY_EVENT_TYPE.get(event.event_type)
            if state is not None:
                return state
        return None

    def _assert_transition_allowed(
        self,
        *,
        parent_session_id: str,
        worker_task_ref: str,
        next_event_type: str,
    ) -> None:
        current_state = self._current_worker_state(
            parent_session_id=parent_session_id,
            worker_task_ref=worker_task_ref,
        )
        if current_state in _TERMINAL_WORKER_STATES:
            raise ValueError(f"terminal future worker state: {current_state}")
        allowed_events = _ALLOWED_NEXT_WORKER_EVENTS.get(current_state, set())
        if next_event_type not in allowed_events:
            next_state = _WORKER_STATE_BY_EVENT_TYPE.get(next_event_type, "unknown")
            source_state = current_state or "none"
            raise ValueError(f"invalid future worker transition: {source_state} -> {next_state}")

    def _require_request_event(self, *, parent_session_id: str, worker_task_ref: str):
        for event in reversed(
            self._worker_events(
                parent_session_id=parent_session_id,
                worker_task_ref=worker_task_ref,
            )
        ):
            if event.event_type == "future_worker_requested":
                return event
        raise ValueError(f"unknown future worker request: {worker_task_ref}")

    def _require_started_event(self, *, parent_session_id: str, worker_task_ref: str):
        for event in reversed(
            self._worker_events(
                parent_session_id=parent_session_id,
                worker_task_ref=worker_task_ref,
            )
        ):
            if event.event_type == "future_worker_started":
                return event
        raise ValueError(f"missing future worker start event: {worker_task_ref}")

    def _require_completed_event(self, *, parent_session_id: str, worker_task_ref: str):
        for event in reversed(
            self._worker_events(
                parent_session_id=parent_session_id,
                worker_task_ref=worker_task_ref,
            )
        ):
            if event.event_type == "future_worker_completed":
                return event
        raise ValueError(f"missing future worker completed event: {worker_task_ref}")

    def _record_lifecycle_event(
        self,
        *,
        event_type: str,
        project_id: str,
        parent_session_id: str,
        worker_task_ref: str,
        occurred_at: str,
        related_ids: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._session_service.record_event(
            event_type=event_type,
            project_id=project_id,
            session_id=parent_session_id,
            occurred_at=occurred_at,
            correlation_id=self._correlation_id(worker_task_ref),
            related_ids={
                "worker_task_ref": worker_task_ref,
                **dict(related_ids or {}),
            },
            payload=dict(payload or {}),
        )
