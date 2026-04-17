from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from watchdog.main import create_app
from watchdog.services.approvals.service import materialize_canonical_approval
from watchdog.services.delivery.store import DeliveryOutboxRecord
from watchdog.services.policy.decisions import CanonicalDecisionRecord
from watchdog.settings import Settings
from watchdog.storage.action_receipts import receipt_key


class FakeAClient:
    def __init__(self) -> None:
        self.decision_calls: list[tuple[str, str, str, str]] = []
        self.handoff_calls: list[tuple[str, str]] = []
        self.pause_calls: list[str] = []

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
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-07T00:10:00Z",
            },
        }

    def get_envelope_by_thread(self, thread_id: str) -> dict[str, object]:
        return {
            "success": True,
            "data": {
                "project_id": "repo-a",
                "thread_id": thread_id,
                "status": "running",
                "phase": "approval",
                "pending_approval": True,
                "last_summary": "waiting for approval",
                "files_touched": ["src/example.py"],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-07T00:10:00Z",
            },
        }

    def list_approvals(
        self,
        *,
        status: str | None = None,
        project_id: str | None = None,
        decided_by: str | None = None,
        callback_status: str | None = None,
    ):
        _ = (status, project_id, decided_by, callback_status)
        return []

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

    def trigger_pause(self, project_id: str) -> dict[str, object]:
        self.pause_calls.append(project_id)
        return {
            "success": True,
            "data": {"project_id": project_id, "status": "paused"},
        }

    def trigger_resume(
        self,
        project_id: str,
        *,
        mode: str,
        handoff_summary: str,
    ) -> dict[str, object]:
        return {
            "success": True,
            "data": {"project_id": project_id, "status": "running", "mode": mode},
        }


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        api_token="watchdog-token",
        a_agent_token="a-agent-token",
        a_agent_base_url="http://a-control.test",
        data_dir=str(tmp_path),
    )


def _decision() -> CanonicalDecisionRecord:
    return CanonicalDecisionRecord(
        decision_id="decision:feishu-control",
        decision_key=(
            "session:repo-a|fact-v7|policy-v1|require_user_decision|execute_recovery|appr_001"
        ),
        session_id="session:repo-a",
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="thr_native_1",
        approval_id="appr_001",
        action_ref="execute_recovery",
        trigger="resident_supervision",
        decision_result="require_user_decision",
        risk_class="human_gate",
        decision_reason="explicit human approval required",
        matched_policy_rules=["human_gate"],
        why_not_escalated=None,
        why_escalated="human gate matched",
        uncertainty_reasons=[],
        policy_version="policy-v1",
        fact_snapshot_version="fact-v7",
        idempotency_key=(
            "session:repo-a|fact-v7|policy-v1|require_user_decision|execute_recovery|appr_001"
        ),
        created_at="2026-04-07T00:00:00Z",
        operator_notes=[],
        evidence={
            "facts": [],
            "matched_policy_rules": ["human_gate"],
            "decision": {
                "decision_result": "require_user_decision",
                "action_ref": "execute_recovery",
                "approval_id": "appr_001",
            },
        },
    )


def _control_body(
    approval,
    *,
    interaction_context_id: str = "ctx-approval-1",
    interaction_family_id: str = "family-approval-1",
    channel_kind: str = "dm",
    occurred_at: str = "2026-04-07T00:10:00Z",
    action_window_expires_at: str = "2026-04-07T00:30:00Z",
    client_request_id: str = "req-feishu-1",
) -> dict[str, object]:
    return {
        "event_type": "approval_response",
        "interaction_context_id": interaction_context_id,
        "interaction_family_id": interaction_family_id,
        "actor_id": "user:carol",
        "channel_kind": channel_kind,
        "occurred_at": occurred_at,
        "action_window_expires_at": action_window_expires_at,
        "envelope_id": approval.envelope_id,
        "approval_id": approval.approval_id,
        "decision_id": approval.decision.decision_id,
        "response_action": "approve",
        "response_token": approval.approval_token,
        "client_request_id": client_request_id,
        "note": "ship it",
    }


def _seed_delivery_context(
    app,
    *,
    envelope_id: str,
    interaction_context_id: str,
    interaction_family_id: str,
    delivery_status: str,
    updated_at: str,
) -> None:
    app.state.delivery_outbox_store.update_delivery_record(
        DeliveryOutboxRecord(
            envelope_id=envelope_id,
            envelope_type="notification",
            correlation_id=f"corr:{interaction_family_id}:{interaction_context_id}",
            session_id="session:repo-a",
            project_id="repo-a",
            native_thread_id="thr_native_1",
            policy_version="policy-v1",
            fact_snapshot_version="fact-v7",
            idempotency_key=f"idem:{interaction_context_id}",
            audit_ref=f"audit:{interaction_context_id}",
            created_at=updated_at,
            updated_at=updated_at,
            outbox_seq=1 if interaction_context_id.endswith("old") else 2,
            delivery_status=delivery_status,
            envelope_payload={
                "envelope_type": "notification",
                "interaction_context_id": interaction_context_id,
                "interaction_family_id": interaction_family_id,
                "actor_id": "user:carol",
                "channel_kind": "dm",
            },
        )
    )


def test_feishu_control_requires_dm_for_approval_responses(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings=settings, a_client=FakeAClient())
    approval = materialize_canonical_approval(
        _decision(),
        approval_store=app.state.canonical_approval_store,
        session_service=app.state.session_service,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/control",
            json=_control_body(approval, channel_kind="group"),
            headers={"Authorization": f"Bearer {settings.api_token}"},
        )

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["error"]["code"] == "INVALID_ARGUMENT"
    assert "dm" in response.json()["error"]["message"].lower()
    assert app.state.session_service.list_events(
        session_id=approval.session_id,
        event_type="human_override_recorded",
    ) == []


def test_feishu_control_records_receipt_before_approval_side_effects(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings=settings, a_client=FakeAClient())
    approval = materialize_canonical_approval(
        _decision(),
        approval_store=app.state.canonical_approval_store,
        session_service=app.state.session_service,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/control",
            json=_control_body(approval),
            headers={"Authorization": f"Bearer {settings.api_token}"},
        )

    assert response.status_code == 200
    assert response.json()["success"] is True
    events = app.state.session_service.list_events(session_id=approval.session_id)
    assert [event.event_type for event in events] == [
        "approval_requested",
        "notification_receipt_recorded",
        "approval_approved",
        "human_override_recorded",
    ]
    assert events[1].related_ids["interaction_context_id"] == "ctx-approval-1"
    assert events[1].related_ids["interaction_family_id"] == "family-approval-1"
    assert events[1].payload["channel_kind"] == "dm"


def test_feishu_control_records_interaction_window_expired_and_rejects(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings=settings, a_client=FakeAClient())
    approval = materialize_canonical_approval(
        _decision(),
        approval_store=app.state.canonical_approval_store,
        session_service=app.state.session_service,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/control",
            json=_control_body(
                approval,
                occurred_at="2026-04-07T00:40:00Z",
                action_window_expires_at="2026-04-07T00:30:00Z",
                client_request_id="req-feishu-expired",
            ),
            headers={"Authorization": f"Bearer {settings.api_token}"},
        )

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["error"]["code"] == "INVALID_ARGUMENT"
    events = app.state.session_service.list_events(
        session_id=approval.session_id,
        event_type="interaction_window_expired",
    )
    assert len(events) == 1
    assert events[0].related_ids["interaction_context_id"] == "ctx-approval-1"
    assert app.state.session_service.list_events(
        session_id=approval.session_id,
        event_type="human_override_recorded",
    ) == []


def test_feishu_control_rejects_superseded_context_and_audits_it(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings=settings, a_client=FakeAClient())
    approval = materialize_canonical_approval(
        _decision(),
        approval_store=app.state.canonical_approval_store,
        session_service=app.state.session_service,
    )
    _seed_delivery_context(
        app,
        envelope_id="notification-envelope:ctx-old",
        interaction_context_id="ctx-old",
        interaction_family_id="family-approval-1",
        delivery_status="superseded",
        updated_at="2026-04-07T00:10:00Z",
    )
    _seed_delivery_context(
        app,
        envelope_id="notification-envelope:ctx-new",
        interaction_context_id="ctx-new",
        interaction_family_id="family-approval-1",
        delivery_status="delivered",
        updated_at="2026-04-07T00:15:00Z",
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/control",
            json=_control_body(
                approval,
                interaction_context_id="ctx-old",
                interaction_family_id="family-approval-1",
                client_request_id="req-feishu-stale",
            ),
            headers={"Authorization": f"Bearer {settings.api_token}"},
        )

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["error"]["code"] == "INVALID_ARGUMENT"
    events = app.state.session_service.list_events(
        session_id=approval.session_id,
        event_type="interaction_context_superseded",
    )
    assert len(events) == 1
    assert events[0].related_ids["interaction_context_id"] == "ctx-old"
    assert events[0].payload["active_interaction_context_id"] == "ctx-new"
    assert app.state.session_service.list_events(
        session_id=approval.session_id,
        event_type="human_override_recorded",
    ) == []


def test_feishu_control_command_request_routes_progress_query_to_canonical_reply(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings=settings, a_client=FakeAClient())

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/control",
            json={
                "event_type": "command_request",
                "interaction_context_id": "ctx-command-1",
                "interaction_family_id": "family-command-1",
                "actor_id": "user:carol",
                "channel_kind": "dm",
                "occurred_at": "2026-04-07T00:10:00Z",
                "action_window_expires_at": "2026-04-07T00:30:00Z",
                "client_request_id": "req-feishu-command-1",
                "project_id": "repo-a",
                "command_text": "现在进展",
            },
            headers={"Authorization": f"Bearer {settings.api_token}"},
        )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["data"]["intent_code"] == "get_progress"
    assert response.json()["data"]["reply_code"] == "task_progress_view"
    assert response.json()["data"]["progress"]["project_id"] == "repo-a"


def test_feishu_control_command_request_maps_plain_approval_reply_to_latest_pending_approval(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    a_client = FakeAClient()
    app = create_app(settings=settings, a_client=a_client)
    approval = materialize_canonical_approval(
        _decision(),
        approval_store=app.state.canonical_approval_store,
        session_service=app.state.session_service,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/control",
            json={
                "event_type": "command_request",
                "interaction_context_id": "ctx-command-approval-1",
                "interaction_family_id": "family-command-approval-1",
                "actor_id": "user:carol",
                "channel_kind": "dm",
                "occurred_at": "2026-04-07T00:10:00Z",
                "action_window_expires_at": "2026-04-07T00:30:00Z",
                "client_request_id": "req-feishu-command-approval-1",
                "project_id": "repo-a",
                "session_id": "session:repo-a",
                "command_text": "批准",
            },
            headers={"Authorization": f"Bearer {settings.api_token}"},
        )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["data"]["approval_id"] == approval.approval_id
    assert response.json()["data"]["response_action"] == "approve"
    assert a_client.decision_calls == [(approval.approval_id, "approve", "user:carol", "")]
    events = app.state.session_service.list_events(session_id=approval.session_id)
    assert [event.event_type for event in events] == [
        "approval_requested",
        "notification_receipt_recorded",
        "approval_approved",
        "human_override_recorded",
    ]


def test_feishu_control_command_request_routes_pause_and_persists_receipt(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    a_client = FakeAClient()
    app = create_app(settings=settings, a_client=a_client)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/control",
            json={
                "event_type": "command_request",
                "interaction_context_id": "ctx-command-2",
                "interaction_family_id": "family-command-2",
                "actor_id": "user:carol",
                "channel_kind": "dm",
                "occurred_at": "2026-04-07T00:10:00Z",
                "action_window_expires_at": "2026-04-07T00:30:00Z",
                "client_request_id": "req-feishu-command-2",
                "project_id": "repo-a",
                "command_text": "暂停",
            },
            headers={"Authorization": f"Bearer {settings.api_token}"},
        )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["data"]["intent_code"] == "pause_session"
    assert response.json()["data"]["action_result"]["effect"] == "session_paused"
    assert a_client.pause_calls == ["repo-a"]
    stored = app.state.action_receipt_store.get(
        receipt_key(
            action_code="pause_session",
            project_id="repo-a",
            idempotency_key="feishu:req-feishu-command-2",
        )
    )
    assert stored is not None
    assert stored.effect == "session_paused"


def test_feishu_control_command_request_can_route_by_native_thread(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings=settings, a_client=FakeAClient())

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/control",
            json={
                "event_type": "command_request",
                "interaction_context_id": "ctx-command-3",
                "interaction_family_id": "family-command-3",
                "actor_id": "user:carol",
                "channel_kind": "dm",
                "occurred_at": "2026-04-07T00:10:00Z",
                "action_window_expires_at": "2026-04-07T00:30:00Z",
                "client_request_id": "req-feishu-command-3",
                "native_thread_id": "thr_native_1",
                "command_text": "任务状态",
            },
            headers={"Authorization": f"Bearer {settings.api_token}"},
        )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["data"]["intent_code"] == "get_session"
    assert response.json()["data"]["reply_code"] == "session_projection"
    assert response.json()["data"]["session"]["project_id"] == "repo-a"
    assert response.json()["data"]["session"]["native_thread_id"] == "thr_native_1"
