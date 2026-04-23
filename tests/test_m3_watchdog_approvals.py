from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
from fastapi.testclient import TestClient

from watchdog.main import create_app
from watchdog.settings import Settings


def test_watchdog_approvals_proxy_error() -> None:
    app = create_app(Settings(api_token="wt", codex_runtime_base_url="http://127.0.0.1:1"))
    c = TestClient(app)
    with patch("watchdog.api.approvals_proxy.httpx.Client") as m:
        mock_inst = MagicMock()
        m.return_value.__enter__.return_value = mock_inst
        mock_inst.get.side_effect = httpx.ConnectError("e", request=MagicMock())
        r = c.get("/api/v1/watchdog/approvals", headers={"Authorization": "Bearer wt"})
    assert r.status_code == 200
    b = r.json()
    assert b["success"] is False
    assert b["error"]["code"] == "CONTROL_LINK_ERROR"


def test_watchdog_decision_proxy_ok() -> None:
    app = create_app(Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a"))
    c = TestClient(app)
    with patch("watchdog.api.approvals_proxy.httpx.Client") as m:
        mock_inst = MagicMock()
        m.return_value.__enter__.return_value = mock_inst
        mock_inst.post.return_value.json.return_value = {
            "success": True,
            "data": {"status": "approved"},
        }
        r = c.post(
            "/api/v1/watchdog/approvals/x/decision",
            json={"decision": "approve", "operator": "w"},
            headers={"Authorization": "Bearer wt"},
        )
    assert r.status_code == 200
    assert r.json()["success"] is True
