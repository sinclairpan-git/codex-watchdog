from __future__ import annotations

from pathlib import Path
import threading

from fastapi.testclient import TestClient

from watchdog.main import create_app
from watchdog.services.policy.decisions import CanonicalDecisionRecord
from watchdog.settings import Settings
from watchdog.storage.action_receipts import ActionReceiptStore


class FakeAClient:
    def __init__(self, *, context_pressure: str = "critical") -> None:
        self._context_pressure = context_pressure
        self.decision_calls: list[tuple[str, str, str, str]] = []
        self.handoff_calls: list[tuple[str, str]] = []
        self.resume_calls: list[tuple[str, str, str]] = []

    def get_envelope(self, project_id: str) -> dict[str, object]:
        return {
            "success": True,
            "data": {
                "project_id": project_id,
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "approval",
                "pending_approval": True,
                "last_summary": "waiting for approval",
                "files_touched": ["src/example.py"],
                "context_pressure": self._context_pressure,
                "stuck_level": 2,
                "failure_count": 3,
                "last_progress_at": "2026-04-05T05:20:00Z",
            },
        }

    def decide_approval(
        self,
        approval_id: str,
        *,
        decision: str,
        operator: str,
        note: str = "",
    ) -> dict[str, object]:
        self.decision_calls.append((approval_id, decision, operator, note))
        return {
            "success": True,
            "data": {
                "approval_id": approval_id,
                "status": "approved" if decision == "approve" else "rejected",
                "operator": operator,
                "note": note,
            },
        }

    def trigger_handoff(
        self,
        project_id: str,
        *,
        reason: str,
    ) -> dict[str, object]:
        self.handoff_calls.append((project_id, reason))
        return {
            "success": True,
            "data": {"handoff_file": f"/tmp/{project_id}.handoff.md", "summary": "handoff"},
        }

    def trigger_resume(
        self,
        project_id: str,
        *,
        mode: str,
        handoff_summary: str,
    ) -> dict[str, object]:
        self.resume_calls.append((project_id, mode, handoff_summary))
        return {
            "success": True,
            "data": {"project_id": project_id, "status": "running", "mode": mode},
        }


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
    )


def _decision(
    *,
    decision_result: str = "require_user_decision",
    action_ref: str = "execute_recovery",
    approval_id: str = "appr_001",
) -> CanonicalDecisionRecord:
    return CanonicalDecisionRecord(
        decision_id="decision:needs-human",
        decision_key=(
            "session:repo-a|fact-v7|policy-v1|require_user_decision|execute_recovery|appr_001"
        ),
        session_id="session:repo-a",
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="thr_native_1",
        approval_id=approval_id,
        action_ref=action_ref,
        trigger="resident_supervision",
        decision_result=decision_result,
        risk_class="human_gate",
        decision_reason="session requires explicit human decision",
        matched_policy_rules=["human_gate"],
        why_not_escalated=None,
        why_escalated="human_gate matched persisted facts",
        uncertainty_reasons=[],
        policy_version="policy-v1",
        fact_snapshot_version="fact-v7",
        idempotency_key=(
            "session:repo-a|fact-v7|policy-v1|require_user_decision|execute_recovery|appr_001"
        ),
        created_at="2026-04-07T00:00:00Z",
        operator_notes=[],
        evidence={
            "decision": {
                "action_ref": action_ref,
                "decision_result": decision_result,
            }
        },
    )


def test_materialize_canonical_approval_reuses_same_record_for_same_decision(tmp_path: Path) -> None:
    from watchdog.services.approvals.service import (
        CanonicalApprovalStore,
        materialize_canonical_approval,
    )
    from watchdog.services.delivery.store import DeliveryOutboxStore

    store = CanonicalApprovalStore(tmp_path / "canonical_approvals.json")
    delivery_store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")

    first = materialize_canonical_approval(
        _decision(),
        approval_store=store,
        delivery_outbox_store=delivery_store,
    )
    second = materialize_canonical_approval(
        _decision(),
        approval_store=store,
        delivery_outbox_store=delivery_store,
    )

    assert first.envelope_id == second.envelope_id
    assert first.approval_id == "appr_001"
    assert first.requested_action == "execute_recovery"
    assert first.decision_options == ["approve", "reject", "execute_action"]
    pending = delivery_store.list_pending_delivery_records(session_id=first.session_id)
    assert [record.envelope_type for record in pending] == ["approval"]
    assert pending[0].envelope_id == first.envelope_id


def test_approve_response_is_idempotent_and_executes_requested_action_once(
    tmp_path: Path,
) -> None:
    from watchdog.services.approvals.service import (
        ApprovalResponseStore,
        CanonicalApprovalStore,
        materialize_canonical_approval,
        respond_to_canonical_approval,
    )
    from watchdog.services.delivery.store import DeliveryOutboxStore

    client = FakeAClient(context_pressure="critical")
    approval_store = CanonicalApprovalStore(tmp_path / "canonical_approvals.json")
    response_store = ApprovalResponseStore(tmp_path / "approval_responses.json")
    receipt_store = ActionReceiptStore(tmp_path / "action_receipts.json")
    delivery_store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    approval = materialize_canonical_approval(
        _decision(),
        approval_store=approval_store,
        delivery_outbox_store=delivery_store,
    )

    first = respond_to_canonical_approval(
        envelope_id=approval.envelope_id,
        response_action="approve",
        client_request_id="req-001",
        operator="alice",
        note="looks safe",
        approval_store=approval_store,
        response_store=response_store,
        settings=_settings(tmp_path),
        client=client,
        receipt_store=receipt_store,
        delivery_outbox_store=delivery_store,
    )
    second = respond_to_canonical_approval(
        envelope_id=approval.envelope_id,
        response_action="approve",
        client_request_id="req-001",
        operator="alice",
        note="looks safe",
        approval_store=approval_store,
        response_store=response_store,
        settings=_settings(tmp_path),
        client=client,
        receipt_store=receipt_store,
        delivery_outbox_store=delivery_store,
    )

    assert client.decision_calls == [("appr_001", "approve", "alice", "looks safe")]
    assert client.handoff_calls == [("repo-a", "context_critical")]
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.approval_status == "approved"
    assert first.execution_result is not None
    assert first.execution_result.effect == "handoff_triggered"
    pending = delivery_store.list_pending_delivery_records(session_id=approval.session_id)
    assert [record.envelope_type for record in pending] == ["approval", "notification"]
    assert pending[1].envelope_payload["notification_kind"] == "approval_result"


def test_reject_response_records_rejection_without_executing_requested_action(
    tmp_path: Path,
) -> None:
    from watchdog.services.approvals.service import (
        ApprovalResponseStore,
        CanonicalApprovalStore,
        materialize_canonical_approval,
        respond_to_canonical_approval,
    )
    from watchdog.services.delivery.store import DeliveryOutboxStore

    client = FakeAClient(context_pressure="critical")
    approval_store = CanonicalApprovalStore(tmp_path / "canonical_approvals.json")
    response_store = ApprovalResponseStore(tmp_path / "approval_responses.json")
    delivery_store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    approval = materialize_canonical_approval(
        _decision(),
        approval_store=approval_store,
        delivery_outbox_store=delivery_store,
    )

    result = respond_to_canonical_approval(
        envelope_id=approval.envelope_id,
        response_action="reject",
        client_request_id="req-002",
        operator="bob",
        note="needs more evidence",
        approval_store=approval_store,
        response_store=response_store,
        settings=_settings(tmp_path),
        client=client,
        receipt_store=ActionReceiptStore(tmp_path / "action_receipts.json"),
        delivery_outbox_store=delivery_store,
    )

    assert client.decision_calls == [("appr_001", "reject", "bob", "needs more evidence")]
    assert client.handoff_calls == []
    assert result.approval_status == "rejected"
    assert result.execution_result is None
    pending = delivery_store.list_pending_delivery_records(session_id=approval.session_id)
    assert [record.envelope_type for record in pending] == ["approval", "notification"]
    assert pending[1].envelope_payload["severity"] == "critical"


def test_openclaw_response_api_uses_response_tuple_as_idempotency_key(tmp_path: Path) -> None:
    from watchdog.services.approvals.service import materialize_canonical_approval

    settings = _settings(tmp_path)
    app = create_app(settings=settings, a_client=FakeAClient(context_pressure="critical"))
    approval = materialize_canonical_approval(
        _decision(),
        approval_store=app.state.canonical_approval_store,
    )

    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {settings.api_token}"}
        body = {
            "envelope_id": approval.envelope_id,
            "envelope_type": "approval",
            "approval_id": approval.approval_id,
            "decision_id": approval.decision.decision_id,
            "response_action": "approve",
            "response_token": approval.approval_token,
            "user_ref": "user:carol",
            "channel_ref": "feishu:chat:approval-room",
            "client_request_id": "req-003",
            "operator": "carol",
            "note": "ship it",
        }

        first = client.post("/api/v1/watchdog/openclaw/responses", json=body, headers=headers)
        second = client.post("/api/v1/watchdog/openclaw/responses", json=body, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["success"] is True
    assert first.json()["data"] == second.json()["data"]


def test_concurrent_approval_responses_execute_side_effects_once(tmp_path: Path) -> None:
    from watchdog.services.approvals.service import (
        ApprovalResponseStore,
        CanonicalApprovalStore,
        materialize_canonical_approval,
        respond_to_canonical_approval,
    )
    from watchdog.services.delivery.store import DeliveryOutboxStore

    client = FakeAClient(context_pressure="critical")
    approval_store = CanonicalApprovalStore(tmp_path / "canonical_approvals.json")
    response_store = ApprovalResponseStore(tmp_path / "approval_responses.json")
    receipt_store = ActionReceiptStore(tmp_path / "action_receipts.json")
    delivery_store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    approval = materialize_canonical_approval(
        _decision(),
        approval_store=approval_store,
        delivery_outbox_store=delivery_store,
    )

    barrier = threading.Barrier(3)
    results: list[object] = []

    def _worker() -> None:
        barrier.wait()
        results.append(
            respond_to_canonical_approval(
                envelope_id=approval.envelope_id,
                response_action="approve",
                client_request_id="req-concurrent",
                operator="alice",
                note="looks safe",
                approval_store=approval_store,
                response_store=response_store,
                settings=_settings(tmp_path),
                client=client,
                receipt_store=receipt_store,
                delivery_outbox_store=delivery_store,
            )
        )

    first = threading.Thread(target=_worker)
    second = threading.Thread(target=_worker)
    first.start()
    second.start()
    barrier.wait()
    first.join()
    second.join()

    assert len(results) == 2
    assert results[0].model_dump(mode="json") == results[1].model_dump(mode="json")
    assert client.decision_calls == [("appr_001", "approve", "alice", "looks safe")]
    assert client.handoff_calls == [("repo-a", "context_critical")]
    pending = delivery_store.list_pending_delivery_records(session_id=approval.session_id)
    assert [record.envelope_type for record in pending] == ["approval", "notification"]
