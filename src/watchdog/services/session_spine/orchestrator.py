from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from watchdog.contracts.session_spine.enums import ActionStatus, Effect, ReplyCode
from watchdog.contracts.session_spine.models import FactRecord, WatchdogActionResult
from watchdog.services.brain.models import ApprovalReadSnapshot, DecisionTrace
from watchdog.services.brain.release_gate_evidence import (
    CertificationPacketCorpus,
    ReleaseGateEvidenceBundle,
    ShadowDecisionLedger,
)
from watchdog.services.brain.release_gate import (
    parse_release_gate_report,
    ReleaseGateEvaluator,
    ReleaseGateReport,
    ReleaseGateVerdict,
)
from watchdog.services.brain.replay import DecisionReplayService
from watchdog.services.brain.service import BrainDecisionService
from watchdog.services.brain.validator import DecisionValidator
from watchdog.services.actions.executor import (
    build_watchdog_action_from_decision,
    execute_canonical_decision,
)
from watchdog.services.approvals.service import CanonicalApprovalStore, materialize_canonical_approval
from watchdog.services.delivery.envelopes import (
    build_envelopes_for_decision,
    build_progress_summary_envelope,
    progress_summary_fingerprint,
)
from watchdog.services.delivery.store import DeliveryOutboxStore
from watchdog.services.future_worker.service import FutureWorkerExecutionService
from watchdog.services.goal_contract.models import GoalContractReadiness
from watchdog.services.goal_contract.service import GoalContractService
from watchdog.services.policy.decisions import PolicyDecisionStore
from watchdog.services.policy.engine import evaluate_persisted_session_policy
from watchdog.services.policy.rules import (
    DECISION_AUTO_EXECUTE_AND_NOTIFY,
    DECISION_BLOCK_AND_ALERT,
    DECISION_REQUIRE_USER_DECISION,
)
from watchdog.services.session_service.service import SessionService
from watchdog.services.session_spine.service import SessionSpineUpstreamError
from watchdog.services.session_spine.command_leases import CommandLeaseStore
from watchdog.services.session_spine.orchestration_store import ResidentOrchestrationStateStore
from watchdog.services.session_spine.store import PersistedSessionRecord, SessionSpineStore
from watchdog.services.a_client.client import AControlAgentClient
from watchdog.settings import Settings
from watchdog.storage.action_receipts import ActionReceiptStore, receipt_key_for_action


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _decision_facts(decision) -> list[FactRecord]:
    facts = decision.evidence.get("facts")
    if not isinstance(facts, list):
        return []
    return [FactRecord.model_validate(fact) for fact in facts if isinstance(fact, dict)]


@dataclass(frozen=True, slots=True)
class ResidentOrchestrationOutcome:
    project_id: str
    action_ref: str | None
    decision_result: str | None
    emitted_progress_summary: bool


@dataclass(frozen=True, slots=True)
class AutoExecuteCommandPlan:
    command_id: str
    claim_seq: int | None
    should_execute: bool


class ResidentOrchestrator:
    def __init__(
        self,
        *,
        settings: Settings,
        client: AControlAgentClient,
        session_spine_store: SessionSpineStore,
        decision_store: PolicyDecisionStore,
        approval_store: CanonicalApprovalStore,
        action_receipt_store: ActionReceiptStore,
        delivery_outbox_store: DeliveryOutboxStore,
        command_lease_store: CommandLeaseStore,
        state_store: ResidentOrchestrationStateStore,
        session_service: SessionService | None = None,
        future_worker_service: FutureWorkerExecutionService | None = None,
        brain_service: BrainDecisionService | None = None,
        replay_service: DecisionReplayService | None = None,
        decision_validator: DecisionValidator | None = None,
        release_gate_evaluator: ReleaseGateEvaluator | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._session_spine_store = session_spine_store
        self._decision_store = decision_store
        self._approval_store = approval_store
        self._action_receipt_store = action_receipt_store
        self._delivery_outbox_store = delivery_outbox_store
        self._command_lease_store = command_lease_store
        self._state_store = state_store
        self._session_service = session_service
        self._future_worker_service = future_worker_service
        self._brain_service = brain_service or BrainDecisionService()
        self._replay_service = replay_service or DecisionReplayService()
        self._decision_validator = decision_validator or DecisionValidator()
        self._release_gate_evaluator = release_gate_evaluator or ReleaseGateEvaluator()

    @staticmethod
    def _command_id_for_decision(decision) -> str:
        return f"command:{decision.decision_id}"

    @staticmethod
    def _decision_correlation_id(decision) -> str:
        return f"corr:decision:{decision.decision_id}"

    @staticmethod
    def _decision_related_ids(decision, **extra: str | None) -> dict[str, str]:
        related_ids = {
            "decision_id": decision.decision_id,
            "action_ref": decision.action_ref,
        }
        if decision.approval_id:
            related_ids["approval_id"] = decision.approval_id
        for key, value in extra.items():
            if value:
                related_ids[key] = value
        return related_ids

    def _record_decision_lifecycle(self, decision) -> None:
        if self._session_service is None:
            return
        correlation_id = self._decision_correlation_id(decision)
        decision_evidence = decision.evidence if isinstance(decision.evidence, dict) else {}
        decision_trace = decision_evidence.get("decision_trace")
        validator_verdict = decision_evidence.get("validator_verdict")
        release_gate_verdict = decision_evidence.get("release_gate_verdict")
        self._session_service.record_event(
            event_type="decision_proposed",
            project_id=decision.project_id,
            session_id=decision.session_id,
            correlation_id=correlation_id,
            related_ids=self._decision_related_ids(decision),
            payload={
                "trigger": decision.trigger,
                "action_ref": decision.action_ref,
                "brain_intent": decision.brain_intent,
                "runtime_disposition": decision.runtime_disposition,
                "policy_version": decision.policy_version,
                "fact_snapshot_version": decision.fact_snapshot_version,
                "decision_trace_ref": (
                    decision_trace.get("trace_id") if isinstance(decision_trace, dict) else None
                ),
            },
        )
        self._session_service.record_event(
            event_type="decision_validated",
            project_id=decision.project_id,
            session_id=decision.session_id,
            correlation_id=correlation_id,
            causation_id=decision.decision_id,
            related_ids=self._decision_related_ids(decision),
            payload={
                "decision_result": decision.decision_result,
                "brain_intent": decision.brain_intent,
                "runtime_disposition": decision.runtime_disposition,
                "risk_class": decision.risk_class,
                "decision_reason": decision.decision_reason,
                "matched_policy_rules": list(decision.matched_policy_rules),
                "decision_trace": decision_trace,
                "validator_verdict": validator_verdict,
                "release_gate_verdict": release_gate_verdict,
            },
        )

    def _record_command_created(self, decision, *, command_id: str) -> None:
        if self._session_service is None:
            return
        self._session_service.record_event(
            event_type="command_created",
            project_id=decision.project_id,
            session_id=decision.session_id,
            correlation_id=self._decision_correlation_id(decision),
            causation_id=decision.decision_id,
            related_ids=self._decision_related_ids(decision, command_id=command_id),
            payload={
                "command_id": command_id,
                "action_ref": decision.action_ref,
                "decision_result": decision.decision_result,
            },
        )

    def _lease_expires_at(self, *, now: datetime) -> str:
        expiry = now + timedelta(
            seconds=max(float(self._settings.resident_orchestrator_interval_seconds), 30.0)
        )
        return expiry.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def _plan_auto_execute_command(
        self,
        decision,
        *,
        now: datetime,
    ) -> AutoExecuteCommandPlan:
        command_id = self._command_id_for_decision(decision)
        current = self._command_lease_store.get_command(command_id)
        if current is None or current.status == "requeued":
            claim = self._command_lease_store.claim_command(
                command_id=command_id,
                session_id=decision.session_id,
                worker_id="resident_orchestrator",
                claimed_at=now.astimezone(UTC).replace(microsecond=0).isoformat().replace(
                    "+00:00",
                    "Z",
                ),
                lease_expires_at=self._lease_expires_at(now=now),
            )
            return AutoExecuteCommandPlan(
                command_id=command_id,
                claim_seq=claim.claim_seq,
                should_execute=True,
            )
        if current.status == "claimed" and current.worker_id == "resident_orchestrator":
            self._command_lease_store.renew_lease(
                command_id=command_id,
                worker_id="resident_orchestrator",
                claim_seq=current.claim_seq,
                renewed_at=now.astimezone(UTC).replace(microsecond=0).isoformat().replace(
                    "+00:00",
                    "Z",
                ),
                lease_expires_at=self._lease_expires_at(now=now),
            )
        return AutoExecuteCommandPlan(
            command_id=command_id,
            claim_seq=None,
            should_execute=False,
        )

    def _record_command_terminal_result(
        self,
        *,
        decision,
        result: WatchdogActionResult,
        command_id: str,
        claim_seq: int | None,
        now: datetime,
    ) -> None:
        if claim_seq is None:
            return
        payload = self._command_terminal_payload(
            decision=decision,
            command_id=command_id,
            claim_seq=claim_seq,
            result=result,
        )
        self._command_lease_store.record_terminal_result(
            command_id=command_id,
            worker_id="resident_orchestrator",
            claim_seq=claim_seq,
            result_type=(
                "command_executed"
                if result.action_status == ActionStatus.COMPLETED
                else "command_failed"
            ),
            occurred_at=now.astimezone(UTC).replace(microsecond=0).isoformat().replace(
                "+00:00",
                "Z",
            ),
            payload=payload,
        )

    @staticmethod
    def _artifact_ref(prefix: str, identifier: str) -> str:
        return f"{prefix}:{identifier}"

    @staticmethod
    def _decision_evidence_map(decision) -> dict[str, Any]:
        return decision.evidence if isinstance(decision.evidence, dict) else {}

    @staticmethod
    def _decision_trace_ref(decision) -> str | None:
        evidence = decision.evidence if isinstance(decision.evidence, dict) else {}
        trace = evidence.get("decision_trace")
        if not isinstance(trace, dict):
            return None
        trace_id = trace.get("trace_id")
        return trace_id if isinstance(trace_id, str) and trace_id else None

    def _decision_relevant_session_events(self, decision, *, command_id: str):
        if self._session_service is None:
            return []
        decision_trace_ref = self._decision_trace_ref(decision)
        return [
            event
            for event in self._session_service.list_events(session_id=decision.session_id)
            if event.related_ids.get("decision_id") == decision.decision_id
            or (
                event.event_type == "command_created"
                and event.related_ids.get("command_id") == command_id
            )
            or (
                decision_trace_ref is not None
                and event.event_type.startswith("future_worker_")
                and (
                    event.related_ids.get("decision_trace_ref") == decision_trace_ref
                    or event.payload.get("decision_trace_ref") == decision_trace_ref
                )
            )
        ]

    def _command_terminal_replay_summary(self, decision, *, command_id: str) -> dict[str, Any]:
        evidence = self._decision_evidence_map(decision)
        trace = evidence.get("decision_trace")
        if not isinstance(trace, dict):
            return {
                "packet_replay": self._replay_service.packet_replay(
                    packet_input=None,
                    frozen_contract={},
                    current_contract={},
                ).model_dump(mode="json"),
                "session_semantic_replay": self._replay_service.session_semantic_replay(
                    session_events=[],
                    required_event_ids=[],
                ).model_dump(mode="json"),
            }
        runtime_contract = self._release_gate_runtime_contract(
            trace=DecisionTrace.model_validate(trace)
        )
        relevant_events = self._decision_relevant_session_events(decision, command_id=command_id)
        required_event_ids = [
            event.event_id
            for event in relevant_events
            if event.event_type in {
                "decision_proposed",
                "decision_validated",
                "command_created",
            }
            or event.event_type.startswith("future_worker_")
        ]
        return {
            "packet_replay": self._replay_service.packet_replay(
                packet_input={
                    "decision_trace_ref": trace.get("trace_id"),
                    "goal_contract_version": trace.get("goal_contract_version"),
                    "action_ref": decision.action_ref,
                },
                frozen_contract=runtime_contract,
                current_contract=runtime_contract,
            ).model_dump(mode="json"),
            "session_semantic_replay": self._replay_service.session_semantic_replay(
                session_events=[{"event_id": event.event_id} for event in relevant_events],
                required_event_ids=required_event_ids,
            ).model_dump(mode="json"),
        }

    @staticmethod
    def _future_worker_state_event(event) -> bool:
        return event.event_type in {
            "future_worker_requested",
            "future_worker_started",
            "future_worker_completed",
            "future_worker_failed",
            "future_worker_cancelled",
            "future_worker_result_consumed",
            "future_worker_result_rejected",
        }

    def _consume_completed_future_worker_results(
        self,
        decision,
        *,
        command_id: str,
        occurred_at: str,
    ) -> list[str]:
        if self._session_service is None or self._future_worker_service is None:
            return []
        relevant_events = self._decision_relevant_session_events(decision, command_id=command_id)
        grouped_events: dict[str, list[object]] = {}
        for event in relevant_events:
            if not event.event_type.startswith("future_worker_"):
                continue
            worker_task_ref = str(event.related_ids.get("worker_task_ref") or "").strip()
            if not worker_task_ref:
                continue
            grouped_events.setdefault(worker_task_ref, []).append(event)

        consumed_refs: list[str] = []
        for worker_task_ref, events in grouped_events.items():
            ordered_events = sorted(
                events,
                key=lambda event: (
                    event.log_seq or 0,
                    _parse_iso(event.occurred_at) or datetime.min.replace(tzinfo=UTC),
                    event.event_id,
                ),
            )
            last_state_event = next(
                (
                    event
                    for event in reversed(ordered_events)
                    if self._future_worker_state_event(event)
                ),
                None,
            )
            if last_state_event is None or last_state_event.event_type != "future_worker_completed":
                continue
            self._future_worker_service.consume_result(
                worker_task_ref=worker_task_ref,
                project_id=decision.project_id,
                parent_session_id=decision.session_id,
                consumed_by_decision_id=decision.decision_id,
                occurred_at=occurred_at,
            )
            consumed_refs.append(worker_task_ref)
        return consumed_refs

    def _command_terminal_metrics_summary(
        self,
        decision,
        *,
        claim_seq: int,
        result: WatchdogActionResult,
    ) -> dict[str, Any]:
        evidence = self._decision_evidence_map(decision)
        release_gate_verdict = evidence.get("release_gate_verdict")
        return {
            "decision_result": decision.decision_result,
            "action_status": str(result.action_status),
            "reply_code": str(result.reply_code) if result.reply_code is not None else None,
            "claim_seq": claim_seq,
            "auto_execute_total": 1,
            "delivery_enqueue_expected": int(result.action_status == ActionStatus.COMPLETED),
            "release_gate_status": (
                str(release_gate_verdict.get("status"))
                if isinstance(release_gate_verdict, dict)
                else "unknown"
            ),
        }

    def _command_terminal_payload(
        self,
        *,
        decision,
        command_id: str,
        claim_seq: int,
        result: WatchdogActionResult,
    ) -> dict[str, Any]:
        evidence = self._decision_evidence_map(decision)
        trace = evidence.get("decision_trace")
        release_gate_verdict = evidence.get("release_gate_verdict")
        bundle = evidence.get("release_gate_evidence_bundle")
        action = build_watchdog_action_from_decision(decision)
        completion_evidence_ref = self._artifact_ref(
            "receipt",
            receipt_key_for_action(action),
        )
        replay_ref = self._artifact_ref("replay", decision.decision_id)
        metrics_ref = self._artifact_ref("metrics", decision.decision_id)
        payload: dict[str, Any] = {
            "completion_evidence_ref": completion_evidence_ref,
            "completion_judgment": {
                "status": (
                    "completed" if result.action_status == ActionStatus.COMPLETED else "failed"
                ),
                "action_status": str(result.action_status),
                "reply_code": str(result.reply_code) if result.reply_code is not None else None,
                "decision_trace_ref": (
                    trace.get("trace_id") if isinstance(trace, dict) else None
                ),
                "goal_contract_version": (
                    trace.get("goal_contract_version") if isinstance(trace, dict) else None
                ),
                "receipt_ref": completion_evidence_ref,
            },
            "replay_ref": replay_ref,
            "replay_summary": self._command_terminal_replay_summary(
                decision,
                command_id=command_id,
            ),
            "metrics_ref": metrics_ref,
            "metrics_summary": self._command_terminal_metrics_summary(
                decision,
                claim_seq=claim_seq,
                result=result,
            ),
        }
        if isinstance(release_gate_verdict, dict):
            payload["release_gate_verdict"] = release_gate_verdict
        if isinstance(bundle, dict):
            payload["release_gate_evidence_bundle"] = bundle
        return payload

    def _cache_auto_continue_control_link_error(
        self,
        decision,
        exc: SessionSpineUpstreamError,
    ) -> bool:
        error = exc.error if isinstance(exc.error, dict) else {}
        if decision.action_ref != "continue_session":
            return False
        if str(error.get("code") or "") != "CONTROL_LINK_ERROR":
            return False
        action = build_watchdog_action_from_decision(decision)
        self._action_receipt_store.put(
            receipt_key_for_action(action),
            WatchdogActionResult(
                action_code=action.action_code,
                project_id=action.project_id,
                approval_id=str(action.arguments.get("approval_id") or "") or None,
                idempotency_key=action.idempotency_key,
                action_status=ActionStatus.ERROR,
                effect=Effect.NOOP,
                reply_code=ReplyCode.CONTROL_LINK_ERROR,
                message=str(error.get("message") or "resident continue_session failed"),
                facts=_decision_facts(decision),
            ),
        )
        return True

    def _is_auto_continue_in_cooldown(
        self,
        project_id: str,
        *,
        now: datetime,
    ) -> bool:
        checkpoint = self._state_store.get_auto_continue_checkpoint(project_id)
        if checkpoint is None:
            return False
        last_auto_continue = _parse_iso(checkpoint.last_auto_continue_at)
        if last_auto_continue is None:
            return False
        elapsed = (now - last_auto_continue.astimezone(UTC)).total_seconds()
        return elapsed < max(self._settings.auto_continue_cooldown_seconds, 0.0)

    def _record_auto_continue(
        self,
        project_id: str,
        *,
        now: datetime,
    ) -> None:
        created_at = now.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        self._state_store.put_auto_continue_checkpoint(
            project_id=project_id,
            last_auto_continue_at=created_at,
        )

    def _goal_contract_readiness_for_record(
        self,
        record: PersistedSessionRecord,
    ) -> GoalContractReadiness | None:
        if self._session_service is None:
            return None
        service = GoalContractService(self._session_service)
        contract = service.get_current_contract(
            project_id=record.project_id,
            session_id=record.thread_id,
        )
        if contract is None:
            return None
        return service.evaluate_readiness(
            project_id=record.project_id,
            session_id=record.thread_id,
        )

    def _goal_contract_version_for_record(self, record: PersistedSessionRecord) -> str:
        if self._session_service is None:
            return "goal-contract:unknown"
        service = GoalContractService(self._session_service)
        contract = service.get_current_contract(
            project_id=record.project_id,
            session_id=record.thread_id,
        )
        if contract is None:
            return "goal-contract:unknown"
        return contract.version

    def _evaluate_brain_intent(self, record: PersistedSessionRecord):
        return self._brain_service.evaluate_session(
            record=record,
        )

    @staticmethod
    def _action_ref_for_brain_intent(
        record: PersistedSessionRecord,
        brain_intent: str,
    ) -> str | None:
        if brain_intent in {"propose_execute", "require_approval", "suggest_only", "observe_only"}:
            if brain_intent == "observe_only" and not record.facts:
                return None
            return "continue_session"
        if brain_intent == "propose_recovery":
            return "execute_recovery"
        if brain_intent == "candidate_closure":
            return "post_operator_guidance"
        return None

    @staticmethod
    def _candidate_closure_action_args(record: PersistedSessionRecord) -> dict[str, object]:
        return {
            "message": (
                "Review completion candidate for "
                f"{record.project_id}: {record.progress.summary or 'session reached done state'}"
            ),
            "reason_code": "candidate_closure",
            "stuck_level": 0,
        }

    def _release_gate_runtime_contract(self, *, trace: DecisionTrace) -> dict[str, str]:
        return self._settings.build_runtime_contract(
            provider=trace.provider,
            model=trace.model,
            prompt_schema_ref=trace.prompt_schema_ref,
            output_schema_ref=trace.output_schema_ref,
        )

    def _load_release_gate_report(self) -> ReleaseGateReport | None:
        report_path = self._settings.release_gate_report_path
        if not report_path:
            return None
        payload = json.loads(Path(report_path).read_text(encoding="utf-8"))
        return parse_release_gate_report(payload)

    @staticmethod
    def _release_gate_now(now: datetime) -> str:
        return now.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _report_load_failure_verdict(
        *,
        trace: DecisionTrace,
        approval_read: ApprovalReadSnapshot | None,
        input_hash: str,
    ) -> ReleaseGateVerdict:
        approval_read_ref = (
            f"approval:event:{approval_read.approval_event_id}"
            if approval_read is not None
            else "approval:none"
        )
        return ReleaseGateVerdict(
            status="degraded",
            decision_trace_ref=trace.trace_id,
            approval_read_ref=approval_read_ref,
            degrade_reason="report_load_failed",
            report_id="report:load_failed",
            report_hash="sha256:load_failed",
            input_hash=input_hash,
        )

    def _decision_evidence_for_intent(
        self,
        record: PersistedSessionRecord,
        *,
        brain_intent,
        action_ref: str,
        goal_contract_readiness: GoalContractReadiness | None,
        now: datetime,
    ) -> dict[str, object]:
        evidence: dict[str, object] = {"brain_rationale": brain_intent.rationale}
        decision_trace = self._decision_trace_for_intent(
            record,
            brain_intent=brain_intent.intent,
            action_ref=action_ref,
            goal_contract_version=self._goal_contract_version_for_record(record),
        )
        validator_verdict = self._decision_validator.validate(
            brain_intent=brain_intent.intent,
            goal_contract_readiness=goal_contract_readiness,
            memory_conflict_detected=self._session_has_event(
                session_id=record.thread_id,
                event_type="memory_conflict_detected",
            ),
            memory_unavailable=self._session_has_event(
                session_id=record.thread_id,
                event_type="memory_unavailable_degraded",
            ),
        )
        approval_read = self._approval_read_snapshot_for_session(record)
        report = None
        verdict = None
        if self._settings.release_gate_report_path:
            try:
                report = self._load_release_gate_report()
            except (OSError, ValueError, json.JSONDecodeError, ValidationError):
                verdict = self._report_load_failure_verdict(
                    trace=decision_trace,
                    approval_read=approval_read,
                    input_hash=self._release_gate_evaluator._input_hash_for_trace(decision_trace),
                )
        release_gate_verdict = self._release_gate_evaluator.evaluate(
            brain_intent=brain_intent.intent,
            trace=decision_trace,
            validator_verdict=validator_verdict,
            approval_read=approval_read,
            verdict=verdict,
            report=report,
            runtime_contract=self._release_gate_runtime_contract(trace=decision_trace),
            now=self._release_gate_now(now),
        )
        evidence["decision_trace"] = decision_trace.model_dump(mode="json")
        evidence["validator_verdict"] = validator_verdict.model_dump(mode="json")
        evidence["release_gate_verdict"] = release_gate_verdict.model_dump(mode="json")
        if self._settings.release_gate_report_path:
            evidence["release_gate_evidence_bundle"] = ReleaseGateEvidenceBundle(
                certification_packet_corpus=CertificationPacketCorpus(
                    artifact_ref=self._settings.release_gate_certification_packet_corpus_ref
                ),
                shadow_decision_ledger=ShadowDecisionLedger(
                    artifact_ref=self._settings.release_gate_shadow_decision_ledger_ref
                ),
                release_gate_report_ref=self._settings.release_gate_report_path,
            ).model_dump(mode="json")
        if brain_intent.intent == "candidate_closure":
            evidence["requested_action_args"] = self._candidate_closure_action_args(record)
        return evidence

    def _record_and_store_decision(self, decision):
        existing = self._decision_store.get(decision.decision_key)
        if existing is not None:
            if not self._decision_has_runtime_gate(existing):
                self._record_decision_lifecycle(decision)
                return self._decision_store.update(decision)
            if not self._has_canonical_decision_events(existing):
                self._record_decision_lifecycle(existing)
            return existing
        self._record_decision_lifecycle(decision)
        return self._decision_store.put(decision)

    @staticmethod
    def _decision_allows_auto_execute(decision) -> bool:
        if decision.brain_intent not in (None, "propose_execute"):
            return False
        evidence = decision.evidence if isinstance(decision.evidence, dict) else {}
        validator_verdict = evidence.get("validator_verdict")
        if not isinstance(validator_verdict, dict) or validator_verdict.get("status") != "pass":
            return False
        release_gate_verdict = evidence.get("release_gate_verdict")
        if not isinstance(release_gate_verdict, dict) or release_gate_verdict.get("status") != "pass":
            return False
        return True

    def _has_canonical_decision_events(self, decision) -> bool:
        if self._session_service is None:
            return True
        events = self._session_service.list_events(
            session_id=decision.session_id,
            correlation_id=self._decision_correlation_id(decision),
        )
        event_types = {event.event_type for event in events}
        return {"decision_proposed", "decision_validated"}.issubset(event_types)

    @staticmethod
    def _decision_has_runtime_gate(decision) -> bool:
        evidence = decision.evidence if isinstance(decision.evidence, dict) else {}
        return isinstance(evidence.get("validator_verdict"), dict) and isinstance(
            evidence.get("release_gate_verdict"), dict
        )

    def _session_has_event(self, *, session_id: str, event_type: str) -> bool:
        if self._session_service is None:
            return False
        events = self._session_service.list_events(
            session_id=session_id,
            event_type=event_type,
        )
        return bool(events)

    def _approval_read_snapshot_for_session(
        self,
        record: PersistedSessionRecord,
    ) -> ApprovalReadSnapshot | None:
        approvals = sorted(
            (
                approval
                for approval in self._approval_store.list_records()
                if approval.session_id == record.thread_id
                and approval.project_id == record.project_id
                and approval.status == "pending"
            ),
            key=lambda approval: approval.created_at,
        )
        if not approvals:
            return None
        approval = approvals[-1]
        approval_events = self._session_service.list_events(
            session_id=record.thread_id,
            event_type="approval_requested",
        ) if self._session_service is not None else []
        matching_event = next(
            (
                event
                for event in reversed(approval_events)
                if event.related_ids.get("approval_id") == approval.approval_id
            ),
            None,
        )
        return ApprovalReadSnapshot(
            approval_event_id=matching_event.event_id if matching_event is not None else approval.approval_id,
            approval_id=approval.approval_id,
            status=approval.status,
            requested_action=approval.requested_action,
            session_id=approval.session_id,
            project_id=approval.project_id,
            fact_snapshot_version=approval.fact_snapshot_version,
            goal_contract_version=approval.goal_contract_version or "goal-contract:unknown",
            expires_at=approval.expires_at or "approval:no-expiry",
            decided_by=approval.decided_by,
            log_seq=matching_event.log_seq if matching_event is not None else None,
        )

    def _decision_trace_for_intent(
        self,
        record: PersistedSessionRecord,
        *,
        brain_intent: str,
        action_ref: str,
        goal_contract_version: str,
    ) -> DecisionTrace:
        event_cursor = None
        if self._session_service is not None:
            session_events = self._session_service.list_events(session_id=record.thread_id)
            if session_events:
                last_log_seq = max((event.log_seq or 0) for event in session_events)
                event_cursor = f"log_seq:{last_log_seq}"
        payload = {
            "project_id": record.project_id,
            "session_id": record.thread_id,
            "fact_snapshot_version": record.fact_snapshot_version,
            "brain_intent": brain_intent,
            "action_ref": action_ref,
            "goal_contract_version": goal_contract_version,
            "session_event_cursor": event_cursor,
        }
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        trace_id = f"trace:{hashlib.sha256(serialized.encode('utf-8')).hexdigest()[:16]}"
        return DecisionTrace(
            trace_id=trace_id,
            session_event_cursor=event_cursor,
            goal_contract_version=goal_contract_version,
            policy_ruleset_hash=f"sha256:{hashlib.sha256(b'policy-v1').hexdigest()[:16]}",
            memory_packet_input_ids=[],
            memory_packet_input_hashes=[],
            provider="resident_orchestrator",
            model="rule-based-brain",
            prompt_schema_ref="prompt:none",
            output_schema_ref="schema:decision-trace-v1",
            approval_read=self._approval_read_snapshot_for_session(record),
        )

    def orchestrate_all(self, *, now: datetime | None = None) -> list[ResidentOrchestrationOutcome]:
        current = now or datetime.now(UTC)
        self._command_lease_store.expire_and_requeue_expired(
            now=current.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            reason="resident_orchestrator_tick",
        )
        return [
            self._orchestrate_record(record, now=current)
            for record in self._session_spine_store.list_records()
        ]

    def _orchestrate_record(
        self,
        record: PersistedSessionRecord,
        *,
        now: datetime,
    ) -> ResidentOrchestrationOutcome:
        brain_intent = self._evaluate_brain_intent(record)
        action_ref = self._action_ref_for_brain_intent(record, brain_intent.intent)
        decision_result: str | None = None
        goal_contract_readiness = self._goal_contract_readiness_for_record(record)

        if (
            brain_intent.intent == "propose_execute"
            and action_ref == "continue_session"
            and self._is_auto_continue_in_cooldown(
            record.project_id,
            now=now,
            )
        ):
            action_ref = None

        if action_ref is not None:
            intent_evidence = self._decision_evidence_for_intent(
                record,
                brain_intent=brain_intent,
                action_ref=action_ref,
                goal_contract_readiness=goal_contract_readiness,
                now=now,
            )
            decision = evaluate_persisted_session_policy(
                record,
                action_ref=action_ref,
                trigger="resident_orchestrator",
                brain_intent=brain_intent.intent,
                validator_verdict=(
                    intent_evidence.get("validator_verdict")
                    if isinstance(intent_evidence.get("validator_verdict"), dict)
                    else None
                ),
                release_gate_verdict=(
                    intent_evidence.get("release_gate_verdict")
                    if isinstance(intent_evidence.get("release_gate_verdict"), dict)
                    else None
                ),
                goal_contract_readiness=goal_contract_readiness,
            )
            decision = decision.model_copy(
                update={
                    "evidence": {
                        **intent_evidence,
                        **decision.evidence,
                    }
                }
            )
            decision = self._record_and_store_decision(decision)
            decision_result = decision.decision_result
            if decision.decision_result != DECISION_REQUIRE_USER_DECISION:
                supersede_reason = (
                    "approval_superseded_by_decision "
                    f"decision_id={decision.decision_id} "
                    f"result={decision.decision_result} "
                    f"action={decision.action_ref} "
                    f"snapshot={decision.fact_snapshot_version}"
                )
                superseded = self._approval_store.supersede_pending_records(
                    session_id=decision.session_id,
                    project_id=decision.project_id,
                    fact_snapshot_version=decision.fact_snapshot_version,
                    reason=supersede_reason,
                )
                if superseded:
                    updated_at = now.astimezone(UTC).replace(microsecond=0).isoformat().replace(
                        "+00:00",
                        "Z",
                    )
                    self._delivery_outbox_store.supersede_records(
                        envelope_reasons={
                            approval.envelope_id: supersede_reason for approval in superseded
                        },
                        updated_at=updated_at,
            )
            if (
                decision.decision_result == DECISION_AUTO_EXECUTE_AND_NOTIFY
                and self._decision_allows_auto_execute(decision)
            ):
                self._record_command_created(
                    decision,
                    command_id=self._command_id_for_decision(decision),
                )
                command_plan = self._plan_auto_execute_command(decision, now=now)
                if command_plan.should_execute:
                    try:
                        result = execute_canonical_decision(
                            decision,
                            settings=self._settings,
                            client=self._client,
                            receipt_store=self._action_receipt_store,
                            session_service=self._session_service,
                        )
                        if result.action_status == ActionStatus.COMPLETED:
                            self._consume_completed_future_worker_results(
                                decision,
                                command_id=command_plan.command_id,
                                occurred_at=now.astimezone(UTC)
                                .replace(microsecond=0)
                                .isoformat()
                                .replace("+00:00", "Z"),
                            )
                        self._record_command_terminal_result(
                            decision=decision,
                            result=result,
                            command_id=command_plan.command_id,
                            claim_seq=command_plan.claim_seq,
                            now=now,
                        )
                        if (
                            decision.action_ref == "continue_session"
                            and result.action_status == ActionStatus.COMPLETED
                        ):
                            self._record_auto_continue(record.project_id, now=now)
                        if result.action_status == ActionStatus.COMPLETED:
                            self._delivery_outbox_store.enqueue_envelopes(
                                build_envelopes_for_decision(decision)
                            )
                    except SessionSpineUpstreamError as exc:
                        action = build_watchdog_action_from_decision(decision)
                        self._record_command_terminal_result(
                            decision=decision,
                            result=WatchdogActionResult(
                                action_code=action.action_code,
                                project_id=action.project_id,
                                approval_id=str(action.arguments.get("approval_id") or "") or None,
                                idempotency_key=action.idempotency_key,
                                action_status=ActionStatus.ERROR,
                                effect=Effect.NOOP,
                                reply_code=ReplyCode.CONTROL_LINK_ERROR,
                                message=str(exc),
                                facts=_decision_facts(decision),
                            ),
                            command_id=command_plan.command_id,
                            claim_seq=command_plan.claim_seq,
                            now=now,
                        )
                        if not self._cache_auto_continue_control_link_error(decision, exc):
                            raise
            elif decision.decision_result == DECISION_REQUIRE_USER_DECISION:
                materialize_canonical_approval(
                    decision,
                    approval_store=self._approval_store,
                    delivery_outbox_store=self._delivery_outbox_store,
                    session_service=self._session_service,
                )
            elif decision.decision_result == DECISION_BLOCK_AND_ALERT:
                self._delivery_outbox_store.enqueue_envelopes(build_envelopes_for_decision(decision))

        emitted_progress_summary = self._maybe_emit_progress_summary(record, now=now)
        return ResidentOrchestrationOutcome(
            project_id=record.project_id,
            action_ref=action_ref,
            decision_result=decision_result,
            emitted_progress_summary=emitted_progress_summary,
        )

    def _maybe_emit_progress_summary(
        self,
        record: PersistedSessionRecord,
        *,
        now: datetime,
    ) -> bool:
        progress_at = _parse_iso(record.progress.last_progress_at)
        if progress_at is None:
            return False
        age_seconds = (now - progress_at.astimezone(UTC)).total_seconds()
        if age_seconds > max(self._settings.progress_summary_max_age_seconds, 0.0):
            return False
        fingerprint = progress_summary_fingerprint(record)
        checkpoint = self._state_store.get_progress_checkpoint(record.project_id)
        if checkpoint is not None and checkpoint.progress_fingerprint == fingerprint:
            return False
        if checkpoint is not None:
            last_sent = _parse_iso(checkpoint.last_progress_notification_at)
            if last_sent is not None:
                elapsed = (now - last_sent.astimezone(UTC)).total_seconds()
                if elapsed < max(self._settings.progress_summary_interval_seconds, 0.0):
                    return False
        created_at = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        envelope = build_progress_summary_envelope(
            record,
            created_at=created_at,
            progress_fingerprint=fingerprint,
        )
        self._delivery_outbox_store.enqueue_envelopes([envelope])
        self._state_store.put_progress_checkpoint(
            project_id=record.project_id,
            progress_fingerprint=fingerprint,
            last_progress_notification_at=created_at,
        )
        return True
