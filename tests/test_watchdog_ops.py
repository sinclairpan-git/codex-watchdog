from __future__ import annotations

import importlib
from pathlib import Path

from fastapi.testclient import TestClient

from watchdog.contracts.session_spine.enums import ActionCode, ActionStatus, Effect, ReplyCode
from watchdog.contracts.session_spine.models import WatchdogActionResult
from watchdog.api.ops import build_ops_summary
from watchdog.main import create_app
from watchdog.services.approvals.service import CanonicalApprovalRecord, CanonicalApprovalStore
from watchdog.services.delivery.store import DeliveryOutboxRecord, DeliveryOutboxStore
from watchdog.services.policy.decisions import CanonicalDecisionRecord, PolicyDecisionStore
from watchdog.services.session_service.service import SessionService
from watchdog.services.session_service.store import SessionServiceStore
from watchdog.settings import Settings
from watchdog.storage.action_receipts import ActionReceiptStore, receipt_key
from a_control_agent.storage.tasks_store import TaskStore


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


def test_watchdog_ops_can_requeue_historical_transport_failures(tmp_path: Path) -> None:
    app = create_app(Settings(api_token="wt", data_dir=str(tmp_path)))
    app.state.delivery_outbox_store.update_delivery_record(
        DeliveryOutboxRecord(
            envelope_id="notification-envelope:historical-failed",
            envelope_type="notification",
            correlation_id="corr:historical-failed",
            session_id="session:repo-a",
            project_id="repo-a",
            native_thread_id="thr_native_1",
            policy_version="policy-v1",
            fact_snapshot_version="fact-v7",
            idempotency_key="idem:historical-failed",
            audit_ref="audit:historical-failed",
            created_at="2099-01-01T00:20:00Z",
            updated_at="2099-01-01T00:21:00Z",
            outbox_seq=1,
            delivery_status="delivery_failed",
            delivery_attempt=3,
            failure_code="transport_error",
            operator_notes=["delivery_failed failure_code=transport_error attempts=3"],
            envelope_payload={
                "envelope_type": "notification",
                "event_id": "event:historical-failed",
                "notification_kind": "decision_result",
                "severity": "warning",
                "title": "decision update",
                "summary": "historical failed notification",
                "occurred_at": "2099-01-01T00:20:00Z",
            },
        )
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/watchdog/ops/delivery/requeue-transport-failures",
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["requeued"] == 1
    assert payload["data"]["envelope_ids"] == ["notification-envelope:historical-failed"]

    updated = app.state.delivery_outbox_store.get_delivery_record(
        "notification-envelope:historical-failed"
    )
    assert updated is not None
    assert updated.delivery_status == "pending"
    assert updated.failure_code is None
    assert updated.operator_notes[-1].startswith(
        "delivery_requeued reason=manual_transport_recovered"
    )

    events = app.state.session_service.list_events(
        session_id="session:repo-a",
        related_id_key="envelope_id",
        related_id_value="notification-envelope:historical-failed",
    )
    assert [event.event_type for event in events] == ["notification_requeued"]

    summary = build_ops_summary(
        data_dir=tmp_path,
        settings=Settings(api_token="wt", data_dir=str(tmp_path)),
        approval_store=app.state.canonical_approval_store,
        delivery_store=app.state.delivery_outbox_store,
        receipt_store=app.state.action_receipt_store,
        decision_store=app.state.policy_decision_store,
    )
    assert summary.active_alerts == 0


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
    assert 'watchdog_release_gate_blocker_active{reason="none"} 0' in response.text


def test_watchdog_ops_exposes_fixed_resident_expert_runtime_registry(tmp_path: Path) -> None:
    app = create_app(Settings(api_token="wt", data_dir=str(tmp_path)))
    client = TestClient(app)

    response = client.get(
        "/api/v1/watchdog/ops/resident-experts",
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    experts = payload["data"]["experts"]
    assert [expert["expert_id"] for expert in experts] == [
        "managed-agent-expert",
        "hermes-agent-expert",
    ]
    assert experts[0]["independence"] == "outside_project_delivery"
    assert experts[0]["status"] == "unavailable"
    assert experts[1]["display_name_zh_cn"] == "Hermes Agent专家"


def test_watchdog_ops_can_mark_resident_expert_consult_restore_state(tmp_path: Path) -> None:
    app = create_app(Settings(api_token="wt", data_dir=str(tmp_path)))
    client = TestClient(app)

    response = client.post(
        "/api/v1/watchdog/ops/resident-experts/consult",
        headers={"Authorization": "Bearer wt"},
        json={
            "expert_ids": ["managed-agent-expert"],
            "consultation_ref": "decision:resident:1",
            "observed_runtime_handles": {"managed-agent-expert": "agent:managed:1"},
            "consulted_at": "2026-04-18T06:10:00Z",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    experts = {expert["expert_id"]: expert for expert in payload["data"]["experts"]}
    assert experts["managed-agent-expert"]["status"] == "available"
    assert experts["managed-agent-expert"]["runtime_handle"] == "agent:managed:1"
    assert experts["managed-agent-expert"]["last_consultation_ref"] == "decision:resident:1"
    assert experts["managed-agent-expert"]["last_seen_at"] == "2026-04-18T06:10:00Z"
    assert experts["hermes-agent-expert"]["status"] == "unavailable"


def test_watchdog_ops_exposes_resident_expert_decision_audit_rows(tmp_path: Path) -> None:
    decision_store = PolicyDecisionStore(tmp_path / "policy_decisions.json")
    app = create_app(Settings(api_token="wt", data_dir=str(tmp_path)))
    client = TestClient(app)

    decision_store.put(
        CanonicalDecisionRecord(
            decision_id="decision:repo-a:recorded",
            decision_key="decision-key:repo-a:recorded",
            session_id="session:repo-a",
            project_id="repo-a",
            thread_id="session:repo-a",
            native_thread_id="thr_native_1",
            approval_id=None,
            action_ref="continue_session",
            trigger="resident_orchestrator",
            decision_result="block_and_alert",
            risk_class="hard_block",
            decision_reason="waiting for recovery",
            matched_policy_rules=["runtime_gate_missing"],
            why_not_escalated=None,
            why_escalated="recovery guard",
            uncertainty_reasons=["runtime_gate_missing"],
            policy_version="policy-v1",
            fact_snapshot_version="fact-v12",
            idempotency_key="idem:repo-a:recorded",
            created_at="2026-04-18T06:10:00Z",
            operator_notes=[],
            evidence={
                "resident_expert_consultation": {
                    "consultation_ref": "decision:repo-a:recorded",
                    "consulted_at": "2026-04-18T06:10:00Z",
                    "experts": [
                        {
                            "expert_id": "managed-agent-expert",
                            "status": "available",
                            "runtime_handle": "agent:managed:1",
                            "last_seen_at": "2026-04-18T06:09:00Z",
                            "last_consulted_at": "2026-04-18T06:10:00Z",
                            "last_consultation_ref": "decision:repo-a:recorded",
                        },
                        {
                            "expert_id": "hermes-agent-expert",
                            "status": "restoring",
                            "runtime_handle": "agent:hermes:1",
                            "last_seen_at": "2026-04-18T06:08:00Z",
                            "last_consulted_at": "2026-04-18T06:10:00Z",
                            "last_consultation_ref": "decision:repo-a:recorded",
                        },
                    ],
                }
            },
        )
    )
    decision_store.put(
        CanonicalDecisionRecord(
            decision_id="decision:repo-b:missing",
            decision_key="decision-key:repo-b:missing",
            session_id="session:repo-b",
            project_id="repo-b",
            thread_id="session:repo-b",
            native_thread_id="thr_native_2",
            approval_id=None,
            action_ref="continue_session",
            trigger="resident_orchestrator",
            decision_result="observe_only",
            risk_class="none",
            decision_reason="monitor only",
            matched_policy_rules=[],
            why_not_escalated="observe only",
            why_escalated=None,
            uncertainty_reasons=[],
            policy_version="policy-v1",
            fact_snapshot_version="fact-v13",
            idempotency_key="idem:repo-b:missing",
            created_at="2026-04-18T06:11:00Z",
            operator_notes=[],
            evidence={},
        )
    )

    response = client.get(
        "/api/v1/watchdog/ops/resident-experts/decision-audit",
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    rows = payload["data"]["decisions"]
    assert [row["decision_id"] for row in rows] == [
        "decision:repo-b:missing",
        "decision:repo-a:recorded",
    ]
    assert rows[0]["consultation_status"] == "missing"
    assert rows[0]["consultation_ref"] is None
    assert rows[0]["experts"] == []
    assert rows[1]["consultation_status"] == "recorded"
    assert rows[1]["consultation_ref"] == "decision:repo-a:recorded"
    assert rows[1]["consulted_at"] == "2026-04-18T06:10:00Z"
    assert [item["expert_id"] for item in rows[1]["experts"]] == [
        "managed-agent-expert",
        "hermes-agent-expert",
    ]
    assert [item["status"] for item in rows[1]["experts"]] == [
        "available",
        "restoring",
    ]


def test_watchdog_ops_can_filter_resident_expert_decision_audit_rows(tmp_path: Path) -> None:
    decision_store = PolicyDecisionStore(tmp_path / "policy_decisions.json")
    app = create_app(Settings(api_token="wt", data_dir=str(tmp_path)))
    client = TestClient(app)

    for decision_id, project_id, session_id in (
        ("decision:repo-a:1", "repo-a", "session:repo-a"),
        ("decision:repo-b:1", "repo-b", "session:repo-b"),
    ):
        decision_store.put(
            CanonicalDecisionRecord(
                decision_id=decision_id,
                decision_key=f"decision-key:{decision_id}",
                session_id=session_id,
                project_id=project_id,
                thread_id=session_id,
                native_thread_id=f"thr_native:{project_id}",
                approval_id=None,
                action_ref="continue_session",
                trigger="resident_orchestrator",
                decision_result="observe_only",
                risk_class="none",
                decision_reason="monitor only",
                matched_policy_rules=[],
                why_not_escalated="observe only",
                why_escalated=None,
                uncertainty_reasons=[],
                policy_version="policy-v1",
                fact_snapshot_version="fact-v1",
                idempotency_key=f"idem:{decision_id}",
                created_at="2026-04-18T06:10:00Z",
                operator_notes=[],
                evidence={
                    "resident_expert_consultation": {
                        "consultation_ref": decision_id,
                        "consulted_at": "2026-04-18T06:10:00Z",
                        "experts": [],
                    }
                },
            )
        )

    response = client.get(
        "/api/v1/watchdog/ops/resident-experts/decision-audit",
        headers={"Authorization": "Bearer wt"},
        params={"project_id": "repo-b"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    rows = payload["data"]["decisions"]
    assert [row["decision_id"] for row in rows] == ["decision:repo-b:1"]
    assert rows[0]["project_id"] == "repo-b"
    assert rows[0]["session_id"] == "session:repo-b"


def test_watchdog_healthz_degrades_when_release_gate_blocker_exists_without_alert_bucket(
    tmp_path: Path,
) -> None:
    decision_store = PolicyDecisionStore(tmp_path / "policy_decisions.json")
    app = create_app(Settings(api_token="wt", data_dir=str(tmp_path)))
    client = TestClient(app)

    decision_store.put(
        CanonicalDecisionRecord(
            decision_id="decision:healthz-release-gate",
            decision_key=(
                "session:repo-a|fact-v7|policy-v1|observe_only|"
                "propose_execute|continue_session|"
            ),
            session_id="session:repo-a",
            project_id="repo-a",
            thread_id="session:repo-a",
            native_thread_id="thr_native_1",
            approval_id=None,
            action_ref="continue_session",
            trigger="resident_orchestrator",
            brain_intent="propose_execute",
            runtime_disposition="observe_only",
            decision_result="observe_only",
            risk_class="runtime_gate",
            decision_reason="release gate blocks promotion",
            matched_policy_rules=[],
            why_not_escalated=None,
            why_escalated=None,
            uncertainty_reasons=[],
            policy_version="policy-v1",
            fact_snapshot_version="fact-v7",
            idempotency_key=(
                "session:repo-a|fact-v7|policy-v1|observe_only|"
                "propose_execute|continue_session|"
            ),
            created_at="2099-01-01T00:00:00Z",
            operator_notes=[],
            evidence={
                "release_gate_verdict": {
                    "status": "degraded",
                    "degrade_reason": "report_expired",
                    "report_id": "report:healthz",
                    "report_hash": "sha256:report",
                    "input_hash": "sha256:input",
                    "decision_trace_ref": "trace:healthz",
                    "approval_read_ref": "approval:none",
                }
            },
        )
    )

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["active_alerts"] == 0
    assert response.json()["release_gate_blockers"] == 1


def test_watchdog_metrics_exports_task_approval_and_recovery_totals(tmp_path: Path) -> None:
    task_store = TaskStore(tmp_path / "tasks.json")
    approval_store = CanonicalApprovalStore(tmp_path / "canonical_approvals.json")
    receipt_store = ActionReceiptStore(tmp_path / "action_receipts.json")
    app = create_app(Settings(api_token="wt", data_dir=str(tmp_path)))
    client = TestClient(app)

    task_store.upsert_from_create(
        "repo-a",
        {
            "cwd": "/tmp/repo-a",
            "task_title": "Repo A",
            "status": "running",
        },
    )
    task_store.upsert_from_create(
        "repo-b",
        {
            "cwd": "/tmp/repo-b",
            "task_title": "Repo B",
            "status": "paused",
        },
    )
    approval_store.put(
        CanonicalApprovalRecord(
            approval_id="appr_pending_metric_1",
            envelope_id="approval-envelope:metric-1",
            approval_kind="canonical_user_decision",
            requested_action="execute_recovery",
            requested_action_args={},
            approval_token="approval-token:metric-1",
            decision_options=["approve", "reject"],
            policy_version="policy-v1",
            fact_snapshot_version="fact-v7",
            idempotency_key="metric:approval:pending:1",
            project_id="repo-a",
            session_id="session:repo-a",
            thread_id="session:repo-a",
            native_thread_id="thr_native_1",
            status="pending",
            created_at="2026-04-16T08:00:00Z",
            decided_at=None,
            decided_by=None,
            operator_notes=[],
            decision=CanonicalDecisionRecord(
                decision_id="decision:metric-1",
                decision_key="metric:decision:1",
                session_id="session:repo-a",
                project_id="repo-a",
                thread_id="session:repo-a",
                native_thread_id="thr_native_1",
                approval_id="appr_pending_metric_1",
                action_ref="execute_recovery",
                trigger="resident_supervision",
                decision_result="require_user_decision",
                risk_class="human_gate",
                decision_reason="metric coverage",
                matched_policy_rules=["human_gate"],
                why_not_escalated=None,
                why_escalated="needs approval",
                uncertainty_reasons=[],
                policy_version="policy-v1",
                fact_snapshot_version="fact-v7",
                idempotency_key="metric:decision:1",
                created_at="2026-04-16T08:00:00Z",
                operator_notes=[],
                evidence={},
            ),
        )
    )
    receipt_store.put(
        receipt_key(
            action_code=ActionCode.EXECUTE_RECOVERY,
            project_id="repo-a",
            approval_id=None,
            idempotency_key="metric:recovery:1",
        ),
        WatchdogActionResult(
            action_code=ActionCode.EXECUTE_RECOVERY,
            project_id="repo-a",
            approval_id=None,
            idempotency_key="metric:recovery:1",
            action_status=ActionStatus.COMPLETED,
            effect=Effect.HANDOFF_TRIGGERED,
            reply_code=ReplyCode.RECOVERY_EXECUTION_RESULT,
            message="recovery completed",
            facts=[],
        ),
    )

    response = client.get("/metrics")

    assert response.status_code == 200
    assert "watchdog_task_records_total 2" in response.text
    assert "watchdog_approval_pending_total 1" in response.text
    assert "watchdog_recovery_receipts_total 1" in response.text


def test_watchdog_metrics_reads_task_totals_from_a_control_agent_store_path(
    tmp_path: Path,
) -> None:
    task_store = TaskStore(tmp_path / "tasks_store.json")
    app = create_app(Settings(api_token="wt", data_dir=str(tmp_path)))
    client = TestClient(app)

    task_store.upsert_from_create(
        "repo-a",
        {
            "cwd": "/tmp/repo-a",
            "task_title": "Repo A",
            "status": "running",
        },
    )
    task_store.upsert_from_create(
        "repo-b",
        {
            "cwd": "/tmp/repo-b",
            "task_title": "Repo B",
            "status": "paused",
        },
    )

    response = client.get("/metrics")

    assert response.status_code == 200
    assert "watchdog_task_records_total 2" in response.text


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


def test_watchdog_metrics_pending_approval_total_uses_latest_pending_record_per_session(
    tmp_path: Path,
) -> None:
    approval_store = CanonicalApprovalStore(tmp_path / "canonical_approvals.json")
    app = create_app(Settings(api_token="wt", data_dir=str(tmp_path)))
    client = TestClient(app)

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

    response = client.get("/metrics")

    assert response.status_code == 200
    assert "watchdog_approval_pending_total 1" in response.text


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
    assert len(summary.release_gate_blockers) == 1
    assert summary.release_gate_blockers[0].reason == "report_load_failed"
    assert summary.release_gate_blockers[0].report_id == "report:load_failed"
    assert summary.release_gate_blockers[0].input_hash == "sha256:input"


def test_release_gate_read_contract_module_exports_typed_surface() -> None:
    module = importlib.import_module("watchdog.services.brain.release_gate_read_contract")

    assert hasattr(module, "ReleaseGateDecisionReadSnapshot")
    assert hasattr(module, "read_release_gate_decision_evidence")


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


def test_build_ops_summary_surfaces_provider_output_schema_degradation(
    tmp_path: Path,
) -> None:
    decision_store = PolicyDecisionStore(tmp_path / "policy_decisions.json")
    settings = Settings(data_dir=str(tmp_path))

    decision_store.put(
        CanonicalDecisionRecord(
            decision_id="decision:provider-output-invalid",
            decision_key=(
                "session:repo-a|fact-v7|policy-v1|allow|propose_execute|continue_session|"
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
            decision_result="allow",
            risk_class="low",
            decision_reason="provider output degraded to local rule-based decision",
            matched_policy_rules=[],
            why_not_escalated=None,
            why_escalated=None,
            uncertainty_reasons=[],
            policy_version="policy-v1",
            fact_snapshot_version="fact-v7",
            idempotency_key=(
                "session:repo-a|fact-v7|policy-v1|allow|propose_execute|continue_session|"
            ),
            created_at="2099-01-01T00:00:00Z",
            operator_notes=[],
            evidence={
                "decision_trace": {
                    "trace_id": "trace:provider-output-invalid",
                    "goal_contract_version": "goal-contract:v1",
                    "policy_ruleset_hash": "sha256:policy",
                    "memory_packet_input_ids": [],
                    "memory_packet_input_hashes": [],
                    "provider": "resident_orchestrator",
                    "model": "rule-based-brain",
                    "prompt_schema_ref": "prompt:none",
                    "output_schema_ref": "schema:decision-trace-v1",
                    "provider_output_schema_ref": "schema:provider-decision-v2",
                    "degrade_reason": "provider_output_invalid",
                }
            },
        )
    )

    summary = build_ops_summary(data_dir=tmp_path, settings=settings)

    assert summary.status == "degraded"
    assert summary.active_alerts == 1
    assert [item.alert_code for item in summary.alerts] == ["provider_output_invalid"]
    assert summary.alerts[0].count == 1


def test_watchdog_ops_alerts_expose_release_gate_blocker_metadata(tmp_path: Path) -> None:
    decision_store = PolicyDecisionStore(tmp_path / "policy_decisions.json")
    app = create_app(Settings(api_token="wt", data_dir=str(tmp_path)))
    client = TestClient(app)

    decision_store.put(
        CanonicalDecisionRecord(
            decision_id="decision:runtime-gate-metadata",
            decision_key=(
                "session:repo-a|fact-v7|policy-v1|block_and_alert|"
                "propose_execute|continue_session|"
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
            why_escalated="release gate verdict is not pass: report_expired",
            uncertainty_reasons=["report_expired"],
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
                    "degrade_reason": "report_expired",
                    "report_id": "report:2026-04-14",
                    "report_hash": "sha256:report",
                    "input_hash": "sha256:input",
                    "decision_trace_ref": "trace:1",
                    "approval_read_ref": "approval:none",
                },
                "release_gate_evidence_bundle": {
                    "certification_packet_corpus": {
                        "artifact_ref": "artifacts/certification-packets.jsonl"
                    },
                    "shadow_decision_ledger": {
                        "artifact_ref": "artifacts/shadow-ledger.jsonl"
                    },
                    "release_gate_report_ref": "artifacts/release-gate-report.json",
                    "label_manifest_ref": "tests/fixtures/release_gate_label_manifest.json",
                    "generated_by": "codex",
                    "report_approved_by": "operator-a",
                },
            },
        )
    )

    response = client.get(
        "/api/v1/watchdog/ops/alerts",
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    blocker = response.json()["data"]["release_gate_blockers"][0]
    assert blocker["reason"] == "report_expired"
    assert blocker["report_id"] == "report:2026-04-14"
    assert blocker["report_ref"] == "artifacts/release-gate-report.json"
    assert blocker["certification_packet_corpus_ref"] == "artifacts/certification-packets.jsonl"
    assert blocker["shadow_decision_ledger_ref"] == "artifacts/shadow-ledger.jsonl"
    assert blocker.get("label_manifest_ref") == "tests/fixtures/release_gate_label_manifest.json"
    assert blocker.get("generated_by") == "codex"
    assert blocker.get("report_approved_by") == "operator-a"


def test_build_ops_summary_drops_partial_release_gate_bundle_metadata(tmp_path: Path) -> None:
    decision_store = PolicyDecisionStore(tmp_path / "policy_decisions.json")
    settings = Settings(data_dir=str(tmp_path))

    decision_store.put(
        CanonicalDecisionRecord(
            decision_id="decision:runtime-gate-partial-bundle",
            decision_key=(
                "session:repo-a|fact-v7|policy-v1|block_and_alert|"
                "propose_execute|continue_session|"
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
            why_escalated="release gate verdict is not pass: report_expired",
            uncertainty_reasons=["report_expired"],
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
                    "degrade_reason": "report_expired",
                    "report_id": "report:2026-04-14",
                    "report_hash": "sha256:report",
                    "input_hash": "sha256:input",
                    "decision_trace_ref": "trace:1",
                    "approval_read_ref": "approval:none",
                },
                "release_gate_evidence_bundle": {
                    "certification_packet_corpus": "invalid",
                    "shadow_decision_ledger": {
                        "artifact_ref": "artifacts/shadow-ledger.jsonl"
                    },
                    "release_gate_report_ref": "artifacts/release-gate-report.json",
                    "label_manifest_ref": "tests/fixtures/release_gate_label_manifest.json",
                    "generated_by": "codex",
                    "report_approved_by": "operator-a",
                },
            },
        )
    )

    summary = build_ops_summary(data_dir=tmp_path, settings=settings)

    blocker = summary.release_gate_blockers[0]
    assert blocker.reason == "report_expired"
    assert blocker.report_id == "report:2026-04-14"
    assert blocker.report_hash == "sha256:report"
    assert blocker.input_hash == "sha256:input"
    assert blocker.report_ref is None
    assert blocker.certification_packet_corpus_ref is None
    assert blocker.shadow_decision_ledger_ref is None
    assert blocker.label_manifest_ref is None
    assert blocker.generated_by is None
    assert blocker.report_approved_by is None


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


def test_build_ops_summary_falls_back_to_unknown_runtime_gate_reason(tmp_path: Path) -> None:
    decision_store = PolicyDecisionStore(tmp_path / "policy_decisions.json")
    settings = Settings(data_dir=str(tmp_path))

    decision_store.put(
        CanonicalDecisionRecord(
            decision_id="decision:runtime-gate-unknown",
            decision_key=(
                "session:runtime-gate-unknown|fact-v7|policy-v1|block_and_alert|"
                "propose_execute|continue_session|"
            ),
            session_id="session:runtime-gate-unknown",
            project_id="repo:runtime-gate-unknown",
            thread_id="session:runtime-gate-unknown",
            native_thread_id="thr_native:runtime-gate-unknown",
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
            why_escalated="release gate verdict is not pass: empty reason",
            uncertainty_reasons=[],
            policy_version="policy-v1",
            fact_snapshot_version="fact-v7",
            idempotency_key=(
                "session:runtime-gate-unknown|fact-v7|policy-v1|block_and_alert|"
                "propose_execute|continue_session|"
            ),
            created_at="2099-01-01T00:00:00Z",
            operator_notes=[],
            evidence={},
        )
    )

    summary = build_ops_summary(data_dir=tmp_path, settings=settings)

    assert summary.status == "degraded"
    assert summary.active_alerts == 1
    assert [item.alert_code for item in summary.alerts] == ["runtime_gate_unknown"]
    assert summary.alerts[0].count == 1


def test_build_ops_summary_surfaces_future_worker_status_and_blocking_reason(
    tmp_path: Path,
) -> None:
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    settings = Settings(data_dir=str(tmp_path))

    session_service.record_event(
        event_type="future_worker_requested",
        project_id="repo-a",
        session_id="session:repo-a",
        occurred_at="2026-04-14T05:00:00Z",
        correlation_id="corr:future-worker:task-running",
        related_ids={
            "worker_task_ref": "worker:task-running",
            "decision_trace_ref": "trace:running",
        },
        payload={"scope": "read_only"},
    )
    session_service.record_event(
        event_type="future_worker_started",
        project_id="repo-a",
        session_id="session:repo-a",
        occurred_at="2026-04-14T05:01:00Z",
        correlation_id="corr:future-worker:task-running",
        related_ids={"worker_task_ref": "worker:task-running"},
        payload={"worker_runtime_contract": {"provider": "codex"}},
    )
    session_service.record_event(
        event_type="future_worker_heartbeat",
        project_id="repo-a",
        session_id="session:repo-a",
        occurred_at="2026-04-14T05:02:00Z",
        correlation_id="corr:future-worker:task-running",
        related_ids={"worker_task_ref": "worker:task-running"},
        payload={"heartbeat": {"progress": "indexing"}},
    )

    session_service.record_event(
        event_type="future_worker_requested",
        project_id="repo-b",
        session_id="session:repo-b",
        occurred_at="2026-04-14T05:10:00Z",
        correlation_id="corr:future-worker:task-rejected",
        related_ids={
            "worker_task_ref": "worker:task-rejected",
            "decision_trace_ref": "trace:rejected",
        },
        payload={"scope": "read_only"},
    )
    session_service.record_event(
        event_type="future_worker_started",
        project_id="repo-b",
        session_id="session:repo-b",
        occurred_at="2026-04-14T05:11:00Z",
        correlation_id="corr:future-worker:task-rejected",
        related_ids={"worker_task_ref": "worker:task-rejected"},
        payload={"worker_runtime_contract": {"provider": "codex"}},
    )
    session_service.record_event(
        event_type="future_worker_completed",
        project_id="repo-b",
        session_id="session:repo-b",
        occurred_at="2026-04-14T05:12:00Z",
        correlation_id="corr:future-worker:task-rejected",
        related_ids={
            "worker_task_ref": "worker:task-rejected",
            "summary_ref": "summary:worker:rejected",
        },
        payload={
            "worker_task_ref": "worker:task-rejected",
            "parent_session_id": "session:repo-b",
            "decision_trace_ref": "trace:rejected",
            "result_summary_ref": "summary:worker:rejected",
            "artifact_refs": [],
            "input_contract_hash": "sha256:input",
            "result_hash": "sha256:result",
            "produced_at": "2026-04-14T05:12:00Z",
            "status": "completed",
            "worker_runtime_contract": {"provider": "codex"},
        },
    )
    session_service.record_event(
        event_type="future_worker_result_rejected",
        project_id="repo-b",
        session_id="session:repo-b",
        occurred_at="2026-04-14T05:13:00Z",
        correlation_id="corr:future-worker:task-rejected",
        related_ids={"worker_task_ref": "worker:task-rejected"},
        payload={"reason": "late_result"},
    )

    summary = build_ops_summary(data_dir=tmp_path, settings=settings)

    assert summary.status == "ok"
    assert summary.active_alerts == 0
    assert [item.worker_task_ref for item in summary.future_workers] == [
        "worker:task-rejected",
        "worker:task-running",
    ]
    statuses = {item.worker_task_ref: item for item in summary.future_workers}
    assert statuses["worker:task-running"].status == "running"
    assert statuses["worker:task-running"].last_event_type == "future_worker_heartbeat"
    assert statuses["worker:task-running"].decision_trace_ref == "trace:running"
    assert statuses["worker:task-running"].blocking_reason is None
    assert statuses["worker:task-rejected"].status == "rejected"
    assert statuses["worker:task-rejected"].last_event_type == "future_worker_result_rejected"
    assert statuses["worker:task-rejected"].decision_trace_ref == "trace:rejected"
    assert statuses["worker:task-rejected"].blocking_reason == "late_result"


def test_watchdog_metrics_exports_future_worker_status_and_blocking_reason(
    tmp_path: Path,
) -> None:
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    app = create_app(Settings(api_token="wt", data_dir=str(tmp_path)))
    client = TestClient(app)

    session_service.record_event(
        event_type="future_worker_requested",
        project_id="repo-a",
        session_id="session:repo-a",
        occurred_at="2026-04-14T05:20:00Z",
        correlation_id="corr:future-worker:task-rejected",
        related_ids={
            "worker_task_ref": "worker:task-rejected",
            "decision_trace_ref": "trace:rejected",
        },
        payload={"scope": "read_only"},
    )
    session_service.record_event(
        event_type="future_worker_started",
        project_id="repo-a",
        session_id="session:repo-a",
        occurred_at="2026-04-14T05:21:00Z",
        correlation_id="corr:future-worker:task-rejected",
        related_ids={"worker_task_ref": "worker:task-rejected"},
        payload={"worker_runtime_contract": {"provider": "codex"}},
    )
    session_service.record_event(
        event_type="future_worker_completed",
        project_id="repo-a",
        session_id="session:repo-a",
        occurred_at="2026-04-14T05:22:00Z",
        correlation_id="corr:future-worker:task-rejected",
        related_ids={
            "worker_task_ref": "worker:task-rejected",
            "summary_ref": "summary:worker:rejected",
        },
        payload={
            "worker_task_ref": "worker:task-rejected",
            "parent_session_id": "session:repo-a",
            "decision_trace_ref": "trace:rejected",
            "result_summary_ref": "summary:worker:rejected",
            "artifact_refs": [],
            "input_contract_hash": "sha256:input",
            "result_hash": "sha256:result",
            "produced_at": "2026-04-14T05:22:00Z",
            "status": "completed",
            "worker_runtime_contract": {"provider": "codex"},
        },
    )
    session_service.record_event(
        event_type="future_worker_result_rejected",
        project_id="repo-a",
        session_id="session:repo-a",
        occurred_at="2026-04-14T05:23:00Z",
        correlation_id="corr:future-worker:task-rejected",
        related_ids={"worker_task_ref": "worker:task-rejected"},
        payload={"reason": "late_result"},
    )

    response = client.get("/metrics")

    assert response.status_code == 200
    assert 'watchdog_future_worker_status_active{status="rejected"} 1' in response.text
    assert 'watchdog_future_worker_blocked_active{reason="late_result"} 1' in response.text


def test_watchdog_ops_alerts_expose_future_worker_read_side(tmp_path: Path) -> None:
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    app = create_app(Settings(api_token="wt", data_dir=str(tmp_path)))
    client = TestClient(app)

    session_service.record_event(
        event_type="future_worker_requested",
        project_id="repo-a",
        session_id="session:repo-a",
        occurred_at="2026-04-14T05:30:00Z",
        correlation_id="corr:future-worker:task-running",
        related_ids={
            "worker_task_ref": "worker:task-running",
            "decision_trace_ref": "trace:running",
        },
        payload={"scope": "read_only"},
    )
    session_service.record_event(
        event_type="future_worker_started",
        project_id="repo-a",
        session_id="session:repo-a",
        occurred_at="2026-04-14T05:31:00Z",
        correlation_id="corr:future-worker:task-running",
        related_ids={"worker_task_ref": "worker:task-running"},
        payload={"worker_runtime_contract": {"provider": "codex"}},
    )

    response = client.get(
        "/api/v1/watchdog/ops/alerts",
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    future_workers = response.json()["data"]["future_workers"]
    assert len(future_workers) == 1
    assert future_workers[0]["worker_task_ref"] == "worker:task-running"
    assert future_workers[0]["status"] == "running"
    assert future_workers[0]["decision_trace_ref"] == "trace:running"


def test_build_ops_summary_preserves_worker_state_after_transition_rejection(
    tmp_path: Path,
) -> None:
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    settings = Settings(data_dir=str(tmp_path))

    session_service.record_event(
        event_type="future_worker_requested",
        project_id="repo-a",
        session_id="session:repo-a",
        occurred_at="2026-04-14T05:40:00Z",
        correlation_id="corr:future-worker:task-dup",
        related_ids={
            "worker_task_ref": "worker:task-dup",
            "decision_trace_ref": "trace:dup",
        },
        payload={"scope": "read_only"},
    )
    session_service.record_event(
        event_type="future_worker_started",
        project_id="repo-a",
        session_id="session:repo-a",
        occurred_at="2026-04-14T05:41:00Z",
        correlation_id="corr:future-worker:task-dup",
        related_ids={"worker_task_ref": "worker:task-dup"},
        payload={"worker_runtime_contract": {"provider": "codex"}},
    )
    session_service.record_event(
        event_type="future_worker_transition_rejected",
        project_id="repo-a",
        session_id="session:repo-a",
        occurred_at="2026-04-14T05:42:00Z",
        correlation_id="corr:future-worker:task-dup",
        related_ids={
            "worker_task_ref": "worker:task-dup",
            "attempted_event_type": "future_worker_started",
        },
        payload={
            "attempted_event_type": "future_worker_started",
            "current_state": "running",
            "reason": "invalid_transition:running->running",
        },
    )

    summary = build_ops_summary(data_dir=tmp_path, settings=settings)

    assert len(summary.future_workers) == 1
    assert summary.future_workers[0].worker_task_ref == "worker:task-dup"
    assert summary.future_workers[0].status == "running"
    assert summary.future_workers[0].last_event_type == "future_worker_transition_rejected"
    assert summary.future_workers[0].blocking_reason == "invalid_transition:running->running"


def test_build_ops_summary_preserves_completed_state_after_duplicate_completion_rejection(
    tmp_path: Path,
) -> None:
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    settings = Settings(data_dir=str(tmp_path))

    session_service.record_event(
        event_type="future_worker_requested",
        project_id="repo-a",
        session_id="session:repo-a",
        occurred_at="2026-04-14T05:50:00Z",
        correlation_id="corr:future-worker:task-dup-complete",
        related_ids={
            "worker_task_ref": "worker:task-dup-complete",
            "decision_trace_ref": "trace:dup-complete",
        },
        payload={"scope": "read_only"},
    )
    session_service.record_event(
        event_type="future_worker_started",
        project_id="repo-a",
        session_id="session:repo-a",
        occurred_at="2026-04-14T05:51:00Z",
        correlation_id="corr:future-worker:task-dup-complete",
        related_ids={"worker_task_ref": "worker:task-dup-complete"},
        payload={"worker_runtime_contract": {"provider": "codex"}},
    )
    session_service.record_event(
        event_type="future_worker_completed",
        project_id="repo-a",
        session_id="session:repo-a",
        occurred_at="2026-04-14T05:52:00Z",
        correlation_id="corr:future-worker:task-dup-complete",
        related_ids={
            "worker_task_ref": "worker:task-dup-complete",
            "summary_ref": "summary:dup-complete",
        },
        payload={
            "worker_task_ref": "worker:task-dup-complete",
            "parent_session_id": "session:repo-a",
            "decision_trace_ref": "trace:dup-complete",
            "result_summary_ref": "summary:dup-complete",
            "artifact_refs": [],
            "input_contract_hash": "sha256:dup-complete-input",
            "result_hash": "sha256:dup-complete-result",
            "produced_at": "2026-04-14T05:52:00Z",
            "status": "completed",
            "worker_runtime_contract": {"provider": "codex"},
        },
    )
    session_service.record_event(
        event_type="future_worker_transition_rejected",
        project_id="repo-a",
        session_id="session:repo-a",
        occurred_at="2026-04-14T05:53:00Z",
        correlation_id=(
            "corr:future-worker:task-dup-complete:future_worker_completed:2026-04-14T05:53:00Z"
        ),
        related_ids={
            "worker_task_ref": "worker:task-dup-complete",
            "attempted_event_type": "future_worker_completed",
        },
        payload={
            "attempted_event_type": "future_worker_completed",
            "current_state": "completed",
            "reason": "invalid_transition:completed->completed",
            "worker_task_ref": "worker:task-dup-complete",
        },
    )

    summary = build_ops_summary(data_dir=tmp_path, settings=settings)

    assert len(summary.future_workers) == 1
    assert summary.future_workers[0].worker_task_ref == "worker:task-dup-complete"
    assert summary.future_workers[0].status == "completed"
    assert summary.future_workers[0].last_event_type == "future_worker_transition_rejected"
    assert summary.future_workers[0].blocking_reason == "invalid_transition:completed->completed"


def test_build_ops_summary_can_reuse_injected_store_instances(tmp_path: Path) -> None:
    settings = Settings(data_dir=str(tmp_path))
    decision = CanonicalDecisionRecord(
        decision_id="decision:injected",
        decision_key="session:repo-a|fact-v1|policy-v1|block_and_alert|execute_recovery|",
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
        fact_snapshot_version="fact-v1",
        idempotency_key="idem:decision:injected",
        created_at="2000-01-01T00:00:00Z",
        operator_notes=[],
        evidence={},
    )

    class _InjectedDecisionStore:
        def list_records(self) -> list[CanonicalDecisionRecord]:
            return [decision]

    class _InjectedApprovalStore:
        def list_records(self) -> list[CanonicalApprovalRecord]:
            return []

    class _InjectedDeliveryStore:
        def list_records(self) -> list[DeliveryOutboxRecord]:
            return []

    class _InjectedReceiptStore:
        def list_items(self) -> list[tuple[str, WatchdogActionResult]]:
            return []

    summary = build_ops_summary(
        data_dir=tmp_path / "missing-data-dir",
        settings=settings,
        decision_store=_InjectedDecisionStore(),
        approval_store=_InjectedApprovalStore(),
        delivery_store=_InjectedDeliveryStore(),
        receipt_store=_InjectedReceiptStore(),
    )

    assert summary.status == "degraded"
    assert summary.active_alerts == 2
