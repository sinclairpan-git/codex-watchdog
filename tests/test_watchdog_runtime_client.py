from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from watchdog.main import create_app
from watchdog.services.delivery.feishu_client import FeishuAppDeliveryClient
from watchdog.services.runtime_client.client import CodexRuntimeClient
from watchdog.settings import Settings


def _settings() -> Settings:
    return Settings(
        api_token="wt",
        codex_runtime_token="rt",
        codex_runtime_base_url="http://runtime.test",
    )


def test_list_approvals_raises_when_upstream_reports_failure() -> None:
    with patch("watchdog.services.runtime_client.client.httpx.Client") as client_cls:
        client = MagicMock()
        client_cls.return_value.__enter__.return_value = client
        client.get.return_value.json.return_value = {
            "success": False,
            "error": {"code": "AUTH_ERROR", "message": "bad token"},
        }

        api = CodexRuntimeClient(_settings())

        with pytest.raises(RuntimeError):
            api.list_approvals(status="pending")


def test_list_approvals_forwards_all_supported_filters() -> None:
    with patch("watchdog.services.runtime_client.client.httpx.Client") as client_cls:
        client = MagicMock()
        client_cls.return_value.__enter__.return_value = client
        client.get.return_value.json.return_value = {
            "success": True,
            "data": {
                "items": [],
            },
        }

        api = CodexRuntimeClient(_settings())

        api.list_approvals(
            status="approved",
            project_id="repo-a",
            decided_by="policy-auto",
            callback_status="deferred",
        )

        _, kwargs = client.get.call_args
        assert kwargs["params"] == {
            "status": "approved",
            "project_id": "repo-a",
            "decided_by": "policy-auto",
            "callback_status": "deferred",
        }


def test_list_tasks_raises_when_upstream_reports_failure() -> None:
    with patch("watchdog.services.runtime_client.client.httpx.Client") as client_cls:
        client = MagicMock()
        client_cls.return_value.__enter__.return_value = client
        client.get.return_value.json.return_value = {
            "success": False,
            "error": {"code": "AUTH_ERROR", "message": "bad token"},
        }

        api = CodexRuntimeClient(_settings())

        with pytest.raises(RuntimeError):
            api.list_tasks()


def test_codex_runtime_client_ignores_proxy_environment() -> None:
    with patch("watchdog.services.runtime_client.client.httpx.Client") as client_cls:
        client = MagicMock()
        client_cls.return_value.__enter__.return_value = client
        client.get.return_value.json.return_value = {
            "success": True,
            "data": {
                "tasks": [],
            },
        }

        api = CodexRuntimeClient(_settings())

        api.list_tasks()

        _, kwargs = client_cls.call_args
        assert kwargs["trust_env"] is False


def test_create_app_uses_runtime_client_and_drops_legacy_routes(tmp_path) -> None:
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="rt",
            codex_runtime_base_url="http://runtime.test",
            data_dir=str(tmp_path),
        )
    )

    assert hasattr(app.state, "runtime_client")
    assert not hasattr(app.state, "a_client")
    assert isinstance(app.state.delivery_client, FeishuAppDeliveryClient)

    paths = {route.path for route in app.routes}
    assert "/api/v1/watchdog/feishu/control" in paths
    assert "/api/v1/watchdog/sessions" in paths
    assert "/api/v1/watchdog/approval-inbox" in paths
