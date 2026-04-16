from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from watchdog.main import create_app
from watchdog.services.goal_contract.service import GoalContractService
from watchdog.settings import Settings


class _IngressAClient:
    def __init__(self, *, tasks: list[dict[str, object]]) -> None:
        self._tasks = tasks
        self.pause_calls: list[str] = []

    def list_tasks(self) -> list[dict[str, object]]:
        return [dict(task) for task in self._tasks]

    def trigger_pause(self, project_id: str) -> dict[str, object]:
        self.pause_calls.append(project_id)
        return {
            "success": True,
            "data": {"project_id": project_id, "status": "paused"},
        }

    def get_envelope(self, project_id: str) -> dict[str, object]:
        task = next(task for task in self._tasks if task["project_id"] == project_id)
        return {"success": True, "data": dict(task)}

    def get_envelope_by_thread(self, thread_id: str) -> dict[str, object]:
        task = next(task for task in self._tasks if task["thread_id"] == thread_id)
        return {"success": True, "data": dict(task)}

    def list_approvals(self, **_: object) -> list[dict[str, object]]:
        return []


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        api_token="watchdog-token",
        a_agent_token="a-agent-token",
        a_agent_base_url="http://a-control.test",
        data_dir=str(tmp_path),
        feishu_verification_token="verify-token",
    )


def _task(
    project_id: str,
    *,
    thread_id: str | None = None,
    native_thread_id: str | None = None,
    status: str = "running",
) -> dict[str, object]:
    return {
        "project_id": project_id,
        "thread_id": thread_id or f"session:{project_id}",
        "native_thread_id": native_thread_id or f"thr:{project_id}",
        "status": status,
        "phase": "planning",
        "pending_approval": False,
        "last_summary": "waiting",
        "files_touched": [],
        "context_pressure": "low",
        "stuck_level": 0,
        "failure_count": 0,
        "last_progress_at": "2026-04-16T13:00:00Z",
    }


def _message_event(
    text: str,
    *,
    token: str = "verify-token",
    event_id: str = "evt-feishu-1",
    message_id: str = "om_message_1",
) -> dict[str, object]:
    return {
        "schema": "2.0",
        "header": {
            "event_id": event_id,
            "event_type": "im.message.receive_v1",
            "create_time": "1713274200000",
            "token": token,
            "app_id": "cli_app",
            "tenant_key": "tenant-1",
        },
        "event": {
            "message": {
                "message_id": message_id,
                "chat_type": "p2p",
                "message_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
            "sender": {"sender_id": {"open_id": "ou_actor_1"}},
        },
    }


def test_feishu_ingress_answers_url_verification_challenge(tmp_path: Path) -> None:
    app = create_app(settings=_settings(tmp_path), a_client=_IngressAClient(tasks=[]))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json={
                "type": "url_verification",
                "token": "verify-token",
                "challenge": "challenge-123",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"challenge": "challenge-123"}


def test_feishu_ingress_routes_text_message_with_explicit_repo_prefix(tmp_path: Path) -> None:
    a_client = _IngressAClient(tasks=[_task("repo-a")])
    app = create_app(settings=_settings(tmp_path), a_client=a_client)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("repo:repo-a pause"),
        )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert a_client.pause_calls == ["repo-a"]


def test_feishu_ingress_can_auto_bind_single_active_task_for_goal_bootstrap(
    tmp_path: Path,
) -> None:
    a_client = _IngressAClient(tasks=[_task("repo-a", thread_id="session:repo-a")])
    app = create_app(settings=_settings(tmp_path), a_client=a_client)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("/goal 继续把主链路打通到 release gate"),
        )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    events = app.state.session_service.list_events(session_id="session:repo-a")
    assert events[0].event_type == "goal_contract_created"


def test_feishu_ingress_rejects_ambiguous_project_binding(tmp_path: Path) -> None:
    a_client = _IngressAClient(tasks=[_task("repo-a"), _task("repo-b")])
    app = create_app(settings=_settings(tmp_path), a_client=a_client)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("/goal 继续推进"),
        )

    assert response.status_code == 400
    assert "project" in response.json()["detail"].lower()


def test_feishu_ingress_does_not_auto_bind_only_completed_task(tmp_path: Path) -> None:
    a_client = _IngressAClient(tasks=[_task("repo-a", status="completed")])
    app = create_app(settings=_settings(tmp_path), a_client=a_client)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("/goal 继续推进"),
        )

    assert response.status_code == 400
    assert "project" in response.json()["detail"].lower()


def test_feishu_ingress_rejects_malformed_create_time(tmp_path: Path) -> None:
    a_client = _IngressAClient(tasks=[_task("repo-a")])
    app = create_app(settings=_settings(tmp_path), a_client=a_client)
    body = _message_event("repo:repo-a pause")
    body["header"]["create_time"] = "not-a-timestamp"

    with TestClient(app) as client:
        response = client.post("/api/v1/watchdog/feishu/events", json=body)

    assert response.status_code == 400
    assert "timestamp" in response.json()["detail"].lower()


def test_feishu_ingress_auto_bind_uses_active_thread_envelope(tmp_path: Path) -> None:
    a_client = _IngressAClient(
        tasks=[
            _task(
                "repo-a",
                thread_id="session:completed",
                native_thread_id="thr:completed",
                status="completed",
            ),
            _task(
                "repo-a",
                thread_id="session:active",
                native_thread_id="thr:active",
                status="running",
            ),
        ]
    )
    app = create_app(settings=_settings(tmp_path), a_client=a_client)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("/goal 只绑定活跃 session"),
        )

    assert response.status_code == 200
    contracts = GoalContractService(app.state.session_service)
    assert contracts.get_current_contract(
        project_id="repo-a",
        session_id="session:active",
    ) is not None
    assert contracts.get_current_contract(
        project_id="repo-a",
        session_id="session:completed",
    ) is None


def test_feishu_ingress_replay_does_not_overwrite_newer_goal_contract(tmp_path: Path) -> None:
    a_client = _IngressAClient(tasks=[_task("repo-a", thread_id="session:repo-a")])
    app = create_app(settings=_settings(tmp_path), a_client=a_client)

    with TestClient(app) as client:
        first = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event(
                "/goal 先把 Feishu 主链路打通",
                event_id="evt-feishu-1",
                message_id="om_message_1",
            ),
        )
        second = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event(
                "/goal 再把 release gate 收口",
                event_id="evt-feishu-2",
                message_id="om_message_2",
            ),
        )
        replay = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event(
                "/goal 先把 Feishu 主链路打通",
                event_id="evt-feishu-1",
                message_id="om_message_1",
            ),
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert replay.status_code == 200
    assert replay.json()["data"]["replayed"] is True

    contract = GoalContractService(app.state.session_service).get_current_contract(
        project_id="repo-a",
        session_id="session:repo-a",
    )
    assert contract is not None
    assert contract.current_phase_goal == "再把 release gate 收口"
    events = [
        event
        for event in app.state.session_service.list_events(session_id="session:repo-a")
        if event.event_type in {"goal_contract_created", "goal_contract_revised"}
    ]
    assert [event.related_ids["feishu_event_id"] for event in events] == [
        "evt-feishu-1",
        "evt-feishu-2",
    ]
