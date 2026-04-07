from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from watchdog.contracts.session_spine.enums import ActionStatus, Effect, ReplyCode
from watchdog.contracts.session_spine.models import FactRecord, WatchdogActionResult
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
from watchdog.services.policy.decisions import PolicyDecisionStore
from watchdog.services.policy.engine import evaluate_persisted_session_policy
from watchdog.services.policy.rules import (
    DECISION_AUTO_EXECUTE_AND_NOTIFY,
    DECISION_BLOCK_AND_ALERT,
    DECISION_REQUIRE_USER_DECISION,
)
from watchdog.services.session_spine.service import SessionSpineUpstreamError
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
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _select_action_ref(record: PersistedSessionRecord) -> str | None:
    fact_codes = {fact.fact_code for fact in record.facts}
    if "context_critical" in fact_codes:
        return "execute_recovery"
    if fact_codes.intersection({"approval_pending", "awaiting_human_direction"}):
        return "continue_session"
    if fact_codes.intersection({"stuck_no_progress", "repeat_failure"}):
        return "continue_session"
    return None


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
        state_store: ResidentOrchestrationStateStore,
    ) -> None:
        self._settings = settings
        self._client = client
        self._session_spine_store = session_spine_store
        self._decision_store = decision_store
        self._approval_store = approval_store
        self._action_receipt_store = action_receipt_store
        self._delivery_outbox_store = delivery_outbox_store
        self._state_store = state_store

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

    def orchestrate_all(self, *, now: datetime | None = None) -> list[ResidentOrchestrationOutcome]:
        current = now or datetime.now(UTC)
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
        action_ref = _select_action_ref(record)
        decision_result: str | None = None

        if action_ref is not None:
            decision = self._decision_store.put(
                evaluate_persisted_session_policy(
                    record,
                    action_ref=action_ref,
                    trigger="resident_orchestrator",
                )
            )
            decision_result = decision.decision_result
            if decision.decision_result == DECISION_AUTO_EXECUTE_AND_NOTIFY:
                try:
                    execute_canonical_decision(
                        decision,
                        settings=self._settings,
                        client=self._client,
                        receipt_store=self._action_receipt_store,
                    )
                except SessionSpineUpstreamError as exc:
                    if not self._cache_auto_continue_control_link_error(decision, exc):
                        raise
                else:
                    self._delivery_outbox_store.enqueue_envelopes(build_envelopes_for_decision(decision))
            elif decision.decision_result == DECISION_REQUIRE_USER_DECISION:
                materialize_canonical_approval(
                    decision,
                    approval_store=self._approval_store,
                    delivery_outbox_store=self._delivery_outbox_store,
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
