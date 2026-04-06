from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from a_control_agent.main import create_app
from a_control_agent.settings import Settings


class FakeBridge:
    def __init__(self, *, fail_resume: bool = False, fail_approval: bool = False) -> None:
        self.started = False
        self.stopped = False
        self.fail_resume = fail_resume
        self.fail_approval = fail_approval
        self.active_turns: dict[str, str] = {}
        self.resume_calls: list[str] = []
        self.start_calls: list[tuple[str, str]] = []
        self.steer_calls: list[tuple[str, str]] = []
        self.approval_calls: list[tuple[str, str, str]] = []

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    def active_turn_id(self, thread_id: str) -> str | None:
        return self.active_turns.get(thread_id)

    async def resume_thread(self, thread_id: str) -> dict[str, object]:
        if self.fail_resume:
            raise RuntimeError("bridge down")
        self.resume_calls.append(thread_id)
        return {"thread_id": thread_id, "active_turn_id": self.active_turns.get(thread_id)}

    async def start_turn(self, thread_id: str, *, prompt: str) -> dict[str, object]:
        self.start_calls.append((thread_id, prompt))
        self.active_turns[thread_id] = "turn_started"
        return {"thread_id": thread_id, "turn_id": "turn_started"}

    async def steer_turn(self, thread_id: str, *, message: str) -> dict[str, object]:
        self.steer_calls.append((thread_id, message))
        return {"thread_id": thread_id, "turn_id": self.active_turns.get(thread_id, "turn_steered")}

    async def resolve_pending_approval(
        self,
        request_id: str,
        *,
        decision: str,
        note: str = "",
    ) -> dict[str, object]:
        if self.fail_approval:
            raise RuntimeError("callback failed")
        self.approval_calls.append((request_id, decision, note))
        return {"request_id": request_id, "decision": decision}


def _make_client(tmp_path: Path, bridge: FakeBridge) -> TestClient:
    settings = Settings(api_token="test-token", data_dir=str(tmp_path / "agent-data"))
    app = create_app(settings, codex_bridge=bridge, start_background_workers=False)
    return TestClient(app)


def test_steer_uses_turn_start_when_thread_is_idle(tmp_path: Path) -> None:
    bridge = FakeBridge()
    headers = {"Authorization": "Bearer test-token"}

    with _make_client(tmp_path, bridge) as client:
        created = client.post(
            "/api/v1/tasks",
            json={"project_id": "ai-demo", "cwd": "/tmp/w1", "task_title": "t1"},
            headers=headers,
        )
        assert created.status_code == 200

        response = client.post(
            "/api/v1/tasks/ai-demo/steer",
            json={"message": "continue the interrupted work", "reason": "watchdog"},
            headers=headers,
        )

    assert response.status_code == 200
    assert bridge.start_calls == [(created.json()["data"]["thread_id"], "continue the interrupted work")]
    assert bridge.steer_calls == []


def test_resume_replays_handoff_summary_into_live_thread(tmp_path: Path) -> None:
    bridge = FakeBridge()
    headers = {"Authorization": "Bearer test-token"}

    with _make_client(tmp_path, bridge) as client:
        created = client.post(
            "/api/v1/tasks",
            json={"project_id": "ai-demo", "cwd": "/tmp/w1", "task_title": "t1"},
            headers=headers,
        )
        thread_id = created.json()["data"]["thread_id"]

        response = client.post(
            "/api/v1/tasks/ai-demo/resume",
            json={"handoff_summary": "resume from saved handoff"},
            headers=headers,
        )

    assert response.status_code == 200
    assert bridge.resume_calls == [thread_id]
    assert bridge.start_calls == [(thread_id, "resume from saved handoff")]


def test_handoff_event_is_exposed_in_task_events(tmp_path: Path) -> None:
    bridge = FakeBridge()
    headers = {"Authorization": "Bearer test-token"}

    with _make_client(tmp_path, bridge) as client:
        created = client.post(
            "/api/v1/tasks",
            json={"project_id": "ai-demo", "cwd": "/tmp/w1", "task_title": "t1"},
            headers=headers,
        )
        assert created.status_code == 200

        response = client.post(
            "/api/v1/tasks/ai-demo/handoff",
            json={"reason": "operator_takeover"},
            headers=headers,
        )
        events = client.get("/api/v1/tasks/ai-demo/events?follow=false", headers=headers)

    assert response.status_code == 200
    assert events.status_code == 200
    assert "event: handoff" in events.text
    assert '"reason":"operator_takeover"' in events.text


def test_resume_event_is_exposed_in_task_events(tmp_path: Path) -> None:
    bridge = FakeBridge()
    headers = {"Authorization": "Bearer test-token"}

    with _make_client(tmp_path, bridge) as client:
        created = client.post(
            "/api/v1/tasks",
            json={"project_id": "ai-demo", "cwd": "/tmp/w1", "task_title": "t1"},
            headers=headers,
        )
        assert created.status_code == 200

        response = client.post(
            "/api/v1/tasks/ai-demo/resume",
            json={"handoff_summary": "resume from saved handoff"},
            headers=headers,
        )
        events = client.get("/api/v1/tasks/ai-demo/events?follow=false", headers=headers)

    assert response.status_code == 200
    assert events.status_code == 200
    assert "event: resume" in events.text
    assert '"mode":"resume_or_new_thread"' in events.text


def test_approval_decision_posts_back_to_bridge(tmp_path: Path) -> None:
    bridge = FakeBridge()
    headers = {"Authorization": "Bearer test-token"}

    with _make_client(tmp_path, bridge) as client:
        created = client.post(
            "/api/v1/tasks",
            json={"project_id": "ai-demo", "cwd": "/tmp/w1", "task_title": "t1"},
            headers=headers,
        )
        thread_id = created.json()["data"]["thread_id"]
        approval = client.app.state.approvals_store.create_request(
            project_id="ai-demo",
            thread_id=thread_id,
            command="curl https://example.com",
            reason="Need confirmation",
            bridge_request_id="req_123",
        )
        client.app.state.task_store.merge_update(
            "ai-demo",
            {"pending_approval": True, "approval_risk": approval["risk_level"], "phase": "approval"},
        )

        response = client.post(
            f"/api/v1/approvals/{approval['approval_id']}/decision",
            json={"decision": "approve", "operator": "human", "note": "ok"},
            headers=headers,
        )
        task = client.get("/api/v1/tasks/ai-demo", headers=headers).json()["data"]

    assert response.status_code == 200
    assert bridge.approval_calls == [("req_123", "approve", "ok")]
    assert task["pending_approval"] is False


def test_approval_decided_event_is_exposed_in_task_events(tmp_path: Path) -> None:
    bridge = FakeBridge()
    headers = {"Authorization": "Bearer test-token"}

    with _make_client(tmp_path, bridge) as client:
        created = client.post(
            "/api/v1/tasks",
            json={"project_id": "ai-demo", "cwd": "/tmp/w1", "task_title": "t1"},
            headers=headers,
        )
        thread_id = created.json()["data"]["thread_id"]
        approval = client.app.state.approvals_store.create_request(
            project_id="ai-demo",
            thread_id=thread_id,
            command="curl https://example.com",
            reason="Need confirmation",
            bridge_request_id="req_123",
        )
        client.app.state.task_store.merge_update(
            "ai-demo",
            {"pending_approval": True, "approval_risk": approval["risk_level"], "phase": "approval"},
        )

        response = client.post(
            f"/api/v1/approvals/{approval['approval_id']}/decision",
            json={"decision": "approve", "operator": "human", "note": "ok"},
            headers=headers,
        )
        events = client.get("/api/v1/tasks/ai-demo/events?follow=false", headers=headers)

    assert response.status_code == 200
    assert events.status_code == 200
    assert "event: approval_decided" in events.text
    assert f'"approval_id":"{approval["approval_id"]}"' in events.text


def test_resume_failure_does_not_mark_task_running(tmp_path: Path) -> None:
    bridge = FakeBridge(fail_resume=True)
    headers = {"Authorization": "Bearer test-token"}

    with _make_client(tmp_path, bridge) as client:
        client.post(
            "/api/v1/tasks",
            json={"project_id": "ai-demo", "cwd": "/tmp/w1", "task_title": "t1"},
            headers=headers,
        )

        response = client.post(
            "/api/v1/tasks/ai-demo/resume",
            json={"handoff_summary": "resume from saved handoff"},
            headers=headers,
        )
        task = client.get("/api/v1/tasks/ai-demo", headers=headers).json()["data"]

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert task["status"] == "resume_failed"
    assert task["phase"] == "recovery"


def test_approval_callback_failure_keeps_request_pending(tmp_path: Path) -> None:
    bridge = FakeBridge(fail_approval=True)
    headers = {"Authorization": "Bearer test-token"}

    with _make_client(tmp_path, bridge) as client:
        created = client.post(
            "/api/v1/tasks",
            json={"project_id": "ai-demo", "cwd": "/tmp/w1", "task_title": "t1"},
            headers=headers,
        )
        thread_id = created.json()["data"]["thread_id"]
        approval = client.app.state.approvals_store.create_request(
            project_id="ai-demo",
            thread_id=thread_id,
            command="curl https://example.com",
            reason="Need confirmation",
            bridge_request_id="req_123",
        )
        client.app.state.task_store.merge_update(
            "ai-demo",
            {"pending_approval": True, "approval_risk": approval["risk_level"], "phase": "approval"},
        )

        response = client.post(
            f"/api/v1/approvals/{approval['approval_id']}/decision",
            json={"decision": "approve", "operator": "human", "note": "ok"},
            headers=headers,
        )
        task = client.get("/api/v1/tasks/ai-demo", headers=headers).json()["data"]
        stored = client.app.state.approvals_store.get(approval["approval_id"])

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert stored is not None
    assert stored["status"] == "pending"
    assert task["pending_approval"] is True


def test_auto_approved_callback_can_be_retried_via_approval_decision_route(tmp_path: Path) -> None:
    bridge = FakeBridge()
    headers = {"Authorization": "Bearer test-token"}

    with _make_client(tmp_path, bridge) as client:
        created = client.post(
            "/api/v1/tasks",
            json={"project_id": "ai-demo", "cwd": "/tmp/w1", "task_title": "t1"},
            headers=headers,
        )
        thread_id = created.json()["data"]["thread_id"]
        approval = client.app.state.approvals_store.create_request(
            project_id="ai-demo",
            thread_id=thread_id,
            command="pytest -q",
            reason="Safe callback replay",
            bridge_request_id="req_auto_123",
        )

        response = client.post(
            f"/api/v1/approvals/{approval['approval_id']}/decision",
            json={"decision": "approve", "operator": "human", "note": "retry callback"},
            headers=headers,
        )

    assert approval["status"] == "approved"
    assert approval["decided_by"] == "policy-auto"
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert bridge.approval_calls == [("req_auto_123", "approve", "retry callback")]
