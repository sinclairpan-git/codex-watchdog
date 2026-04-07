from __future__ import annotations

from pathlib import Path

from watchdog.services.approvals.service import (
    CanonicalApprovalRecord,
    CanonicalApprovalResponseRecord,
)
from watchdog.services.delivery.envelopes import (
    build_envelopes_for_approval_response,
    build_envelopes_for_decision,
)
from watchdog.services.delivery.store import DeliveryOutboxStore
from watchdog.services.delivery.worker import DeliveryWorker
from watchdog.services.policy.decisions import CanonicalDecisionRecord
from watchdog.settings import Settings


def _decision(
    *,
    project_id: str = "repo-a",
    session_id: str = "session:repo-a",
    thread_id: str = "session:repo-a",
    native_thread_id: str = "thr_native_1",
    fact_snapshot_version: str = "fact-v7",
    decision_result: str = "auto_execute_and_notify",
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
    assert auto_execute[1].notification_kind == "decision_result"
    assert auto_execute[1].severity == "info"

    assert [envelope.envelope_type for envelope in require_user] == ["approval"]
    assert require_user[0].approval_id == "appr_001"
    assert require_user[0].requested_action == "execute_recovery"

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


def test_delivery_outbox_store_assigns_monotonic_outbox_seq_and_seeds_delivery_state(
    tmp_path: Path,
) -> None:
    store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")

    first = store.enqueue_envelopes(
        build_envelopes_for_decision(
            _decision(decision_result="auto_execute_and_notify", fact_snapshot_version="fact-v7")
        )
    )
    second = store.enqueue_envelopes(
        build_envelopes_for_decision(
            _decision(decision_result="block_and_alert", fact_snapshot_version="fact-v8")
        )
    )

    assert [record.outbox_seq for record in first + second] == [1, 2, 3]
    assert [record.delivery_status for record in first + second] == [
        "pending",
        "pending",
        "pending",
    ]


def test_delivery_outbox_store_orders_same_session_by_fact_snapshot_then_outbox_seq(
    tmp_path: Path,
) -> None:
    store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")

    later_snapshot = store.enqueue_envelopes(
        build_envelopes_for_decision(
            _decision(
                decision_result="auto_execute_and_notify",
                fact_snapshot_version="fact-v10",
                action_ref="execute_recovery",
            )
        )
    )
    earlier_snapshot = store.enqueue_envelopes(
        build_envelopes_for_decision(
            _decision(
                decision_result="auto_execute_and_notify",
                fact_snapshot_version="fact-v2",
                action_ref="continue_session",
            )
        )
    )

    pending = store.list_pending_delivery_records(session_id="session:repo-a")

    assert [record.fact_snapshot_version for record in pending] == [
        "fact-v2",
        "fact-v2",
        "fact-v10",
        "fact-v10",
    ]
    assert [record.envelope_id for record in pending] == [
        earlier_snapshot[0].envelope_id,
        earlier_snapshot[1].envelope_id,
        later_snapshot[0].envelope_id,
        later_snapshot[1].envelope_id,
    ]


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=str(tmp_path),
        delivery_initial_backoff_seconds=5.0,
        delivery_max_attempts=2,
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


def test_delivery_worker_blocks_later_records_in_same_session_while_head_is_retrying(
    tmp_path: Path,
) -> None:
    from datetime import datetime, timezone

    store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    first = store.enqueue_envelopes(
        build_envelopes_for_decision(
            _decision(
                decision_result="auto_execute_and_notify",
                fact_snapshot_version="fact-v7",
                action_ref="execute_recovery",
            )
        )
    )[0]
    second = store.enqueue_envelopes(
        build_envelopes_for_decision(
            _decision(
                decision_result="auto_execute_and_notify",
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


def test_delivery_worker_records_dead_letter_note_when_retry_budget_is_exhausted(
    tmp_path: Path,
) -> None:
    from datetime import datetime, timezone

    store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    first = store.enqueue_envelopes(
        build_envelopes_for_decision(
            _decision(
                decision_result="auto_execute_and_notify",
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
    assert failed.operator_notes[-1] == "delivery_failed failure_code=upstream_503 attempts=2"
