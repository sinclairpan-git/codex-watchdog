from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from watchdog.contracts.session_spine.enums import ActionStatus, Effect, ReplyCode
from watchdog.contracts.session_spine.models import FactRecord, WatchdogActionResult
from watchdog.services.brain.service import BrainDecisionService
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
        brain_service: BrainDecisionService | None = None,
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
        self._brain_service = brain_service or BrainDecisionService()

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
        command_id: str,
        claim_seq: int | None,
        action_status: ActionStatus,
        now: datetime,
    ) -> None:
        if claim_seq is None:
            return
        self._command_lease_store.record_terminal_result(
            command_id=command_id,
            worker_id="resident_orchestrator",
            claim_seq=claim_seq,
            result_type=(
                "command_executed"
                if action_status == ActionStatus.COMPLETED
                else "command_failed"
            ),
            occurred_at=now.astimezone(UTC).replace(microsecond=0).isoformat().replace(
                "+00:00",
                "Z",
            ),
        )

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

    def _decision_evidence_for_intent(
        self,
        record: PersistedSessionRecord,
        *,
        brain_intent,
    ) -> dict[str, object]:
        evidence: dict[str, object] = {"brain_rationale": brain_intent.rationale}
        if brain_intent.intent == "candidate_closure":
            evidence["requested_action_args"] = self._candidate_closure_action_args(record)
        return evidence

    def _record_and_store_decision(self, decision):
        existing = self._decision_store.get(decision.decision_key)
        if existing is not None:
            return existing
        self._record_decision_lifecycle(decision)
        return self._decision_store.put(decision)

    @staticmethod
    def _decision_allows_auto_execute(decision) -> bool:
        if decision.brain_intent not in (None, "propose_execute"):
            return False
        evidence = decision.evidence if isinstance(decision.evidence, dict) else {}
        validator_verdict = evidence.get("validator_verdict")
        if isinstance(validator_verdict, dict) and validator_verdict.get("status") != "pass":
            return False
        release_gate_verdict = evidence.get("release_gate_verdict")
        if isinstance(release_gate_verdict, dict) and release_gate_verdict.get("status") != "pass":
            return False
        return True

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
            decision = evaluate_persisted_session_policy(
                record,
                action_ref=action_ref,
                trigger="resident_orchestrator",
                brain_intent=brain_intent.intent,
                goal_contract_readiness=self._goal_contract_readiness_for_record(record),
            )
            decision = decision.model_copy(
                update={
                    "evidence": {
                        **decision.evidence,
                        **self._decision_evidence_for_intent(record, brain_intent=brain_intent),
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
                        self._record_command_terminal_result(
                            command_id=command_plan.command_id,
                            claim_seq=command_plan.claim_seq,
                            action_status=result.action_status,
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
                        self._record_command_terminal_result(
                            command_id=command_plan.command_id,
                            claim_seq=command_plan.claim_seq,
                            action_status=ActionStatus.ERROR,
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
