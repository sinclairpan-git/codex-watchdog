from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from watchdog.contracts.session_spine.enums import ActionCode, ActionStatus, Effect, ReplyCode
from watchdog.contracts.session_spine.models import WatchdogActionResult
from watchdog.main import create_app
from watchdog.services.approvals.service import CanonicalApprovalRecord, CanonicalApprovalStore
from watchdog.services.delivery.store import DeliveryOutboxRecord, DeliveryOutboxStore
from watchdog.services.policy.decisions import CanonicalDecisionRecord, PolicyDecisionStore
from watchdog.settings import Settings
from watchdog.storage.action_receipts import ActionReceiptStore, receipt_key


def _seed_ops_alerts(data_dir: Path) -> None:
    decision_store = PolicyDecisionStore(data_dir / "policy_decisions.json")
    approval_store = CanonicalApprovalStore(data_dir / "canonical_approvals.json")
    delivery_store = DeliveryOutboxStore(data_dir / "delivery_outbox.json")
    receipt_store = ActionReceiptStore(data_dir / "action_receipts.json")

    blocked_decision = CanonicalDecisionRecord(
        decision_id="decision:blocked-1",
        decision_key="session:repo-a|fact-v9|policy-v1|block_and_alert|execute_recovery|",
        session_id="session:repo-a",
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="thr_native_1",
        approval_id=None,
        action_ref="execute_recovery",
        trigger="resident_supervision",
        decision_result="block_and_alert",
        risk_class="hard_block",
        decision_reason="mapping incomplete",
        matched_policy_rules=["hard_block"],
        why_not_escalated="controlled uncertainty",
        why_escalated=None,
        uncertainty_reasons=["mapping_incomplete"],
        policy_version="policy-v1",
        fact_snapshot_version="fact-v9",
        idempotency_key="session:repo-a|fact-v9|policy-v1|block_and_alert|execute_recovery|",
        created_at="2000-01-01T00:00:00Z",
        operator_notes=["uncertainty=mapping_incomplete"],
        evidence={},
    )
    decision_store.put(blocked_decision)

    pending_approval = CanonicalApprovalRecord(
        approval_id="appr_pending_1",
        envelope_id="approval-envelope:pending-1",
        approval_kind="canonical_user_decision",
        requested_action="execute_recovery",
        requested_action_args={},
        approval_token="approval-token:pending-1",
        decision_options=["approve", "reject", "execute_action"],
        policy_version="policy-v1",
        fact_snapshot_version="fact-v9",
        idempotency_key="session:repo-b|fact-v9|policy-v1|require_user_decision|execute_recovery|appr_pending_1|approval",
        project_id="repo-b",
        session_id="session:repo-b",
        thread_id="session:repo-b",
        native_thread_id="thr_native_2",
        status="pending",
        created_at="2000-01-01T00:10:00Z",
        decided_at=None,
        decided_by=None,
        operator_notes=["approval pending"],
        decision=blocked_decision.model_copy(
            update={
                "decision_id": "decision:approval-1",
                "decision_key": "session:repo-b|fact-v9|policy-v1|require_user_decision|execute_recovery|appr_pending_1",
                "session_id": "session:repo-b",
                "project_id": "repo-b",
                "thread_id": "session:repo-b",
                "decision_result": "require_user_decision",
                "risk_class": "human_gate",
                "uncertainty_reasons": [],
                "why_not_escalated": None,
                "why_escalated": "destructive recovery needs approval",
                "approval_id": "appr_pending_1",
                "created_at": "2000-01-01T00:10:00Z",
            }
        ),
    )
    approval_store.put(pending_approval)

    delivery_store.update_delivery_record(
        DeliveryOutboxRecord(
            envelope_id="notification-envelope:failed-1",
            envelope_type="notification",
            correlation_id="decision:blocked-1",
            session_id="session:repo-a",
            project_id="repo-a",
            native_thread_id="thr_native_1",
            policy_version="policy-v1",
            fact_snapshot_version="fact-v9",
            idempotency_key="decision:blocked-1|delivery",
            audit_ref="decision:blocked-1",
            created_at="2000-01-01T00:20:00Z",
            outbox_seq=1,
            delivery_status="delivery_failed",
            delivery_attempt=3,
            receipt_id=None,
            next_retry_at=None,
            failure_code="network_error",
            operator_notes=["delivery_failed failure_code=network_error attempts=3"],
            envelope_payload={},
        )
    )

    recovery_failed = WatchdogActionResult(
        action_code=ActionCode.EXECUTE_RECOVERY,
        project_id="repo-a",
        approval_id=None,
        idempotency_key="session:repo-a|fact-v9|policy-v1|block_and_alert|execute_recovery|",
        action_status=ActionStatus.ERROR,
        effect=Effect.NOOP,
        reply_code=ReplyCode.RECOVERY_EXECUTION_RESULT,
        message="recovery failed",
        facts=[],
    )
    receipt_store.put(
        receipt_key(
            action_code=recovery_failed.action_code,
            project_id=recovery_failed.project_id,
            approval_id=recovery_failed.approval_id,
            idempotency_key=recovery_failed.idempotency_key,
        ),
        recovery_failed,
    )


def test_watchdog_ops_alerts_and_healthz_report_degraded_status(tmp_path: Path) -> None:
    _seed_ops_alerts(tmp_path)

    app = create_app(Settings(api_token="wt", data_dir=str(tmp_path)))
    client = TestClient(app)

    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["status"] == "degraded"
    assert health.json()["active_alerts"] == 5

    alerts = client.get(
        "/api/v1/watchdog/ops/alerts",
        headers={"Authorization": "Bearer wt"},
    )
    assert alerts.status_code == 200
    payload = alerts.json()
    assert payload["success"] is True
    assert [item["alert_code"] for item in payload["data"]["alerts"]] == [
        "approval_pending_too_long",
        "blocked_too_long",
        "delivery_failed",
        "mapping_incomplete",
        "recovery_failed",
    ]


def test_watchdog_metrics_exports_critical_ops_alert_gauges(tmp_path: Path) -> None:
    _seed_ops_alerts(tmp_path)

    app = create_app(Settings(api_token="wt", data_dir=str(tmp_path)))
    client = TestClient(app)

    response = client.get("/metrics")
    assert response.status_code == 200
    assert 'watchdog_ops_alert_active{alert="approval_pending_too_long"} 1' in response.text
    assert 'watchdog_ops_alert_active{alert="blocked_too_long"} 1' in response.text
    assert 'watchdog_ops_alert_active{alert="delivery_failed"} 1' in response.text
    assert 'watchdog_ops_alert_active{alert="mapping_incomplete"} 1' in response.text
    assert 'watchdog_ops_alert_active{alert="recovery_failed"} 1' in response.text
