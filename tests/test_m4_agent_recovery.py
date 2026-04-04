from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from a_control_agent.main import create_app
from a_control_agent.settings import Settings


def test_handoff_and_resume(tmp_path: Path) -> None:
    root = tmp_path / "d"
    s = Settings(api_token="t", data_dir=str(root))
    c = TestClient(create_app(s))
    h = {"Authorization": "Bearer t"}
    c.post(
        "/api/v1/tasks",
        json={"project_id": "p1", "cwd": "/", "task_title": "t"},
        headers=h,
    )
    r = c.post("/api/v1/tasks/p1/handoff", json={"reason": "ctx"}, headers=h)
    assert r.status_code == 200
    b = r.json()
    assert b["success"] is True
    assert "handoff_file" in b["data"]
    assert len(b["data"]["summary"]) > 10
    hf = Path(b["data"]["handoff_file"])
    assert hf.is_file()

    r2 = c.post(
        "/api/v1/tasks/p1/resume",
        json={"mode": "resume_or_new_thread", "handoff_summary": "x"},
        headers=h,
    )
    assert r2.json()["data"]["status"] == "running"


def test_handoff_unknown(tmp_path: Path) -> None:
    s = Settings(api_token="t", data_dir=str(tmp_path / "d"))
    c = TestClient(create_app(s))
    r = c.post(
        "/api/v1/tasks/x/handoff",
        json={"reason": "r"},
        headers={"Authorization": "Bearer t"},
    )
    assert r.json()["success"] is False
