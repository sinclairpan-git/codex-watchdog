from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError

from watchdog.contracts.session_spine.enums import ActionStatus, Effect, ReplyCode
from watchdog.contracts.session_spine.models import ApprovalProjection, FactRecord, WatchdogActionResult
from watchdog.services.brain.models import ApprovalReadSnapshot, DecisionIntent, DecisionTrace
from watchdog.services.brain.release_gate import (
    ReleaseGateEvaluator,
    ReleaseGateVerdict,
)
from watchdog.services.brain.release_gate_loading import load_release_gate_artifacts
from watchdog.services.brain.release_gate_read_contract import (
    read_release_gate_decision_evidence,
)
from watchdog.services.brain.release_gate_write_contract import (
    build_release_gate_runtime_evidence,
)
from watchdog.services.session_spine.event_gate_payload_contract import (
    build_session_event_gate_payload,
)
from watchdog.services.brain.replay import DecisionReplayService
from watchdog.services.brain.service import BrainDecisionService
from watchdog.services.brain.validator import (
    DecisionValidator,
    validate_managed_action_arguments,
)
from watchdog.services.brain.validator_read_contract import (
    read_validator_decision_evidence,
)
from watchdog.services.actions.executor import (
    build_watchdog_action_from_decision,
    execute_canonical_decision,
)
from watchdog.services.approvals.service import (
    CanonicalApprovalRecord,
    CanonicalApprovalStore,
    materialize_canonical_approval,
    requested_action_args_from_decision,
)
from watchdog.services.delivery.envelopes import (
    build_envelopes_for_decision,
    build_progress_summary_envelope,
    progress_summary_fingerprint,
)
from watchdog.services.delivery.store import DeliveryOutboxStore
from watchdog.services.future_worker.models import FutureWorkerExecutionRequest
from watchdog.services.future_worker.service import FutureWorkerExecutionService
from watchdog.services.goal_contract.models import GoalContractReadiness
from watchdog.services.goal_contract.service import GoalContractService
from watchdog.services.policy.decisions import CanonicalDecisionRecord, PolicyDecisionStore
from watchdog.services.policy.engine import evaluate_persisted_session_policy
from watchdog.services.policy.rules import (
    DECISION_AUTO_EXECUTE_AND_NOTIFY,
    DECISION_BLOCK_AND_ALERT,
    DECISION_REQUIRE_USER_DECISION,
    POLICY_VERSION,
)
from watchdog.services.resident_experts.service import ResidentExpertRuntimeService
from watchdog.services.session_service.service import SessionService
from watchdog.services.session_spine.service import SessionSpineUpstreamError
from watchdog.services.session_spine.command_leases import CommandLeaseStore
from watchdog.services.session_spine.orchestration_store import ResidentOrchestrationStateStore
from watchdog.services.session_spine.store import PersistedSessionRecord, SessionSpineStore
from watchdog.services.a_client.client import AControlAgentClient
from watchdog.settings import Settings
from watchdog.storage.action_receipts import ActionReceiptStore, receipt_key_for_action

logger = logging.getLogger(__name__)
_CANONICAL_APPROVAL_DECISION_OPTIONS = ["approve", "reject", "execute_action"]


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


def _json_fingerprint(payload: object) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _fact_snapshot_order(value: str | None) -> tuple[int, str]:
    if not value:
        return (-1, "")
    match = re.fullmatch(r"fact-v(\d+)", value)
    if match is None:
        return (2**31 - 1, str(value))
    return (int(match.group(1)), str(value))


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
    current_status: str | None = None


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
        resident_expert_runtime_service: ResidentExpertRuntimeService | None = None,
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
        self._brain_service = brain_service or BrainDecisionService(
            session_service=self._session_service,
        )
        self._replay_service = replay_service or DecisionReplayService()
        self._decision_validator = decision_validator or DecisionValidator()
        self._release_gate_evaluator = release_gate_evaluator or ReleaseGateEvaluator()
        self._resident_expert_runtime_service = resident_expert_runtime_service

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
        self._session_service.record_event_once(
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
        self._session_service.record_event_once(
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
                "why_not_escalated": decision.why_not_escalated,
                "why_escalated": decision.why_escalated,
                "uncertainty_reasons": list(decision.uncertainty_reasons),
                "decision_trace": decision_trace,
                "release_gate_evidence_fingerprint": (
                    _json_fingerprint(decision_evidence.get("release_gate_evidence_bundle"))
                    if decision_evidence.get("release_gate_evidence_bundle") is not None
                    else None
                ),
                **build_session_event_gate_payload(
                    evidence=decision_evidence,
                    include_validator=True,
                    include_bundle=False,
                ),
            },
        )

    def _record_command_created(self, decision, *, command_id: str) -> None:
        if self._session_service is None:
            return
        self._session_service.record_event_once(
            event_type="command_created",
            project_id=decision.project_id,
            session_id=decision.session_id,
            correlation_id=self._decision_correlation_id(decision),
            causation_id=decision.decision_id,
            related_ids=self._decision_related_ids(decision, command_id=command_id),
            payload={
                "command_id": command_id,
                "action_ref": decision.action_ref,
                "action_args": requested_action_args_from_decision(decision),
                "decision_result": decision.decision_result,
                "policy_version": decision.policy_version,
                "fact_snapshot_version": decision.fact_snapshot_version,
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
            try:
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
            except ValueError:
                conflicted = self._recover_command_conflict_state(
                    command_id=command_id,
                    session_id=decision.session_id,
                )
                if conflicted is None:
                    raise
                return AutoExecuteCommandPlan(
                    command_id=command_id,
                    claim_seq=None,
                    should_execute=False,
                    current_status=conflicted.status,
                )
            return AutoExecuteCommandPlan(
                command_id=command_id,
                claim_seq=claim.claim_seq,
                should_execute=True,
                current_status="claimed",
            )
        if current.status == "claimed" and current.worker_id == "resident_orchestrator":
            try:
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
            except ValueError:
                conflicted = self._recover_command_conflict_state(
                    command_id=command_id,
                    session_id=decision.session_id,
                )
                if conflicted is None:
                    raise
                return AutoExecuteCommandPlan(
                    command_id=command_id,
                    claim_seq=None,
                    should_execute=False,
                    current_status=conflicted.status,
                )
        return AutoExecuteCommandPlan(
            command_id=command_id,
            claim_seq=None,
            should_execute=False,
            current_status=current.status,
        )

    def _recover_command_conflict_state(self, *, command_id: str, session_id: str):
        current = self._command_lease_store.get_command(command_id)
        if current is None:
            return None
        if current.session_id != session_id:
            return None
        return current

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

    @staticmethod
    def _resident_expert_consultation_ref(decision) -> str:
        return decision.decision_id

    @staticmethod
    def _resident_expert_consultation_bundle(decision) -> dict[str, Any] | None:
        evidence = decision.evidence if isinstance(decision.evidence, dict) else {}
        bundle = evidence.get("resident_expert_consultation")
        return bundle if isinstance(bundle, dict) else None

    def _decision_has_resident_expert_consultation(self, decision) -> bool:
        bundle = self._resident_expert_consultation_bundle(decision)
        if bundle is None:
            return False
        return bundle.get("consultation_ref") == self._resident_expert_consultation_ref(decision)

    def _with_resident_expert_consultation(self, decision):
        if self._resident_expert_runtime_service is None:
            return decision
        if self._decision_has_resident_expert_consultation(decision):
            return decision
        consultation_ref = self._resident_expert_consultation_ref(decision)
        consulted_at = decision.created_at
        bindings = self._resident_expert_runtime_service.consult_or_restore(
            consultation_ref=consultation_ref,
            consulted_at=consulted_at,
        )
        consultation_bundle = {
            "consultation_ref": consultation_ref,
            "consulted_at": consulted_at,
            "experts": [
                {
                    "expert_id": binding.expert_id,
                    "status": binding.status,
                    "runtime_handle": binding.runtime_handle,
                    "last_seen_at": binding.last_seen_at,
                    "last_consulted_at": binding.last_consulted_at,
                    "last_consultation_ref": binding.last_consultation_ref,
                }
                for binding in bindings
            ],
        }
        evidence = decision.evidence if isinstance(decision.evidence, dict) else {}
        return decision.model_copy(
            update={
                "evidence": {
                    **evidence,
                    "resident_expert_consultation": consultation_bundle,
                }
            }
        )

    def _future_worker_request_contracts(self, decision) -> list[FutureWorkerExecutionRequest]:
        evidence = self._decision_evidence_map(decision)
        requests = evidence.get("future_worker_requests")
        if not isinstance(requests, list):
            return []
        return [FutureWorkerExecutionRequest.model_validate(request) for request in requests]

    def _materialized_future_worker_request_exists(
        self,
        *,
        parent_session_id: str,
        worker_task_ref: str,
    ) -> bool:
        if self._session_service is None:
            return False
        return any(
            event.event_type == "future_worker_requested"
            and event.related_ids.get("worker_task_ref") == worker_task_ref
            for event in self._session_service.list_events(session_id=parent_session_id)
        )

    def _materialize_future_worker_requests(
        self,
        decision,
        *,
        occurred_at: str,
    ) -> list[str]:
        if self._future_worker_service is None:
            return []
        decision_trace_ref = self._decision_trace_ref(decision)
        request_contracts = self._future_worker_request_contracts(decision)
        requests_to_materialize: list[FutureWorkerExecutionRequest] = []
        for request in request_contracts:
            if request.project_id != decision.project_id:
                raise ValueError("future worker request project drift")
            if request.parent_session_id != decision.session_id:
                raise ValueError("future worker request session drift")
            if decision_trace_ref is None or request.decision_trace_ref != decision_trace_ref:
                raise ValueError("future worker request decision trace drift")
            if self._materialized_future_worker_request_exists(
                parent_session_id=request.parent_session_id,
                worker_task_ref=request.worker_task_ref,
            ):
                continue
            requests_to_materialize.append(request)
        materialized_refs: list[str] = []
        for request in requests_to_materialize:
            self._future_worker_service.request_worker(
                project_id=request.project_id,
                parent_session_id=request.parent_session_id,
                worker_task_ref=request.worker_task_ref,
                decision_trace_ref=request.decision_trace_ref,
                goal_contract_version=request.goal_contract_version,
                scope=request.scope,
                allowed_hands=list(request.allowed_hands),
                input_packet_refs=list(request.input_packet_refs),
                retrieval_handles=list(request.retrieval_handles),
                distilled_summary_ref=request.distilled_summary_ref,
                execution_budget_ref=request.execution_budget_ref,
                occurred_at=occurred_at,
            )
            materialized_refs.append(request.worker_task_ref)
        return materialized_refs

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
        release_gate_verdict = read_release_gate_decision_evidence(evidence).verdict
        return {
            "decision_result": decision.decision_result,
            "action_status": str(result.action_status),
            "reply_code": str(result.reply_code) if result.reply_code is not None else None,
            "claim_seq": claim_seq,
            "auto_execute_total": 1,
            "delivery_enqueue_expected": int(result.action_status == ActionStatus.COMPLETED),
            "release_gate_status": (
                release_gate_verdict.status
                if release_gate_verdict is not None
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
        payload.update(
            build_session_event_gate_payload(
                evidence=evidence,
                include_validator=False,
                include_bundle=True,
            )
        )
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

    def _load_release_gate_report(self, *, trace: DecisionTrace):
        report_path = self._settings.release_gate_report_path
        if not report_path:
            return None
        return load_release_gate_artifacts(
            report_path=report_path,
            runtime_contract=self._release_gate_runtime_contract(trace=trace),
            certification_packet_corpus_ref=self._settings.release_gate_certification_packet_corpus_ref,
            shadow_decision_ledger_ref=self._settings.release_gate_shadow_decision_ledger_ref,
        )

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
        requested_action_args: dict[str, Any],
        goal_contract_readiness: GoalContractReadiness | None,
        now: datetime,
    ) -> dict[str, object]:
        evidence: dict[str, object] = {"brain_rationale": brain_intent.rationale}
        if requested_action_args:
            evidence["requested_action_args"] = dict(requested_action_args)
        brain_output: dict[str, object] = {}
        if brain_intent.confidence is not None:
            brain_output["confidence"] = brain_intent.confidence
        if brain_intent.goal_coverage:
            brain_output["goal_coverage"] = brain_intent.goal_coverage
        if brain_intent.remaining_work_hypothesis:
            brain_output["remaining_work_hypothesis"] = list(
                brain_intent.remaining_work_hypothesis
            )
        if brain_intent.evidence_codes:
            brain_output["evidence_codes"] = list(brain_intent.evidence_codes)
        if brain_output:
            evidence["brain_output"] = brain_output
        decision_trace = self._decision_trace_for_intent(
            record,
            brain_intent=brain_intent,
            action_ref=action_ref,
            goal_contract_version=self._goal_contract_version_for_record(record),
        )
        action_args_contract = validate_managed_action_arguments(
            action_ref=action_ref,
            action_arguments=requested_action_args,
        )
        validator_verdict = self._decision_validator.validate(
            brain_intent=brain_intent.intent,
            action_ref=action_ref,
            action_arguments=requested_action_args,
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
        approval_read = self._approval_read_snapshot_for_session(
            record,
            allow_canonical_fallback=False,
        )
        report = None
        loaded_artifacts = None
        verdict = None
        if self._settings.release_gate_report_path:
            try:
                loaded_artifacts = self._load_release_gate_report(trace=decision_trace)
                report = loaded_artifacts.report
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
        release_gate_evidence = build_release_gate_runtime_evidence(
            verdict=release_gate_verdict,
            loaded_artifacts=loaded_artifacts,
            report_path=self._settings.release_gate_report_path,
            certification_packet_corpus_ref=(
                self._settings.release_gate_certification_packet_corpus_ref
            ),
            shadow_decision_ledger_ref=self._settings.release_gate_shadow_decision_ledger_ref,
        )
        evidence["decision_trace"] = decision_trace.model_dump(mode="json")
        evidence["managed_action_args_contract"] = action_args_contract.model_dump(mode="json")
        evidence["validator_verdict"] = validator_verdict.model_dump(mode="json")
        evidence["release_gate_verdict"] = release_gate_evidence.verdict.model_dump(mode="json")
        if release_gate_evidence.evidence_bundle is not None:
            evidence["release_gate_evidence_bundle"] = release_gate_evidence.evidence_bundle.model_dump(
                mode="json",
                exclude_none=True,
            )
        return evidence

    def _record_and_store_decision(self, decision):
        existing = self._decision_store.get(decision.decision_key)
        if existing is None or not self._decision_has_resident_expert_consultation(existing):
            decision = self._with_resident_expert_consultation(decision)
        if existing is not None:
            has_canonical_events = self._has_canonical_decision_events(existing)
            if not self._decision_has_runtime_gate(existing):
                updated = decision
                if has_canonical_events:
                    updated = self._merge_existing_lifecycle_evidence(existing, decision)
                else:
                    self._record_decision_lifecycle(decision)
                return self._decision_store.update(updated)
            if not has_canonical_events:
                self._record_decision_lifecycle(existing)
            if not self._decision_has_resident_expert_consultation(existing):
                updated = self._merge_existing_lifecycle_evidence(existing, decision)
                return self._decision_store.update(updated)
            return existing
        if self._has_canonical_decision_events(decision):
            return self._decision_store.put(decision)
        self._record_decision_lifecycle(decision)
        return self._decision_store.put(decision)

    @staticmethod
    def _merge_existing_lifecycle_evidence(existing, regenerated):
        existing_evidence = existing.evidence if isinstance(existing.evidence, dict) else {}
        regenerated_evidence = (
            regenerated.evidence if isinstance(regenerated.evidence, dict) else {}
        )
        merged_evidence = {
            **existing_evidence,
            **regenerated_evidence,
        }
        for key in ("decision_trace", "validator_verdict", "release_gate_verdict"):
            if key in existing_evidence:
                merged_evidence[key] = existing_evidence[key]
        return existing.model_copy(update={"evidence": merged_evidence})

    @staticmethod
    def _pass_verdict_requires_bundle(release_gate_verdict: ReleaseGateVerdict) -> bool:
        return release_gate_verdict.report_id != "report:resident_default"

    @staticmethod
    def _decision_allows_auto_execute(decision) -> bool:
        if decision.brain_intent not in (None, "propose_execute", "propose_recovery"):
            return False
        evidence = decision.evidence if isinstance(decision.evidence, dict) else {}
        managed_boundary = evidence.get("managed_agent_boundary")
        if isinstance(managed_boundary, dict):
            if managed_boundary.get("status") != "pass":
                return False
            if not bool(managed_boundary.get("auto_execute_eligible")):
                return False
        validator_verdict = read_validator_decision_evidence(evidence).verdict
        if validator_verdict is None or validator_verdict.status != "pass":
            return False
        release_gate = read_release_gate_decision_evidence(evidence)
        release_gate_verdict = release_gate.verdict
        if release_gate_verdict is None:
            return False
        if decision.brain_intent == "propose_recovery":
            return release_gate_verdict.status in {"pass", "not_applicable"}
        if release_gate_verdict.status != "pass":
            return False
        if (
            ResidentOrchestrator._pass_verdict_requires_bundle(release_gate_verdict)
            and release_gate.evidence_bundle is None
        ):
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
        release_gate = read_release_gate_decision_evidence(evidence)
        validator_verdict = read_validator_decision_evidence(evidence).verdict
        release_gate_verdict = release_gate.verdict
        if (
            decision.brain_intent == "propose_recovery"
            and validator_verdict is not None
            and validator_verdict.status == "pass"
            and release_gate_verdict is not None
            and release_gate_verdict.status in {"pass", "not_applicable"}
        ):
            return True
        return (
            validator_verdict is not None
            and validator_verdict.status == "pass"
            and release_gate_verdict is not None
            and (
                not ResidentOrchestrator._pass_verdict_requires_bundle(release_gate_verdict)
                or release_gate.evidence_bundle is not None
            )
        )

    def _session_has_event(self, *, session_id: str, event_type: str) -> bool:
        if self._session_service is None:
            return False
        events = self._session_service.list_events(
            session_id=session_id,
            event_type=event_type,
        )
        return bool(events)

    def _projected_approval_is_locally_pending(
        self,
        *,
        approval_id: str,
        session_id: str,
        project_id: str,
    ) -> bool:
        records = self._approval_store.records_for_approval_id(
            approval_id,
            session_id=session_id,
            project_id=project_id,
        )
        if not records:
            return True
        return any(record.status == "pending" for record in records)

    def _active_projected_approvals(
        self,
        record: PersistedSessionRecord,
    ) -> list[ApprovalProjection]:
        approvals = sorted(
            (
                approval
                for approval in record.approval_queue
                if approval.thread_id == record.thread_id
                and approval.project_id == record.project_id
                and approval.status == "pending"
            ),
            key=lambda approval: approval.requested_at,
        )
        return [
            approval
            for approval in approvals
            if self._projected_approval_is_locally_pending(
                approval_id=approval.approval_id,
                session_id=record.thread_id,
                project_id=record.project_id,
            )
        ]

    @staticmethod
    def _approval_projection_order(
        approval: ApprovalProjection,
    ) -> tuple[bool, str, str]:
        requested_at = str(approval.requested_at or "")
        return (requested_at == "", requested_at, approval.approval_id)

    def _canonical_pending_approval_projections(
        self,
        record: PersistedSessionRecord,
    ) -> list[ApprovalProjection]:
        pending_records = sorted(
            (
                approval
                for approval in self._approval_store.list_records()
                if approval.project_id == record.project_id
                and approval.session_id == record.thread_id
                and approval.status == "pending"
            ),
            key=lambda approval: (
                str(approval.created_at or "") == "",
                str(approval.created_at or ""),
                approval.approval_id,
            ),
        )
        return [
            ApprovalProjection(
                approval_id=approval.approval_id,
                project_id=record.project_id,
                thread_id=record.thread_id,
                native_thread_id=approval.native_thread_id or record.native_thread_id,
                risk_level=approval.decision.risk_class,
                command=approval.requested_action,
                reason=approval.decision.decision_reason,
                alternative="",
                status=approval.status,
                requested_at=approval.created_at,
                decided_at=approval.decided_at,
                decided_by=approval.decided_by,
            )
            for approval in pending_records
        ]

    def _active_approvals(
        self,
        record: PersistedSessionRecord,
        *,
        include_canonical_fallback: bool = True,
    ) -> list[ApprovalProjection]:
        projected_approvals = self._active_projected_approvals(record)
        if projected_approvals:
            return projected_approvals
        if not include_canonical_fallback:
            return []
        approvals_by_id: dict[str, ApprovalProjection] = {}
        for approval in self._canonical_pending_approval_projections(record):
            approvals_by_id.setdefault(approval.approval_id, approval)
        return sorted(
            approvals_by_id.values(),
            key=self._approval_projection_order,
        )

    def _record_with_local_approval_overlay(
        self,
        record: PersistedSessionRecord,
    ) -> PersistedSessionRecord:
        active_approvals = self._active_approvals(record)
        approval_fact_codes = {"approval_pending", "awaiting_human_direction"}
        facts = (
            [fact for fact in record.facts if fact.fact_code not in approval_fact_codes]
            if not active_approvals
            else list(record.facts)
        )
        session = (
            record.session.model_copy(update={"pending_approval_count": len(active_approvals)})
            if record.session.pending_approval_count != len(active_approvals)
            else record.session
        )
        if (
            active_approvals == record.approval_queue
            and facts == record.facts
            and session == record.session
        ):
            return record
        return record.model_copy(
            update={
                "approval_queue": active_approvals,
                "facts": facts,
                "session": session,
            }
        )

    def _requested_action_args_for_intent(
        self,
        record: PersistedSessionRecord,
        *,
        brain_intent,
    ) -> dict[str, Any]:
        if brain_intent.action_arguments:
            return dict(brain_intent.action_arguments)
        if brain_intent.intent == "candidate_closure":
            return self._candidate_closure_action_args(record)
        return {}

    @staticmethod
    def _approval_record_matches_intent(
        *,
        approval_record,
        action_ref: str,
        requested_action_args: dict[str, Any],
        goal_contract_version: str | None,
        policy_version: str,
        fact_snapshot_version: str,
    ) -> bool:
        if approval_record.requested_action != action_ref:
            return False
        if dict(approval_record.requested_action_args) != dict(requested_action_args):
            return False
        if approval_record.goal_contract_version != goal_contract_version:
            return False
        if approval_record.policy_version != policy_version:
            return False
        if list(approval_record.decision_options) != _CANONICAL_APPROVAL_DECISION_OPTIONS:
            return False
        if _fact_snapshot_order(approval_record.fact_snapshot_version) > _fact_snapshot_order(
            fact_snapshot_version
        ):
            return False
        return True

    @staticmethod
    def _approval_event_matches_intent(
        event,
        *,
        action_ref: str,
        requested_action_args: dict[str, Any],
        goal_contract_version: str | None,
        policy_version: str,
        fact_snapshot_version: str,
    ) -> bool:
        payload = event.payload if isinstance(event.payload, dict) else {}
        if payload.get("requested_action") != action_ref:
            return False
        if payload.get("requested_action_args", {}) != dict(requested_action_args):
            return False
        if payload.get("goal_contract_version") != goal_contract_version:
            return False
        if payload.get("policy_version") != policy_version:
            return False
        if payload.get("decision_options") != _CANONICAL_APPROVAL_DECISION_OPTIONS:
            return False
        existing_snapshot = payload.get("fact_snapshot_version")
        if isinstance(existing_snapshot, str) and _fact_snapshot_order(
            existing_snapshot
        ) > _fact_snapshot_order(fact_snapshot_version):
            return False
        return True

    def _approval_projection_is_trustworthy_for_intent(
        self,
        approval: ApprovalProjection,
        *,
        record: PersistedSessionRecord,
        action_ref: str,
        requested_action_args: dict[str, Any],
        goal_contract_version: str | None,
        policy_version: str,
    ) -> bool:
        if approval.command != action_ref:
            return False
        approval_records = self._approval_store.records_for_approval_id(
            approval.approval_id,
            session_id=record.thread_id,
            project_id=record.project_id,
        )
        for approval_record in approval_records:
            if not self._approval_record_matches_intent(
                approval_record=approval_record,
                action_ref=action_ref,
                requested_action_args=requested_action_args,
                goal_contract_version=goal_contract_version,
                policy_version=policy_version,
                fact_snapshot_version=record.fact_snapshot_version,
            ):
                return False
        if self._session_service is None:
            return True
        approval_events = self._session_service.list_events(
            session_id=record.thread_id,
            event_type="approval_requested",
            related_id_key="approval_id",
            related_id_value=approval.approval_id,
        )
        for event in approval_events:
            if not self._approval_event_matches_intent(
                event,
                action_ref=action_ref,
                requested_action_args=requested_action_args,
                goal_contract_version=goal_contract_version,
                policy_version=policy_version,
                fact_snapshot_version=record.fact_snapshot_version,
            ):
                return False
        return True

    def _trusted_approvals_for_intent(
        self,
        record: PersistedSessionRecord,
        *,
        action_ref: str,
        requested_action_args: dict[str, Any],
        goal_contract_version: str | None,
        policy_version: str,
    ) -> list[ApprovalProjection]:
        active_approvals = [
            approval
            for approval in record.approval_queue
            if self._approval_projection_is_trustworthy_for_intent(
                approval,
                record=record,
                action_ref=action_ref,
                requested_action_args=requested_action_args,
                goal_contract_version=goal_contract_version,
                policy_version=policy_version,
            )
        ]
        if active_approvals:
            return active_approvals
        approvals_by_id: dict[str, ApprovalProjection] = {}
        for approval in self._canonical_pending_approval_projections(record):
            if approval.approval_id in approvals_by_id:
                continue
            if not self._approval_projection_is_trustworthy_for_intent(
                approval,
                record=record,
                action_ref=action_ref,
                requested_action_args=requested_action_args,
                goal_contract_version=goal_contract_version,
                policy_version=policy_version,
            ):
                continue
            approvals_by_id[approval.approval_id] = approval
        return sorted(
            approvals_by_id.values(),
            key=self._approval_projection_order,
        )

    def _record_with_trustworthy_approval_identity(
        self,
        record: PersistedSessionRecord,
        *,
        action_ref: str,
        requested_action_args: dict[str, Any],
        goal_contract_version: str | None,
        policy_version: str,
    ) -> PersistedSessionRecord:
        trusted_approvals = self._trusted_approvals_for_intent(
            record,
            action_ref=action_ref,
            requested_action_args=requested_action_args,
            goal_contract_version=goal_contract_version,
            policy_version=policy_version,
        )
        approval_fact_codes = {"approval_pending", "awaiting_human_direction"}
        facts = (
            [fact for fact in record.facts if fact.fact_code not in approval_fact_codes]
            if not trusted_approvals
            else list(record.facts)
        )
        session = (
            record.session.model_copy(update={"pending_approval_count": len(trusted_approvals)})
            if record.session.pending_approval_count != len(trusted_approvals)
            else record.session
        )
        if (
            trusted_approvals == record.approval_queue
            and facts == record.facts
            and session == record.session
        ):
            return record
        return record.model_copy(
            update={
                "approval_queue": trusted_approvals,
                "facts": facts,
                "session": session,
            }
        )

    def _supersede_stale_pending_approvals(
        self,
        *,
        previous_record: PersistedSessionRecord,
        trusted_record: PersistedSessionRecord,
        decision: CanonicalDecisionRecord,
        now: datetime,
    ) -> None:
        stale_approval_ids = {
            approval.approval_id
            for approval in previous_record.approval_queue
            if approval.status == "pending"
        } - {
            approval.approval_id
            for approval in trusted_record.approval_queue
            if approval.status == "pending"
        }
        if not stale_approval_ids:
            return
        updated_at = now.astimezone(UTC).replace(microsecond=0).isoformat().replace(
            "+00:00",
            "Z",
        )
        reason = (
            "approval_superseded_by_identity_drift "
            f"decision_id={decision.decision_id} "
            f"action={decision.action_ref} "
            f"snapshot={decision.fact_snapshot_version}"
        )
        superseded_records: list[CanonicalApprovalRecord] = []
        for approval_id in sorted(stale_approval_ids):
            approval_records = self._approval_store.records_for_approval_id(
                approval_id,
                session_id=decision.session_id,
                project_id=decision.project_id,
            )
            for approval_record in approval_records:
                if approval_record.status != "pending":
                    continue
                notes = list(approval_record.operator_notes)
                notes.append(reason)
                superseded_records.append(
                    self._approval_store.update(
                        approval_record.model_copy(
                            update={
                                "status": "superseded",
                                "decided_at": updated_at,
                                "decided_by": "policy-identity-drift",
                                "operator_notes": notes,
                            }
                        )
                    )
                )
        if superseded_records:
            self._delivery_outbox_store.supersede_records(
                envelope_reasons={
                    approval.envelope_id: reason for approval in superseded_records
                },
                updated_at=updated_at,
            )

    def _approval_read_snapshot_for_session(
        self,
        record: PersistedSessionRecord,
        *,
        allow_canonical_fallback: bool = True,
    ) -> ApprovalReadSnapshot | None:
        approvals = self._active_approvals(
            record,
            include_canonical_fallback=allow_canonical_fallback,
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
        payload = matching_event.payload if matching_event is not None else {}
        return ApprovalReadSnapshot(
            approval_event_id=matching_event.event_id if matching_event is not None else approval.approval_id,
            approval_id=approval.approval_id,
            status=approval.status,
            requested_action=str(payload.get("requested_action") or approval.command),
            session_id=approval.thread_id,
            project_id=approval.project_id,
            fact_snapshot_version=str(
                payload.get("fact_snapshot_version") or record.fact_snapshot_version
            ),
            goal_contract_version=str(
                payload.get("goal_contract_version") or "goal-contract:unknown"
            ),
            expires_at=str(payload.get("expires_at") or "approval:no-expiry"),
            decided_by=approval.decided_by,
            log_seq=matching_event.log_seq if matching_event is not None else None,
        )

    def _decision_trace_for_intent(
        self,
        record: PersistedSessionRecord,
        *,
        brain_intent: DecisionIntent,
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
            "brain_intent": brain_intent.intent,
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
            provider=brain_intent.provider,
            model=brain_intent.model,
            prompt_schema_ref=brain_intent.prompt_schema_ref,
            output_schema_ref=brain_intent.output_schema_ref,
            provider_output_schema_ref=brain_intent.provider_output_schema_ref,
            approval_read=self._approval_read_snapshot_for_session(
                record,
                allow_canonical_fallback=False,
            ),
            degrade_reason=brain_intent.degrade_reason,
        )

    def orchestrate_all(
        self,
        *,
        now: datetime | None = None,
        continue_on_error: bool = False,
    ) -> list[ResidentOrchestrationOutcome]:
        current = now or datetime.now(UTC)
        self._command_lease_store.expire_and_requeue_expired(
            now=current.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            reason="resident_orchestrator_tick",
        )
        outcomes: list[ResidentOrchestrationOutcome] = []
        for record in self._session_spine_store.list_records():
            try:
                outcomes.append(self._orchestrate_record(record, now=current))
            except Exception:
                if not continue_on_error:
                    raise
                logger.exception(
                    "resident orchestrator record failed: project=%s session=%s",
                    record.project_id,
                    record.thread_id,
                )
        return outcomes

    def _orchestrate_record(
        self,
        record: PersistedSessionRecord,
        *,
        now: datetime,
    ) -> ResidentOrchestrationOutcome:
        record = self._record_with_local_approval_overlay(record)
        overlay_record = record
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
            requested_action_args = self._requested_action_args_for_intent(
                record,
                brain_intent=brain_intent,
            )
            record = self._record_with_trustworthy_approval_identity(
                record,
                action_ref=action_ref,
                requested_action_args=requested_action_args,
                goal_contract_version=self._goal_contract_version_for_record(record),
                policy_version=POLICY_VERSION,
            )
            trusted_record = record
            intent_evidence = self._decision_evidence_for_intent(
                record,
                brain_intent=brain_intent,
                action_ref=action_ref,
                requested_action_args=requested_action_args,
                goal_contract_readiness=goal_contract_readiness,
                now=now,
            )
            decision = evaluate_persisted_session_policy(
                record,
                action_ref=action_ref,
                trigger="resident_orchestrator",
                brain_intent=brain_intent.intent,
                validator_verdict=intent_evidence,
                release_gate_verdict=intent_evidence,
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
                self._materialize_future_worker_requests(
                    decision,
                    occurred_at=now.astimezone(UTC).replace(microsecond=0).isoformat().replace(
                        "+00:00",
                        "Z",
                    ),
                )
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
                elif command_plan.current_status == "executed":
                    self._consume_completed_future_worker_results(
                        decision,
                        command_id=command_plan.command_id,
                        occurred_at=now.astimezone(UTC)
                        .replace(microsecond=0)
                        .isoformat()
                        .replace("+00:00", "Z"),
                    )
            elif decision.decision_result == DECISION_REQUIRE_USER_DECISION:
                materialize_canonical_approval(
                    decision,
                    approval_store=self._approval_store,
                    delivery_outbox_store=self._delivery_outbox_store,
                    session_service=self._session_service,
                )
                self._supersede_stale_pending_approvals(
                    previous_record=overlay_record,
                    trusted_record=trusted_record,
                    decision=decision,
                    now=now,
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
