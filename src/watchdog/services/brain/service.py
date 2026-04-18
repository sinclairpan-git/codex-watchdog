from __future__ import annotations

from typing import TYPE_CHECKING

from watchdog.services.goal_contract.service import GoalContractService
from watchdog.services.brain.provider_runtime import (
    OpenAICompatibleBrainProvider,
    ProviderOutputSchemaError,
)
from watchdog.services.memory_hub.models import ContextQualitySnapshot
from watchdog.services.memory_hub.service import MemoryHubService
from watchdog.services.brain.models import DecisionIntent, DecisionTrace
from watchdog.settings import Settings

if TYPE_CHECKING:
    import httpx

    from watchdog.services.session_spine.store import PersistedSessionRecord
    from watchdog.services.session_service.service import SessionService


class BrainDecisionService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        memory_hub_service: MemoryHubService | None = None,
        session_service: SessionService | None = None,
        provider_transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings or Settings()
        self._memory_hub_service = memory_hub_service or MemoryHubService()
        self._session_service = session_service
        self._provider = OpenAICompatibleBrainProvider(
            settings=self._settings,
            transport=provider_transport,
        )

    @staticmethod
    def _memory_quality_snapshot() -> ContextQualitySnapshot:
        return ContextQualitySnapshot(
            key_fact_recall=0.8,
            irrelevant_summary_precision=0.8,
            token_budget_utilization=0.4,
            expansion_miss_rate=0.1,
        )

    @staticmethod
    def _memory_source_ref(payload: dict[str, object]) -> str | None:
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

    def _session_truth(self, record: PersistedSessionRecord) -> dict[str, object]:
        truth: dict[str, object] = {
            "status": record.session.session_state,
            "activity_phase": record.progress.activity_phase,
        }
        if self._session_service is None:
            return truth
        contracts = GoalContractService(self._session_service)
        contract = contracts.get_current_contract(
            project_id=record.project_id,
            session_id=record.thread_id,
        )
        if contract is not None and contract.current_phase_goal:
            truth["current_phase_goal"] = contract.current_phase_goal
        return truth

    def _consume_memory_advisory_context(
        self,
        record: PersistedSessionRecord | None,
    ) -> dict[str, object] | None:
        if record is None:
            return None
        try:
            payload = self._memory_hub_service.build_runtime_advisory_context(
                query=record.progress.summary or record.project_id,
                project_id=record.project_id,
                session_id=record.thread_id,
                limit=4,
                quality=self._memory_quality_snapshot(),
                session_truth=self._session_truth(record),
            )
        except Exception:
            if self._session_service is not None:
                self._session_service.record_memory_unavailable_degraded(
                    project_id=record.project_id,
                    session_id=record.thread_id,
                    memory_scope="project",
                    fallback_mode="session_service_runtime_snapshot",
                    degradation_reason="memory_hub_unreachable",
                )
            return None
        degradation = payload.get("degradation")
        if (
            self._session_service is not None
            and isinstance(degradation, dict)
            and str(degradation.get("reason_code") or "") == "memory_conflict_detected"
        ):
            self._session_service.record_memory_conflict_detected(
                project_id=record.project_id,
                session_id=record.thread_id,
                memory_scope="project",
                conflict_reason="runtime_advisory_conflict",
                resolution=str(degradation.get("resolution") or "session_service_truth"),
                source_ref=self._memory_source_ref(payload),
            )
        return payload

    def _rule_based_intent(
        self,
        *,
        record: PersistedSessionRecord | None,
        intent: str | None = None,
        rationale: str | None = None,
        provider_output_schema_ref: str | None = None,
        degrade_reason: str | None = None,
    ) -> DecisionIntent:
        if intent is None:
            fact_codes = {fact.fact_code for fact in record.facts} if record is not None else set()
            if "task_completed" in fact_codes:
                intent = "candidate_closure"
                rationale = rationale or "session reached a terminal completed state"
            elif fact_codes.intersection({"approval_pending", "awaiting_human_direction"}):
                intent = "require_approval"
                rationale = rationale or "session requires explicit human guidance"
            elif "context_critical" in fact_codes:
                intent = "propose_recovery"
                rationale = rationale or "session requires recovery handoff"
            elif fact_codes.intersection({"stuck_no_progress", "repeat_failure"}):
                intent = "propose_execute"
                rationale = rationale or "session can continue autonomously"
            else:
                intent = "observe_only"
                rationale = rationale or "no executable action proposed"
        return DecisionIntent(
            intent=intent,
            rationale=rationale,
            action_arguments=self._rule_based_action_arguments(
                record=record,
                intent=intent,
                rationale=rationale,
            ),
            provider_output_schema_ref=provider_output_schema_ref,
            degrade_reason=degrade_reason,
        )

    @staticmethod
    def _rule_based_action_arguments(
        *,
        record: PersistedSessionRecord | None,
        intent: str,
        rationale: str | None,
    ) -> dict[str, object]:
        if intent == "candidate_closure" and record is not None:
            summary = record.progress.summary or "session reached done state"
            return {
                "message": f"Review completion candidate for {record.project_id}: {summary}",
                "reason_code": "candidate_closure",
                "stuck_level": 0,
            }
        if intent != "propose_execute" or record is None:
            return {}
        summary = str(record.progress.summary or "current task").strip()
        if not summary:
            summary = "current task"
        stuck_level = int(record.progress.stuck_level or 0)
        message = f"下一步建议：继续推进 {summary}，并优先验证最近改动。"
        if rationale and "recovery" in rationale.lower():
            message = "下一步建议：继续推进恢复流程，并优先验证最近改动。"
        return {
            "message": message,
            "reason_code": "rule_based_continue",
            "stuck_level": max(stuck_level, 0),
        }

    def evaluate_session(
        self,
        *,
        record: PersistedSessionRecord | None = None,
        suggested_action_ref: str | None = None,
        trace: DecisionTrace | None = None,
        intent: str | None = None,
        rationale: str | None = None,
    ) -> DecisionIntent:
        _ = (trace, suggested_action_ref)
        memory_context = self._consume_memory_advisory_context(record)
        if intent is not None:
            return self._rule_based_intent(record=record, intent=intent, rationale=rationale)
        if record is not None and self._provider.configured():
            try:
                return self._provider.decide(
                    record=record,
                    session_truth=self._session_truth(record),
                    memory_advisory_context=memory_context,
                )
            except ProviderOutputSchemaError as exc:
                return self._rule_based_intent(
                    record=record,
                    intent=intent,
                    rationale=rationale,
                    provider_output_schema_ref=exc.schema_ref,
                    degrade_reason=exc.degrade_reason,
                )
            except Exception:
                pass
        return self._rule_based_intent(record=record, intent=intent, rationale=rationale)
