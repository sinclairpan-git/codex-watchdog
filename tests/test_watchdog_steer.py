from __future__ import annotations

from unittest.mock import MagicMock, patch

from watchdog.services.action_executor.steer import post_steer


def test_post_steer_ignores_proxy_environment() -> None:
    with patch("watchdog.services.action_executor.steer.httpx.Client") as client_cls:
        client = MagicMock()
        response = MagicMock()
        response.json.return_value = {"success": True}
        client.post.return_value = response
        client_cls.return_value.__enter__.return_value = client

        post_steer(
            "http://127.0.0.1:8710",
            "token",
            "project-1",
            message="continue",
            reason="openclaw_continue_session",
        )

        _, kwargs = client_cls.call_args
        assert kwargs["trust_env"] is False


def test_post_steer_keeps_proxy_environment_for_non_local_base_url() -> None:
    with patch("watchdog.services.action_executor.steer.httpx.Client") as client_cls:
        client = MagicMock()
        response = MagicMock()
        response.json.return_value = {"success": True}
        client.post.return_value = response
        client_cls.return_value.__enter__.return_value = client

        post_steer(
            "https://a-control.example.com",
            "token",
            "project-1",
            message="continue",
            reason="openclaw_continue_session",
        )

        _, kwargs = client_cls.call_args
        assert kwargs["trust_env"] is True


def test_runtime_steer_templates_are_registered_for_waiting_direction_break_loop_and_handoff() -> None:
    from watchdog.services.action_executor import steer

    registry = steer.steer_template_registry()

    assert registry["soft"].reason_code == "soft_steer"
    assert "当前进展" in registry["soft"].message
    assert registry["waiting_for_direction"].reason_code == "waiting_for_direction"
    assert registry["break_loop"].reason_code == "break_loop"
    assert registry["handoff_summary"].reason_code == "handoff_summary"
    assert registry["severe_takeover"].reason_code == "severe_takeover"
