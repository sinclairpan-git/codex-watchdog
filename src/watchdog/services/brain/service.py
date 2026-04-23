from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import yaml

from watchdog.services.goal_contract.service import GoalContractService
from watchdog.services.brain.provider_runtime import (
    OpenAICompatibleBrainProvider,
    PROVIDER_RATE_LIMITED_DEGRADE_REASON,
    PROVIDER_UNAVAILABLE_DEGRADE_REASON,
    ProviderOutputSchemaError,
)
from watchdog.services.memory_hub.models import ContextQualitySnapshot
from watchdog.services.memory_hub.service import MemoryHubService
from watchdog.services.session_spine.approval_visibility import is_visible_projected_approval
from watchdog.services.brain.models import (
    DecisionIntent,
    PCDIApprovalRef,
    DecisionTrace,
    PCDIBranchRef,
    PCDICompletionRef,
    PCDIDecisionScopeRef,
    PCDIErrorRef,
    PCDIFreshnessRef,
    PCDIGovernanceRef,
    PCDIProgressRef,
    PCDIProjectRef,
    PCDISessionRef,
    ProjectContinuationDecisionInput,
)
from watchdog.services.session_spine.text import sanitize_session_summary
from watchdog.settings import Settings

if TYPE_CHECKING:
    import httpx

    from watchdog.services.session_spine.store import PersistedSessionRecord
    from watchdog.services.session_service.service import SessionService


class BrainDecisionService:
    _SUMMARY_PLACEHOLDER_FRAGMENTS = (
        "当前进展待汇总",
        "请汇总当前进展",
        "需要先返回已完成内容、阻塞点和下一步动作",
    )

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        memory_hub_service: MemoryHubService | None = None,
        session_service: SessionService | None = None,
        repo_root: Path | None = None,
        provider_transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings or Settings()
        self._memory_hub_service = memory_hub_service or MemoryHubService()
        self._session_service = session_service
        self._repo_root = repo_root or Path(__file__).resolve().parents[4]
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

    def _read_yaml_mapping(self, relative_path: str) -> dict[str, object]:
        path = self._repo_root / relative_path
        if not path.is_file():
            return {}
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _nested_mapping(payload: dict[str, object], *keys: str) -> dict[str, object]:
        current: object = payload
        for key in keys:
            if not isinstance(current, dict):
                return {}
            current = current.get(key)
        return current if isinstance(current, dict) else {}

    @staticmethod
    def _string_list(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        items: list[str] = []
        for item in value:
            normalized = str(item or "").strip()
            if normalized:
                items.append(normalized)
        return items

    @staticmethod
    def _int_or_none(value: object) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _fact_codes(record: PersistedSessionRecord) -> list[str]:
        return [
            code
            for code in (str(getattr(fact, "fact_code", "") or "").strip() for fact in record.facts)
            if code
        ]

    @staticmethod
    def _latest_error_summary(record: PersistedSessionRecord) -> str | None:
        for fact in reversed(record.facts):
            severity = str(getattr(fact, "severity", "") or "").strip().lower()
            detail = str(getattr(fact, "detail", "") or "").strip()
            summary = str(getattr(fact, "summary", "") or "").strip()
            if severity in {"error", "critical"}:
                return detail or summary or None
        return None

    @staticmethod
    def _approval_actionable_commands(record: PersistedSessionRecord) -> list[str]:
        actionable = {"list_pending_approvals", "approve_approval", "reject_approval"}
        return [
            intent
            for intent in record.session.available_intents
            if str(intent or "").strip() in actionable
        ]

    @staticmethod
    def _latest_approval_reason(
        record: PersistedSessionRecord,
        *,
        has_pending_approval: bool,
    ) -> str | None:
        if not has_pending_approval or not record.approval_queue:
            return None
        approval = next(
            (item for item in record.approval_queue if is_visible_projected_approval(item)),
            None,
        )
        if approval is None:
            return None
        reason = str(getattr(approval, "reason", "") or "").strip()
        alternative = str(getattr(approval, "alternative", "") or "").strip()
        return reason or alternative or None

    def _decision_scope_ref(self, record: PersistedSessionRecord) -> PCDIDecisionScopeRef:
        available_intents = {str(intent or "").strip() for intent in record.session.available_intents}
        return PCDIDecisionScopeRef(
            can_request_approval=bool(available_intents.intersection({"approve_approval", "reject_approval"})),
            can_continue_current_branch="continue" in available_intents,
            can_recover_current_branch=True,
            can_switch_branch=self._int_or_none(
                self._read_yaml_mapping(".ai-sdlc/project/config/project-state.yaml").get("next_work_item_seq")
            )
            is not None,
            can_close_session="close" in available_intents or "done" in available_intents,
        )

    @classmethod
    def _summary_is_placeholder(cls, summary: str) -> bool:
        normalized = str(summary or "").strip()
        if not normalized:
            return True
        return any(fragment in normalized for fragment in cls._SUMMARY_PLACEHOLDER_FRAGMENTS)

    @staticmethod
    def _join_unique(parts: list[str]) -> str:
        ordered: list[str] = []
        seen: set[str] = set()
        for part in parts:
            normalized = str(part or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)
        return "；".join(ordered)

    def _progress_summary_for_decision_context(
        self,
        *,
        record: PersistedSessionRecord,
        branch_goal: str,
        completion_signals: list[str],
    ) -> str:
        summary = sanitize_session_summary(record.progress.summary)
        if not self._summary_is_placeholder(summary):
            return summary
        blocker_codes = [str(item or "").strip() for item in record.progress.blocker_fact_codes if str(item or "").strip()]
        primary_codes = [str(item or "").strip() for item in record.progress.primary_fact_codes if str(item or "").strip()]
        phase = str(record.progress.activity_phase or record.session.activity_phase or "").strip()
        synthesized_parts: list[str] = []
        if branch_goal and branch_goal != "goal-contract:missing":
            synthesized_parts.append(f"当前分支目标：{branch_goal}")
        if phase:
            synthesized_parts.append(f"当前阶段：{phase}")
        if blocker_codes:
            synthesized_parts.append(f"阻塞信号：{', '.join(blocker_codes[:3])}")
        elif primary_codes:
            synthesized_parts.append(f"当前信号：{', '.join(primary_codes[:3])}")
        if completion_signals:
            synthesized_parts.append(f"待完成：{', '.join(completion_signals[:2])}")
        if int(record.session.pending_approval_count or 0) > 0:
            synthesized_parts.append("当前存在待审批项")
        synthesized = self._join_unique(synthesized_parts)
        return synthesized or "当前进展待汇总；需先补齐阶段状态、阻塞点和下一步动作。"

    def progress_summary_for_decision_context(
        self,
        record: PersistedSessionRecord,
    ) -> str:
        contract = None
        if self._session_service is not None:
            contract = GoalContractService(self._session_service).get_current_contract(
                project_id=record.project_id,
                session_id=record.thread_id,
            )
        branch_goal = "goal-contract:missing"
        completion_signals: list[str] = []
        if contract is not None:
            branch_goal = contract.current_phase_goal
            completion_signals = list(contract.completion_signals)
        return self._progress_summary_for_decision_context(
            record=record,
            branch_goal=branch_goal,
            completion_signals=completion_signals,
        )

    def _build_decision_context(
        self,
        record: PersistedSessionRecord,
    ) -> ProjectContinuationDecisionInput:
        checkpoint = self._read_yaml_mapping(".ai-sdlc/state/checkpoint.yml")
        project_state = self._read_yaml_mapping(".ai-sdlc/project/config/project-state.yaml")
        state_resume = self._read_yaml_mapping(".ai-sdlc/state/resume-pack.yaml")
        feature = self._nested_mapping(checkpoint, "feature")
        goal_contract_version = str(record.progress.goal_contract_version or "").strip() or "goal-contract:unknown"
        project_total_goal = "goal-contract:missing"
        branch_goal = "goal-contract:missing"
        completion_signals: list[str] = []
        goal_contract_readiness: str | None = "missing"

        if self._session_service is not None:
            contracts = GoalContractService(self._session_service)
            contract = contracts.get_current_contract(
                project_id=record.project_id,
                session_id=record.thread_id,
            )
            if contract is not None:
                goal_contract_version = contract.version
                project_total_goal = contract.original_goal
                branch_goal = contract.current_phase_goal
                completion_signals = list(contract.completion_signals)
            readiness = contracts.evaluate_readiness(
                project_id=record.project_id,
                session_id=record.thread_id,
            )
            goal_contract_readiness = readiness.mode

        project_execution_state = self._normalize_project_execution_state(
            record_project_id=record.project_id,
            project_state=project_state,
            checkpoint=checkpoint,
            state_resume=state_resume,
        )
        next_work_item_seq = self._int_or_none(project_state.get("next_work_item_seq"))
        continuation_identity = (
            f"{record.project_id}:{record.thread_id}:{record.effective_native_thread_id or 'none'}"
        )
        route_key = f"{continuation_identity}:{record.fact_snapshot_version}"
        next_branch_candidate = (
            f"work-item-seq:{next_work_item_seq}" if next_work_item_seq is not None else None
        )
        branch_switch_token = (
            f"branch-switch:{record.project_id}:{next_work_item_seq}:{record.fact_snapshot_version}"
            if next_work_item_seq is not None
            else None
        )
        fact_codes = self._fact_codes(record)
        blocker_fact_codes = list(record.progress.blocker_fact_codes)
        latest_error_summary = self._latest_error_summary(record)
        approval_commands = self._approval_actionable_commands(record)
        pending_approval_count = max(int(record.session.pending_approval_count or 0), 0)
        visible_projected_approvals = (
            [
                item for item in record.approval_queue if is_visible_projected_approval(item)
            ]
            if pending_approval_count > 0
            else []
        )
        has_pending_approval = pending_approval_count > 0 or bool(visible_projected_approvals)

        return ProjectContinuationDecisionInput(
            packet_version="pcdi:v1",
            project_ref=PCDIProjectRef(
                project_id=record.project_id,
                project_execution_state=project_execution_state,
                project_total_goal=project_total_goal,
            ),
            branch_ref=PCDIBranchRef(
                active_work_item_id=str(feature.get("id") or "").strip() or None,
                active_branch=str(feature.get("current_branch") or "").strip() or None,
                branch_goal=branch_goal,
                branch_completion_signals=completion_signals,
                next_work_item_seq=next_work_item_seq,
                next_branch_candidate=next_branch_candidate,
                target_work_item_seq=next_work_item_seq,
            ),
            progress_ref=PCDIProgressRef(
                current_phase=record.progress.activity_phase,
                current_progress_summary=self._progress_summary_for_decision_context(
                    record=record,
                    branch_goal=branch_goal,
                    completion_signals=completion_signals,
                ),
                files_touched=list(record.progress.files_touched),
                remaining_tasks=list(completion_signals),
                next_recommended_tasks=[],
            ),
            session_ref=PCDISessionRef(
                session_id=record.thread_id,
                native_thread_id=record.effective_native_thread_id,
                task_status=str(record.session.session_state),
                available_intents=list(record.session.available_intents),
            ),
            governance_ref=PCDIGovernanceRef(
                goal_contract_version=goal_contract_version,
                goal_contract_readiness=goal_contract_readiness,
                pending_approval=has_pending_approval,
            ),
            approval_ref=PCDIApprovalRef(
                pending_approval_count=pending_approval_count,
                actionable_commands=approval_commands,
                latest_approval_reason=self._latest_approval_reason(
                    record,
                    has_pending_approval=has_pending_approval,
                ),
            ),
            completion_ref=PCDICompletionRef(
                task_completion_candidate="task_completed" in fact_codes,
                branch_completion_candidate="branch_goal_complete" in fact_codes,
                next_branch_available=next_work_item_seq is not None,
                target_work_item_seq=next_work_item_seq,
            ),
            error_ref=PCDIErrorRef(
                primary_fact_codes=list(record.progress.primary_fact_codes),
                blocker_fact_codes=blocker_fact_codes,
                latest_error_summary=latest_error_summary,
                recovery_candidate=bool(
                    {"context_critical", "repeat_failure", "stuck_no_progress"}.intersection(fact_codes)
                ),
            ),
            decision_scope_ref=self._decision_scope_ref(record),
            freshness_ref=PCDIFreshnessRef(
                snapshot_epoch=f"session-seq:{record.session_seq}",
                snapshot_version=record.fact_snapshot_version,
                snapshot_observed_at=record.last_refreshed_at,
            ),
            continuation_identity=continuation_identity,
            route_key=route_key,
            branch_switch_token=branch_switch_token,
        )

    @staticmethod
    def _normalize_project_execution_state(
        *,
        record_project_id: str,
        project_state: dict[str, object],
        checkpoint: dict[str, object],
        state_resume: dict[str, object],
    ) -> str:
        repo_project_name = str(project_state.get("project_name") or "").strip()
        repo_project_key = repo_project_name.lower()
        record_project_key = str(record_project_id or "").strip().lower()
        if repo_project_key and repo_project_key != record_project_key:
            return "active"

        explicit_state_candidates = (
            state_resume.get("project_execution_state"),
            project_state.get("project_execution_state"),
            project_state.get("execution_state"),
            checkpoint.get("project_execution_state"),
            checkpoint.get("execution_state"),
            project_state.get("status"),
            checkpoint.get("status"),
        )
        stage_candidates = (
            state_resume.get("current_stage"),
            project_state.get("current_stage"),
            checkpoint.get("current_stage"),
        )
        all_candidates = (*explicit_state_candidates, *stage_candidates)
        for candidate in all_candidates:
            normalized = str(candidate or "").strip().lower()
            if normalized in {
                "paused",
                "stopped",
                "branch_transition_in_progress",
                "completed",
                "archived",
                "close",
                "closed",
            }:
                if normalized == "close":
                    return "closed"
                return normalized
        for candidate in all_candidates:
            normalized = str(candidate or "").strip().lower()
            if normalized in {
                "execute",
                "decompose",
                "design",
                "refine",
                "init",
                "initialized",
                "active",
                "running",
            }:
                return "active"
        return "unknown"

    def _provider_precondition_block(
        self,
        *,
        record: PersistedSessionRecord,
        decision_context: ProjectContinuationDecisionInput,
    ) -> DecisionIntent | None:
        if decision_context.project_ref.project_execution_state != "active":
            return self._rule_based_intent(
                record=record,
                intent="observe_only",
                rationale="project is not active for autonomous continuation",
                evidence_codes=["project_execution_state_not_active"],
                remaining_work_hypothesis=["wait until project execution state returns to active"],
            )
        if decision_context.governance_ref.pending_approval:
            return self._rule_based_intent(
                record=record,
                intent="require_approval",
                rationale="pending approval blocks autonomous continuation",
                evidence_codes=["approval_pending"],
                remaining_work_hypothesis=["review the pending approval and decide approve or reject"],
            )
        if (
            decision_context.governance_ref.goal_contract_version == "goal-contract:unknown"
            or decision_context.governance_ref.goal_contract_readiness != "autonomous_ready"
        ):
            return self._rule_based_intent(
                record=record,
                rationale="goal contract is not ready for autonomous continuation",
                evidence_codes=["goal_contract_not_ready"],
                remaining_work_hypothesis=["refresh goal and branch contract before autonomous continuation"],
            )
        return None

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
        goal_coverage: str | None = None,
        remaining_work_hypothesis: list[str] | None = None,
        evidence_codes: list[str] | None = None,
        provider: str | None = None,
        model: str | None = None,
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
        if evidence_codes is None:
            evidence_codes = []
        if remaining_work_hypothesis is None:
            remaining_work_hypothesis = []
        if intent == "candidate_closure":
            evidence_codes = list(dict.fromkeys([*evidence_codes, "task_completed"]))
        elif intent == "require_approval":
            evidence_codes = list(dict.fromkeys([*evidence_codes, "approval_pending"]))
        elif intent == "propose_recovery":
            evidence_codes = list(dict.fromkeys([*evidence_codes, "recovery_candidate"]))
        elif intent == "propose_execute":
            evidence_codes = list(dict.fromkeys([*evidence_codes, "autonomous_continue_candidate"]))
        elif intent == "observe_only" and not evidence_codes:
            evidence_codes = ["no_actionable_fact"]
        progress_summary = (
            self.progress_summary_for_decision_context(record)
            if record is not None and intent == "propose_execute"
            else None
        )
        return DecisionIntent(
            intent=intent,
            rationale=rationale,
            action_arguments=self._rule_based_action_arguments(
                record=record,
                intent=intent,
                rationale=rationale,
                progress_summary=progress_summary,
            ),
            goal_coverage=goal_coverage,
            remaining_work_hypothesis=remaining_work_hypothesis,
            evidence_codes=evidence_codes,
            provider=provider or "resident_orchestrator",
            model=model or "rule-based-brain",
            provider_output_schema_ref=provider_output_schema_ref,
            degrade_reason=degrade_reason,
        )

    @staticmethod
    def _rule_based_action_arguments(
        *,
        record: PersistedSessionRecord | None,
        intent: str,
        rationale: str | None,
        progress_summary: str | None = None,
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
        summary = str(progress_summary or record.progress.summary or "current task").strip()
        summary = sanitize_session_summary(summary)
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
            decision_context = self._build_decision_context(record)
            blocked = self._provider_precondition_block(
                record=record,
                decision_context=decision_context,
            )
            if blocked is not None:
                return blocked
            try:
                return self._provider.decide(
                    record=record,
                    session_truth=self._session_truth(record),
                    memory_advisory_context=memory_context,
                    decision_context=decision_context,
                )
            except ProviderOutputSchemaError as exc:
                return self._rule_based_intent(
                    record=record,
                    intent=intent,
                    rationale=rationale,
                    evidence_codes=[
                        "provider_output_invalid",
                        f"provider_output_schema_ref:{exc.schema_ref}",
                    ],
                    provider_output_schema_ref=exc.schema_ref,
                    degrade_reason=exc.degrade_reason,
                )
            except Exception as exc:
                profile = self._provider._active_profile()
                degrade_reason = PROVIDER_UNAVAILABLE_DEGRADE_REASON
                evidence_codes = [
                    "provider_unavailable",
                    f"provider_error:{exc.__class__.__name__}",
                ]
                if isinstance(exc, httpx.HTTPStatusError):
                    status_code = int(exc.response.status_code)
                    degrade_reason = self._provider.degrade_reason_for_http_status(status_code)
                    evidence_codes.extend(
                        [
                            f"provider_http_status:{status_code}",
                            degrade_reason,
                        ]
                    )
                    if degrade_reason == PROVIDER_RATE_LIMITED_DEGRADE_REASON:
                        evidence_codes = [
                            code for code in evidence_codes if code != "provider_unavailable"
                        ]
                fact_codes = {
                    str(getattr(fact, "fact_code", "") or "").strip()
                    for fact in record.facts
                }
                fallback_to_resident = bool(
                    isinstance(exc, httpx.TimeoutException)
                    and "task_completed" not in fact_codes
                    and not isinstance(exc, httpx.HTTPStatusError)
                )
                return self._rule_based_intent(
                    record=record,
                    intent=intent,
                    rationale=rationale,
                    evidence_codes=evidence_codes,
                    provider=(
                        None
                        if fallback_to_resident
                        else (profile.name if profile is not None else None)
                    ),
                    model=(
                        None
                        if fallback_to_resident
                        else (str(profile.model or "") if profile is not None else None)
                    ),
                    degrade_reason=degrade_reason,
                )
        return self._rule_based_intent(record=record, intent=intent, rationale=rationale)
