from __future__ import annotations

import inspect
import json
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from watchdog.main import create_app
from watchdog.services.approvals.service import materialize_canonical_approval
from watchdog.services.adapters.openclaw.adapter import OpenClawAdapter
from watchdog.services.a_client.client import AControlAgentClient
from watchdog.services.policy.decisions import CanonicalDecisionRecord
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
    "get_events_snapshot",
    "iter_events",
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
        continuation_packet: dict[str, object] | None = None,
    ) -> dict[str, object]:
        _ = continuation_packet
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
        continuation_packet: dict[str, object] | None = None,
    ) -> dict[str, object]:
        _ = continuation_packet
        self.resume_calls.append((project_id, mode, handoff_summary))
        return {
            "success": True,
            "data": {"project_id": project_id, "status": "running", "mode": mode},
        }

    def get_events_snapshot(
        self,
        project_id: str,
        *,
        poll_interval: float = 0.5,
    ) -> tuple[str, str]:
        assert project_id == self._task["project_id"]
        _ = poll_interval
        return (
            'id: evt_001\n'
            "event: task_created\n"
            'data: {"event_id":"evt_001","project_id":"repo-a","thread_id":"thr_native_1","event_type":"task_created","event_source":"a_control_agent","payload_json":{"status":"running","phase":"planning"},"created_at":"2026-04-05T10:00:00Z"}\n\n',
            "text/event-stream",
        )

    def iter_events(
        self,
        project_id: str,
        *,
        poll_interval: float = 0.5,
    ):
        assert project_id == self._task["project_id"]
        _ = poll_interval
        if False:
            yield ""

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
        continuation_packet: dict[str, object] | None = None,
    ) -> dict[str, object]:
        _ = (project_id, reason, continuation_packet)
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
        continuation_packet: dict[str, object] | None = None,
    ) -> dict[str, object]:
        _ = (project_id, mode, handoff_summary, continuation_packet)
        return {"success": False, "error": {"code": "CONTROL_LINK_ERROR", "message": "broken"}}

    def get_events_snapshot(
        self,
        project_id: str,
        *,
        poll_interval: float = 0.5,
    ) -> tuple[str, str]:
        _ = (project_id, poll_interval)
        raise httpx.ConnectError("refused", request=httpx.Request("GET", f"http://a.test/{project_id}/events"))

    def iter_events(
        self,
        project_id: str,
        *,
        poll_interval: float = 0.5,
    ):
        _ = (project_id, poll_interval)
        raise httpx.ConnectError("refused", request=httpx.Request("GET", f"http://a.test/{project_id}/events"))


def test_integration_fake_a_client_matches_a_control_agent_client_core_signature_contract() -> None:
    _assert_a_client_signature_compatibility(FakeAClient)


def test_integration_fake_a_client_broken_stub_matches_a_control_agent_client_core_signature_contract() -> None:
    _assert_a_client_signature_compatibility(BrokenAClient)


def _adapter(
    tmp_path: Path,
    client,
    *,
    resident_expert_stale_after_seconds: float = 900.0,
) -> OpenClawAdapter:
    return OpenClawAdapter(
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            resident_expert_stale_after_seconds=resident_expert_stale_after_seconds,
        ),
        client=client,
        receipt_store=ActionReceiptStore(tmp_path / "action_receipts.json"),
    )


def _decision_record(
    *,
    project_id: str = "repo-a",
    session_id: str = "session:repo-a",
    fact_snapshot_version: str = "fact-v7",
) -> CanonicalDecisionRecord:
    return CanonicalDecisionRecord(
        decision_id=f"decision:{project_id}:{fact_snapshot_version}:require_user_decision",
        decision_key=(
            f"{session_id}|{fact_snapshot_version}|policy-v1|require_user_decision|execute_recovery|"
        ),
        session_id=session_id,
        project_id=project_id,
        thread_id=session_id,
        native_thread_id=f"native:{project_id}",
        approval_id=None,
        action_ref="execute_recovery",
        trigger="resident_supervision",
        decision_result="require_user_decision",
        risk_class="human_gate",
        decision_reason="manual approval required",
        matched_policy_rules=["registered_action"],
        why_not_escalated=None,
        why_escalated="manual decision required",
        uncertainty_reasons=[],
        policy_version="policy-v1",
        fact_snapshot_version=fact_snapshot_version,
        idempotency_key=(
            f"{session_id}|{fact_snapshot_version}|policy-v1|require_user_decision|execute_recovery|"
        ),
        created_at="2026-04-07T00:00:00Z",
        operator_notes=[],
        evidence={
            "facts": [
                {
                    "fact_id": "fact-1",
                    "fact_code": "recovery_available",
                    "fact_kind": "signal",
                    "severity": "info",
                    "summary": "recovery available",
                    "detail": "recovery available",
                    "source": "watchdog",
                    "observed_at": "2026-04-07T00:00:00Z",
                    "related_ids": {},
                }
            ],
            "matched_policy_rules": ["registered_action"],
            "decision": {
                "decision_result": "require_user_decision",
                "action_ref": "execute_recovery",
                "approval_id": None,
            },
        },
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


def test_integration_openclaw_message_route_supports_session_events_queries(
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

    event_reply = adapter.handle_message(
        "事件流",
        project_id="repo-a",
    )
    native_thread_reply = adapter.handle_message(
        "会话事件",
        arguments={"native_thread_id": "thr_native_1"},
    )

    assert event_reply.intent_code == "list_session_events"
    assert event_reply.reply_code == "session_event_snapshot"
    assert event_reply.events is not None
    assert len(event_reply.events) == 1
    assert event_reply.events[0].event_code == "session_created"

    assert native_thread_reply.intent_code == "list_session_events"
    assert native_thread_reply.reply_code == "session_event_snapshot"
    assert native_thread_reply.events is not None
    assert len(native_thread_reply.events) == 1
    assert native_thread_reply.events[0].project_id == "repo-a"


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


def test_integration_continue_session_uses_session_events_when_a_side_is_unavailable(
    tmp_path: Path,
) -> None:
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=BrokenAClient(),
    )
    materialize_canonical_approval(
        _decision_record(project_id="repo-a").model_copy(update={"native_thread_id": "thr_native_1"}),
        approval_store=app.state.canonical_approval_store,
        session_service=app.state.session_service,
    )
    adapter = _adapter(tmp_path, BrokenAClient())

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        reply = adapter.handle_intent(
            "continue_session",
            project_id="repo-a",
            operator="openclaw",
            idempotency_key="idem-continue-event-only-1",
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


def test_integration_list_session_events_prefers_explicit_native_thread_id(tmp_path: Path) -> None:
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
                "event: resume\n"
                'data: {"event_id":"evt_001","project_id":"repo-a","thread_id":"session:repo-a","native_thread_id":"thr_native_1","event_type":"resume","event_source":"a_control_agent","payload_json":{"mode":"resume_or_new_thread"},"created_at":"2026-04-05T10:00:00Z"}\n\n',
                "text/event-stream",
            )

    adapter = _adapter(
        tmp_path,
        EventsClient(
            task={
                "project_id": "repo-a",
                "thread_id": "session:repo-a",
                "native_thread_id": "thr_native_1",
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
    assert reply.events[0].event_code == "session_resumed"
    assert reply.events[0].thread_id == "session:repo-a"
    assert reply.events[0].native_thread_id == "thr_native_1"


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


def test_integration_api_and_adapter_share_stuck_explanation_goal_context_semantics(
    tmp_path: Path,
) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

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
    GoalContractService(app.state.session_service).bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="收口 recovery 自动重入",
        task_prompt="收口 recovery 自动重入",
        last_user_instruction="继续把 recovery 自动重入收口到 child continuation",
        phase="editing_source",
        last_summary="repeated failures",
        current_phase_goal="继续把 recovery 自动重入收口到 child continuation",
        explicit_deliverables=["避免重复 handoff"],
        completion_signals=["child continuation 稳定"],
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
    assert api_reply["message"] == (
        "session appears stuck; repeated failures detected; context pressure is critical"
        " | 当前目标=继续把 recovery 自动重入收口到 child continuation"
    )
    assert adapter_reply.message == f'{api_reply["message"]} | 下一步=卡在哪里'


def test_integration_api_and_adapter_share_session_directory_goal_context_semantics(
    tmp_path: Path,
) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

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
    adapter = _adapter(tmp_path, FakeAClient(task=task, tasks=[task]))
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=FakeAClient(task=task, tasks=[task]),
    )
    GoalContractService(app.state.session_service).bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="收口 recovery 自动重入",
        task_prompt="收口 recovery 自动重入",
        last_user_instruction="继续把 recovery 自动重入收口到 child continuation",
        phase="editing_source",
        last_summary="editing files",
        current_phase_goal="继续把 recovery 自动重入收口到 child continuation",
        explicit_deliverables=["避免重复 handoff"],
        completion_signals=["child continuation 稳定"],
    )
    client = TestClient(app)

    adapter_reply = adapter.handle_intent("list_sessions")
    api_response = client.get(
        "/api/v1/watchdog/sessions",
        headers={"Authorization": "Bearer wt"},
    )

    assert api_response.status_code == 200
    api_reply = api_response.json()["data"]
    assert api_reply["reply_code"] == adapter_reply.reply_code
    assert api_reply["message"] == (
        "多项目进展（1）\n"
        "- repo-a | editing_source | editing files | 上下文=low"
        " | 当前目标=继续把 recovery 自动重入收口到 child continuation"
    )
    assert adapter_reply.message == (
        "多项目进展（1） | 状态=进行中1\n"
        "- repo-a | editing_source | editing files | 上下文=low"
        " | 当前目标=继续把 recovery 自动重入收口到 child continuation"
    )


def test_integration_api_and_adapter_share_progress_goal_context_semantics(
    tmp_path: Path,
) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

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
    GoalContractService(app.state.session_service).bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="收口 recovery 自动重入",
        task_prompt="收口 recovery 自动重入",
        last_user_instruction="继续把 recovery 自动重入收口到 child continuation",
        phase="editing_source",
        last_summary="editing files",
        current_phase_goal="继续把 recovery 自动重入收口到 child continuation",
        explicit_deliverables=["避免重复 handoff"],
        completion_signals=["child continuation 稳定"],
    )
    client = TestClient(app)

    adapter_reply = adapter.handle_intent("get_progress", project_id="repo-a")
    api_response = client.get(
        "/api/v1/watchdog/sessions/repo-a/progress",
        headers={"Authorization": "Bearer wt"},
    )

    assert api_response.status_code == 200
    api_reply = api_response.json()["data"]
    assert api_reply["reply_code"] == adapter_reply.reply_code
    assert api_reply["message"] == "editing files | 当前目标=继续把 recovery 自动重入收口到 child continuation"
    assert adapter_reply.message == api_reply["message"]


def test_integration_api_and_adapter_share_progress_revised_latest_user_instruction_semantics(
    tmp_path: Path,
) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

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
    contracts = GoalContractService(app.state.session_service)
    created = contracts.bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="收口 recovery 自动重入",
        task_prompt="收口 recovery 自动重入",
        last_user_instruction="旧指令",
        phase="editing_source",
        last_summary="editing files",
        current_phase_goal="旧阶段目标",
        explicit_deliverables=["避免重复 handoff"],
        completion_signals=["child continuation 稳定"],
    )
    contracts.revise_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        expected_version=created.version,
        current_phase_goal="继续把 recovery 自动重入收口到 child continuation",
        last_user_instruction="继续把 recovery 自动重入收口到 child continuation",
    )
    client = TestClient(app)

    adapter_reply = adapter.handle_intent("get_progress", project_id="repo-a")
    api_response = client.get(
        "/api/v1/watchdog/sessions/repo-a/progress",
        headers={"Authorization": "Bearer wt"},
    )

    assert api_response.status_code == 200
    api_reply = api_response.json()["data"]
    assert api_reply["reply_code"] == adapter_reply.reply_code
    assert api_reply["message"] == "editing files | 当前目标=继续把 recovery 自动重入收口到 child continuation"
    assert adapter_reply.message == api_reply["message"]
    assert api_reply["progress"]["goal_contract_version"] == adapter_reply.progress.goal_contract_version
    assert api_reply["progress"]["current_phase_goal"] == adapter_reply.progress.current_phase_goal
    assert api_reply["progress"]["last_user_instruction"] == adapter_reply.progress.last_user_instruction


def test_integration_api_and_adapter_share_blocker_explanation_goal_context_semantics(
    tmp_path: Path,
) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

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
    GoalContractService(app.state.session_service).bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="收口 recovery 自动重入",
        task_prompt="收口 recovery 自动重入",
        last_user_instruction="继续把 recovery 自动重入收口到 child continuation",
        phase="approval",
        last_summary="waiting for approval",
        current_phase_goal="继续把 recovery 自动重入收口到 child continuation",
        explicit_deliverables=["避免重复 handoff"],
        completion_signals=["child continuation 稳定"],
    )
    client = TestClient(app)

    adapter_reply = adapter.handle_intent("explain_blocker", project_id="repo-a")
    api_response = client.get(
        "/api/v1/watchdog/sessions/repo-a/blocker-explanation",
        headers={"Authorization": "Bearer wt"},
    )

    assert api_response.status_code == 200
    api_reply = api_response.json()["data"]
    assert api_reply["reply_code"] == adapter_reply.reply_code
    assert api_reply["message"] == (
        "approval required; awaiting operator direction"
        " | 当前目标=继续把 recovery 自动重入收口到 child continuation"
    )
    assert adapter_reply.message == (
        f'{api_reply["message"]} | 下一步=审批列表、回复同意/拒绝、为什么卡住'
    )


def test_integration_api_and_adapter_share_get_session_semantics(tmp_path: Path) -> None:
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

    adapter_reply = adapter.handle_intent("get_session", project_id="repo-a")
    api_response = client.get(
        "/api/v1/watchdog/sessions/repo-a",
        headers={"Authorization": "Bearer wt"},
    )

    assert api_response.status_code == 200
    api_reply = api_response.json()["data"]
    assert api_reply["reply_code"] == adapter_reply.reply_code
    assert api_reply["session"]["project_id"] == adapter_reply.session.project_id
    assert api_reply["session"]["thread_id"] == adapter_reply.session.thread_id
    assert api_reply["session"]["native_thread_id"] == adapter_reply.session.native_thread_id
    assert adapter_reply.progress is not None
    assert api_reply["progress"]["project_id"] == adapter_reply.progress.project_id
    assert api_reply["progress"]["thread_id"] == adapter_reply.progress.thread_id
    assert api_reply["progress"]["native_thread_id"] == adapter_reply.progress.native_thread_id
    assert api_reply["progress"]["summary"] == adapter_reply.progress.summary
    assert api_reply["message"] == "waiting for approval"
    assert adapter_reply.message == f'{api_reply["message"]} | 下一步=审批列表、回复同意/拒绝、卡在哪里'


def test_integration_api_and_adapter_share_get_session_suppression_semantics(tmp_path: Path) -> None:
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="recovery_execution_suppressed",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:recovery-suppressed:repo-a:integration-session",
        related_ids={"recovery_transaction_id": "recovery-tx:repo-a"},
        payload={
            "suppression_reason": "reentry_without_newer_progress",
            "suppression_source": "resident_orchestrator",
            "context_pressure": "critical",
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        occurred_at="2026-04-05T05:21:00Z",
    )
    task = {
        "project_id": "repo-a",
        "thread_id": "thr_native_1",
        "status": "running",
        "phase": "editing_source",
        "pending_approval": False,
        "last_summary": "editing recovery path",
        "files_touched": ["src/recovery.py"],
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

    adapter_reply = adapter.handle_intent("get_session", project_id="repo-a")
    api_response = client.get(
        "/api/v1/watchdog/sessions/repo-a",
        headers={"Authorization": "Bearer wt"},
    )

    assert api_response.status_code == 200
    api_reply = api_response.json()["data"]
    assert api_reply["reply_code"] == adapter_reply.reply_code
    assert api_reply["message"] == "editing recovery path | 恢复抑制=等待新进展"
    assert adapter_reply.message == f'{api_reply["message"]} | 下一步=卡在哪里'
    assert adapter_reply.progress is not None
    assert api_reply["progress"]["recovery_suppression_reason"] == (
        adapter_reply.progress.recovery_suppression_reason
    )
    assert api_reply["progress"]["recovery_suppression_source"] == (
        adapter_reply.progress.recovery_suppression_source
    )
    assert api_reply["progress"]["recovery_suppression_observed_at"] == (
        adapter_reply.progress.recovery_suppression_observed_at
    )


def test_integration_api_and_adapter_share_get_session_cooldown_suppression_semantics(
    tmp_path: Path,
) -> None:
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="recovery_execution_suppressed",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:recovery-suppressed:repo-a:integration-session:cooldown",
        related_ids={"recovery_transaction_id": "recovery-tx:repo-a"},
        payload={
            "suppression_reason": "cooldown_window_active",
            "suppression_source": "resident_orchestrator",
            "context_pressure": "critical",
            "last_progress_at": "2026-04-05T05:20:00Z",
            "cooldown_seconds": "300",
        },
        occurred_at="2026-04-05T05:21:00Z",
    )
    task = {
        "project_id": "repo-a",
        "thread_id": "thr_native_1",
        "status": "running",
        "phase": "editing_source",
        "pending_approval": False,
        "last_summary": "editing recovery path",
        "files_touched": ["src/recovery.py"],
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

    adapter_reply = adapter.handle_intent("get_session", project_id="repo-a")
    api_response = client.get(
        "/api/v1/watchdog/sessions/repo-a",
        headers={"Authorization": "Bearer wt"},
    )

    assert api_response.status_code == 200
    api_reply = api_response.json()["data"]
    assert api_reply["reply_code"] == adapter_reply.reply_code
    assert api_reply["message"] == "editing recovery path | 恢复抑制=恢复冷却中"
    assert adapter_reply.message == f'{api_reply["message"]} | 下一步=卡在哪里'
    assert adapter_reply.progress is not None
    assert api_reply["progress"]["recovery_suppression_reason"] == (
        adapter_reply.progress.recovery_suppression_reason
    )
    assert api_reply["progress"]["recovery_suppression_source"] == (
        adapter_reply.progress.recovery_suppression_source
    )
    assert api_reply["progress"]["recovery_suppression_observed_at"] == (
        adapter_reply.progress.recovery_suppression_observed_at
    )


def test_integration_api_and_adapter_share_get_session_in_flight_suppression_semantics(
    tmp_path: Path,
) -> None:
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="recovery_execution_suppressed",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:recovery-suppressed:repo-a:integration-session:in-flight",
        related_ids={"recovery_transaction_id": "recovery-tx:repo-a"},
        payload={
            "suppression_reason": "recovery_in_flight",
            "suppression_source": "resident_orchestrator",
            "task_status": "handoff_in_progress",
            "context_pressure": "critical",
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        occurred_at="2026-04-05T05:21:00Z",
    )
    task = {
        "project_id": "repo-a",
        "thread_id": "thr_native_1",
        "status": "handoff_in_progress",
        "phase": "handoff",
        "pending_approval": False,
        "last_summary": "handoff drafted",
        "files_touched": ["src/recovery.py"],
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

    adapter_reply = adapter.handle_intent("get_session", project_id="repo-a")
    api_response = client.get(
        "/api/v1/watchdog/sessions/repo-a",
        headers={"Authorization": "Bearer wt"},
    )

    assert api_response.status_code == 200
    api_reply = api_response.json()["data"]
    assert api_reply["reply_code"] == adapter_reply.reply_code
    assert api_reply["message"] == "handoff drafted | 恢复抑制=恢复进行中"
    assert adapter_reply.message == api_reply["message"]
    assert adapter_reply.progress is not None
    assert api_reply["progress"]["recovery_suppression_reason"] == (
        adapter_reply.progress.recovery_suppression_reason
    )
    assert api_reply["progress"]["recovery_suppression_source"] == (
        adapter_reply.progress.recovery_suppression_source
    )
    assert api_reply["progress"]["recovery_suppression_observed_at"] == (
        adapter_reply.progress.recovery_suppression_observed_at
    )


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


def test_integration_session_directory_parity_for_current_child_session_id_resume_shape(
    tmp_path: Path,
) -> None:
    tasks = [
        {
            "project_id": "repo-b",
            "thread_id": "thr_native_2",
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
    ]
    adapter = _adapter(tmp_path, FakeAClient(task=tasks[0], tasks=tasks, approvals=[]))
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=FakeAClient(task=tasks[0], tasks=tasks, approvals=[]),
    )
    client = TestClient(app)
    session_service = SessionService.from_data_dir(tmp_path)
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
            "resume_outcome": "new_child_session",
            "child_session_id": "session:repo-b:thr_child_v1",
            "thread_id": "thr_child_v1",
            "native_thread_id": "thr_child_v1",
        },
    )

    adapter_reply = adapter.handle_intent("list_sessions")
    api_response = client.get(
        "/api/v1/watchdog/sessions",
        headers={"Authorization": "Bearer wt"},
    )

    assert api_response.status_code == 200
    api_reply = api_response.json()["data"]
    assert [item["recovery_outcome"] for item in api_reply["progresses"]] == [
        progress.recovery_outcome for progress in adapter_reply.progresses
    ]
    assert [item["recovery_child_session_id"] for item in api_reply["progresses"]] == [
        progress.recovery_child_session_id for progress in adapter_reply.progresses
    ]
    assert api_reply["message"] == (
        "多项目进展（1）\n"
        "- repo-b | editing_source | editing files | 上下文=low | 恢复=新子会话 repo-b:thr_child_v1"
    )
    assert adapter_reply.message == (
        "多项目进展（1） | 状态=进行中1\n"
        "- repo-b | editing_source | editing files | 上下文=low | 恢复=新子会话 repo-b:thr_child_v1"
    )


def test_integration_session_directory_adapter_adds_relative_freshness_without_mutating_api_payload(
    tmp_path: Path,
) -> None:
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
    a_client = FakeAClient(
        task=task,
        tasks=[
            task,
            {
                "project_id": "repo-b",
                "thread_id": "thr_native_2",
                "status": "running",
                "phase": "planning",
                "pending_approval": False,
                "last_summary": "waiting",
                "files_touched": [],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T01:00:00Z",
            },
        ],
    )
    adapter = _adapter(tmp_path, a_client)
    app = create_app(
        Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        a_client=a_client,
    )

    with TestClient(app) as client:
        api_response = client.get(
            "/api/v1/watchdog/sessions",
            headers={"Authorization": "Bearer wt"},
        )

    adapter_reply = adapter.handle_intent("list_sessions")
    assert api_response.status_code == 200
    api_reply = api_response.json()["data"]
    assert api_reply["message"] == (
        "多项目进展（2）\n"
        "- repo-a | editing_source | editing files | 上下文=low\n"
        "- repo-b | planning | waiting | 上下文=low"
    )
    assert adapter_reply.message == (
        "多项目进展（2） | 状态=进行中2\n"
        "- repo-a | editing_source | editing files | 上下文=low\n"
        "- repo-b | planning | waiting | 上下文=low | 更新=静默"
    )


def test_integration_session_directory_api_and_adapter_share_resident_expert_coverage(
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    stale_seen_at = (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    fresh_seen_at = now.isoformat().replace("+00:00", "Z")
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
        "last_progress_at": fresh_seen_at,
    }
    a_client = FakeAClient(task=task, tasks=[task])
    adapter = _adapter(
        tmp_path,
        a_client,
        resident_expert_stale_after_seconds=60.0,
    )
    app = create_app(
        Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            resident_expert_stale_after_seconds=60.0,
        ),
        a_client=a_client,
    )
    resident_expert_runtime_service = app.state.resident_expert_runtime_service
    resident_expert_runtime_service.bind_runtime_handle(
        expert_id="managed-agent-expert",
        runtime_handle="agent://james",
        observed_at=stale_seen_at,
    )
    resident_expert_runtime_service.bind_runtime_handle(
        expert_id="hermes-agent-expert",
        runtime_handle="agent://hegel",
        observed_at=fresh_seen_at,
    )
    resident_expert_runtime_service.consult_or_restore(
        expert_ids=["managed-agent-expert", "hermes-agent-expert"],
        consultation_ref="consult:repo-a:resident-experts",
        observed_runtime_handles={"hermes-agent-expert": "agent://hegel"},
        consulted_at=fresh_seen_at,
    )

    with TestClient(app) as client:
        api_response = client.get(
            "/api/v1/watchdog/sessions",
            headers={"Authorization": "Bearer wt"},
        )

    adapter_reply = adapter.handle_intent("list_sessions")

    assert api_response.status_code == 200
    api_reply = api_response.json()["data"]
    assert api_reply["resident_expert_coverage"] == adapter_reply.resident_expert_coverage.model_dump(
        mode="json"
    )
    assert adapter_reply.message.startswith(
        "多项目进展（1） | 监督=在线1、过期1 | 最近合议=consult:repo-a:resident-experts"
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
    assert adapter_reply.progress is not None
    assert api_reply["progress"]["project_id"] == adapter_reply.progress.project_id
    assert api_reply["progress"]["native_thread_id"] == adapter_reply.progress.native_thread_id
    assert api_reply["progress"]["summary"] == adapter_reply.progress.summary
    assert [fact["fact_code"] for fact in api_reply["facts"]] == [
        fact.fact_code for fact in adapter_reply.facts
    ]


def test_integration_api_and_adapter_share_session_by_native_thread_goal_contract_adoption_semantics(
    tmp_path: Path,
) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    session_service = SessionService.from_data_dir(tmp_path)
    contracts = GoalContractService(session_service)
    created = contracts.bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="收口 recovery 自动重入",
        task_prompt="收口 recovery 自动重入",
        last_user_instruction="继续把 recovery 自动重入收口到 child continuation",
        phase="editing_source",
        last_summary="editing files",
        current_phase_goal="继续把 recovery 自动重入收口到 child continuation",
        explicit_deliverables=["避免重复 handoff"],
        completion_signals=["child continuation 稳定"],
    )
    contracts.adopt_contract_for_child_session(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        child_session_id="session:repo-a:child-v1",
        child_native_thread_id="thr_child_v1",
        expected_version=created.version,
        recovery_transaction_id="recovery-tx:repo-a",
    )

    adapter = OpenClawAdapter(
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        client=BrokenAClient(),
        receipt_store=ActionReceiptStore(tmp_path / "action_receipts.json"),
    )
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=BrokenAClient(),
    )
    client = TestClient(app)

    adapter_reply = adapter.handle_intent(
        "get_session_by_native_thread",
        arguments={"native_thread_id": "thr_child_v1"},
    )
    api_response = client.get(
        "/api/v1/watchdog/sessions/by-native-thread/thr_child_v1",
        headers={"Authorization": "Bearer wt"},
    )

    assert api_response.status_code == 200
    api_reply = api_response.json()["data"]
    assert api_reply["reply_code"] == adapter_reply.reply_code
    assert api_reply["intent_code"] == adapter_reply.intent_code
    assert api_reply["message"] == "editing files | 当前目标=继续把 recovery 自动重入收口到 child continuation"
    assert adapter_reply.message == api_reply["message"]
    assert api_reply["session"]["thread_id"] == adapter_reply.session.thread_id
    assert api_reply["session"]["native_thread_id"] == adapter_reply.session.native_thread_id
    assert api_reply["progress"]["goal_contract_version"] == adapter_reply.progress.goal_contract_version
    assert api_reply["progress"]["native_thread_id"] == adapter_reply.progress.native_thread_id


def test_integration_api_and_adapter_share_workspace_activity_semantics(tmp_path: Path) -> None:
    task = {
        "project_id": "repo-a",
        "thread_id": "session:repo-a",
        "native_thread_id": "thr_native_1",
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
    assert api_reply["workspace_activity"]["thread_id"] == "session:repo-a"
    assert api_reply["workspace_activity"]["native_thread_id"] == "thr_native_1"
    assert api_reply["workspace_activity"]["recent_change_count"] == 1
    assert api_reply["workspace_activity"]["recent_window_minutes"] == 30
    assert adapter_reply.workspace_activity is not None
    assert adapter_reply.workspace_activity.thread_id == "session:repo-a"
    assert adapter_reply.workspace_activity.native_thread_id == "thr_native_1"


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
