from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from watchdog.main import create_app
from watchdog.settings import Settings


def test_evaluate_connection_error() -> None:
    app = create_app(Settings(api_token="wt", a_agent_base_url="http://127.0.0.1:9", data_dir="/tmp/wd"))
    c = TestClient(app)
    with patch("watchdog.services.a_client.client.httpx.Client") as m:
        mock_inst = MagicMock()
        m.return_value.__enter__.return_value = mock_inst
        import httpx

        mock_inst.get.side_effect = httpx.ConnectError("x", request=MagicMock())
        r = c.post(
            "/api/v1/watchdog/tasks/x/evaluate",
            headers={"Authorization": "Bearer wt"},
        )
    assert r.status_code == 200
    assert r.json()["success"] is False
    assert r.json()["error"]["code"] == "CONTROL_LINK_ERROR"


def test_evaluate_steer_path(tmp_path) -> None:
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
    app = create_app(
        Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path / "wd"),
        )
    )
    c = TestClient(app)
    with patch("watchdog.services.a_client.client.httpx.Client") as mcli:
        mock_inst = MagicMock()
        mcli.return_value.__enter__.return_value = mock_inst
        mock_inst.get.return_value.json.return_value = {"success": True, "data": task_data}
        mock_inst.post.return_value.json.return_value = {"success": True, "data": {"status": "running"}}
        mock_inst.post.return_value.raise_for_status = MagicMock()
        r = c.post(
            "/api/v1/watchdog/tasks/p1/evaluate",
            headers={"Authorization": "Bearer wt"},
        )
    assert r.status_code == 200
    b = r.json()
    assert b["success"] is True
    assert b["data"]["steer_sent"] is True
    mock_inst.post.assert_called_once()
