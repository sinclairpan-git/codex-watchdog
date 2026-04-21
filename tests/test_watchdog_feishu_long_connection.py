from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import pytest

from watchdog.main import create_app
from watchdog.services.feishu_long_connection import (
    FeishuLongConnectionConfigError,
    FeishuLongConnectionGateway,
    FeishuLongConnectionRuntime,
)
from watchdog.services.goal_contract.service import GoalContractService
from watchdog.settings import Settings


class _IngressAClient:
    def __init__(self, *, tasks: list[dict[str, object]]) -> None:
        self._tasks = tasks
        self.pause_calls: list[str] = []

    def list_tasks(self) -> list[dict[str, object]]:
        return [dict(task) for task in self._tasks]

    def trigger_pause(self, project_id: str) -> dict[str, object]:
        self.pause_calls.append(project_id)
        return {
            "success": True,
            "data": {"project_id": project_id, "status": "paused"},
        }

    def get_envelope(self, project_id: str) -> dict[str, object]:
        task = next(task for task in self._tasks if task["project_id"] == project_id)
        return {"success": True, "data": dict(task)}

    def get_envelope_by_thread(self, thread_id: str) -> dict[str, object]:
        task = next(
            task
            for task in self._tasks
            if task["thread_id"] == thread_id or task.get("native_thread_id") == thread_id
        )
        return {"success": True, "data": dict(task)}

    def list_approvals(self, **_: object) -> list[dict[str, object]]:
        return []


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        api_token="watchdog-token",
        a_agent_token="a-agent-token",
        a_agent_base_url="http://a-control.test",
        data_dir=str(tmp_path),
        feishu_event_ingress_mode="long_connection",
        feishu_callback_ingress_mode="long_connection",
        feishu_app_id="cli_long_connection",
        feishu_app_secret="secret-long-connection",
        feishu_verification_token="verify-token",
    )


def _task(
    project_id: str,
    *,
    thread_id: str | None = None,
    native_thread_id: str | None = None,
    status: str = "running",
) -> dict[str, object]:
    return {
        "project_id": project_id,
        "thread_id": thread_id or f"session:{project_id}",
        "native_thread_id": native_thread_id or f"thr:{project_id}",
        "status": status,
        "phase": "planning",
        "pending_approval": False,
        "last_summary": "waiting",
        "files_touched": [],
        "context_pressure": "low",
        "stuck_level": 0,
        "failure_count": 0,
        "last_progress_at": "2026-04-16T13:00:00Z",
    }


def _message_event(
    text: str,
    *,
    token: str = "verify-token",
    event_id: str = "evt-feishu-1",
    message_id: str = "om_message_1",
) -> dict[str, object]:
    return {
        "schema": "2.0",
        "header": {
            "event_id": event_id,
            "event_type": "im.message.receive_v1",
            "create_time": "1713274200000",
            "token": token,
            "app_id": "cli_app",
            "tenant_key": "tenant-1",
        },
        "event": {
            "message": {
                "message_id": message_id,
                "chat_id": "oc_dm_chat_1",
                "chat_type": "p2p",
                "message_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
            "sender": {"sender_id": {"open_id": "ou_actor_1"}},
        },
    }


def _callback_event(event_type: str) -> dict[str, object]:
    return {
        "schema": "2.0",
        "header": {
            "event_id": "evt-callback-1",
            "event_type": event_type,
            "create_time": "1713274200000",
            "token": "verify-token",
            "app_id": "cli_app",
            "tenant_key": "tenant-1",
        },
        "event": {
            "operator": {"open_id": "ou_actor_1"},
            "token": "callback-token",
            "action": {"value": {"decision": "approve"}},
            "context": {"open_message_id": "om_message_1"},
        },
    }


def _p2p_entered_event() -> dict[str, object]:
    return {
        "schema": "2.0",
        "header": {
            "event_id": "evt-entered-1",
            "event_type": "im.chat.access_event.bot_p2p_chat_entered_v1",
            "create_time": "1713274200000",
            "token": "verify-token",
            "app_id": "cli_app",
            "tenant_key": "tenant-1",
        },
        "event": {
            "chat_id": "oc_dm_chat_1",
            "operator_id": {"open_id": "ou_actor_1"},
            "last_message_id": "om_last_1",
            "last_message_create_time": "1713274200000",
        },
    }


def test_feishu_long_connection_gateway_routes_message_event(tmp_path: Path) -> None:
    app = create_app(settings=_settings(tmp_path), a_client=_IngressAClient(tasks=[_task("repo-a")]))
    gateway = FeishuLongConnectionGateway.from_app(app)

    result = gateway.handle_message_event(_message_event("repo:repo-a pause"))

    assert result["accepted"] is True
    assert result["event_type"] == "command_request"
    assert result["chat_id"] == "oc_dm_chat_1"
    assert result["sender_open_id"] == "ou_actor_1"
    assert app.state.a_client.pause_calls == ["repo-a"]


def test_feishu_long_connection_gateway_import_boundary_suppresses_sdk_deprecation_warnings(
    tmp_path: Path,
) -> None:
    for module_name in list(sys.modules):
        if module_name == "lark_oapi" or module_name.startswith("lark_oapi.") or module_name == "websockets" or module_name.startswith("websockets."):
            sys.modules.pop(module_name, None)

    app = create_app(settings=_settings(tmp_path), a_client=_IngressAClient(tasks=[_task("repo-a")]))
    gateway = FeishuLongConnectionGateway.from_app(app)

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        result = gateway.handle_message_event(_message_event("repo:repo-a pause"))

    assert result["accepted"] is True


def test_feishu_long_connection_gateway_can_bootstrap_goal_contract(tmp_path: Path) -> None:
    app = create_app(
        settings=_settings(tmp_path),
        a_client=_IngressAClient(tasks=[_task("repo-a", thread_id="session:repo-a")]),
    )
    gateway = FeishuLongConnectionGateway.from_app(app)

    result = gateway.handle_message_event(_message_event("/goal 继续推进 release gate"))

    assert result["accepted"] is True
    contracts = GoalContractService(app.state.session_service)
    assert contracts.get_current_contract(
        project_id="repo-a",
        session_id="session:repo-a",
    ) is not None


def test_feishu_long_connection_gateway_uses_default_project_binding_when_configured(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path).model_copy(update={"default_project_id": "repo-a"})
    app = create_app(
        settings=settings,
        a_client=_IngressAClient(
            tasks=[
                _task("repo-a", thread_id="session:repo-a"),
                _task("repo-b", thread_id="session:repo-b"),
            ]
        ),
    )
    gateway = FeishuLongConnectionGateway.from_app(app)

    result = gateway.handle_message_event(_message_event("/goal 继续推进 release gate"))

    assert result["accepted"] is True
    contracts = GoalContractService(app.state.session_service)
    assert contracts.get_current_contract(
        project_id="repo-a",
        session_id="session:repo-a",
    ) is not None


def test_feishu_long_connection_gateway_acknowledges_card_callback(tmp_path: Path) -> None:
    app = create_app(settings=_settings(tmp_path), a_client=_IngressAClient(tasks=[]))
    gateway = FeishuLongConnectionGateway.from_app(app)

    result = gateway.handle_card_action_callback(_callback_event("card.action.trigger"))

    assert result["toast"]["type"] == "info"


def test_feishu_long_connection_gateway_accepts_p2p_chat_entered_event(tmp_path: Path) -> None:
    app = create_app(settings=_settings(tmp_path), a_client=_IngressAClient(tasks=[]))
    gateway = FeishuLongConnectionGateway.from_app(app)

    result = gateway.handle_bot_p2p_chat_entered_event(_p2p_entered_event())

    assert result == {
        "accepted": "true",
        "chat_id": "oc_dm_chat_1",
        "operator_open_id": "ou_actor_1",
    }


def test_feishu_long_connection_gateway_rejects_unexpected_websocket_header_token(tmp_path: Path) -> None:
    app = create_app(settings=_settings(tmp_path), a_client=_IngressAClient(tasks=[]))
    gateway = FeishuLongConnectionGateway.from_app(app)

    with pytest.raises(ValueError, match="invalid feishu verification token"):
        gateway.handle_bot_p2p_chat_entered_event(
            _p2p_entered_event()
            | {
                "header": {
                    **_p2p_entered_event()["header"],
                    "token": "unexpected-ws-token",
                }
            }
        )


def test_feishu_long_connection_runtime_requires_credentials(tmp_path: Path) -> None:
    settings = _settings(tmp_path).model_copy(update={"feishu_app_secret": None})
    app = create_app(settings=settings, a_client=_IngressAClient(tasks=[]))
    runtime = FeishuLongConnectionRuntime(
        settings=settings,
        gateway=FeishuLongConnectionGateway.from_app(app),
    )

    with pytest.raises(FeishuLongConnectionConfigError):
        runtime.validate_configuration()
