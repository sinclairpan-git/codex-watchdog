from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from a_control_agent.main import create_app
from a_control_agent.settings import Settings
from watchdog.main import create_app as create_watchdog_app
from watchdog.settings import Settings as WSettings


def test_chain_create_task_workspace_metrics(tmp_path: Path) -> None:
    root = tmp_path / "a"
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "f.txt").write_text("x")
    s = Settings(api_token="tok", data_dir=str(root))
    c = TestClient(create_app(s))
    h = {"Authorization": "Bearer tok"}
    r = c.post(
        "/api/v1/tasks",
        json={
            "project_id": "proj-a",
            "cwd": str(repo),
            "task_title": "t",
        },
        headers=h,
    )
    assert r.json()["success"] is True
    r2 = c.get("/api/v1/tasks/proj-a/workspace-activity", headers=h)
    assert r2.json()["success"] is True
    assert r2.json()["data"]["activity"]["cwd_exists"] is True
    rm = c.get("/metrics")
    assert "aca_tasks_total 1" in rm.text


def test_chain_approval_create_and_decision(tmp_path: Path) -> None:
    s = Settings(api_token="tok", data_dir=str(tmp_path / "a"))
    c = TestClient(create_app(s))
    h = {"Authorization": "Bearer tok"}
    c.post(
        "/api/v1/tasks",
        json={"project_id": "p1", "cwd": "/", "task_title": "t"},
        headers=h,
    )
    tr = c.get("/api/v1/tasks/p1", headers=h)
    tid = tr.json()["data"]["thread_id"]
    r = c.post(
        "/api/v1/approvals",
        json={
            "project_id": "p1",
            "thread_id": tid,
            "command": "curl https://example.com",
            "reason": "need network",
        },
        headers=h,
    )
    assert r.json()["success"] is True
    assert r.json()["data"]["status"] == "pending"
    aid = r.json()["data"]["approval_id"]
    r2 = c.post(
        f"/api/v1/approvals/{aid}/decision",
        json={"decision": "reject", "operator": "integration"},
        headers=h,
    )
    assert r2.json()["success"] is True


def test_chain_watchdog_evaluate_steer_mock(tmp_path: Path) -> None:
    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    task_data = {
        "status": "running",
        "phase": "planning",
        "last_summary": "",
        "files_touched": [],
        "pending_approval": False,
        "context_pressure": "low",
        "last_progress_at": old,
        "stuck_level": 0,
    }
    app = create_watchdog_app(
        WSettings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path / "wd"),
        )
    )
    c = TestClient(app)
    with patch("watchdog.services.runtime_client.client.httpx.Client") as mcli:
        mock_inst = MagicMock()
        mcli.return_value.__enter__.return_value = mock_inst
        mock_inst.get.return_value.json.return_value = {"success": True, "data": task_data}
        mock_inst.post.return_value.json.return_value = {"success": True, "data": {"status": "running"}}
        mock_inst.post.return_value.raise_for_status = MagicMock()
        r = c.post(
            "/api/v1/watchdog/tasks/p1/evaluate",
            headers={"Authorization": "Bearer wt"},
        )
    assert r.json()["success"] is True
    assert r.json()["data"]["steer_sent"] is True
    rm = c.get("/metrics")
    assert "watchdog_auto_steer_total" in rm.text
