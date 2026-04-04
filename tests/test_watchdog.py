from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
from fastapi.testclient import TestClient

from watchdog.main import create_app
from watchdog.settings import Settings


def test_watchdog_healthz() -> None:
    app = create_app(Settings(api_token="wt", a_agent_base_url="http://127.0.0.1:9"))
    c = TestClient(app)
    r = c.get("/healthz")
    assert r.status_code == 200


@patch("watchdog.services.a_client.client.httpx.Client")
def test_progress_ok(mock_cls: MagicMock) -> None:
    mock_inst = MagicMock()
    mock_cls.return_value.__enter__.return_value = mock_inst
    mock_inst.get.return_value.json.return_value = {
        "success": True,
        "data": {
            "status": "running",
            "phase": "planning",
            "last_summary": "",
            "files_touched": [],
            "pending_approval": False,
            "context_pressure": "low",
            "last_progress_at": None,
        },
    }
    app = create_app(Settings(api_token="wt", a_agent_token="at"))
    c = TestClient(app)
    r = c.get(
        "/api/v1/watchdog/tasks/x/progress",
        headers={"Authorization": "Bearer wt"},
    )
    assert r.status_code == 200
    b = r.json()
    assert b["success"] is True
    assert b["data"]["status"] == "running"


@patch("watchdog.services.a_client.client.httpx.Client")
def test_progress_a_unreachable(mock_cls: MagicMock) -> None:
    mock_inst = MagicMock()
    mock_cls.return_value.__enter__.return_value = mock_inst
    mock_inst.get.side_effect = httpx.ConnectError("refused", request=MagicMock())

    app = create_app(Settings(api_token="wt"))
    c = TestClient(app)
    r = c.get(
        "/api/v1/watchdog/tasks/x/progress",
        headers={"Authorization": "Bearer wt"},
    )
    assert r.status_code == 200
    b = r.json()
    assert b["success"] is False
    assert b["error"]["code"] == "CONTROL_LINK_ERROR"
