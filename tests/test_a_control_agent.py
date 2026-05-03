from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from a_control_agent.main import _sync_codex_threads, create_app
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


class PauseBridge(FakeBridge):
    def __init__(self) -> None:
        super().__init__()
        self.pause_calls: list[str] = []

    async def pause_thread(self, thread_id: str) -> dict[str, str]:
        self.pause_calls.append(thread_id)
        return {"thread_id": thread_id, "status": "paused"}


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
    assert body["data"]["status"] == "waiting_for_approval"

    task = c.get("/api/v1/tasks/by-thread/thr_native_api_1", headers=h).json()["data"]
    assert task["task_title"] == "Native API Session"
    assert task["status"] == "waiting_for_approval"
    assert task["phase"] == "planning"
    assert task["pending_approval"] is True
    assert task["approval_risk"] == "L2"
    assert task["last_summary"] == "waiting for approval"


def test_native_codex_sessions_normalize_legacy_watchdog_project_identity(tmp_path: Path) -> None:
    s = Settings(api_token="test-token", data_dir=str(tmp_path / "agent-data"))
    app = create_app(
        s,
        codex_client=FakeCodexClient(
            [
                {
                    "thread_id": "thr_native_legacy_1",
                    "project_id": "openclaw-codex-watchdog",
                    "cwd": "/Users/sinclairpan/project/openclaw-codex-watchdog",
                    "task_title": "Legacy Watchdog Session",
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
    assert tasks[0]["project_id"] == "codex-watchdog"
    assert tasks[0]["cwd"] == "/Users/sinclairpan/project/codex-watchdog"


def test_create_task_rejects_invalid_status_and_phase(tmp_path: Path) -> None:
    s = Settings(api_token="test-token", data_dir=str(tmp_path / "agent-data"))
    c = TestClient(create_app(s, start_background_workers=False))
    h = {"Authorization": "Bearer test-token", "X-Request-Id": "rid-invalid"}

    response = c.post(
        "/api/v1/tasks",
        json={
            "project_id": "repo-a",
            "cwd": "/tmp/w",
            "task_title": "bad",
            "status": "waiting_human",
            "phase": "approval",
        },
        headers=h,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "INVALID_ARGUMENT"
    assert "status" in body["error"]["message"]


def test_create_task_rejects_invalid_stuck_level_and_context_pressure(tmp_path: Path) -> None:
    s = Settings(api_token="test-token", data_dir=str(tmp_path / "agent-data"))
    c = TestClient(create_app(s, start_background_workers=False))
    h = {"Authorization": "Bearer test-token", "X-Request-Id": "rid-invalid-shape"}

    response_context = c.post(
        "/api/v1/tasks",
        json={
            "project_id": "repo-a",
            "cwd": "/tmp/w",
            "task_title": "bad-shape",
            "context_pressure": "severe",
        },
        headers=h,
    )
    response_stuck = c.post(
        "/api/v1/tasks",
        json={
            "project_id": "repo-a",
            "cwd": "/tmp/w",
            "task_title": "bad-shape",
            "stuck_level": "abc",
        },
        headers=h,
    )

    assert response_context.status_code == 200
    body_context = response_context.json()
    assert body_context["success"] is False
    assert body_context["error"]["code"] == "INVALID_ARGUMENT"
    assert "context_pressure" in body_context["error"]["message"]

    assert response_stuck.status_code == 200
    body_stuck = response_stuck.json()
    assert body_stuck["success"] is False
    assert body_stuck["error"]["code"] == "INVALID_ARGUMENT"
    assert "stuck_level" in body_stuck["error"]["message"]


def test_create_task_pending_approval_forces_waiting_for_approval_status(tmp_path: Path) -> None:
    s = Settings(api_token="test-token", data_dir=str(tmp_path / "agent-data"))
    c = TestClient(create_app(s, start_background_workers=False))
    h = {"Authorization": "Bearer test-token", "X-Request-Id": "rid-pending"}

    response = c.post(
        "/api/v1/tasks",
        json={
            "project_id": "repo-a",
            "cwd": "/tmp/w",
            "task_title": "needs approval",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": True,
            "approval_risk": "L2",
        },
        headers=h,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "waiting_for_approval"

    task = c.get("/api/v1/tasks/repo-a", headers=h).json()["data"]
    assert task["status"] == "waiting_for_approval"
    assert task["pending_approval"] is True


def test_create_task_rejects_non_boolean_pending_approval(tmp_path: Path) -> None:
    s = Settings(api_token="test-token", data_dir=str(tmp_path / "agent-data"))
    c = TestClient(create_app(s, start_background_workers=False))
    h = {"Authorization": "Bearer test-token", "X-Request-Id": "rid-pending-shape"}

    response = c.post(
        "/api/v1/tasks",
        json={
            "project_id": "repo-a",
            "cwd": "/tmp/w",
            "task_title": "shape",
            "pending_approval": "false",
        },
        headers=h,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "INVALID_ARGUMENT"
    assert "pending_approval" in body["error"]["message"]


def test_register_native_thread_rejects_non_boolean_pending_approval(tmp_path: Path) -> None:
    repo = tmp_path / "repo-a"
    repo.mkdir()
    s = Settings(api_token="test-token", data_dir=str(tmp_path / "agent-data"))
    c = TestClient(create_app(s, start_background_workers=False))
    h = {"Authorization": "Bearer test-token", "X-Request-Id": "rid-native-pending-shape"}

    response = c.post(
        "/api/v1/tasks/native-threads",
        json={
            "thread_id": "thr_native_pending_shape",
            "cwd": str(repo),
            "status": "running",
            "phase": "editing_source",
            "pending_approval": "false",
        },
        headers=h,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "INVALID_ARGUMENT"
    assert "pending_approval" in body["error"]["message"]


def test_register_native_thread_preserves_canonical_values_when_update_uses_unknown_state(tmp_path: Path) -> None:
    repo = tmp_path / "repo-a"
    repo.mkdir()
    s = Settings(api_token="test-token", data_dir=str(tmp_path / "agent-data"))
    c = TestClient(create_app(s, start_background_workers=False))
    h = {"Authorization": "Bearer test-token"}

    c.post(
        "/api/v1/tasks/native-threads",
        json={
            "thread_id": "thr_native_api_2",
            "cwd": str(repo),
            "task_title": "Native API Session",
            "status": "running",
            "phase": "planning",
        },
        headers=h,
    )
    c.post(
        "/api/v1/tasks/native-threads",
        json={
            "thread_id": "thr_native_api_2",
            "cwd": str(repo),
            "status": "mystery_state",
            "phase": "alien_phase",
            "context_pressure": "exploding",
            "stuck_level": "oops",
        },
        headers=h,
    )

    task = c.get("/api/v1/tasks/by-thread/thr_native_api_2", headers=h).json()["data"]
    assert task["status"] == "running"
    assert task["phase"] == "planning"
    assert task["context_pressure"] == "low"
    assert task["stuck_level"] == 0


def test_healthz_reports_persisted_thread_counts_after_restart(tmp_path: Path) -> None:
    data_dir = tmp_path / "agent-data"
    repo = tmp_path / "repo-a"
    repo.mkdir()
    settings = Settings(api_token="test-token", data_dir=str(data_dir))
    headers = {"Authorization": "Bearer test-token"}

    with TestClient(create_app(settings, start_background_workers=False)) as client:
        created = client.post(
            "/api/v1/tasks/native-threads",
            json={
                "thread_id": "thr_native_restart_1",
                "cwd": str(repo),
                "task_title": "Restart Session",
                "status": "running",
            },
            headers=headers,
        )
        assert created.status_code == 200

    with TestClient(create_app(settings, start_background_workers=False)) as restarted:
        health = restarted.get("/healthz")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["tracked_threads"] == 1
    assert health.json()["tracked_projects"] == 1


def test_healthz_counts_projects_distinct_from_threads(tmp_path: Path) -> None:
    data_dir = tmp_path / "agent-data"
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    settings = Settings(api_token="test-token", data_dir=str(data_dir))
    headers = {"Authorization": "Bearer test-token"}

    with TestClient(create_app(settings, start_background_workers=False)) as client:
        created_a = client.post(
            "/api/v1/tasks",
            json={"project_id": "repo-a", "cwd": str(repo_a), "task_title": "A1"},
            headers=headers,
        )
        assert created_a.status_code == 200
        created_b = client.post(
            "/api/v1/tasks",
            json={"project_id": "repo-a", "cwd": str(repo_b), "task_title": "A2"},
            headers=headers,
        )
        assert created_b.status_code == 200
        health = client.get("/healthz")

    assert health.status_code == 200
    assert health.json()["tracked_threads"] == 2
    assert health.json()["tracked_projects"] == 1


def test_metrics_export_projects_distinct_from_threads(tmp_path: Path) -> None:
    data_dir = tmp_path / "agent-data"
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    settings = Settings(api_token="test-token", data_dir=str(data_dir))
    headers = {"Authorization": "Bearer test-token"}

    with TestClient(create_app(settings, start_background_workers=False)) as client:
        created_a = client.post(
            "/api/v1/tasks",
            json={"project_id": "repo-a", "cwd": str(repo_a), "task_title": "A1"},
            headers=headers,
        )
        assert created_a.status_code == 200
        created_b = client.post(
            "/api/v1/tasks",
            json={"project_id": "repo-a", "cwd": str(repo_b), "task_title": "A2"},
            headers=headers,
        )
        assert created_b.status_code == 200
        metrics = client.get("/metrics")

    assert metrics.status_code == 200
    assert "aca_tasks_total 2.0" in metrics.text
    assert "aca_projects_total 1.0" in metrics.text


def test_pause_task_marks_runtime_paused(tmp_path: Path) -> None:
    repo = tmp_path / "repo-a"
    repo.mkdir()
    bridge = PauseBridge()
    c = TestClient(
        create_app(
            Settings(api_token="test-token", data_dir=str(tmp_path / "agent-data")),
            codex_bridge=bridge,
            start_background_workers=False,
        )
    )
    h = {"Authorization": "Bearer test-token"}

    c.post(
        "/api/v1/tasks",
        json={"project_id": "repo-a", "cwd": str(repo), "task_title": "t1"},
        headers=h,
    )
    response = c.post("/api/v1/tasks/repo-a/pause", json={}, headers=h)

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["data"]["status"] == "paused"

    task = c.get("/api/v1/tasks/repo-a", headers=h).json()["data"]
    assert task["status"] == "paused"
    assert bridge.pause_calls == [task["thread_id"]]


def test_sync_does_not_overwrite_operator_paused_status(tmp_path: Path) -> None:
    repo = tmp_path / "repo-a"
    repo.mkdir()
    thread_id = "thr_native_1"
    app = create_app(
        Settings(api_token="test-token", data_dir=str(tmp_path / "agent-data")),
        codex_client=FakeCodexClient(
            [
                {
                    "project_id": "repo-a",
                    "thread_id": thread_id,
                    "cwd": str(repo),
                    "task_title": "Native Session",
                    "status": "running",
                    "phase": "planning",
                    "last_summary": "still executing",
                }
            ]
        ),
        start_background_workers=False,
    )
    c = TestClient(app)
    h = {"Authorization": "Bearer test-token"}

    app.state.task_store.upsert_native_thread(
        {
            "project_id": "repo-a",
            "thread_id": thread_id,
            "cwd": str(repo),
            "task_title": "Native Session",
            "status": "running",
            "phase": "planning",
        }
    )
    app.state.task_store.merge_update(
        "repo-a",
        {
            "status": "paused",
            "phase": "planning",
        },
    )

    asyncio.run(_sync_codex_threads(app))

    task = c.get(f"/api/v1/tasks/by-thread/{thread_id}", headers=h).json()["data"]
    assert task["thread_id"] == thread_id
    assert task["status"] == "paused"
    assert task["last_summary"] == "still executing"


def test_task_list_only_exposes_current_active_native_threads_after_sync(tmp_path: Path) -> None:
    active_repo = tmp_path / "repo-active"
    stale_repo = tmp_path / "repo-stale"
    active_repo.mkdir()
    stale_repo.mkdir()
    app = create_app(
        Settings(api_token="test-token", data_dir=str(tmp_path / "agent-data")),
        codex_client=FakeCodexClient(
            [
                {
                    "project_id": "repo-active",
                    "thread_id": "thr_active",
                    "cwd": str(active_repo),
                    "task_title": "Active Native Session",
                    "status": "running",
                    "phase": "planning",
                    "last_summary": "current work",
                }
            ]
        ),
        start_background_workers=False,
    )
    c = TestClient(app)
    h = {"Authorization": "Bearer test-token"}
    app.state.task_store.upsert_native_thread(
        {
            "project_id": "repo-stale",
            "thread_id": "thr_stale",
            "cwd": str(stale_repo),
            "task_title": "Old Native Session",
            "status": "running",
            "phase": "planning",
            "last_summary": "old work",
        }
    )

    asyncio.run(_sync_codex_threads(app))

    listed = c.get("/api/v1/tasks", headers=h).json()["data"]["tasks"]
    assert [task["thread_id"] for task in listed] == ["thr_active"]
    stale = c.get("/api/v1/tasks/by-thread/thr_stale", headers=h).json()["data"]
    assert stale["thread_id"] == "thr_stale"


def test_task_list_returns_empty_when_active_native_sync_finds_no_threads(
    tmp_path: Path,
) -> None:
    stale_repo = tmp_path / "repo-stale"
    stale_repo.mkdir()
    app = create_app(
        Settings(api_token="test-token", data_dir=str(tmp_path / "agent-data")),
        codex_client=FakeCodexClient([]),
        start_background_workers=False,
    )
    c = TestClient(app)
    h = {"Authorization": "Bearer test-token"}
    app.state.task_store.upsert_native_thread(
        {
            "project_id": "repo-stale",
            "thread_id": "thr_stale",
            "cwd": str(stale_repo),
            "task_title": "Old Native Session",
            "status": "running",
            "phase": "planning",
            "last_summary": "old work",
        }
    )

    asyncio.run(_sync_codex_threads(app))

    listed = c.get("/api/v1/tasks", headers=h).json()["data"]["tasks"]
    assert listed == []
    stale = c.get("/api/v1/tasks/by-thread/thr_stale", headers=h).json()["data"]
    assert stale["thread_id"] == "thr_stale"


def test_project_lookup_hides_stale_native_thread_after_empty_active_sync(
    tmp_path: Path,
) -> None:
    stale_repo = tmp_path / "repo-stale"
    stale_repo.mkdir()
    app = create_app(
        Settings(api_token="test-token", data_dir=str(tmp_path / "agent-data")),
        codex_client=FakeCodexClient([]),
        start_background_workers=False,
    )
    c = TestClient(app)
    h = {"Authorization": "Bearer test-token"}
    app.state.task_store.upsert_native_thread(
        {
            "project_id": "repo-stale",
            "thread_id": "thr_stale",
            "cwd": str(stale_repo),
            "task_title": "Old Native Session",
            "status": "running",
            "phase": "planning",
            "last_summary": "old work",
        }
    )

    asyncio.run(_sync_codex_threads(app))

    project = c.get("/api/v1/tasks/repo-stale", headers=h).json()
    assert project["success"] is False
    assert project["error"]["code"] == "NOT_FOUND"
    by_thread = c.get("/api/v1/tasks/by-thread/thr_stale", headers=h).json()["data"]
    assert by_thread["thread_id"] == "thr_stale"


def test_registered_thread_remains_visible_between_active_native_sync_ticks(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo-active"
    repo.mkdir()
    app = create_app(
        Settings(api_token="test-token", data_dir=str(tmp_path / "agent-data")),
        codex_client=FakeCodexClient([]),
        start_background_workers=False,
    )
    c = TestClient(app)
    h = {"Authorization": "Bearer test-token"}

    asyncio.run(_sync_codex_threads(app))
    registered = c.post(
        "/api/v1/tasks/native-threads",
        headers=h,
        json={
            "project_id": "repo-active",
            "thread_id": "thr_new",
            "cwd": str(repo),
            "task_title": "New Native Session",
            "status": "running",
            "phase": "planning",
        },
    )

    assert registered.status_code == 200
    listed = c.get("/api/v1/tasks", headers=h).json()["data"]["tasks"]
    assert [task["thread_id"] for task in listed] == ["thr_new"]


def test_risk_classifier_fails_closed_for_workspace_boundary_and_network_like_commands() -> None:
    from a_control_agent.risk.classifier import auto_approve_allowed, classify_risk

    assert auto_approve_allowed(classify_risk("ls ../")) is False
    assert auto_approve_allowed(classify_risk("permissions:network.http")) is False
    assert auto_approve_allowed(classify_risk("ping api.openai.com")) is False
    assert auto_approve_allowed(classify_risk("dig internal.service.local")) is False
    assert auto_approve_allowed(classify_risk("nslookup release.example.com")) is False
    assert auto_approve_allowed(classify_risk("nc -vz prod-db.internal 5432")) is False
    assert auto_approve_allowed(classify_risk("sudo launchctl kickstart system/com.apple.sshd")) is False
    assert auto_approve_allowed(classify_risk("systemctl restart nginx")) is False
    assert auto_approve_allowed(classify_risk("/usr/bin/systemctl restart nginx")) is False
    assert auto_approve_allowed(classify_risk("rc-service nginx restart")) is False
    assert auto_approve_allowed(classify_risk("systemd-run --unit healthcheck /bin/true")) is False
    assert auto_approve_allowed(classify_risk("shutdown -r now")) is False
    assert auto_approve_allowed(classify_risk("/bin/shutdown -r now")) is False
    assert auto_approve_allowed(classify_risk("reboot")) is False
    assert auto_approve_allowed(classify_risk("poweroff")) is False
    assert auto_approve_allowed(classify_risk("halt")) is False
    assert auto_approve_allowed(classify_risk("init 0")) is False
    assert auto_approve_allowed(classify_risk("init 6")) is False
    assert auto_approve_allowed(classify_risk("killall python")) is False
    assert auto_approve_allowed(classify_risk("pkill -f pytest")) is False
    assert auto_approve_allowed(classify_risk("mount /dev/sda1 /mnt")) is False
    assert auto_approve_allowed(classify_risk("umount /mnt")) is False
    assert auto_approve_allowed(classify_risk("useradd testuser")) is False
    assert auto_approve_allowed(classify_risk("passwd root")) is False
    assert auto_approve_allowed(classify_risk("visudo")) is False
    assert auto_approve_allowed(classify_risk("chmod 600 ~/.ssh/id_rsa")) is False
    assert auto_approve_allowed(classify_risk("cat ~/.ssh/id_rsa")) is False
    assert auto_approve_allowed(classify_risk("cat ~/.aws/credentials")) is False
    assert auto_approve_allowed(classify_risk("cat /proc/self/environ")) is False
    assert auto_approve_allowed(classify_risk("head /proc/self/environ")) is False
    assert auto_approve_allowed(classify_risk("/usr/bin/ping 1.1.1.1")) is False
    assert auto_approve_allowed(classify_risk("ls && mount /dev/sda1 /mnt")) is False
    assert auto_approve_allowed(classify_risk("git status && visudo")) is False
    assert auto_approve_allowed(classify_risk("ls | useradd testuser")) is False
    assert auto_approve_allowed(classify_risk("pwd & mount /dev/sda1 /mnt")) is False
    assert auto_approve_allowed(classify_risk("ls\nmount /dev/sda1 /mnt")) is False
    assert auto_approve_allowed(classify_risk("git status\r\nvisudo")) is False
    assert auto_approve_allowed(classify_risk("ls\tmount /dev/sda1 /mnt")) is False
    assert auto_approve_allowed(classify_risk("pwd\vmount /dev/sda1 /mnt")) is False
    assert auto_approve_allowed(classify_risk("pwd\fmount /dev/sda1 /mnt")) is False
    assert auto_approve_allowed(classify_risk("ls $(mount /dev/sda1 /mnt)")) is False
    assert auto_approve_allowed(classify_risk("git status `visudo`")) is False
    assert auto_approve_allowed(classify_risk("ls <(mount /dev/sda1 /mnt)")) is False
    assert auto_approve_allowed(classify_risk("git status >(visudo)")) is False
    assert auto_approve_allowed(classify_risk("ls /tmp")) is False
    assert auto_approve_allowed(classify_risk("du /var")) is False
    assert auto_approve_allowed(classify_risk("tree /opt")) is False
    assert auto_approve_allowed(classify_risk("git status /tmp")) is False
    assert auto_approve_allowed(classify_risk("pytest ..")) is False
    assert auto_approve_allowed(classify_risk("pytest /tmp")) is False
    assert auto_approve_allowed(classify_risk("pytest --rootdir=/tmp")) is False
    assert auto_approve_allowed(classify_risk("pytest --rootdir /tmp")) is False
    assert auto_approve_allowed(classify_risk("uv run pytest ..")) is False
    assert auto_approve_allowed(classify_risk("uv run pytest --rootdir=/tmp")) is False
    assert auto_approve_allowed(classify_risk("python3 -m pytest /tmp")) is False
    assert auto_approve_allowed(classify_risk("python3 -m pytest --rootdir=/tmp")) is False
    assert auto_approve_allowed(classify_risk("echo snapshot")) is False
    assert auto_approve_allowed(classify_risk("python -c \"print('snapshot')\"")) is False
    assert auto_approve_allowed(classify_risk('bash -lc "shutdown now"')) is False
    assert auto_approve_allowed(classify_risk('sh -c "ping api.openai.com"')) is False
    assert (
        auto_approve_allowed(
            classify_risk('python -c "import os; os.system(\'reboot\')"')
        )
        is False
    )
    assert auto_approve_allowed(classify_risk('bash -lc "echo ok;shutdown now"')) is False
    assert auto_approve_allowed(classify_risk('bash -lc "echo ok&&reboot"')) is False
    assert auto_approve_allowed(classify_risk('bash -lc "echo ok|ping api.openai.com"')) is False
    assert auto_approve_allowed(classify_risk("printenv OPENAI_API_KEY")) is False
    assert auto_approve_allowed(classify_risk("rm -rf /tmp/build")) is False
    assert auto_approve_allowed(classify_risk("python scripts/release.py --publish")) is False


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
