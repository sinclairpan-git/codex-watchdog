from __future__ import annotations

from typing import Any

from watchdog.services.goal_contract.models import (
    GoalContractReadiness,
    GoalContractSnapshot,
    StageGoalAlignmentOutcome,
)
from watchdog.services.session_service.models import SessionEventRecord
from watchdog.services.session_service.service import SessionService

_GOAL_CONTRACT_EVENT_TYPES = {
    "goal_contract_created",
    "goal_contract_revised",
    "goal_contract_adopted_by_child_session",
}
_DEFAULT_INFERENCE_BOUNDARY = (
    "Only explicit deliverables and explicit completion signals can unlock autonomous progression."
)


def _normalize_text(value: str | None) -> str:
    return " ".join(str(value or "").split()).strip()


def _next_goal_contract_version(current: str | None) -> str:
    if not current:
        return "goal-v1"
    prefix, _, suffix = current.rpartition("v")
    if prefix != "goal-" or not suffix.isdigit():
        raise ValueError(f"unsupported goal contract version: {current}")
    return f"goal-v{int(suffix) + 1}"


class GoalContractService:
    def __init__(self, session_service: SessionService) -> None:
        self._session_service = session_service

    def bootstrap_contract(
        self,
        *,
        project_id: str,
        session_id: str,
        task_title: str,
        task_prompt: str,
        last_user_instruction: str,
        phase: str,
        last_summary: str,
        current_phase_goal: str | None = None,
        explicit_deliverables: list[str] | None = None,
        completion_signals: list[str] | None = None,
        non_goals: list[str] | None = None,
        inference_boundary: str | None = None,
        stage: str | None = None,
        active_goal: str | None = None,
    ) -> GoalContractSnapshot:
        version = "goal-v1"
        contract = GoalContractSnapshot(
            version=version,
            project_id=project_id,
            session_id=session_id,
            original_goal=self._pick_first_nonempty(task_prompt, task_title, last_user_instruction, last_summary),
            explicit_deliverables=self._normalize_list(
                explicit_deliverables,
                fallback=[task_title] if explicit_deliverables is None and task_title.strip() else [],
            ),
            non_goals=self._normalize_list(non_goals),
            completion_signals=self._normalize_list(
                completion_signals,
                fallback=[
                    "Goal contract deliverables explicitly verified."
                ]
                if completion_signals is None
                else [],
            ),
            inference_boundary=_normalize_text(inference_boundary) or _DEFAULT_INFERENCE_BOUNDARY,
            current_phase_goal=self._pick_first_nonempty(
                current_phase_goal,
                active_goal,
                last_user_instruction,
                task_title,
                task_prompt,
            ),
            phase=_normalize_text(phase) or None,
            stage=_normalize_text(stage) or None,
            active_goal=_normalize_text(active_goal) or None,
            metadata={
                "task_title": _normalize_text(task_title),
                "last_summary": _normalize_text(last_summary),
                "last_user_instruction": _normalize_text(last_user_instruction),
            },
        )
        self._record_goal_contract_event(
            event_type="goal_contract_created",
            project_id=project_id,
            session_id=session_id,
            contract=contract,
        )
        return contract

    def revise_contract(
        self,
        *,
        project_id: str,
        session_id: str,
        expected_version: str,
        current_phase_goal: str | None = None,
        explicit_deliverables: list[str] | None = None,
        completion_signals: list[str] | None = None,
        non_goals: list[str] | None = None,
        inference_boundary: str | None = None,
        active_goal: str | None = None,
        phase: str | None = None,
        stage: str | None = None,
    ) -> GoalContractSnapshot:
        current = self.get_current_contract(project_id=project_id, session_id=session_id)
        if current is None:
            raise ValueError(f"goal contract not found for session: {session_id}")
        if current.version != expected_version:
            raise ValueError(
                f"goal contract version mismatch for {session_id}: expected {expected_version}, got {current.version}"
            )
        revised = current.model_copy(
            update={
                "version": _next_goal_contract_version(current.version),
                "current_phase_goal": self._pick_first_nonempty(
                    current_phase_goal,
                    active_goal,
                    current.current_phase_goal,
                ),
                "explicit_deliverables": self._replace_if_provided(
                    explicit_deliverables,
                    fallback=current.explicit_deliverables,
                ),
                "completion_signals": self._replace_if_provided(
                    completion_signals,
                    fallback=current.completion_signals,
                ),
                "non_goals": self._replace_if_provided(non_goals, fallback=current.non_goals),
                "inference_boundary": _normalize_text(inference_boundary) or current.inference_boundary,
                "active_goal": _normalize_text(active_goal) or current.active_goal,
                "phase": _normalize_text(phase) or current.phase,
                "stage": _normalize_text(stage) or current.stage,
            }
        )
        self._record_goal_contract_event(
            event_type="goal_contract_revised",
            project_id=project_id,
            session_id=session_id,
            contract=revised,
            causation_id=expected_version,
        )
        return revised

    def adopt_contract_for_child_session(
        self,
        *,
        project_id: str,
        parent_session_id: str,
        child_session_id: str,
        expected_version: str | None = None,
        recovery_transaction_id: str | None = None,
        source_packet_id: str | None = None,
    ) -> GoalContractSnapshot:
        parent = self.get_current_contract(project_id=project_id, session_id=parent_session_id)
        if parent is None:
            raise ValueError(f"goal contract not found for session: {parent_session_id}")
        if expected_version is not None and parent.version != expected_version:
            raise ValueError(
                f"goal contract version mismatch for {parent_session_id}: expected {expected_version}, got {parent.version}"
            )
        adopted = parent.model_copy(
            update={
                "session_id": child_session_id,
                "source_session_id": parent_session_id,
            }
        )
        self._record_goal_contract_event(
            event_type="goal_contract_adopted_by_child_session",
            project_id=project_id,
            session_id=child_session_id,
            contract=adopted,
            causation_id=recovery_transaction_id,
            related_ids={
                "goal_contract_version": adopted.version,
                "parent_session_id": parent_session_id,
                **(
                    {"recovery_transaction_id": recovery_transaction_id}
                    if recovery_transaction_id is not None
                    else {}
                ),
                **(
                    {"source_packet_id": source_packet_id}
                    if source_packet_id is not None
                    else {}
                ),
            },
            payload_extra={
                "parent_session_id": parent_session_id,
                "recovery_transaction_id": recovery_transaction_id,
                "source_packet_id": source_packet_id,
            },
        )
        return adopted

    def get_current_contract(
        self,
        *,
        project_id: str,
        session_id: str,
    ) -> GoalContractSnapshot | None:
        relevant = [
            event
            for event in self._session_service.list_events(session_id=session_id)
            if event.project_id == project_id and event.event_type in _GOAL_CONTRACT_EVENT_TYPES
        ]
        if not relevant:
            return None
        latest = max(relevant, key=lambda event: event.log_seq or 0)
        contract_payload = latest.payload.get("contract")
        if not isinstance(contract_payload, dict):
            raise ValueError(f"goal contract payload missing contract snapshot for event {latest.event_id}")
        return GoalContractSnapshot.model_validate(contract_payload)

    def evaluate_readiness(
        self,
        *,
        project_id: str,
        session_id: str,
    ) -> GoalContractReadiness:
        contract = self.get_current_contract(project_id=project_id, session_id=session_id)
        if contract is None:
            return GoalContractReadiness(
                mode="observe_only",
                missing_fields=["goal_contract"],
            )
        missing_fields: list[str] = []
        if not contract.explicit_deliverables:
            missing_fields.append("explicit_deliverables")
        if not contract.completion_signals:
            missing_fields.append("completion_signals")
        return GoalContractReadiness(
            mode="observe_only" if missing_fields else "autonomous_ready",
            missing_fields=missing_fields,
        )

    def ensure_stage_alignment(
        self,
        *,
        project_id: str,
        session_id: str,
        stage: str,
        active_goal: str | None,
    ) -> StageGoalAlignmentOutcome:
        contract = self.get_current_contract(project_id=project_id, session_id=session_id)
        normalized_active_goal = _normalize_text(active_goal)
        if contract is None or not normalized_active_goal:
            return StageGoalAlignmentOutcome(blocked=False)
        normalized_current_goal = _normalize_text(contract.current_phase_goal)
        if normalized_current_goal == normalized_active_goal:
            return StageGoalAlignmentOutcome(blocked=False)
        conflict_summary = (
            f"stage active goal '{normalized_active_goal}' conflicts with current phase goal "
            f"'{contract.current_phase_goal}'."
        )
        event = self._session_service.record_event(
            event_type="stage_goal_conflict_detected",
            project_id=project_id,
            session_id=session_id,
            correlation_id=(
                "corr:stage-goal-conflict:"
                f"{session_id}:{contract.version}:{_normalize_text(stage)}:{normalized_active_goal}"
            ),
            causation_id=contract.version,
            related_ids={
                "goal_contract_version": contract.version,
                "stage": _normalize_text(stage),
            },
            payload={
                "current_phase_goal": contract.current_phase_goal,
                "stage_active_goal": normalized_active_goal,
                "stage": _normalize_text(stage),
                "summary": conflict_summary,
            },
        )
        return StageGoalAlignmentOutcome(
            blocked=True,
            conflict_event_id=event.event_id,
            conflict_summary=conflict_summary,
        )

    def _record_goal_contract_event(
        self,
        *,
        event_type: str,
        project_id: str,
        session_id: str,
        contract: GoalContractSnapshot,
        causation_id: str | None = None,
        related_ids: dict[str, str] | None = None,
        payload_extra: dict[str, Any] | None = None,
    ) -> SessionEventRecord:
        normalized_related_ids = {
            "goal_contract_version": contract.version,
            **dict(related_ids or {}),
        }
        payload = {
            "contract": contract.model_dump(mode="json"),
            **dict(payload_extra or {}),
        }
        return self._session_service.record_event(
            event_type=event_type,
            project_id=project_id,
            session_id=session_id,
            correlation_id=f"corr:{event_type}:{session_id}:{contract.version}",
            causation_id=causation_id,
            related_ids=normalized_related_ids,
            payload=payload,
        )

    @staticmethod
    def _pick_first_nonempty(*values: str | None) -> str:
        for value in values:
            normalized = _normalize_text(value)
            if normalized:
                return normalized
        raise ValueError("goal contract requires at least one non-empty source field")

    @staticmethod
    def _normalize_list(values: list[str] | None, *, fallback: list[str] | None = None) -> list[str]:
        source = values if values is not None else fallback or []
        return [_normalize_text(value) for value in source if _normalize_text(value)]

    @classmethod
    def _replace_if_provided(cls, values: list[str] | None, *, fallback: list[str]) -> list[str]:
        if values is None:
            return list(fallback)
        return cls._normalize_list(values)
