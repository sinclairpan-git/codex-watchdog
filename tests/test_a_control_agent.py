from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from a_control_agent.main import create_app
from a_control_agent.settings import Settings


class FakeCodexClient:
    def __init__(self, sessions: list[dict[str, str]]) -> None:
        self._sessions = sessions

    def ping(self) -> bool:
        return True

    def list_threads(self) -> list[dict[str, str]]:
        return list(self._sessions)

    def describe_thread(self, thread_id: str) -> dict[str, str]:
        for session in self._sessions:
            if session["thread_id"] == thread_id:
                return dict(session)
        raise KeyError(thread_id)


class FakeBridge:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


class FailingSteerBridge(FakeBridge):
    def active_turn_id(self, thread_id: str) -> str | None:
        return None

    async def start_turn(self, thread_id: str, *, prompt: str) -> dict[str, str]:
        raise RuntimeError("bridge down")


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    s = Settings(api_token="test-token", data_dir=str(tmp_path / "agent-data"))
    app = create_app(s, start_background_workers=False)
    return TestClient(app)


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_create_app_builds_default_bridge_when_enabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        api_token="test-token",
        data_dir=str(tmp_path / "agent-data"),
        codex_bridge_enabled=True,
    )
    built: list[FakeBridge] = []

    def fake_builder(*_: object, **__: object) -> FakeBridge:
        bridge = FakeBridge()
        built.append(bridge)
        return bridge

    monkeypatch.setattr("a_control_agent.main.build_default_codex_bridge", fake_builder)

    with TestClient(create_app(settings, start_background_workers=False)) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert len(built) == 1
    assert client.app.state.codex_bridge is built[0]
    assert built[0].started is True
    assert built[0].stopped is True


def test_create_task_unauthorized(client: TestClient) -> None:
    r = client.post("/api/v1/tasks", json={"project_id": "p1"})
    assert r.status_code == 401


def test_create_and_get_task(client: TestClient) -> None:
    h = {"Authorization": "Bearer test-token", "X-Request-Id": "rid-1"}
    r = client.post(
        "/api/v1/tasks",
        json={
            "project_id": "ai-demo",
            "cwd": "/tmp/w",
            "task_title": "t",
            "task_prompt": "p",
            "model": "gpt-5.4",
            "sandbox": "workspace-write",
            "approval_policy": "on-request",
        },
        headers=h,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["project_id"] == "ai-demo"
    assert body["data"]["thread_id"].startswith("thr_")

    r2 = client.get("/api/v1/tasks/ai-demo", headers=h)
    assert r2.status_code == 200
    b2 = r2.json()
    assert b2["success"] is True
    assert b2["data"]["status"] == "running"


def test_project_keeps_multiple_threads_and_can_query_by_thread(tmp_path: Path) -> None:
    s = Settings(api_token="test-token", data_dir=str(tmp_path / "agent-data"))
    c = TestClient(create_app(s, start_background_workers=False))
    h = {"Authorization": "Bearer test-token"}
    r1 = c.post(
        "/api/v1/tasks",
        json={"project_id": "ai-demo", "cwd": "/tmp/w1", "task_title": "t1"},
        headers=h,
    )
    r2 = c.post(
        "/api/v1/tasks",
        json={"project_id": "ai-demo", "cwd": "/tmp/w2", "task_title": "t2"},
        headers=h,
    )
    tid1 = r1.json()["data"]["thread_id"]
    tid2 = r2.json()["data"]["thread_id"]
    assert tid1 != tid2

    listed = c.get("/api/v1/tasks", headers=h).json()["data"]["tasks"]
    assert len(listed) == 2
    assert {task["thread_id"] for task in listed} == {tid1, tid2}

    current = c.get("/api/v1/tasks/ai-demo", headers=h).json()["data"]
    assert current["thread_id"] == tid2
    assert current["cwd"] == "/tmp/w2"

    first = c.get(f"/api/v1/tasks/by-thread/{tid1}", headers=h).json()["data"]
    assert first["project_id"] == "ai-demo"
    assert first["thread_id"] == tid1
    assert first["cwd"] == "/tmp/w1"


def test_native_codex_sessions_sync_on_startup(tmp_path: Path) -> None:
    repo = tmp_path / "repo-a"
    repo.mkdir()
    s = Settings(api_token="test-token", data_dir=str(tmp_path / "agent-data"))
    app = create_app(
        s,
        codex_client=FakeCodexClient(
            [
                {
                    "thread_id": "thr_native_1",
                    "cwd": str(repo),
                    "task_title": "Native Session",
                    "status": "running",
                }
            ]
        ),
        start_background_workers=True,
    )
    h = {"Authorization": "Bearer test-token"}
    with TestClient(app) as c:
        listed = c.get("/api/v1/tasks", headers=h)
    body = listed.json()
    assert body["success"] is True
    tasks = body["data"]["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["thread_id"] == "thr_native_1"
    assert tasks[0]["project_id"] == "repo-a"
    assert tasks[0]["task_title"] == "Native Session"


def test_register_native_thread_via_api(tmp_path: Path) -> None:
    repo = tmp_path / "repo-a"
    repo.mkdir()
    s = Settings(api_token="test-token", data_dir=str(tmp_path / "agent-data"))
    c = TestClient(create_app(s, start_background_workers=False))
    h = {"Authorization": "Bearer test-token"}

    r = c.post(
        "/api/v1/tasks/native-threads",
        json={
            "thread_id": "thr_native_api_1",
            "cwd": str(repo),
            "task_title": "Native API Session",
            "status": "running",
            "phase": "editing_source",
            "last_summary": "editing files",
        },
        headers=h,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["thread_id"] == "thr_native_api_1"
    assert body["data"]["project_id"] == "repo-a"
    assert body["data"]["status"] == "running"

    current = c.get("/api/v1/tasks/repo-a", headers=h).json()["data"]
    assert current["thread_id"] == "thr_native_api_1"
    assert current["phase"] == "editing_source"
    assert current["last_summary"] == "editing files"


def test_register_native_thread_upserts_existing_thread(tmp_path: Path) -> None:
    repo = tmp_path / "repo-a"
    repo.mkdir()
    s = Settings(api_token="test-token", data_dir=str(tmp_path / "agent-data"))
    c = TestClient(create_app(s, start_background_workers=False))
    h = {"Authorization": "Bearer test-token"}

    c.post(
        "/api/v1/tasks/native-threads",
        json={
            "thread_id": "thr_native_api_1",
            "cwd": str(repo),
            "task_title": "Native API Session",
            "status": "running",
            "phase": "planning",
        },
        headers=h,
    )
    r = c.post(
        "/api/v1/tasks/native-threads",
        json={
            "thread_id": "thr_native_api_1",
            "cwd": str(repo),
            "status": "waiting_human",
            "phase": "approval",
            "pending_approval": True,
            "approval_risk": "L2",
            "last_summary": "waiting for approval",
        },
        headers=h,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["thread_id"] == "thr_native_api_1"
    assert body["data"]["status"] == "waiting_human"

    task = c.get("/api/v1/tasks/by-thread/thr_native_api_1", headers=h).json()["data"]
    assert task["task_title"] == "Native API Session"
    assert task["status"] == "waiting_human"
    assert task["phase"] == "approval"
    assert task["pending_approval"] is True
    assert task["approval_risk"] == "L2"
    assert task["last_summary"] == "waiting for approval"


def test_get_unknown_project(client: TestClient) -> None:
    h = {"Authorization": "Bearer test-token"}
    r = client.get("/api/v1/tasks/missing", headers=h)
    assert r.status_code == 200
    b = r.json()
    assert b["success"] is False
    assert b["error"]["code"] == "NOT_FOUND"


def test_task_events_endpoint_returns_sse_snapshot(client: TestClient) -> None:
    h = {"Authorization": "Bearer test-token", "X-Request-Id": "rid-events"}
    created = client.post(
        "/api/v1/tasks",
        json={"project_id": "ai-demo", "cwd": "/tmp/w", "task_title": "t"},
        headers=h,
    )
    assert created.status_code == 200

    steered = client.post(
        "/api/v1/tasks/ai-demo/steer",
        json={"message": "continue", "reason": "policy", "source": "watchdog"},
        headers=h,
    )
    assert steered.status_code == 200

    response = client.get("/api/v1/tasks/ai-demo/events?follow=false", headers=h)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: task_created" in response.text
    assert "event: steer" in response.text
    assert '"project_id":"ai-demo"' in response.text


def test_workspace_activity_route_returns_legacy_raw_activity_summary(tmp_path: Path) -> None:
    repo = tmp_path / "repo-a"
    repo.mkdir()
    (repo / "README.md").write_text("hello\n", encoding="utf-8")

    s = Settings(api_token="test-token", data_dir=str(tmp_path / "agent-data"))
    c = TestClient(create_app(s, start_background_workers=False))
    h = {"Authorization": "Bearer test-token"}

    created = c.post(
        "/api/v1/tasks",
        json={"project_id": "repo-a", "cwd": str(repo), "task_title": "t"},
        headers=h,
    )
    assert created.status_code == 200

    response = c.get(
        "/api/v1/tasks/repo-a/workspace-activity?recent_minutes=30",
        headers=h,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["project_id"] == "repo-a"
    assert body["data"]["activity"]["cwd_exists"] is True
    assert body["data"]["activity"]["files_scanned"] >= 1
    assert body["data"]["activity"]["recent_window_minutes"] == 30


def test_steer_bridge_failure_returns_control_link_error_and_audit(tmp_path: Path) -> None:
    s = Settings(api_token="test-token", data_dir=str(tmp_path / "agent-data"))
    app = create_app(s, codex_bridge=FailingSteerBridge(), start_background_workers=False)
    client = TestClient(app, raise_server_exceptions=False)
    h = {"Authorization": "Bearer test-token", "X-Request-Id": "rid-steer-fail"}

    created = client.post(
        "/api/v1/tasks",
        json={"project_id": "ai-demo", "cwd": "/tmp/w", "task_title": "t"},
        headers=h,
    )
    assert created.status_code == 200

    response = client.post(
        "/api/v1/tasks/ai-demo/steer",
        json={"message": "continue", "reason": "policy", "source": "watchdog"},
        headers=h,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "CONTROL_LINK_ERROR"
    assert body["data"]["project_id"] == "ai-demo"
    assert body["data"]["status"] == "running"

    task = client.get("/api/v1/tasks/ai-demo", headers=h).json()["data"]
    assert "continue" not in str(task.get("last_summary") or "")

    audit_path = tmp_path / "agent-data" / "audit.jsonl"
    audit_rows = [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(row.get("action") == "steer_failed" for row in audit_rows)
    assert not any(row.get("action") == "steer_injected" for row in audit_rows)
