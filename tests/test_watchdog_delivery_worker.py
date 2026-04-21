from __future__ import annotations

from pathlib import Path

import pytest

from watchdog.contracts.session_spine.models import FactRecord, SessionProjection, TaskProgressView
from watchdog.services.approvals.service import (
    CanonicalApprovalRecord,
    CanonicalApprovalResponseRecord,
    build_canonical_approval_record,
)
from watchdog.services.delivery.envelopes import (
    DecisionEnvelope,
    NotificationEnvelope,
    build_progress_summary_envelope,
    build_envelopes_for_approval_response,
    build_envelopes_for_decision,
)
from watchdog.services.delivery.http_client import DeliveryAttemptResult
from watchdog.services.delivery.store import DeliveryOutboxStore
from watchdog.services.delivery.worker import DeliveryWorker
from watchdog.services.policy.decisions import CanonicalDecisionRecord
from watchdog.services.session_service import SessionService, SessionServiceStore
from watchdog.services.session_spine.store import PersistedSessionRecord
from watchdog.settings import Settings


def _decision(
    *,
    project_id: str = "repo-a",
    session_id: str = "session:repo-a",
    thread_id: str = "session:repo-a",
    native_thread_id: str = "thr_native_1",
    fact_snapshot_version: str = "fact-v7",
    decision_result: str = "block_and_alert",
    action_ref: str = "execute_recovery",
    approval_id: str | None = None,
) -> CanonicalDecisionRecord:
    return CanonicalDecisionRecord(
        decision_id=f"decision:{project_id}:{fact_snapshot_version}:{decision_result}",
        decision_key=(
            f"{session_id}|{fact_snapshot_version}|policy-v1|{decision_result}|"
            f"{action_ref}|{approval_id or ''}"
        ),
        session_id=session_id,
        project_id=project_id,
        thread_id=thread_id,
        native_thread_id=native_thread_id,
        approval_id=approval_id,
        action_ref=action_ref,
        trigger="resident_supervision",
        decision_result=decision_result,
        risk_class="none" if decision_result == "auto_execute_and_notify" else "human_gate",
        decision_reason="frozen test decision",
        matched_policy_rules=["registered_action"],
        why_not_escalated=(
            "policy_allows_auto_execution"
            if decision_result == "auto_execute_and_notify"
            else None
        ),
        why_escalated="manual decision required"
        if decision_result == "require_user_decision"
        else "critical block"
        if decision_result == "block_and_alert"
        else None,
        uncertainty_reasons=["mapping_incomplete"]
        if decision_result == "block_and_alert"
        else [],
        policy_version="policy-v1",
        fact_snapshot_version=fact_snapshot_version,
        idempotency_key=(
            f"{session_id}|{fact_snapshot_version}|policy-v1|{decision_result}|"
            f"{action_ref}|{approval_id or ''}"
        ),
        created_at="2026-04-07T00:00:00Z",
        operator_notes=[],
        evidence={
            "facts": [
                {
                    "fact_id": "fact-1",
                    "fact_code": "recovery_available",
                    "fact_kind": "signal",
                    "severity": "info",
                    "summary": "recovery available",
                    "detail": "recovery available",
                    "source": "watchdog",
                    "observed_at": "2026-04-07T00:00:00Z",
                    "related_ids": {},
                }
            ],
            "matched_policy_rules": ["registered_action"],
            "decision": {
                "decision_result": decision_result,
                "action_ref": action_ref,
                "approval_id": approval_id,
            },
        },
    )


def _approval_response(
    *,
    decision: CanonicalDecisionRecord,
    response_action: str = "approve",
    approval_status: str = "approved",
) -> tuple[CanonicalApprovalRecord, CanonicalApprovalResponseRecord]:
    approval = CanonicalApprovalRecord(
        approval_id="appr_001",
        envelope_id="approval-envelope:test",
        approval_kind="canonical_user_decision",
        requested_action=decision.action_ref,
        requested_action_args={},
        approval_token="approval-token:test",
        decision_options=["approve", "reject", "execute_action"],
        policy_version=decision.policy_version,
        fact_snapshot_version=decision.fact_snapshot_version,
        idempotency_key=f"{decision.idempotency_key}|approval",
        project_id=decision.project_id,
        session_id=decision.session_id,
        thread_id=decision.thread_id,
        native_thread_id=decision.native_thread_id,
        status=approval_status,
        created_at="2026-04-07T00:00:00Z",
        decided_at="2026-04-07T00:00:30Z",
        decided_by="openclaw",
        operator_notes=[],
        decision=decision,
    )
    response = CanonicalApprovalResponseRecord(
        response_id="approval-response:test",
        envelope_id=approval.envelope_id,
        approval_id=approval.approval_id,
        response_action=response_action,
        client_request_id="req_001",
        idempotency_key=f"{approval.envelope_id}|{response_action}|req_001",
        project_id=decision.project_id,
        approval_status=approval_status,
        operator="openclaw",
        note="looks safe",
        created_at="2026-04-07T00:00:31Z",
        operator_notes=[],
        approval_result=None,
        execution_result=None,
    )
    return approval, response


def _progress_record(*, last_progress_at: str = "2026-04-07T00:00:00Z") -> PersistedSessionRecord:
    return PersistedSessionRecord(
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="thr_native_1",
        session_seq=7,
        fact_snapshot_version="fact-v7",
        last_refreshed_at="2026-04-07T00:20:00Z",
        session=SessionProjection(
            project_id="repo-a",
            thread_id="session:repo-a",
            native_thread_id="thr_native_1",
            session_state="active",
            activity_phase="editing_source",
            attention_state="normal",
            headline="editing files",
            pending_approval_count=0,
            available_intents=["continue"],
        ),
        progress=TaskProgressView(
            project_id="repo-a",
            thread_id="session:repo-a",
            native_thread_id="thr_native_1",
            activity_phase="editing_source",
            summary="editing files",
            files_touched=["src/example.py"],
            context_pressure="low",
            stuck_level=0,
            primary_fact_codes=["recovery_available"],
            blocker_fact_codes=[],
            last_progress_at=last_progress_at,
        ),
        facts=[
            FactRecord(
                fact_id="fact-recovery-available",
                fact_code="recovery_available",
                fact_kind="signal",
                severity="info",
                summary="recovery available",
                detail="recovery available",
                source="watchdog",
                observed_at="2026-04-07T00:00:00Z",
            )
        ],
        approval_queue=[],
    )


def _notification(
    *,
    envelope_id: str = "notification-envelope:test",
    correlation_id: str = "notification:test",
    session_id: str = "session:repo-a",
    project_id: str = "repo-a",
    native_thread_id: str = "thr_native_1",
    fact_snapshot_version: str = "fact-v7",
    created_at: str = "2026-04-07T00:20:00Z",
    occurred_at: str = "2026-04-07T00:20:00Z",
    event_id: str = "event:test-notification",
    severity: str = "info",
    notification_kind: str = "progress_summary",
    title: str = "progress update for repo-a",
    summary: str = "still coding locally",
    reason: str = "phase=editing_source; context=low; stuck=0",
) -> NotificationEnvelope:
    return NotificationEnvelope(
        envelope_id=envelope_id,
        correlation_id=correlation_id,
        session_id=session_id,
        project_id=project_id,
        native_thread_id=native_thread_id,
        policy_version="policy-v1",
        fact_snapshot_version=fact_snapshot_version,
        idempotency_key=(
            f"{session_id}|{fact_snapshot_version}|{notification_kind}|{envelope_id}"
        ),
        audit_ref=correlation_id,
        created_at=created_at,
        occurred_at=occurred_at,
        event_id=event_id,
        severity=severity,
        notification_kind=notification_kind,
        title=title,
        summary=summary,
        reason=reason,
    )


def test_envelope_builder_freezes_delivery_matrix_for_decision_results() -> None:
    auto_execute = build_envelopes_for_decision(
        _decision(decision_result="auto_execute_and_notify", action_ref="execute_recovery")
    )
    require_user = build_envelopes_for_decision(
        _decision(
            decision_result="require_user_decision",
            action_ref="execute_recovery",
            approval_id="appr_001",
        )
    )
    block_and_alert = build_envelopes_for_decision(
        _decision(decision_result="block_and_alert", action_ref="continue_session")
    )

    assert [envelope.envelope_type for envelope in auto_execute] == ["decision", "notification"]
    assert auto_execute[0].decision_result == "auto_execute_and_notify"
    assert auto_execute[0].execution_state == "queued"
    assert auto_execute[0].risk_class == "none"
    assert auto_execute[1].notification_kind == "decision_result"
    assert auto_execute[1].decision_result == "auto_execute_and_notify"
    assert auto_execute[1].severity == "info"

    assert [envelope.envelope_type for envelope in require_user] == ["approval"]
    assert require_user[0].approval_id == "appr_001"
    assert require_user[0].requested_action == "execute_recovery"
    assert require_user[0].risk_level == "L2"
    assert require_user[0].command == "execute_recovery"
    assert require_user[0].reason == "frozen test decision"
    assert require_user[0].status == "pending"
    assert require_user[0].requested_at == "2026-04-07T00:00:00Z"

    assert [envelope.envelope_type for envelope in block_and_alert] == ["notification"]
    assert block_and_alert[0].notification_kind == "decision_result"
    assert block_and_alert[0].severity == "critical"


def test_envelope_builder_emits_approval_result_notification_after_user_response() -> None:
    decision = _decision(
        decision_result="require_user_decision",
        action_ref="execute_recovery",
        approval_id="appr_001",
    )
    approval, response = _approval_response(decision=decision)

    envelopes = build_envelopes_for_approval_response(approval, response)

    assert [envelope.envelope_type for envelope in envelopes] == ["notification"]
    assert envelopes[0].notification_kind == "approval_result"
    assert envelopes[0].severity == "info"
    assert envelopes[0].summary == "approval approved via approve"


def test_approval_envelope_carries_openclaw_compatibility_fields_and_action_args() -> None:
    decision = _decision(
        decision_result="require_user_decision",
        action_ref="execute_recovery",
        approval_id="appr_001",
    )
    decision.evidence["requested_action_args"] = {"mode": "safe", "approval_id": "appr_001"}

    envelope = build_envelopes_for_decision(decision)[0]

    assert envelope.requested_action_args == {"mode": "safe", "approval_id": "appr_001"}
    assert envelope.command == 'execute_recovery {"approval_id":"appr_001","mode":"safe"}'
    assert envelope.reason == "frozen test decision"
    assert envelope.risk_level == "L2"


def test_decision_artifacts_use_effective_native_thread_id_from_legacy_decision_record() -> None:
    decision = _decision(
        decision_result="require_user_decision",
        action_ref="execute_recovery",
        approval_id="appr_001",
    ).model_copy(
        update={
            "native_thread_id": None,
            "evidence": {
                **_decision(
                    decision_result="require_user_decision",
                    action_ref="execute_recovery",
                    approval_id="appr_001",
                ).evidence,
                "target": {
                    "session_id": "session:repo-a",
                    "project_id": "repo-a",
                    "thread_id": "session:repo-a",
                    "native_thread_id": "thr_native_legacy",
                    "approval_id": "appr_001",
                },
            },
        }
    )

    approval_record = build_canonical_approval_record(decision)
    envelope = build_envelopes_for_decision(decision)[0]
    legacy_approval = approval_record.model_copy(
        update={
            "native_thread_id": None,
            "decision": approval_record.decision.model_copy(update={"native_thread_id": None}),
        }
    )

    assert approval_record.native_thread_id == "thr_native_legacy"
    assert legacy_approval.effective_native_thread_id == "thr_native_legacy"
    assert envelope.native_thread_id == "thr_native_legacy"


def test_decision_envelope_carries_openclaw_compatibility_fields_and_action_args() -> None:
    decision = _decision(
        decision_result="auto_execute_and_notify",
        action_ref="execute_recovery",
        approval_id=None,
    )
    decision.evidence["requested_action_args"] = {"mode": "safe", "resume": True}

    envelope = build_envelopes_for_decision(decision)[0]

    assert envelope.action_args == {"mode": "safe", "resume": True}
    assert envelope.title == "decision auto_execute_and_notify"
    assert envelope.summary == "frozen test decision"
    assert envelope.reason == "frozen test decision"
    assert envelope.command == 'execute_recovery {"mode":"safe","resume":true}'
    assert envelope.risk_level == "L0"


def test_approval_identity_stays_stable_across_fact_snapshot_versions() -> None:
    approval_v1 = _decision(
        decision_result="require_user_decision",
        action_ref="execute_recovery",
        approval_id="appr_001",
        fact_snapshot_version="fact-v7",
    )
    approval_v2 = _decision(
        decision_result="require_user_decision",
        action_ref="execute_recovery",
        approval_id="appr_001",
        fact_snapshot_version="fact-v8",
    )

    envelope_v1 = build_envelopes_for_decision(approval_v1)[0]
    envelope_v2 = build_envelopes_for_decision(approval_v2)[0]
    record_v1 = build_canonical_approval_record(approval_v1)
    record_v2 = build_canonical_approval_record(approval_v2)

    assert envelope_v1.envelope_id == envelope_v2.envelope_id
    assert envelope_v1.approval_token == envelope_v2.approval_token
    assert record_v1.envelope_id == record_v2.envelope_id
    assert record_v1.approval_token == record_v2.approval_token


def test_delivery_outbox_store_assigns_monotonic_outbox_seq_and_seeds_delivery_state(
    tmp_path: Path,
) -> None:
    store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")

    first = store.enqueue_envelopes(
        build_envelopes_for_decision(
            _decision(decision_result="block_and_alert", fact_snapshot_version="fact-v7")
        )
    )
    second = store.enqueue_envelopes(
        build_envelopes_for_decision(
            _decision(
                decision_result="require_user_decision",
                fact_snapshot_version="fact-v8",
                approval_id="appr_001",
            )
        )
    )

    assert [record.outbox_seq for record in first + second] == [1, 2]
    assert [record.delivery_status for record in first + second] == ["pending", "pending"]


def test_delivery_outbox_store_refreshes_pending_approval_payload_for_same_envelope_id(
    tmp_path: Path,
) -> None:
    store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    first_decision = _decision(
        decision_result="require_user_decision",
        action_ref="execute_recovery",
        approval_id="appr_001",
        fact_snapshot_version="fact-v7",
    )
    first_decision.evidence["requested_action_args"] = {"mode": "safe"}
    second_decision = _decision(
        decision_result="require_user_decision",
        action_ref="execute_recovery",
        approval_id="appr_001",
        fact_snapshot_version="fact-v8",
    ).model_copy(
        update={
            "decision_reason": "newer snapshot still requires explicit human decision",
            "why_escalated": "human_gate matched newer persisted facts",
            "idempotency_key": (
                "session:repo-a|fact-v8|policy-v1|require_user_decision|execute_recovery|appr_001"
            ),
            "decision_key": (
                "session:repo-a|fact-v8|policy-v1|require_user_decision|execute_recovery|appr_001"
            ),
        }
    )
    second_decision.evidence["requested_action_args"] = {"mode": "safe", "resume": True}

    first = store.enqueue_envelopes(build_envelopes_for_decision(first_decision))[0]
    store.update_delivery_record(
        first.model_copy(
            update={
                "delivery_status": "retrying",
                "delivery_attempt": 2,
                "failure_code": "transport_error",
                "next_retry_at": "2026-04-07T00:10:00Z",
                "receipt_id": "rcpt_stale",
            }
        )
    )
    second = store.enqueue_envelopes(build_envelopes_for_decision(second_decision))[0]

    assert second.envelope_id == first.envelope_id
    assert second.outbox_seq == first.outbox_seq
    assert second.fact_snapshot_version == "fact-v8"
    assert second.idempotency_key == (
        "session:repo-a|fact-v8|policy-v1|require_user_decision|execute_recovery|appr_001|approval"
    )
    assert second.delivery_status == "pending"
    assert second.delivery_attempt == 0
    assert second.failure_code is None
    assert second.next_retry_at is None
    assert second.receipt_id is None
    assert second.envelope_payload["fact_snapshot_version"] == "fact-v8"
    assert second.envelope_payload["requested_action_args"] == {
        "mode": "safe",
        "resume": True,
    }
    assert second.envelope_payload["summary"] == "newer snapshot still requires explicit human decision"


def test_delivery_outbox_store_keeps_delivered_approval_stable_for_same_envelope_id(
    tmp_path: Path,
) -> None:
    store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    first_decision = _decision(
        decision_result="require_user_decision",
        action_ref="execute_recovery",
        approval_id="appr_001",
        fact_snapshot_version="fact-v7",
    )
    second_decision = _decision(
        decision_result="require_user_decision",
        action_ref="execute_recovery",
        approval_id="appr_001",
        fact_snapshot_version="fact-v8",
    ).model_copy(
        update={
            "decision_reason": "newer snapshot still requires explicit human decision",
            "why_escalated": "human_gate matched newer persisted facts",
            "idempotency_key": (
                "session:repo-a|fact-v8|policy-v1|require_user_decision|execute_recovery|appr_001"
            ),
            "decision_key": (
                "session:repo-a|fact-v8|policy-v1|require_user_decision|execute_recovery|appr_001"
            ),
        }
    )

    first = store.enqueue_envelopes(build_envelopes_for_decision(first_decision))[0]
    delivered = store.update_delivery_record(
        first.model_copy(
            update={
                "delivery_status": "delivered",
                "delivery_attempt": 1,
                "receipt_id": "rcpt_001",
                "updated_at": "2026-04-07T00:02:00Z",
            }
        )
    )
    second = store.enqueue_envelopes(build_envelopes_for_decision(second_decision))[0]

    assert second.envelope_id == first.envelope_id
    assert second.outbox_seq == first.outbox_seq
    assert second.delivery_status == "delivered"
    assert second.delivery_attempt == 1
    assert second.receipt_id == "rcpt_001"
    assert second.fact_snapshot_version == delivered.fact_snapshot_version
    assert second.idempotency_key == delivered.idempotency_key
    assert second.envelope_payload["fact_snapshot_version"] == "fact-v7"
    assert second.envelope_payload["summary"] == first.envelope_payload["summary"]


def test_delivery_outbox_store_orders_same_session_by_fact_snapshot_then_outbox_seq(
    tmp_path: Path,
) -> None:
    store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")

    later_snapshot = store.enqueue_envelopes(
        build_envelopes_for_decision(
            _decision(
                decision_result="block_and_alert",
                fact_snapshot_version="fact-v10",
                action_ref="execute_recovery",
            )
        )
    )
    earlier_snapshot = store.enqueue_envelopes(
        build_envelopes_for_decision(
            _decision(
                decision_result="block_and_alert",
                fact_snapshot_version="fact-v2",
                action_ref="continue_session",
            )
        )
    )

    pending = store.list_pending_delivery_records(session_id="session:repo-a")

    assert [record.fact_snapshot_version for record in pending] == ["fact-v2", "fact-v10"]
    assert [record.envelope_id for record in pending] == [
        earlier_snapshot[0].envelope_id,
        later_snapshot[0].envelope_id,
    ]


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=str(tmp_path),
        delivery_initial_backoff_seconds=5.0,
        delivery_max_attempts=2,
        progress_summary_max_age_seconds=600.0,
        local_manual_activity_quiet_window_seconds=600.0,
    )


class _OrderedClient:
    def __init__(self, blocked_envelope_id: str) -> None:
        self.blocked_envelope_id = blocked_envelope_id
        self.calls: list[str] = []

    def deliver_record(self, record):
        from watchdog.services.delivery.http_client import DeliveryAttemptResult

        self.calls.append(record.envelope_id)
        if record.envelope_id == self.blocked_envelope_id:
            return DeliveryAttemptResult(
                envelope_id=record.envelope_id,
                delivery_status="retryable_failure",
                failure_code="upstream_503",
                accepted=False,
            )
        return DeliveryAttemptResult(
            envelope_id=record.envelope_id,
            delivery_status="delivered",
            receipt_id="rcpt_ok",
            accepted=True,
        )


class _SessionSpineStoreStub:
    def __init__(self, *, last_local_manual_activity_at: str | None) -> None:
        self._last_local_manual_activity_at = last_local_manual_activity_at

    def get(self, project_id: str):
        if project_id != "repo-a" or self._last_local_manual_activity_at is None:
            return None

        class _Record:
            def __init__(self, value: str) -> None:
                self.last_local_manual_activity_at = value

        return _Record(self._last_local_manual_activity_at)


class _NotificationObservingClient:
    def __init__(self, session_service: SessionService) -> None:
        self._session_service = session_service
        self.calls: list[str] = []
        self.visible_event_types_during_delivery: list[str] = []

    def deliver_record(self, record):
        from watchdog.services.delivery.http_client import DeliveryAttemptResult

        self.calls.append(record.envelope_id)
        self.visible_event_types_during_delivery = [
            event.event_type
            for event in self._session_service.list_events(
                session_id=record.session_id,
                related_id_key="envelope_id",
                related_id_value=record.envelope_id,
            )
        ]
        return DeliveryAttemptResult(
            envelope_id=record.envelope_id,
            delivery_status="delivered",
            receipt_id="rcpt_notification",
            received_at="2026-04-07T00:20:02Z",
            accepted=True,
        )


class _RouteObservingClient:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.payloads: list[dict[str, object]] = []

    def deliver_record(self, record):
        from watchdog.services.delivery.http_client import DeliveryAttemptResult

        self.calls.append(record.envelope_id)
        self.payloads.append(dict(record.envelope_payload))
        return DeliveryAttemptResult(
            envelope_id=record.envelope_id,
            delivery_status="delivered",
            receipt_id="rcpt_route",
            accepted=True,
        )


class _FailingSessionService:
    def __init__(self, error: Exception) -> None:
        self._error = error
        self.calls: list[str] = []

    def record_event(self, **kwargs):
        self.calls.append(str(kwargs["event_type"]))
        raise self._error


def test_delivery_worker_blocks_later_records_in_same_session_while_head_is_retrying(
    tmp_path: Path,
) -> None:
    from datetime import datetime, timezone

    store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    first = store.enqueue_envelopes(
        build_envelopes_for_decision(
            _decision(
                decision_result="block_and_alert",
                fact_snapshot_version="fact-v7",
                action_ref="execute_recovery",
            )
        )
    )[0]
    second = store.enqueue_envelopes(
        build_envelopes_for_decision(
            _decision(
                decision_result="block_and_alert",
                fact_snapshot_version="fact-v8",
                action_ref="continue_session",
            )
        )
    )[0]

    client = _OrderedClient(first.envelope_id)
    worker = DeliveryWorker(store=store, delivery_client=client, settings=_settings(tmp_path))

    first_attempt = worker.process_next_ready(
        now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=timezone.utc),
        session_id="session:repo-a",
    )
    blocked = worker.process_next_ready(
        now=datetime(2026, 4, 7, 0, 0, 1, tzinfo=timezone.utc),
        session_id="session:repo-a",
    )

    assert first_attempt is not None
    assert first_attempt.envelope_id == first.envelope_id
    assert first_attempt.delivery_status == "retrying"
    assert blocked is None
    assert client.calls == [first.envelope_id]
    assert store.get_delivery_record(second.envelope_id).delivery_status == "pending"


def test_delivery_worker_does_not_block_other_sessions_when_one_session_head_is_waiting_for_retry(
    tmp_path: Path,
) -> None:
    from datetime import datetime, timezone

    store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    blocked = store.enqueue_envelopes(
        build_envelopes_for_decision(
            _decision(
                project_id="repo-a",
                session_id="session:repo-a",
                thread_id="session:repo-a",
                native_thread_id="thr_native_1",
                fact_snapshot_version="fact-v7",
            )
        )
    )[0]
    ready = store.enqueue_envelopes(
        build_envelopes_for_decision(
            _decision(
                project_id="repo-b",
                session_id="session:repo-b",
                thread_id="session:repo-b",
                native_thread_id="thr_native_2",
                fact_snapshot_version="fact-v3",
            )
        )
    )[0]
    store.update_delivery_record(
        blocked.model_copy(
            update={
                "delivery_status": "retrying",
                "delivery_attempt": 1,
                "next_retry_at": "2026-04-07T00:00:30Z",
            }
        )
    )

    client = _OrderedClient("never-match")
    worker = DeliveryWorker(store=store, delivery_client=client, settings=_settings(tmp_path))

    delivered = worker.process_next_ready(
        now=datetime(2026, 4, 7, 0, 0, 5, tzinfo=timezone.utc),
    )

    assert delivered is not None
    assert delivered.envelope_id == ready.envelope_id
    assert client.calls == [ready.envelope_id]


def test_delivery_worker_records_notification_session_events_in_delivery_order(
    tmp_path: Path,
) -> None:
    from datetime import datetime, timezone

    service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    (record,) = store.enqueue_envelopes(
        [
            _notification(
                envelope_id="notification-envelope:session-events",
                correlation_id="progress-summary:repo-a:session-events",
                event_id="event:notification-session-events",
            )
        ]
    )

    client = _NotificationObservingClient(service)
    worker = DeliveryWorker(
        store=store,
        delivery_client=client,
        settings=_settings(tmp_path),
        session_service=service,
    )

    delivered = worker.process_next_ready(
        now=datetime(2026, 4, 7, 0, 20, 1, tzinfo=timezone.utc),
        session_id="session:repo-a",
    )

    assert delivered is not None
    assert delivered.envelope_id == record.envelope_id
    assert delivered.delivery_status == "delivered"
    assert client.calls == [record.envelope_id]
    assert client.visible_event_types_during_delivery == ["notification_announced"]

    events = service.list_events(
        session_id="session:repo-a",
        related_id_key="envelope_id",
        related_id_value=record.envelope_id,
    )

    assert [event.event_type for event in events] == [
        "notification_announced",
        "notification_delivery_succeeded",
        "notification_receipt_recorded",
    ]
    assert events[0].payload["notification_kind"] == "progress_summary"
    assert events[1].payload["delivery_attempt"] == 1
    assert events[1].payload["delivery_status"] == "delivered"
    assert events[2].related_ids["receipt_id"] == "rcpt_notification"
    assert events[2].payload["received_at"] == "2026-04-07T00:20:02Z"


def test_delivery_worker_fails_closed_before_notification_side_effect_when_session_barrier_errors(
    tmp_path: Path,
) -> None:
    from datetime import datetime, timezone

    store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    (record,) = store.enqueue_envelopes(
        [
            _notification(
                envelope_id="notification-envelope:session-barrier-failure",
                correlation_id="progress-summary:repo-a:session-barrier-failure",
                event_id="event:notification-session-barrier-failure",
            )
        ]
    )
    barrier_error = RuntimeError("announce barrier offline")
    failing_service = _FailingSessionService(barrier_error)
    client = _OrderedClient("never-match")
    worker = DeliveryWorker(
        store=store,
        delivery_client=client,
        settings=_settings(tmp_path),
        session_service=failing_service,
    )

    with pytest.raises(RuntimeError, match="announce barrier offline"):
        worker.process_next_ready(
            now=datetime(2026, 4, 7, 0, 20, 1, tzinfo=timezone.utc),
            session_id="session:repo-a",
        )

    assert failing_service.calls == ["notification_announced"]
    assert client.calls == []
    persisted = store.get_delivery_record(record.envelope_id)
    assert persisted.delivery_status == "pending"
    assert persisted.delivery_attempt == 0


def test_delivery_worker_resolves_feishu_route_from_latest_session_event(
    tmp_path: Path,
) -> None:
    from datetime import datetime, timezone

    service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    service.record_event(
        event_type="goal_contract_revised",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:goal-contract:repo-a:goal-v8",
        causation_id="evt-feishu-route",
        occurred_at="2026-04-07T00:19:30Z",
        related_ids={
            "feishu_actor_id": "ou_actor_1",
            "feishu_receive_id": "ou_actor_1",
            "feishu_receive_id_type": "open_id",
        },
        payload={"contract": {"version": "goal-v8"}},
    )
    store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    (record,) = store.enqueue_envelopes([_notification(envelope_id="notification-envelope:route-ok")])
    client = _RouteObservingClient()
    worker = DeliveryWorker(
        store=store,
        delivery_client=client,
        settings=_settings(tmp_path).model_copy(update={"delivery_transport": "feishu"}),
        session_service=service,
    )

    delivered = worker.process_next_ready(
        now=datetime(2026, 4, 7, 0, 20, 1, tzinfo=timezone.utc),
        session_id="session:repo-a",
    )

    assert delivered is not None
    assert delivered.delivery_status == "delivered"
    assert client.calls == [record.envelope_id]
    assert client.payloads[0]["receive_id"] == "ou_actor_1"
    assert client.payloads[0]["receive_id_type"] == "open_id"

    persisted = store.get_delivery_record(record.envelope_id)
    assert persisted is not None
    assert persisted.envelope_payload["receive_id"] == "ou_actor_1"
    assert persisted.envelope_payload["receive_id_type"] == "open_id"


def test_delivery_worker_prefers_matching_interaction_family_feishu_route(
    tmp_path: Path,
) -> None:
    from datetime import datetime, timezone

    service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    service.record_event(
        event_type="goal_contract_created",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:goal-contract:repo-a:goal-v7",
        causation_id="evt-feishu-route-match",
        occurred_at="2026-04-07T00:18:30Z",
        related_ids={
            "interaction_family_id": "om_target",
            "feishu_receive_id": "ou_target_actor",
            "feishu_receive_id_type": "open_id",
        },
        payload={"contract": {"version": "goal-v7"}},
    )
    service.record_event(
        event_type="goal_contract_revised",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:goal-contract:repo-a:goal-v8",
        causation_id="evt-feishu-route-other",
        occurred_at="2026-04-07T00:19:30Z",
        related_ids={
            "interaction_family_id": "om_other",
            "feishu_receive_id": "ou_other_actor",
            "feishu_receive_id_type": "open_id",
        },
        payload={"contract": {"version": "goal-v8"}},
    )
    store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    (record,) = store.enqueue_envelopes(
        [
            _notification(envelope_id="notification-envelope:route-family").model_copy(
                update={"interaction_family_id": "om_target"}
            )
        ]
    )
    client = _RouteObservingClient()
    worker = DeliveryWorker(
        store=store,
        delivery_client=client,
        settings=_settings(tmp_path).model_copy(update={"delivery_transport": "feishu"}),
        session_service=service,
    )

    delivered = worker.process_next_ready(
        now=datetime(2026, 4, 7, 0, 20, 1, tzinfo=timezone.utc),
        session_id="session:repo-a",
    )

    assert delivered is not None
    assert delivered.delivery_status == "delivered"
    assert client.payloads[0]["receive_id"] == "ou_target_actor"
    assert client.payloads[0]["receive_id_type"] == "open_id"


def test_delivery_worker_prefers_latest_feishu_route_when_history_contains_multiple_candidates(
    tmp_path: Path,
) -> None:
    from datetime import datetime, timezone

    service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    service.record_event(
        event_type="goal_contract_created",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:goal-contract:repo-a:goal-v7",
        causation_id="evt-feishu-route-a",
        occurred_at="2026-04-07T00:18:30Z",
        related_ids={
            "feishu_receive_id": "ou_route_a",
            "feishu_receive_id_type": "open_id",
        },
        payload={"contract": {"version": "goal-v7"}},
    )
    service.record_event(
        event_type="goal_contract_revised",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:goal-contract:repo-a:goal-v8",
        causation_id="evt-feishu-route-b",
        occurred_at="2026-04-07T00:19:30Z",
        related_ids={
            "feishu_receive_id": "ou_route_b",
            "feishu_receive_id_type": "open_id",
        },
        payload={"contract": {"version": "goal-v8"}},
    )
    store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    (record,) = store.enqueue_envelopes([_notification(envelope_id="notification-envelope:route-ambiguous")])
    worker = DeliveryWorker(
        store=store,
        delivery_client=_RouteObservingClient(),
        settings=_settings(tmp_path).model_copy(update={"delivery_transport": "feishu"}),
        session_service=service,
    )

    updated = worker._apply_dynamic_delivery_route(
        record=record,
        now=datetime(2026, 4, 7, 0, 20, 1, tzinfo=timezone.utc),
    )

    latest_route_event = service.list_events(session_id="session:repo-a")[-1]
    assert updated.envelope_payload["receive_id"] == "ou_route_b"
    assert updated.envelope_payload["receive_id_type"] == "open_id"
    assert updated.operator_notes[-1].startswith("delivery_route_resolved ")
    assert f"source_event_id={latest_route_event.event_id}" in updated.operator_notes[-1]
    persisted = store.get_delivery_record(record.envelope_id)
    assert persisted is not None
    assert persisted.envelope_payload["receive_id"] == "ou_route_b"
    assert persisted.envelope_payload["receive_id_type"] == "open_id"


def test_delivery_worker_records_notification_requeued_after_retryable_failure(
    tmp_path: Path,
) -> None:
    from datetime import datetime, timezone

    service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    (record,) = store.enqueue_envelopes(
        [
            _notification(
                envelope_id="notification-envelope:retry-requeued",
                correlation_id="progress-summary:repo-a:retry-requeued",
                event_id="event:notification-retry-requeued",
            )
        ]
    )
    client = _OrderedClient(record.envelope_id)
    worker = DeliveryWorker(
        store=store,
        delivery_client=client,
        settings=_settings(tmp_path),
        session_service=service,
    )

    retried = worker.process_next_ready(
        now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=timezone.utc),
        session_id="session:repo-a",
    )

    assert retried is not None
    assert retried.delivery_status == "retrying"
    events = service.list_events(
        session_id="session:repo-a",
        related_id_key="envelope_id",
        related_id_value=record.envelope_id,
    )
    assert [event.event_type for event in events] == [
        "notification_announced",
        "notification_delivery_failed",
        "notification_requeued",
    ]
    assert events[1].payload["failure_code"] == "upstream_503"
    assert events[2].payload["reason"] == "retryable_delivery_failure"
    assert events[2].payload["next_retry_at"] == "2026-04-07T00:00:05Z"
    assert events[2].payload["delivery_attempt"] == 1


def test_delivery_worker_replays_notification_delivery_result_idempotently(
    tmp_path: Path,
) -> None:
    service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    (record,) = store.enqueue_envelopes([_notification(envelope_id="notification-envelope:replay-ok")])
    worker = DeliveryWorker(
        store=store,
        delivery_client=_OrderedClient("never-match"),
        settings=_settings(tmp_path),
        session_service=service,
    )
    payload = dict(record.envelope_payload)
    result = DeliveryAttemptResult(
        envelope_id=record.envelope_id,
        delivery_status="delivered",
        accepted=True,
        status_code=200,
        receipt_id="rcpt_notification",
        received_at="2026-04-07T00:20:02Z",
    )

    worker._record_notification_delivery_result(
        record=record.model_copy(update={"delivery_attempt": 1}),
        payload=payload,
        result=result,
    )
    worker._record_notification_delivery_result(
        record=record.model_copy(update={"delivery_attempt": 1}),
        payload=payload,
        result=result,
    )

    events = service.list_events(
        session_id="session:repo-a",
        related_id_key="envelope_id",
        related_id_value=record.envelope_id,
    )
    assert [event.event_type for event in events] == [
        "notification_delivery_succeeded",
        "notification_receipt_recorded",
    ]


def test_delivery_worker_replays_notification_requeued_idempotently(
    tmp_path: Path,
) -> None:
    service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    (record,) = store.enqueue_envelopes([_notification(envelope_id="notification-envelope:requeue-replay-ok")])
    worker = DeliveryWorker(
        store=store,
        delivery_client=_OrderedClient("never-match"),
        settings=_settings(tmp_path),
        session_service=service,
    )
    payload = dict(record.envelope_payload)

    worker._record_notification_requeued(
        record=record.model_copy(update={"delivery_attempt": 1}),
        payload=payload,
        reason="retryable_delivery_failure",
        next_retry_at="2026-04-07T00:00:05Z",
        failure_code="upstream_503",
    )
    worker._record_notification_requeued(
        record=record.model_copy(update={"delivery_attempt": 1}),
        payload=payload,
        reason="retryable_delivery_failure",
        next_retry_at="2026-04-07T00:00:05Z",
        failure_code="upstream_503",
    )

    events = service.list_events(
        session_id="session:repo-a",
        related_id_key="envelope_id",
        related_id_value=record.envelope_id,
    )
    assert [event.event_type for event in events] == ["notification_requeued"]


def test_delivery_worker_does_not_reannounce_notification_on_retry(
    tmp_path: Path,
) -> None:
    from datetime import datetime, timezone

    service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    (record,) = store.enqueue_envelopes(
        [
            _notification(
                envelope_id="notification-envelope:retry-no-reannounce",
                correlation_id="progress-summary:repo-a:retry-no-reannounce",
                event_id="event:notification-retry-no-reannounce",
            )
        ]
    )
    client = _OrderedClient(record.envelope_id)
    worker = DeliveryWorker(
        store=store,
        delivery_client=client,
        settings=_settings(tmp_path),
        session_service=service,
    )

    first = worker.process_next_ready(
        now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=timezone.utc),
        session_id="session:repo-a",
    )
    second = worker.process_next_ready(
        now=datetime(2026, 4, 7, 0, 0, 5, tzinfo=timezone.utc),
        session_id="session:repo-a",
    )

    assert first is not None
    assert first.delivery_status == "retrying"
    assert second is not None
    assert second.delivery_status == "delivery_failed"
    events = service.list_events(
        session_id="session:repo-a",
        related_id_key="envelope_id",
        related_id_value=record.envelope_id,
    )
    assert [event.event_type for event in events] == [
        "notification_announced",
        "notification_delivery_failed",
        "notification_requeued",
        "notification_delivery_failed",
    ]


def test_delivery_worker_raises_on_notification_announcement_payload_drift(
    tmp_path: Path,
) -> None:
    service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    (record,) = store.enqueue_envelopes(
        [
            _notification(
                envelope_id="notification-envelope:announce-drift",
                correlation_id="progress-summary:repo-a:announce-drift",
                event_id="event:notification-announce-drift",
                summary="still coding locally",
            )
        ]
    )
    worker = DeliveryWorker(
        store=store,
        delivery_client=_OrderedClient("never-match"),
        settings=_settings(tmp_path),
        session_service=service,
    )

    worker._record_notification_announced(record=record, payload=record.envelope_payload)
    (refreshed,) = store.enqueue_envelopes(
        [
            _notification(
                envelope_id=record.envelope_id,
                correlation_id=record.correlation_id,
                event_id="event:notification-announce-drift",
                summary="still coding locally",
            ).model_copy(
                update={
                    "facts": [
                        {
                            "fact_id": "fact-2",
                            "fact_code": "context_shifted",
                            "summary": "context changed",
                        }
                    ],
                    "recommended_actions": [
                        {
                            "action_code": "continue_session",
                            "label": "continue session",
                            "action_ref": "continue_session",
                        }
                    ],
                }
            )
        ]
    )

    with pytest.raises(ValueError, match="conflicting session event for idempotency key"):
        worker._record_notification_announced(
            record=refreshed,
            payload=refreshed.envelope_payload,
        )

    events = service.list_events(
        session_id=record.session_id,
        related_id_key="envelope_id",
        related_id_value=record.envelope_id,
    )
    assert len(events) == 1
    assert events[0].payload["summary"] == "still coding locally"
    assert events[0].payload["facts"] == []
    assert events[0].payload["recommended_actions"] == []


def test_delivery_worker_records_dead_letter_note_when_retry_budget_is_exhausted(
    tmp_path: Path,
) -> None:
    from datetime import datetime, timezone

    store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    first = store.enqueue_envelopes(
        build_envelopes_for_decision(
            _decision(
                decision_result="block_and_alert",
                fact_snapshot_version="fact-v7",
            )
        )
    )[0]

    client = _OrderedClient(first.envelope_id)
    worker = DeliveryWorker(store=store, delivery_client=client, settings=_settings(tmp_path))

    worker.process_next_ready(
        now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=timezone.utc),
        session_id="session:repo-a",
    )
    failed = worker.process_next_ready(
        now=datetime(2026, 4, 7, 0, 0, 6, tzinfo=timezone.utc),
        session_id="session:repo-a",
    )

    assert failed is not None
    assert failed.delivery_status == "delivery_failed"
    assert failed.failure_code == "upstream_503"
    assert failed.operator_notes[-2] == (
        "delivery_retry_scheduled "
        "failure_code=upstream_503 attempts=1 "
        "next_retry_at=2026-04-07T00:00:05Z"
    )
    assert failed.operator_notes[-1] == "delivery_dead_letter failure_code=upstream_503 attempts=2"


def test_delivery_worker_records_retry_note_with_next_retry_at(
    tmp_path: Path,
) -> None:
    from datetime import datetime, timezone

    store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    first = store.enqueue_envelopes(
        build_envelopes_for_decision(
            _decision(
                decision_result="block_and_alert",
                fact_snapshot_version="fact-v7",
            )
        )
    )[0]

    client = _OrderedClient(first.envelope_id)
    worker = DeliveryWorker(store=store, delivery_client=client, settings=_settings(tmp_path))

    retried = worker.process_next_ready(
        now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=timezone.utc),
        session_id="session:repo-a",
    )

    assert retried is not None
    assert retried.delivery_status == "retrying"
    assert retried.operator_notes[-1] == (
        "delivery_retry_scheduled "
        "failure_code=upstream_503 attempts=1 "
        "next_retry_at=2026-04-07T00:00:05Z"
    )


def test_delivery_worker_drops_stale_progress_summary_without_calling_downstream(
    tmp_path: Path,
) -> None:
    from datetime import datetime, timezone

    store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    stale_progress = NotificationEnvelope(
        envelope_id="notification-envelope:stale-progress",
        correlation_id="progress-summary:repo-a:stale",
        session_id="session:repo-a",
        project_id="repo-a",
        native_thread_id="thr_native_1",
        policy_version="policy-v1",
        fact_snapshot_version="fact-v7",
        idempotency_key="session:repo-a|fact-v7|progress_summary|stale",
        audit_ref="progress-summary:repo-a:fact-v7",
        created_at="2026-04-07T00:20:00Z",
        occurred_at="2026-04-07T00:00:00Z",
        event_id="event:stale-progress",
        severity="info",
        notification_kind="progress_summary",
        title="progress update for repo-a",
        summary="old progress",
        reason="phase=editing_source; context=low; stuck=0",
    )
    record = store.enqueue_envelopes([stale_progress])[0]

    client = _OrderedClient("never-match")
    worker = DeliveryWorker(store=store, delivery_client=client, settings=_settings(tmp_path))

    dropped = worker.process_next_ready(
        now=datetime(2026, 4, 7, 0, 20, 1, tzinfo=timezone.utc),
        session_id="session:repo-a",
    )

    assert dropped is not None
    assert dropped.envelope_id == record.envelope_id
    assert dropped.delivery_status == "delivery_failed"
    assert dropped.failure_code == "stale_progress_summary"
    assert dropped.delivery_attempt == 0
    assert dropped.operator_notes[-1] == (
        "delivery_skipped failure_code=stale_progress_summary "
        "occurred_at=2026-04-07T00:00:00Z age_seconds=1201"
    )
    assert client.calls == []


def test_build_progress_summary_envelope_normalizes_naive_occurred_at_to_utc() -> None:
    envelope = build_progress_summary_envelope(
        _progress_record(last_progress_at="2026-04-07T00:00:00"),
        created_at="2026-04-07T00:20:00Z",
    )

    assert envelope.occurred_at == "2026-04-07T00:00:00Z"


def test_delivery_worker_treats_naive_progress_summary_timestamp_as_utc(
    tmp_path: Path,
) -> None:
    from datetime import datetime, timezone

    store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    stale_progress = NotificationEnvelope(
        envelope_id="notification-envelope:naive-stale-progress",
        correlation_id="progress-summary:repo-a:naive-stale",
        session_id="session:repo-a",
        project_id="repo-a",
        native_thread_id="thr_native_1",
        policy_version="policy-v1",
        fact_snapshot_version="fact-v7",
        idempotency_key="session:repo-a|fact-v7|progress_summary|naive-stale",
        audit_ref="progress-summary:repo-a:fact-v7",
        created_at="2026-04-07T00:20:00Z",
        occurred_at="2026-04-07T00:00:00",
        event_id="event:naive-stale-progress",
        severity="info",
        notification_kind="progress_summary",
        title="progress update for repo-a",
        summary="old progress",
        reason="phase=editing_source; context=low; stuck=0",
    )
    record = store.enqueue_envelopes([stale_progress])[0]

    client = _OrderedClient("never-match")
    worker = DeliveryWorker(store=store, delivery_client=client, settings=_settings(tmp_path))

    dropped = worker.process_next_ready(
        now=datetime(2026, 4, 7, 0, 20, 1, tzinfo=timezone.utc),
        session_id="session:repo-a",
    )

    assert dropped is not None
    assert dropped.envelope_id == record.envelope_id
    assert dropped.delivery_status == "delivery_failed"
    assert dropped.failure_code == "stale_progress_summary"
    assert dropped.operator_notes[-1] == (
        "delivery_skipped failure_code=stale_progress_summary "
        "occurred_at=2026-04-07T00:00:00 age_seconds=1201"
    )
    assert client.calls == []


def test_delivery_worker_defers_non_critical_notifications_during_local_manual_activity_quiet_window(
    tmp_path: Path,
) -> None:
    from datetime import datetime, timezone

    service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    progress_summary = NotificationEnvelope(
        envelope_id="notification-envelope:quiet-progress",
        correlation_id="progress-summary:repo-a:quiet-window",
        session_id="session:repo-a",
        project_id="repo-a",
        native_thread_id="thr_native_1",
        policy_version="policy-v1",
        fact_snapshot_version="fact-v7",
        idempotency_key="session:repo-a|fact-v7|progress_summary|quiet-window",
        audit_ref="progress-summary:repo-a:fact-v7",
        created_at="2026-04-07T00:20:00Z",
        occurred_at="2026-04-07T00:20:00Z",
        event_id="event:quiet-progress",
        severity="info",
        notification_kind="progress_summary",
        title="progress update for repo-a",
        summary="still coding locally",
        reason="phase=editing_source; context=low; stuck=0",
    )
    critical_rejection = NotificationEnvelope(
        envelope_id="notification-envelope:critical-rejection",
        correlation_id="approval:repo-a:critical-rejection",
        session_id="session:repo-a",
        project_id="repo-a",
        native_thread_id="thr_native_1",
        policy_version="policy-v1",
        fact_snapshot_version="fact-v7",
        idempotency_key="session:repo-a|fact-v7|approval_result|critical-rejection",
        audit_ref="approval-response:repo-a:critical-rejection",
        created_at="2026-04-07T00:20:00Z",
        occurred_at="2026-04-07T00:20:00Z",
        event_id="event:critical-rejection",
        severity="critical",
        notification_kind="approval_result",
        title="approval rejected",
        summary="approval rejected via reject",
        reason="operator rejected the action",
    )
    suppressed_record, delivered_record = store.enqueue_envelopes(
        [progress_summary, critical_rejection]
    )

    client = _OrderedClient("never-match")
    worker = DeliveryWorker(
        store=store,
        delivery_client=client,
        session_spine_store=_SessionSpineStoreStub(
            last_local_manual_activity_at="2026-04-07T00:19:50Z"
        ),
        session_service=service,
        settings=_settings(tmp_path),
    )

    suppressed = worker.process_next_ready(
        now=datetime(2026, 4, 7, 0, 20, 0, tzinfo=timezone.utc),
    )
    delivered = worker.process_next_ready(
        now=datetime(2026, 4, 7, 0, 20, 1, tzinfo=timezone.utc),
    )

    assert suppressed is not None
    assert suppressed.envelope_id == suppressed_record.envelope_id
    assert suppressed.delivery_status == "retrying"
    assert suppressed.failure_code == "suppressed_local_manual_activity"
    assert suppressed.delivery_attempt == 0
    assert suppressed.next_retry_at == "2026-04-07T00:29:50Z"
    assert suppressed.operator_notes[-1] == (
        "delivery_deferred failure_code=suppressed_local_manual_activity "
        "last_local_manual_activity_at=2026-04-07T00:19:50Z age_seconds=10 "
        "next_retry_at=2026-04-07T00:29:50Z"
    )

    assert delivered is not None
    assert delivered.envelope_id == delivered_record.envelope_id
    assert delivered.delivery_status == "delivered"
    assert client.calls == [delivered_record.envelope_id]
    suppressed_events = service.list_events(
        session_id="session:repo-a",
        related_id_key="envelope_id",
        related_id_value=suppressed_record.envelope_id,
    )
    delivered_events = service.list_events(
        session_id="session:repo-a",
        related_id_key="envelope_id",
        related_id_value=delivered_record.envelope_id,
    )
    assert [event.event_type for event in suppressed_events] == ["notification_requeued"]
    assert suppressed_events[0].payload["reason"] == "suppressed_local_manual_activity"
    assert suppressed_events[0].payload["next_retry_at"] == "2026-04-07T00:29:50Z"
    assert [event.event_type for event in delivered_events] == [
        "notification_announced",
        "notification_delivery_succeeded",
        "notification_receipt_recorded",
    ]


def test_delivery_worker_delivers_deferred_notification_after_local_manual_activity_quiet_window(
    tmp_path: Path,
) -> None:
    from datetime import datetime, timezone

    store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    progress_summary = NotificationEnvelope(
        envelope_id="notification-envelope:quiet-progress-followup",
        correlation_id="progress-summary:repo-a:quiet-window-followup",
        session_id="session:repo-a",
        project_id="repo-a",
        native_thread_id="thr_native_1",
        policy_version="policy-v1",
        fact_snapshot_version="fact-v7",
        idempotency_key="session:repo-a|fact-v7|progress_summary|quiet-window-followup",
        audit_ref="progress-summary:repo-a:fact-v7",
        created_at="2026-04-07T00:20:00Z",
        occurred_at="2026-04-07T00:20:00Z",
        event_id="event:quiet-progress-followup",
        severity="info",
        notification_kind="progress_summary",
        title="progress update for repo-a",
        summary="still coding locally",
        reason="phase=editing_source; context=low; stuck=0",
    )
    (record,) = store.enqueue_envelopes([progress_summary])

    client = _OrderedClient("never-match")
    worker = DeliveryWorker(
        store=store,
        delivery_client=client,
        session_spine_store=_SessionSpineStoreStub(
            last_local_manual_activity_at="2026-04-07T00:19:50Z"
        ),
        settings=_settings(tmp_path),
    )

    deferred = worker.process_next_ready(
        now=datetime(2026, 4, 7, 0, 20, 0, tzinfo=timezone.utc),
    )
    delivered = worker.process_next_ready(
        now=datetime(2026, 4, 7, 0, 29, 51, tzinfo=timezone.utc),
    )

    assert deferred is not None
    assert deferred.envelope_id == record.envelope_id
    assert deferred.delivery_status == "retrying"
    assert deferred.failure_code == "suppressed_local_manual_activity"
    assert deferred.delivery_attempt == 0
    assert deferred.next_retry_at == "2026-04-07T00:29:50Z"

    assert delivered is not None
    assert delivered.envelope_id == record.envelope_id
    assert delivered.delivery_status == "delivered"
    assert delivered.failure_code is None
    assert delivered.delivery_attempt == 1
    assert client.calls == [record.envelope_id]


def test_delivery_worker_attempts_stale_auto_execute_envelopes_downstream(
    tmp_path: Path,
) -> None:
    from datetime import datetime, timezone

    store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    stale_envelopes = [
        DecisionEnvelope(
            envelope_id="decision-envelope:stale-auto-execute",
            correlation_id="decision:repo-a:fact-v7:auto_execute_and_notify",
            session_id="session:repo-a",
            project_id="repo-a",
            native_thread_id="thr_native_1",
            policy_version="policy-v1",
            fact_snapshot_version="fact-v7",
            idempotency_key="session:repo-a|fact-v7|policy-v1|auto_execute_and_notify|execute_recovery|",
            audit_ref="decision:repo-a:fact-v7:auto_execute_and_notify",
            created_at="2026-04-07T00:20:00Z",
            occurred_at="2026-04-07T00:00:00Z",
            decision_id="decision:repo-a:fact-v7:auto_execute_and_notify",
            decision_result="auto_execute_and_notify",
            action_name="execute_recovery",
            action_args={},
            risk_class="none",
            decision_reason="old auto execute",
            facts=[],
            matched_policy_rules=["registered_action"],
            why_not_escalated="policy_allows_auto_execution",
        ),
        NotificationEnvelope(
            envelope_id="notification-envelope:stale-auto-execute",
            correlation_id="decision:repo-a:fact-v7:auto_execute_and_notify",
            session_id="session:repo-a",
            project_id="repo-a",
            native_thread_id="thr_native_1",
            policy_version="policy-v1",
            fact_snapshot_version="fact-v7",
            idempotency_key=(
                "session:repo-a|fact-v7|policy-v1|auto_execute_and_notify|execute_recovery||"
                "decision_result"
            ),
            audit_ref="decision:repo-a:fact-v7:auto_execute_and_notify",
            created_at="2026-04-07T00:20:00Z",
            event_id="event:stale-auto-execute",
            severity="info",
            notification_kind="decision_result",
            occurred_at="2026-04-07T00:00:00Z",
            decision_result="auto_execute_and_notify",
            action_name="execute_recovery",
            title="decision auto_execute_and_notify",
            summary="old auto execute",
            reason="old auto execute",
            facts=[],
            recommended_actions=[],
        ),
    ]
    decision_record, notification_record = store.enqueue_envelopes(stale_envelopes)

    client = _OrderedClient("never-match")
    worker = DeliveryWorker(store=store, delivery_client=client, settings=_settings(tmp_path))

    delivered_decision = worker.process_next_ready(
        now=datetime(2026, 4, 7, 0, 20, 1, tzinfo=timezone.utc),
        session_id="session:repo-a",
    )
    delivered_notification = worker.process_next_ready(
        now=datetime(2026, 4, 7, 0, 20, 1, tzinfo=timezone.utc),
        session_id="session:repo-a",
    )

    assert delivered_decision is not None
    assert delivered_decision.envelope_id == decision_record.envelope_id
    assert delivered_decision.delivery_status == "delivered"
    assert delivered_decision.failure_code is None
    assert delivered_decision.delivery_attempt == 1

    assert delivered_notification is not None
    assert delivered_notification.envelope_id == notification_record.envelope_id
    assert delivered_notification.delivery_status == "delivered"
    assert delivered_notification.failure_code is None
    assert delivered_notification.delivery_attempt == 1
    assert client.calls == [decision_record.envelope_id, notification_record.envelope_id]


def test_delivery_worker_attempts_legacy_auto_execute_notification_without_payload_decision_result(
    tmp_path: Path,
) -> None:
    from datetime import datetime, timezone

    store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    notification = NotificationEnvelope(
        envelope_id="notification-envelope:legacy-stale-auto-execute",
        correlation_id="decision:repo-a:fact-v7:auto_execute_and_notify",
        session_id="session:repo-a",
        project_id="repo-a",
        native_thread_id="thr_native_1",
        policy_version="policy-v1",
        fact_snapshot_version="fact-v7",
        idempotency_key=(
            "session:repo-a|fact-v7|policy-v1|auto_execute_and_notify|execute_recovery||"
            "decision_result"
        ),
        audit_ref="decision:repo-a:fact-v7:auto_execute_and_notify",
        created_at="2026-04-07T00:20:00Z",
        event_id="event:legacy-stale-auto-execute",
        severity="info",
        notification_kind="decision_result",
        occurred_at="2026-04-07T00:00:00Z",
        decision_result="auto_execute_and_notify",
        action_name="execute_recovery",
        title="decision auto_execute_and_notify",
        summary="old auto execute",
        reason="old auto execute",
        facts=[],
        recommended_actions=[],
    )
    (record,) = store.enqueue_envelopes([notification])
    legacy_payload = dict(record.envelope_payload)
    legacy_payload.pop("decision_result", None)
    store.update_delivery_record(record.model_copy(update={"envelope_payload": legacy_payload}))

    client = _OrderedClient("never-match")
    worker = DeliveryWorker(store=store, delivery_client=client, settings=_settings(tmp_path))

    delivered = worker.process_next_ready(
        now=datetime(2026, 4, 7, 0, 20, 1, tzinfo=timezone.utc),
        session_id="session:repo-a",
    )

    assert delivered is not None
    assert delivered.envelope_id == record.envelope_id
    assert delivered.delivery_status == "delivered"
    assert delivered.failure_code is None
    assert delivered.delivery_attempt == 1
    assert client.calls == [record.envelope_id]
