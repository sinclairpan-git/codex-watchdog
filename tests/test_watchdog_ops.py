from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from watchdog.contracts.session_spine.enums import ActionCode, ActionStatus, Effect, ReplyCode
from watchdog.contracts.session_spine.models import WatchdogActionResult
from watchdog.api.ops import build_ops_summary
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
            created_at="2099-01-01T00:20:00Z",
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


def test_build_ops_summary_ignores_delivery_skips_and_recovery_noops(tmp_path: Path) -> None:
    delivery_store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    receipt_store = ActionReceiptStore(tmp_path / "action_receipts.json")
    settings = Settings(data_dir=str(tmp_path))

    delivery_store.update_delivery_record(
        DeliveryOutboxRecord(
            envelope_id="notification-envelope:suppressed-local-manual",
            envelope_type="notification",
            correlation_id="progress-summary:repo-a",
            session_id="session:repo-a",
            project_id="repo-a",
            native_thread_id="thr_native_1",
            policy_version="policy-v1",
            fact_snapshot_version="fact-v7",
            idempotency_key="session:repo-a|fact-v7|progress_summary|suppressed",
            audit_ref="progress-summary:repo-a",
            created_at="2000-01-01T00:00:00Z",
            outbox_seq=1,
            delivery_status="delivery_failed",
            delivery_attempt=0,
            receipt_id=None,
            next_retry_at=None,
            failure_code="suppressed_local_manual_activity",
            operator_notes=["delivery_skipped failure_code=suppressed_local_manual_activity"],
            envelope_payload={},
        )
    )
    delivery_store.update_delivery_record(
        DeliveryOutboxRecord(
            envelope_id="notification-envelope:stale-progress",
            envelope_type="notification",
            correlation_id="progress-summary:repo-b",
            session_id="session:repo-b",
            project_id="repo-b",
            native_thread_id="thr_native_2",
            policy_version="policy-v1",
            fact_snapshot_version="fact-v8",
            idempotency_key="session:repo-b|fact-v8|progress_summary|stale",
            audit_ref="progress-summary:repo-b",
            created_at="2000-01-01T00:00:00Z",
            outbox_seq=2,
            delivery_status="delivery_failed",
            delivery_attempt=0,
            receipt_id=None,
            next_retry_at=None,
            failure_code="stale_progress_summary",
            operator_notes=["delivery_skipped failure_code=stale_progress_summary"],
            envelope_payload={},
        )
    )
    receipt_store.put(
        receipt_key(
            action_code=ActionCode.EXECUTE_RECOVERY,
            project_id="repo-a",
            approval_id=None,
            idempotency_key="session:repo-a|fact-v7|policy-v1|auto_execute_and_notify|execute_recovery|",
        ),
        WatchdogActionResult(
            action_code=ActionCode.EXECUTE_RECOVERY,
            project_id="repo-a",
            approval_id=None,
            idempotency_key=(
                "session:repo-a|fact-v7|policy-v1|auto_execute_and_notify|execute_recovery|"
            ),
            action_status=ActionStatus.NOOP,
            effect=Effect.NOOP,
            reply_code=ReplyCode.RECOVERY_EXECUTION_RESULT,
            message="recovery not executed because context is not critical",
            facts=[],
        ),
    )

    summary = build_ops_summary(data_dir=tmp_path, settings=settings)

    assert summary.status == "ok"
    assert summary.active_alerts == 0
    assert summary.alerts == []


def test_build_ops_summary_ignores_stale_delivery_failures(tmp_path: Path) -> None:
    delivery_store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    settings = Settings(
        data_dir=str(tmp_path),
        ops_delivery_failed_alert_window_seconds=900,
    )

    delivery_store.update_delivery_record(
        DeliveryOutboxRecord(
            envelope_id="notification-envelope:old-failure",
            envelope_type="notification",
            correlation_id="decision:repo-a",
            session_id="session:repo-a",
            project_id="repo-a",
            native_thread_id="thr_native_1",
            policy_version="policy-v1",
            fact_snapshot_version="fact-v7",
            idempotency_key="session:repo-a|fact-v7|decision_result|old",
            audit_ref="decision:repo-a",
            created_at="2000-01-01T00:00:00Z",
            outbox_seq=1,
            delivery_status="delivery_failed",
            delivery_attempt=3,
            receipt_id=None,
            next_retry_at=None,
            failure_code="upstream_502",
            operator_notes=["delivery_dead_letter failure_code=upstream_502 attempts=3"],
            envelope_payload={},
        )
    )

    summary = build_ops_summary(data_dir=tmp_path, settings=settings)

    assert summary.status == "ok"
    assert summary.active_alerts == 0
    assert summary.alerts == []


def test_build_ops_summary_keeps_recent_delivery_failures_active(tmp_path: Path) -> None:
    delivery_store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    settings = Settings(
        data_dir=str(tmp_path),
        ops_delivery_failed_alert_window_seconds=900,
    )

    delivery_store.update_delivery_record(
        DeliveryOutboxRecord(
            envelope_id="notification-envelope:recent-failure",
            envelope_type="notification",
            correlation_id="decision:repo-a",
            session_id="session:repo-a",
            project_id="repo-a",
            native_thread_id="thr_native_1",
            policy_version="policy-v1",
            fact_snapshot_version="fact-v7",
            idempotency_key="session:repo-a|fact-v7|decision_result|recent",
            audit_ref="decision:repo-a",
            created_at="2099-01-01T00:00:00Z",
            outbox_seq=1,
            delivery_status="delivery_failed",
            delivery_attempt=3,
            receipt_id=None,
            next_retry_at=None,
            failure_code="upstream_502",
            operator_notes=["delivery_dead_letter failure_code=upstream_502 attempts=3"],
            envelope_payload={},
        )
    )

    summary = build_ops_summary(data_dir=tmp_path, settings=settings)

    assert summary.status == "degraded"
    assert summary.active_alerts == 1
    assert [item.alert_code for item in summary.alerts] == ["delivery_failed"]


def test_build_ops_summary_uses_delivery_failure_update_time(tmp_path: Path) -> None:
    delivery_store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    settings = Settings(
        data_dir=str(tmp_path),
        ops_delivery_failed_alert_window_seconds=900,
    )

    delivery_store.update_delivery_record(
        DeliveryOutboxRecord(
            envelope_id="notification-envelope:late-failure",
            envelope_type="notification",
            correlation_id="decision:repo-a",
            session_id="session:repo-a",
            project_id="repo-a",
            native_thread_id="thr_native_1",
            policy_version="policy-v1",
            fact_snapshot_version="fact-v7",
            idempotency_key="session:repo-a|fact-v7|decision_result|late",
            audit_ref="decision:repo-a",
            created_at="2000-01-01T00:00:00Z",
            updated_at="2099-01-01T00:00:00Z",
            outbox_seq=1,
            delivery_status="delivery_failed",
            delivery_attempt=3,
            receipt_id=None,
            next_retry_at=None,
            failure_code="upstream_502",
            operator_notes=["delivery_dead_letter failure_code=upstream_502 attempts=3"],
            envelope_payload={},
        )
    )

    summary = build_ops_summary(data_dir=tmp_path, settings=settings)

    assert summary.status == "degraded"
    assert summary.active_alerts == 1
    assert [item.alert_code for item in summary.alerts] == ["delivery_failed"]


def test_build_ops_summary_counts_only_latest_pending_approval_per_session(tmp_path: Path) -> None:
    approval_store = CanonicalApprovalStore(tmp_path / "canonical_approvals.json")
    settings = Settings(data_dir=str(tmp_path))

    template_decision = CanonicalDecisionRecord(
        decision_id="decision:approval-template",
        decision_key="session:repo-a|fact-v1|policy-v1|require_user_decision|execute_recovery|approval-template",
        session_id="session:repo-a",
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="thr_native_1",
        approval_id="approval:template",
        action_ref="execute_recovery",
        trigger="resident_supervision",
        decision_result="require_user_decision",
        risk_class="human_gate",
        decision_reason="needs approval",
        matched_policy_rules=["human_gate"],
        why_not_escalated=None,
        why_escalated="destructive recovery needs approval",
        uncertainty_reasons=[],
        policy_version="policy-v1",
        fact_snapshot_version="fact-v1",
        idempotency_key=(
            "session:repo-a|fact-v1|policy-v1|require_user_decision|execute_recovery|approval-template"
        ),
        created_at="2000-01-01T00:00:00Z",
        operator_notes=[],
        evidence={},
    )

    def make_approval(
        *,
        approval_id: str,
        envelope_id: str,
        session_id: str,
        project_id: str,
        fact_snapshot_version: str,
        status: str,
        created_at: str,
    ) -> CanonicalApprovalRecord:
        return CanonicalApprovalRecord(
            approval_id=approval_id,
            envelope_id=envelope_id,
            approval_kind="canonical_user_decision",
            requested_action="execute_recovery",
            requested_action_args={},
            approval_token=f"approval-token:{approval_id}",
            decision_options=["approve", "reject", "execute_action"],
            policy_version="policy-v1",
            fact_snapshot_version=fact_snapshot_version,
            idempotency_key=(
                f"{session_id}|{fact_snapshot_version}|policy-v1|require_user_decision|"
                f"execute_recovery|{approval_id}|approval"
            ),
            project_id=project_id,
            session_id=session_id,
            thread_id=session_id,
            native_thread_id="thr_native_1",
            status=status,
            created_at=created_at,
            decided_at="2000-01-01T01:00:00Z" if status != "pending" else None,
            decided_by="policy-test" if status != "pending" else None,
            operator_notes=[],
            decision=template_decision.model_copy(
                update={
                    "decision_id": f"decision:{approval_id}",
                    "decision_key": (
                        f"{session_id}|{fact_snapshot_version}|policy-v1|require_user_decision|"
                        f"execute_recovery|{approval_id}"
                    ),
                    "session_id": session_id,
                    "project_id": project_id,
                    "thread_id": session_id,
                    "approval_id": approval_id,
                    "fact_snapshot_version": fact_snapshot_version,
                    "created_at": created_at,
                }
            ),
        )

    approval_store.put(
        make_approval(
            approval_id="approval:repo-a-old",
            envelope_id="approval-envelope:repo-a-old",
            session_id="session:repo-a",
            project_id="repo-a",
            fact_snapshot_version="fact-v1",
            status="pending",
            created_at="2000-01-01T00:00:00Z",
        )
    )
    approval_store.put(
        make_approval(
            approval_id="approval:repo-a-new",
            envelope_id="approval-envelope:repo-a-new",
            session_id="session:repo-a",
            project_id="repo-a",
            fact_snapshot_version="fact-v2",
            status="superseded",
            created_at="2000-01-01T00:10:00Z",
        )
    )
    approval_store.put(
        make_approval(
            approval_id="approval:repo-b-old",
            envelope_id="approval-envelope:repo-b-old",
            session_id="session:repo-b",
            project_id="repo-b",
            fact_snapshot_version="fact-v1",
            status="pending",
            created_at="2000-01-01T00:00:00Z",
        )
    )
    approval_store.put(
        make_approval(
            approval_id="approval:repo-b-new",
            envelope_id="approval-envelope:repo-b-new",
            session_id="session:repo-b",
            project_id="repo-b",
            fact_snapshot_version="fact-v2",
            status="pending",
            created_at="2000-01-01T00:10:00Z",
        )
    )

    summary = build_ops_summary(data_dir=tmp_path, settings=settings)

    assert summary.status == "degraded"
    assert summary.active_alerts == 1
    assert [item.alert_code for item in summary.alerts] == ["approval_pending_too_long"]
    assert summary.alerts[0].count == 1


def test_build_ops_summary_surfaces_runtime_gate_degradation_alert(tmp_path: Path) -> None:
    decision_store = PolicyDecisionStore(tmp_path / "policy_decisions.json")
    settings = Settings(data_dir=str(tmp_path))

    decision_store.put(
        CanonicalDecisionRecord(
            decision_id="decision:runtime-gate-1",
            decision_key=(
                "session:repo-a|fact-v7|policy-v1|block_and_alert|propose_execute|continue_session|"
            ),
            session_id="session:repo-a",
            project_id="repo-a",
            thread_id="session:repo-a",
            native_thread_id="thr_native_1",
            approval_id=None,
            action_ref="continue_session",
            trigger="resident_orchestrator",
            brain_intent="propose_execute",
            runtime_disposition="auto_execute_and_notify",
            decision_result="block_and_alert",
            risk_class="hard_block",
            decision_reason="release gate blocks autonomous execution",
            matched_policy_rules=["release_gate_degraded"],
            why_not_escalated=None,
            why_escalated="release gate verdict is not pass: report_load_failed",
            uncertainty_reasons=["report_load_failed"],
            policy_version="policy-v1",
            fact_snapshot_version="fact-v7",
            idempotency_key=(
                "session:repo-a|fact-v7|policy-v1|block_and_alert|"
                "propose_execute|continue_session|"
            ),
            created_at="2099-01-01T00:00:00Z",
            operator_notes=[],
            evidence={
                "release_gate_verdict": {
                    "status": "degraded",
                    "degrade_reason": "report_load_failed",
                    "report_id": "report:load_failed",
                    "report_hash": "sha256:load_failed",
                    "input_hash": "sha256:input",
                    "decision_trace_ref": "trace:1",
                    "approval_read_ref": "approval:none",
                }
            },
        )
    )

    summary = build_ops_summary(data_dir=tmp_path, settings=settings)

    assert summary.status == "degraded"
    assert summary.active_alerts == 1
    assert [item.alert_code for item in summary.alerts] == ["runtime_gate_report_load_failed"]
    assert summary.alerts[0].count == 1


def test_build_ops_summary_breaks_runtime_gate_alerts_down_by_degrade_reason(
    tmp_path: Path,
) -> None:
    decision_store = PolicyDecisionStore(tmp_path / "policy_decisions.json")
    settings = Settings(data_dir=str(tmp_path))

    def _runtime_gate_decision(*, decision_id: str, reason: str) -> CanonicalDecisionRecord:
        return CanonicalDecisionRecord(
            decision_id=decision_id,
            decision_key=(
                f"session:{decision_id}|fact-v7|policy-v1|block_and_alert|"
                f"propose_execute|continue_session|"
            ),
            session_id=f"session:{decision_id}",
            project_id=f"repo:{decision_id}",
            thread_id=f"session:{decision_id}",
            native_thread_id=f"thr_native:{decision_id}",
            approval_id=None,
            action_ref="continue_session",
            trigger="resident_orchestrator",
            brain_intent="propose_execute",
            runtime_disposition="auto_execute_and_notify",
            decision_result="block_and_alert",
            risk_class="hard_block",
            decision_reason="runtime gate blocks autonomous execution",
            matched_policy_rules=["release_gate_degraded"],
            why_not_escalated=None,
            why_escalated=f"release gate verdict is not pass: {reason}",
            uncertainty_reasons=[reason],
            policy_version="policy-v1",
            fact_snapshot_version="fact-v7",
            idempotency_key=(
                f"session:{decision_id}|fact-v7|policy-v1|block_and_alert|"
                "propose_execute|continue_session|"
            ),
            created_at="2099-01-01T00:00:00Z",
            operator_notes=[],
            evidence={},
        )

    decision_store.put(_runtime_gate_decision(decision_id="decision:expired-1", reason="report_expired"))
    decision_store.put(_runtime_gate_decision(decision_id="decision:expired-2", reason="report_expired"))
    decision_store.put(_runtime_gate_decision(decision_id="decision:stale-1", reason="approval_stale"))

    summary = build_ops_summary(data_dir=tmp_path, settings=settings)

    assert summary.status == "degraded"
    assert summary.active_alerts == 2
    assert [item.alert_code for item in summary.alerts] == [
        "runtime_gate_approval_stale",
        "runtime_gate_report_expired",
    ]
    counts = {item.alert_code: item.count for item in summary.alerts}
    assert counts == {
        "runtime_gate_approval_stale": 1,
        "runtime_gate_report_expired": 2,
    }


def test_build_ops_summary_normalizes_runtime_gate_reason_taxonomy(tmp_path: Path) -> None:
    decision_store = PolicyDecisionStore(tmp_path / "policy_decisions.json")
    settings = Settings(data_dir=str(tmp_path))

    def _runtime_gate_decision(*, decision_id: str, reason: str) -> CanonicalDecisionRecord:
        return CanonicalDecisionRecord(
            decision_id=decision_id,
            decision_key=(
                f"session:{decision_id}|fact-v7|policy-v1|block_and_alert|"
                "propose_execute|continue_session|"
            ),
            session_id=f"session:{decision_id}",
            project_id=f"repo:{decision_id}",
            thread_id=f"session:{decision_id}",
            native_thread_id=f"thr_native:{decision_id}",
            approval_id=None,
            action_ref="continue_session",
            trigger="resident_orchestrator",
            brain_intent="propose_execute",
            runtime_disposition="auto_execute_and_notify",
            decision_result="block_and_alert",
            risk_class="hard_block",
            decision_reason="runtime gate blocks autonomous execution",
            matched_policy_rules=["release_gate_degraded"],
            why_not_escalated=None,
            why_escalated=f"release gate verdict is not pass: {reason}",
            uncertainty_reasons=[reason],
            policy_version="policy-v1",
            fact_snapshot_version="fact-v7",
            idempotency_key=(
                f"session:{decision_id}|fact-v7|policy-v1|block_and_alert|"
                "propose_execute|continue_session|"
            ),
            created_at="2099-01-01T00:00:00Z",
            operator_notes=[],
            evidence={},
        )

    decision_store.put(
        _runtime_gate_decision(
            decision_id="decision:contract-1",
            reason="policy_engine_version_mismatch",
        )
    )
    decision_store.put(
        _runtime_gate_decision(
            decision_id="decision:contract-2",
            reason="tool_schema_hash_mismatch",
        )
    )
    decision_store.put(
        _runtime_gate_decision(
            decision_id="decision:validator-1",
            reason="memory_conflict",
        )
    )
    decision_store.put(
        _runtime_gate_decision(
            decision_id="decision:validator-2",
            reason="goal_contract_not_ready",
        )
    )

    summary = build_ops_summary(data_dir=tmp_path, settings=settings)

    assert summary.status == "degraded"
    assert summary.active_alerts == 2
    assert [item.alert_code for item in summary.alerts] == [
        "runtime_gate_contract_mismatch",
        "runtime_gate_validator_degraded",
    ]
    counts = {item.alert_code: item.count for item in summary.alerts}
    assert counts == {
        "runtime_gate_contract_mismatch": 2,
        "runtime_gate_validator_degraded": 2,
    }
