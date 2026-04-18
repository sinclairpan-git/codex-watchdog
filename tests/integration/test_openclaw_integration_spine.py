from __future__ import annotations

import inspect
import json
import importlib.util
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from watchdog.main import create_app
from watchdog.services.adapters.openclaw.adapter import OpenClawAdapter
from watchdog.services.a_client.client import AControlAgentClient
from watchdog.services.session_service import SessionService
from watchdog.settings import Settings
from watchdog.storage.action_receipts import ActionReceiptStore


def _load_template_client_module():
    module_path = Path(__file__).resolve().parents[2] / "examples" / "openclaw_watchdog_client.py"
    spec = importlib.util.spec_from_file_location("openclaw_watchdog_client_template", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_A_CLIENT_CONTRACT_METHODS = (
    "get_envelope",
    "get_envelope_by_thread",
    "list_tasks",
    "list_approvals",
    "decide_approval",
    "trigger_pause",
    "trigger_handoff",
    "trigger_resume",
    "get_workspace_activity_envelope",
)


def _assert_a_client_signature_compatibility(fake_client_cls: type[object]) -> None:
    for method_name in _A_CLIENT_CONTRACT_METHODS:
        assert hasattr(fake_client_cls, method_name), f"{fake_client_cls.__name__} missing {method_name}"
        fake_signature = inspect.signature(getattr(fake_client_cls, method_name))
        real_signature = inspect.signature(getattr(AControlAgentClient, method_name))
        assert tuple(fake_signature.parameters) == tuple(
            real_signature.parameters
        ), f"{fake_client_cls.__name__}.{method_name} parameter names drifted"
        for name, real_parameter in real_signature.parameters.items():
            fake_parameter = fake_signature.parameters[name]
            assert (
                fake_parameter.kind == real_parameter.kind
            ), f"{fake_client_cls.__name__}.{method_name} parameter kind drifted for {name}"
            assert (
                fake_parameter.default == real_parameter.default
            ), f"{fake_client_cls.__name__}.{method_name} default drifted for {name}"


class FakeAClient:
    def __init__(
        self,
        *,
        task: dict[str, object],
        tasks: list[dict[str, object]] | None = None,
        approvals: list[dict[str, object]] | None = None,
    ) -> None:
        self._task = dict(task)
        self._tasks = [dict(row) for row in tasks or [task]]
        self._approvals = [dict(approval) for approval in approvals or []]
        self.decision_calls: list[tuple[str, str, str, str]] = []
        self.handoff_calls: list[tuple[str, str]] = []
        self.pause_calls: list[str] = []
        self.resume_calls: list[tuple[str, str, str]] = []
        self.workspace_activity_calls: list[tuple[str, int]] = []

    def get_envelope(self, project_id: str) -> dict[str, object]:
        for task in self._tasks:
            if project_id == task["project_id"]:
                return {"success": True, "data": dict(task)}
        raise AssertionError(project_id)

    def get_envelope_by_thread(self, thread_id: str) -> dict[str, object]:
        for task in self._tasks:
            if thread_id == task["thread_id"]:
                return {"success": True, "data": dict(task)}
        raise AssertionError(thread_id)

    def list_tasks(self) -> list[dict[str, object]]:
        return [dict(task) for task in self._tasks]

    def list_approvals(
        self,
        *,
        status: str | None = None,
        project_id: str | None = None,
        decided_by: str | None = None,
        callback_status: str | None = None,
    ) -> list[dict[str, object]]:
        rows = [dict(approval) for approval in self._approvals]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if project_id:
            rows = [row for row in rows if row.get("project_id") == project_id]
        if decided_by:
            rows = [row for row in rows if row.get("decided_by") == decided_by]
        if callback_status:
            rows = [row for row in rows if row.get("callback_status") == callback_status]
        return rows

    def decide_approval(
        self,
        approval_id: str,
        *,
        decision: str,
        operator: str,
        note: str = "",
    ) -> dict[str, object]:
        self.decision_calls.append((approval_id, decision, operator, note))
        return {
            "success": True,
            "data": {
                "approval_id": approval_id,
                "status": "approved" if decision == "approve" else "rejected",
            },
        }

    def trigger_handoff(
        self,
        project_id: str,
        *,
        reason: str,
    ) -> dict[str, object]:
        self.handoff_calls.append((project_id, reason))
        return {
            "success": True,
            "data": {"handoff_file": f"/tmp/{project_id}.handoff.md", "summary": "handoff"},
        }

    def trigger_pause(self, project_id: str) -> dict[str, object]:
        self.pause_calls.append(project_id)
        return {
            "success": True,
            "data": {"project_id": project_id, "status": "paused"},
        }

    def trigger_resume(
        self,
        project_id: str,
        *,
        mode: str,
        handoff_summary: str,
    ) -> dict[str, object]:
        self.resume_calls.append((project_id, mode, handoff_summary))
        return {
            "success": True,
            "data": {"project_id": project_id, "status": "running", "mode": mode},
        }

    def get_workspace_activity_envelope(
        self,
        project_id: str,
        *,
        recent_minutes: int = 15,
    ) -> dict[str, object]:
        self.workspace_activity_calls.append((project_id, recent_minutes))
        return {
            "success": True,
            "data": {
                "project_id": project_id,
                "activity": {
                    "cwd_exists": True,
                    "files_scanned": 8,
                    "latest_mtime_iso": "2026-04-05T05:31:00Z",
                    "recent_change_count": 1,
                    "recent_window_minutes": recent_minutes,
                },
            },
        }


class BrokenAClient:
    def get_envelope(self, project_id: str) -> dict[str, object]:
        raise httpx.ConnectError("refused", request=httpx.Request("GET", f"http://a.test/{project_id}"))

    def get_envelope_by_thread(self, thread_id: str) -> dict[str, object]:
        raise httpx.ConnectError("refused", request=httpx.Request("GET", f"http://a.test/{thread_id}"))

    def get_workspace_activity_envelope(
        self,
        project_id: str,
        *,
        recent_minutes: int = 15,
    ) -> dict[str, object]:
        _ = recent_minutes
        raise httpx.ConnectError("refused", request=httpx.Request("GET", f"http://a.test/{project_id}"))

    def list_approvals(
        self,
        *,
        status: str | None = None,
        project_id: str | None = None,
        decided_by: str | None = None,
        callback_status: str | None = None,
    ) -> list[dict[str, object]]:
        _ = (status, project_id, decided_by, callback_status)
        return []

    def list_tasks(self) -> list[dict[str, object]]:
        raise httpx.ConnectError("refused", request=httpx.Request("GET", "http://a.test/tasks"))

    def decide_approval(
        self,
        approval_id: str,
        *,
        decision: str,
        operator: str,
        note: str = "",
    ) -> dict[str, object]:
        _ = (approval_id, decision, operator, note)
        return {"success": False, "error": {"code": "CONTROL_LINK_ERROR", "message": "broken"}}

    def trigger_handoff(
        self,
        project_id: str,
        *,
        reason: str,
    ) -> dict[str, object]:
        _ = (project_id, reason)
        return {"success": False, "error": {"code": "CONTROL_LINK_ERROR", "message": "broken"}}

    def trigger_pause(self, project_id: str) -> dict[str, object]:
        _ = project_id
        return {"success": False, "error": {"code": "CONTROL_LINK_ERROR", "message": "broken"}}

    def trigger_resume(
        self,
        project_id: str,
        *,
        mode: str,
        handoff_summary: str,
    ) -> dict[str, object]:
        _ = (project_id, mode, handoff_summary)
        return {"success": False, "error": {"code": "CONTROL_LINK_ERROR", "message": "broken"}}


def test_integration_fake_a_client_matches_a_control_agent_client_core_signature_contract() -> None:
    _assert_a_client_signature_compatibility(FakeAClient)


def test_integration_fake_a_client_broken_stub_matches_a_control_agent_client_core_signature_contract() -> None:
    _assert_a_client_signature_compatibility(BrokenAClient)


def _adapter(tmp_path: Path, client) -> OpenClawAdapter:
    return OpenClawAdapter(
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        client=client,
        receipt_store=ActionReceiptStore(tmp_path / "action_receipts.json"),
    )


def test_integration_continue_session_success(tmp_path: Path) -> None:
    adapter = _adapter(
        tmp_path,
        FakeAClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "editing files",
                "files_touched": ["src/example.py"],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T05:20:00Z",
            }
        ),
    )

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}
        reply = adapter.handle_intent(
            "continue_session",
            project_id="repo-a",
            operator="openclaw",
            idempotency_key="idem-continue-1",
        )

    assert steer_mock.call_count == 1
    assert reply.reply_code == "action_result"
    assert reply.message == "continue request accepted"


def test_integration_openclaw_message_route_supports_native_thread_and_pause(
    tmp_path: Path,
) -> None:
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "editing files",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    adapter = _adapter(tmp_path, client)

    session_reply = adapter.handle_message(
        "任务状态",
        arguments={"native_thread_id": "thr_native_1"},
    )
    pause_reply = adapter.handle_message(
        "暂停",
        arguments={"native_thread_id": "thr_native_1"},
        idempotency_key="idem-pause-native-1",
    )

    assert session_reply.reply_code == "session_projection"
    assert session_reply.session is not None
    assert session_reply.session.project_id == "repo-a"
    assert pause_reply.reply_code == "action_result"
    assert pause_reply.action_result is not None
    assert pause_reply.action_result.effect == "session_paused"
    assert client.pause_calls == ["repo-a"]


def test_integration_openclaw_template_routes_progress_stuck_and_continue(
    monkeypatch,
) -> None:
    template_client = _load_template_client_module()
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"success": True, "path": request.url.path})

    monkeypatch.setenv("WATCHDOG_API_TOKEN", "wt")
    monkeypatch.setenv("WATCHDOG_DEFAULT_PROJECT_ID", "repo-a")

    assert hasattr(template_client, "WatchdogTemplateClient")

    client = template_client.WatchdogTemplateClient(
        base_url="http://watchdog.test",
        transport=httpx.MockTransport(handler),
    )

    progress = client.query_progress()
    stuck = client.query_stuck()
    continuation = client.continue_session(
        project_id="repo-b",
        operator="openclaw",
        idempotency_key="idem-continue-1",
    )

    assert progress["path"] == "/api/v1/watchdog/sessions/repo-a/progress"
    assert stuck["path"] == "/api/v1/watchdog/sessions/repo-a/stuck-explanation"
    assert continuation["path"] == "/api/v1/watchdog/sessions/repo-b/actions/continue"
    assert [request.url.path for request in captured] == [
        "/api/v1/watchdog/sessions/repo-a/progress",
        "/api/v1/watchdog/sessions/repo-a/stuck-explanation",
        "/api/v1/watchdog/sessions/repo-b/actions/continue",
    ]
    assert all(request.headers["Authorization"] == "Bearer wt" for request in captured)
    assert json.loads(captured[2].content.decode()) == {
        "operator": "openclaw",
        "idempotency_key": "idem-continue-1",
    }


def test_integration_openclaw_template_continue_requires_idempotency_key(monkeypatch) -> None:
    template_client = _load_template_client_module()
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"success": True})

    monkeypatch.setenv("WATCHDOG_API_TOKEN", "wt")
    monkeypatch.setenv("WATCHDOG_DEFAULT_PROJECT_ID", "repo-a")

    client = template_client.WatchdogTemplateClient(
        base_url="http://watchdog.test",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(TypeError):
        client.continue_session(project_id="repo-b", operator="openclaw")

    assert captured == []


def test_integration_openclaw_template_routes_approval_inbox_and_decision(
    monkeypatch,
) -> None:
    template_client = _load_template_client_module()
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"success": True, "path": request.url.path})

    monkeypatch.setenv("WATCHDOG_API_TOKEN", "wt")
    monkeypatch.setenv("WATCHDOG_DEFAULT_PROJECT_ID", "repo-a")

    assert hasattr(template_client, "WatchdogTemplateClient")

    client = template_client.WatchdogTemplateClient(
        base_url="http://watchdog.test",
        transport=httpx.MockTransport(handler),
    )

    inbox = client.list_approval_inbox()
    approved = client.approve_approval(
        "appr_001",
        operator="openclaw",
        idempotency_key="idem-approve-1",
        note="looks safe",
    )
    rejected = client.reject_approval(
        "appr_002",
        operator="openclaw",
        idempotency_key="idem-reject-1",
        note="need narrower command",
    )

    assert inbox["path"] == "/api/v1/watchdog/approval-inbox"
    assert approved["path"] == "/api/v1/watchdog/approvals/appr_001/approve"
    assert rejected["path"] == "/api/v1/watchdog/approvals/appr_002/reject"
    assert str(captured[0].url) == "http://watchdog.test/api/v1/watchdog/approval-inbox?project_id=repo-a"
    assert json.loads(captured[1].content.decode()) == {
        "operator": "openclaw",
        "idempotency_key": "idem-approve-1",
        "note": "looks safe",
    }
    assert json.loads(captured[2].content.decode()) == {
        "operator": "openclaw",
        "idempotency_key": "idem-reject-1",
        "note": "need narrower command",
    }


def test_integration_openclaw_template_approval_decisions_require_idempotency_key(
    monkeypatch,
) -> None:
    template_client = _load_template_client_module()
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"success": True})

    monkeypatch.setenv("WATCHDOG_API_TOKEN", "wt")

    client = template_client.WatchdogTemplateClient(
        base_url="http://watchdog.test",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(TypeError):
        client.approve_approval("appr_001", operator="openclaw")
    with pytest.raises(TypeError):
        client.reject_approval("appr_002", operator="openclaw")

    assert captured == []


def test_integration_continue_session_blocked_by_pending_approval(tmp_path: Path) -> None:
    adapter = _adapter(
        tmp_path,
        FakeAClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "waiting_human",
                "phase": "approval",
                "pending_approval": True,
                "last_summary": "waiting for approval",
                "files_touched": [],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T05:20:00Z",
            },
            approvals=[
                {
                    "approval_id": "appr_001",
                    "project_id": "repo-a",
                    "thread_id": "thr_native_1",
                    "status": "pending",
                    "command": "uv run pytest",
                    "reason": "verify tests",
                    "alternative": "",
                    "requested_at": "2026-04-05T05:21:00Z",
                }
            ],
        ),
    )

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        reply = adapter.handle_intent(
            "continue_session",
            project_id="repo-a",
            operator="openclaw",
            idempotency_key="idem-continue-2",
        )

    assert steer_mock.call_count == 0
    assert reply.reply_code == "action_not_available"
    assert reply.message == "session is awaiting human approval"


def test_integration_continue_session_surfaces_control_link_error(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, BrokenAClient())

    reply = adapter.handle_intent(
        "continue_session",
        project_id="repo-a",
        operator="openclaw",
        idempotency_key="idem-continue-3",
    )

    assert reply.reply_code == "control_link_error"


def test_integration_request_recovery_is_advisory_only(tmp_path: Path) -> None:
    adapter = _adapter(
        tmp_path,
        FakeAClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "repeated failures",
                "files_touched": ["src/example.py"],
                "context_pressure": "critical",
                "stuck_level": 2,
                "failure_count": 3,
                "last_progress_at": "2026-04-05T05:20:00Z",
            }
        ),
    )

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        reply = adapter.handle_intent(
            "request_recovery",
            project_id="repo-a",
            operator="openclaw",
            idempotency_key="idem-recovery-1",
        )

    assert steer_mock.call_count == 0
    assert reply.reply_code == "recovery_availability"
    assert reply.message == "recovery is available"


def test_integration_list_session_events_returns_stable_reply_model(tmp_path: Path) -> None:
    class EventsClient(FakeAClient):
        def get_events_snapshot(
            self,
            project_id: str,
            *,
            poll_interval: float = 0.5,
        ) -> tuple[str, str]:
            assert project_id == "repo-a"
            _ = poll_interval
            return (
                'id: evt_001\n'
                "event: task_created\n"
                'data: {"event_id":"evt_001","project_id":"repo-a","thread_id":"thr_native_1","event_type":"task_created","event_source":"a_control_agent","payload_json":{"status":"running","phase":"planning"},"created_at":"2026-04-05T10:00:00Z"}\n\n',
                "text/event-stream",
            )

    adapter = _adapter(
        tmp_path,
        EventsClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "editing files",
                "files_touched": ["src/example.py"],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T05:20:00Z",
            }
        ),
    )

    reply = adapter.handle_intent("list_session_events", project_id="repo-a")

    assert reply.reply_code == "session_event_snapshot"
    assert len(reply.events) == 1
    assert reply.events[0].event_code == "session_created"


def test_integration_post_operator_guidance_success(tmp_path: Path) -> None:
    adapter = _adapter(
        tmp_path,
        FakeAClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "editing files",
                "files_touched": ["src/example.py"],
                "context_pressure": "low",
                "stuck_level": 1,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T05:20:00Z",
            }
        ),
    )

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}
        reply = adapter.handle_intent(
            "post_operator_guidance",
            project_id="repo-a",
            operator="openclaw",
            idempotency_key="idem-guidance-int-1",
            arguments={
                "message": "Summarize the blocker and next exact command.",
                "reason_code": "operator_guidance",
                "stuck_level": 2,
            },
        )

    assert steer_mock.call_count == 1
    assert reply.reply_code == "action_result"
    assert reply.action_result is not None
    assert reply.action_result.action_code == "post_operator_guidance"
    assert reply.action_result.effect == "steer_posted"


def test_integration_api_and_adapter_share_stuck_explanation_semantics(tmp_path: Path) -> None:
    task = {
        "project_id": "repo-a",
        "thread_id": "thr_native_1",
        "status": "running",
        "phase": "editing_source",
        "pending_approval": False,
        "last_summary": "repeated failures",
        "files_touched": ["src/example.py"],
        "context_pressure": "critical",
        "stuck_level": 2,
        "failure_count": 3,
        "last_progress_at": "2026-04-05T05:20:00Z",
    }
    adapter = _adapter(tmp_path, FakeAClient(task=task))
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=FakeAClient(task=task),
    )
    client = TestClient(app)

    adapter_reply = adapter.handle_intent("why_stuck", project_id="repo-a")
    api_response = client.get(
        "/api/v1/watchdog/sessions/repo-a/stuck-explanation",
        headers={"Authorization": "Bearer wt"},
    )

    assert api_response.status_code == 200
    api_reply = api_response.json()["data"]
    assert api_reply["reply_code"] == adapter_reply.reply_code
    assert [fact["fact_code"] for fact in api_reply["facts"]] == [
        fact.fact_code for fact in adapter_reply.facts
    ]
    assert api_reply["message"] == (
        "session appears stuck; repeated failures detected; context pressure is critical"
    )
    assert adapter_reply.message == f'{api_reply["message"]} | 下一步=卡在哪里'


def test_integration_api_and_adapter_share_session_facts_semantics(tmp_path: Path) -> None:
    task = {
        "project_id": "repo-a",
        "thread_id": "thr_native_1",
        "status": "waiting_human",
        "phase": "approval",
        "pending_approval": True,
        "approval_risk": "L2",
        "last_summary": "waiting for approval",
        "files_touched": ["src/example.py"],
        "context_pressure": "low",
        "stuck_level": 0,
        "failure_count": 0,
        "last_progress_at": "2026-04-05T05:20:00Z",
    }
    approvals = [
        {
            "approval_id": "appr_001",
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "pending",
            "command": "uv run pytest",
            "reason": "verify tests",
            "alternative": "",
            "requested_at": "2026-04-05T05:21:00Z",
        }
    ]
    adapter = _adapter(tmp_path, FakeAClient(task=task, approvals=approvals))
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=FakeAClient(task=task, approvals=approvals),
    )
    client = TestClient(app)

    adapter_reply = adapter.handle_intent("list_session_facts", project_id="repo-a")
    api_response = client.get(
        "/api/v1/watchdog/sessions/repo-a/facts",
        headers={"Authorization": "Bearer wt"},
    )

    assert api_response.status_code == 200
    api_reply = api_response.json()["data"]
    assert api_reply["reply_kind"] == adapter_reply.reply_kind
    assert api_reply["reply_code"] == adapter_reply.reply_code
    assert api_reply["intent_code"] == adapter_reply.intent_code
    assert api_reply["message"] == adapter_reply.message
    assert [fact["fact_code"] for fact in api_reply["facts"]] == [
        fact.fact_code for fact in adapter_reply.facts
    ]


def test_integration_api_and_adapter_share_approval_inbox_semantics(tmp_path: Path) -> None:
    task = {
        "project_id": "repo-a",
        "thread_id": "thr_native_1",
        "status": "waiting_human",
        "phase": "approval",
        "pending_approval": True,
        "last_summary": "waiting for approval",
        "files_touched": [],
        "context_pressure": "low",
        "stuck_level": 0,
        "failure_count": 0,
        "last_progress_at": "2026-04-05T05:20:00Z",
    }
    approvals = [
        {
            "approval_id": "appr_001",
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "pending",
            "command": "uv run pytest",
            "reason": "verify tests",
            "alternative": "",
            "requested_at": "2026-04-05T05:21:00Z",
        },
        {
            "approval_id": "appr_002",
            "project_id": "repo-b",
            "thread_id": "thr_native_2",
            "status": "pending",
            "command": "uv run ruff check",
            "reason": "lint gate",
            "alternative": "",
            "requested_at": "2026-04-05T05:22:00Z",
        },
    ]
    adapter = _adapter(tmp_path, FakeAClient(task=task, approvals=approvals))
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=FakeAClient(task=task, approvals=approvals),
    )
    client = TestClient(app)

    adapter_reply = adapter.handle_intent("list_approval_inbox")
    api_response = client.get(
        "/api/v1/watchdog/approval-inbox",
        headers={"Authorization": "Bearer wt"},
    )

    assert api_response.status_code == 200
    api_reply = api_response.json()["data"]
    assert api_reply["reply_code"] == adapter_reply.reply_code
    assert [item["approval_id"] for item in api_reply["approvals"]] == [
        approval.approval_id for approval in adapter_reply.approvals
    ]
    assert [item["thread_id"] for item in api_reply["approvals"]] == [
        approval.thread_id for approval in adapter_reply.approvals
    ]


def test_integration_api_and_adapter_share_session_directory_semantics(tmp_path: Path) -> None:
    tasks = [
        {
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "editing files",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        {
            "project_id": "repo-b",
            "thread_id": "thr_native_2",
            "status": "waiting_human",
            "phase": "approval",
            "pending_approval": True,
            "last_summary": "waiting for approval",
            "files_touched": [],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:21:00Z",
        },
    ]
    approvals = [
        {
            "approval_id": "appr_001",
            "project_id": "repo-b",
            "thread_id": "thr_native_2",
            "status": "pending",
            "command": "uv run pytest",
            "reason": "verify tests",
            "alternative": "",
            "requested_at": "2026-04-05T05:22:00Z",
        },
    ]
    adapter = _adapter(tmp_path, FakeAClient(task=tasks[0], tasks=tasks, approvals=approvals))
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=FakeAClient(task=tasks[0], tasks=tasks, approvals=approvals),
    )
    client = TestClient(app)
    session_service = SessionService.from_data_dir(tmp_path)
    session_service.record_recovery_execution(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        parent_native_thread_id="thr_native_1",
        recovery_reason="context_critical",
        failure_family="context_pressure",
        failure_signature="critical",
        handoff={
            "handoff_file": "/tmp/repo-a.handoff.md",
            "summary": "handoff",
        },
        resume={
            "project_id": "repo-a",
            "status": "running",
            "mode": "resume_or_new_thread",
            "thread_id": "thr_native_1",
        },
        resume_outcome="same_thread_resume",
    )
    session_service.record_recovery_execution(
        project_id="repo-b",
        parent_session_id="session:repo-b",
        parent_native_thread_id="thr_native_2",
        recovery_reason="context_critical",
        failure_family="context_pressure",
        failure_signature="critical",
        handoff={
            "handoff_file": "/tmp/repo-b.handoff.md",
            "summary": "handoff",
        },
        resume={
            "project_id": "repo-b",
            "status": "running",
            "mode": "resume_or_new_thread",
            "session_id": "session:repo-b:child-v1",
        },
    )

    adapter_reply = adapter.handle_intent("list_sessions")
    api_response = client.get(
        "/api/v1/watchdog/sessions",
        headers={"Authorization": "Bearer wt"},
    )

    assert api_response.status_code == 200
    api_reply = api_response.json()["data"]
    assert api_reply["reply_code"] == adapter_reply.reply_code
    assert [item["project_id"] for item in api_reply["sessions"]] == [
        session.project_id for session in adapter_reply.sessions
    ]
    assert [item["pending_approval_count"] for item in api_reply["sessions"]] == [
        session.pending_approval_count for session in adapter_reply.sessions
    ]
    assert [item["project_id"] for item in api_reply["progresses"]] == [
        progress.project_id for progress in adapter_reply.progresses
    ]
    assert [item["recovery_outcome"] for item in api_reply["progresses"]] == [
        progress.recovery_outcome for progress in adapter_reply.progresses
    ]
    assert [item["recovery_child_session_id"] for item in api_reply["progresses"]] == [
        progress.recovery_child_session_id for progress in adapter_reply.progresses
    ]
    assert api_reply["message"] == (
        "多项目进展（2）\n"
        "- repo-a | editing_source | editing files | 上下文=low | 恢复=原线程续跑\n"
        "- repo-b | approval | waiting for approval | 上下文=low | 恢复=新子会话 repo-b:child-v1"
    )
    assert adapter_reply.message == (
        "多项目进展（2） | 状态=进行中1、待审批1 | 先处理=repo-b:待审批\n"
        "- repo-b | approval | waiting for approval | 上下文=low | 恢复=新子会话 repo-b:child-v1"
        " | 关注=待审批 | 下一步=审批列表、回复同意/拒绝、卡在哪里\n"
        "- repo-a | editing_source | editing files | 上下文=low | 恢复=原线程续跑"
    )


def test_integration_api_and_adapter_share_native_thread_resolution_semantics(tmp_path: Path) -> None:
    task = {
        "project_id": "repo-a",
        "thread_id": "thr_native_1",
        "status": "waiting_human",
        "phase": "approval",
        "pending_approval": True,
        "approval_risk": "L2",
        "last_summary": "waiting for approval",
        "files_touched": ["src/example.py"],
        "context_pressure": "low",
        "stuck_level": 0,
        "failure_count": 0,
        "last_progress_at": "2026-04-05T05:20:00Z",
    }
    approvals = [
        {
            "approval_id": "appr_001",
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "pending",
            "command": "uv run pytest",
            "reason": "verify tests",
            "alternative": "",
            "requested_at": "2026-04-05T05:21:00Z",
        }
    ]
    adapter = _adapter(tmp_path, FakeAClient(task=task, approvals=approvals))
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=FakeAClient(task=task, approvals=approvals),
    )
    client = TestClient(app)

    adapter_reply = adapter.handle_intent(
        "get_session_by_native_thread",
        arguments={"native_thread_id": "thr_native_1"},
    )
    api_response = client.get(
        "/api/v1/watchdog/sessions/by-native-thread/thr_native_1",
        headers={"Authorization": "Bearer wt"},
    )

    assert api_response.status_code == 200
    api_reply = api_response.json()["data"]
    assert api_reply["reply_code"] == adapter_reply.reply_code
    assert api_reply["intent_code"] == adapter_reply.intent_code
    assert api_reply["session"]["project_id"] == adapter_reply.session.project_id
    assert api_reply["session"]["thread_id"] == adapter_reply.session.thread_id
    assert api_reply["session"]["native_thread_id"] == adapter_reply.session.native_thread_id
    assert [fact["fact_code"] for fact in api_reply["facts"]] == [
        fact.fact_code for fact in adapter_reply.facts
    ]


def test_integration_api_and_adapter_share_workspace_activity_semantics(tmp_path: Path) -> None:
    task = {
        "project_id": "repo-a",
        "thread_id": "thr_native_1",
        "status": "running",
        "phase": "editing_source",
        "pending_approval": False,
        "last_summary": "editing files",
        "files_touched": ["src/example.py"],
        "context_pressure": "low",
        "stuck_level": 0,
        "failure_count": 0,
        "last_progress_at": "2026-04-05T05:20:00Z",
    }
    adapter = _adapter(tmp_path, FakeAClient(task=task))
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=FakeAClient(task=task),
    )
    client = TestClient(app)

    adapter_reply = adapter.handle_intent(
        "get_workspace_activity",
        project_id="repo-a",
        arguments={"recent_minutes": 30},
    )
    api_response = client.get(
        "/api/v1/watchdog/sessions/repo-a/workspace-activity?recent_minutes=30",
        headers={"Authorization": "Bearer wt"},
    )

    assert api_response.status_code == 200
    api_reply = api_response.json()["data"]
    assert api_reply["reply_code"] == adapter_reply.reply_code
    assert api_reply["message"] == adapter_reply.message
    assert api_reply["workspace_activity"]["recent_change_count"] == 1
    assert api_reply["workspace_activity"]["recent_window_minutes"] == 30


def test_integration_execute_recovery_triggers_stable_recovery_action(tmp_path: Path) -> None:
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "repeated failures",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    adapter = _adapter(tmp_path, client)

    reply = adapter.handle_intent(
        "execute_recovery",
        project_id="repo-a",
        operator="openclaw",
        idempotency_key="idem-execute-recovery-1",
    )

    assert client.handoff_calls == [("repo-a", "context_critical")]
    assert reply.reply_code == "recovery_execution_result"
    assert reply.message == "recovery handoff triggered"


def test_integration_can_query_execute_recovery_receipt_after_action(tmp_path: Path) -> None:
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "repeated failures",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    adapter = _adapter(tmp_path, client)

    execute_reply = adapter.handle_intent(
        "execute_recovery",
        project_id="repo-a",
        operator="openclaw",
        idempotency_key="idem-execute-recovery-lookup-1",
    )
    receipt_reply = adapter.handle_intent(
        "get_action_receipt",
        project_id="repo-a",
        idempotency_key="idem-execute-recovery-lookup-1",
        arguments={"action_code": "execute_recovery"},
    )

    assert execute_reply.reply_code == "recovery_execution_result"
    assert receipt_reply.reply_code == "action_receipt"
    assert receipt_reply.action_result is not None
    assert receipt_reply.action_result.effect == "handoff_triggered"


def test_integration_approval_actions_cover_approve_and_reject(tmp_path: Path) -> None:
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "waiting_human",
            "phase": "approval",
            "pending_approval": True,
            "last_summary": "waiting for approval",
            "files_touched": [],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        approvals=[
            {
                "approval_id": "appr_001",
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "pending",
                "command": "uv run pytest",
                "reason": "verify tests",
                "alternative": "",
                "requested_at": "2026-04-05T05:21:00Z",
            }
        ],
    )
    adapter = _adapter(tmp_path, client)

    approve = adapter.handle_intent(
        "approve_approval",
        project_id="repo-a",
        operator="openclaw",
        approval_id="appr_001",
        idempotency_key="idem-approval-1",
    )
    reject = adapter.handle_intent(
        "reject_approval",
        project_id="repo-a",
        operator="openclaw",
        approval_id="appr_001",
        idempotency_key="idem-approval-2",
    )

    assert approve.reply_code == "approval_result"
    assert reject.reply_code == "approval_result"
    assert client.decision_calls == [
        ("appr_001", "approve", "openclaw", ""),
        ("appr_001", "reject", "openclaw", ""),
    ]
