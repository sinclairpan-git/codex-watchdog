from __future__ import annotations

from fastapi.testclient import TestClient

from a_control_agent.main import create_app
from a_control_agent.settings import Settings


def test_steer_requires_auth(tmp_path) -> None:
    s = Settings(api_token="t", data_dir=str(tmp_path / "d"))
    c = TestClient(create_app(s))
    r = c.post("/api/v1/tasks/x/steer", json={"message": "m"})
    assert r.status_code == 401


def test_steer_ok(tmp_path) -> None:
    s = Settings(api_token="t", data_dir=str(tmp_path / "d"))
    c = TestClient(create_app(s))
    h = {"Authorization": "Bearer t"}
    c.post(
        "/api/v1/tasks",
        json={"project_id": "p1", "cwd": "/", "task_title": "t"},
        headers=h,
    )
    r = c.post(
        "/api/v1/tasks/p1/steer",
        json={"message": "hello", "source": "watchdog", "reason": "stuck_soft"},
        headers=h,
    )
    assert r.status_code == 200
    b = r.json()
    assert b["success"] is True
    g = c.get("/api/v1/tasks/p1", headers=h).json()
    assert "hello" in g["data"]["last_summary"]
