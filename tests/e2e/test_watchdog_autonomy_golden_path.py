from __future__ import annotations

from pathlib import Path

from unittest.mock import patch

from fastapi.testclient import TestClient

from watchdog.main import create_app
from watchdog.settings import Settings


class _BootstrapAClient:
    def __init__(self) -> None:
        self._task = {
            "project_id": "repo-a",
            "thread_id": "session:repo-a",
            "status": "running",
            "phase": "planning",
            "pending_approval": False,
            "last_summary": "waiting for goal bootstrap",
            "files_touched": ["specs/037-autonomy-golden-path-and-release-gate-e2e/spec.md"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-14T03:20:00Z",
        }

    def list_tasks(self) -> list[dict[str, object]]:
        return [dict(self._task)]

    def get_envelope(self, project_id: str) -> dict[str, object]:
        assert project_id == self._task["project_id"]
        return {"success": True, "data": dict(self._task)}

    def list_approvals(self, **_: object) -> list[dict[str, object]]:
        return []


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        api_token="watchdog-token",
        a_agent_token="a-agent-token",
        a_agent_base_url="http://a-control.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )


def test_feishu_dm_bootstrap_starts_goal_contract_to_release_gate_chain(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    app = create_app(
        settings=settings,
        a_client=_BootstrapAClient(),
        start_background_workers=False,
    )

    body = {
        "event_type": "goal_contract_bootstrap",
        "interaction_context_id": "ctx-bootstrap-1",
        "interaction_family_id": "family-bootstrap-1",
        "actor_id": "user:alice",
        "channel_kind": "dm",
        "occurred_at": "2026-04-14T03:20:00Z",
        "action_window_expires_at": "2026-04-14T03:35:00Z",
        "client_request_id": "req-bootstrap-1",
        "envelope_id": "feishu-bootstrap-envelope-1",
        "response_token": "bootstrap-token",
        "project_id": "repo-a",
        "session_id": "session:repo-a",
        "goal_message": "继续把一期自治通关主链打通到 release blocker。",
    }

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/control",
            json=body,
            headers={"Authorization": f"Bearer {settings.api_token}"},
        )

    assert response.status_code == 200
    assert response.json()["success"] is True

    app.state.session_spine_runtime.refresh_all()
    with patch(
        "watchdog.services.session_spine.actions.post_steer",
        return_value={"accepted": True, "action_ref": "continue_session", "reply_code": "ok"},
    ):
        app.state.resident_orchestrator.orchestrate_all()

    events = app.state.session_service.list_events(session_id="session:repo-a")
    assert [event.event_type for event in events[:3]] == [
        "goal_contract_created",
        "decision_proposed",
        "decision_validated",
    ]
    decisions = app.state.policy_decision_store.list_records()
    assert len(decisions) == 1
    assert "release_gate_verdict" in decisions[0].evidence
