from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from a_control_agent.main import create_app
from a_control_agent.settings import Settings


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    s = Settings(api_token="test-token", data_dir=str(tmp_path / "agent-data"))
    app = create_app(s)
    return TestClient(app)


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


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


def test_get_unknown_project(client: TestClient) -> None:
    h = {"Authorization": "Bearer test-token"}
    r = client.get("/api/v1/tasks/missing", headers=h)
    assert r.status_code == 200
    b = r.json()
    assert b["success"] is False
    assert b["error"]["code"] == "NOT_FOUND"
