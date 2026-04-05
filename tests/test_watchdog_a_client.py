from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from watchdog.services.a_client.client import AControlAgentClient
from watchdog.settings import Settings


def _settings() -> Settings:
    return Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
    )


def test_list_approvals_raises_when_upstream_reports_failure() -> None:
    with patch("watchdog.services.a_client.client.httpx.Client") as client_cls:
        client = MagicMock()
        client_cls.return_value.__enter__.return_value = client
        client.get.return_value.json.return_value = {
            "success": False,
            "error": {"code": "AUTH_ERROR", "message": "bad token"},
        }

        api = AControlAgentClient(_settings())

        with pytest.raises(RuntimeError):
            api.list_approvals(status="pending")


def test_list_tasks_raises_when_upstream_reports_failure() -> None:
    with patch("watchdog.services.a_client.client.httpx.Client") as client_cls:
        client = MagicMock()
        client_cls.return_value.__enter__.return_value = client
        client.get.return_value.json.return_value = {
            "success": False,
            "error": {"code": "AUTH_ERROR", "message": "bad token"},
        }

        api = AControlAgentClient(_settings())

        with pytest.raises(RuntimeError):
            api.list_tasks()
