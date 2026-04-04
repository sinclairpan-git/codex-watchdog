from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from watchdog.main import create_app
from watchdog.settings import Settings


def test_recover_noop_when_not_critical(tmp_path) -> None:
    task_data = {
        "status": "running",
        "phase": "planning",
        "context_pressure": "medium",
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
        r = c.post(
            "/api/v1/watchdog/tasks/p1/recover",
            headers={"Authorization": "Bearer wt"},
        )
    assert r.status_code == 200
    b = r.json()
    assert b["success"] is True
    assert b["data"]["action"] == "noop"
    mock_inst.post.assert_not_called()


def test_recover_handoff_on_critical(tmp_path) -> None:
    task_data = {
        "status": "running",
        "phase": "coding",
        "context_pressure": "critical",
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
        mock_inst.post.return_value.json.return_value = {
            "success": True,
            "data": {"handoff_file": "/tmp/h.md"},
        }
        mock_inst.post.return_value.raise_for_status = MagicMock()
        r = c.post(
            "/api/v1/watchdog/tasks/p1/recover",
            headers={"Authorization": "Bearer wt"},
        )
    assert r.status_code == 200
    b = r.json()
    assert b["success"] is True
    assert b["data"]["action"] == "handoff_triggered"
    mock_inst.post.assert_called_once()
    call_kw = mock_inst.post.call_args
    assert "/tasks/p1/handoff" in str(call_kw[0][0])


def test_recover_get_error(tmp_path) -> None:
    app = create_app(
        Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://127.0.0.1:9",
            data_dir=str(tmp_path / "wd"),
        )
    )
    c = TestClient(app)
    with patch("watchdog.services.a_client.client.httpx.Client") as mcli:
        mock_inst = MagicMock()
        mcli.return_value.__enter__.return_value = mock_inst
        import httpx

        mock_inst.get.side_effect = httpx.ConnectError("x", request=MagicMock())
        r = c.post(
            "/api/v1/watchdog/tasks/x/recover",
            headers={"Authorization": "Bearer wt"},
        )
    assert r.json()["success"] is False
    assert r.json()["error"]["code"] == "CONTROL_LINK_ERROR"
