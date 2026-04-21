from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from watchdog.contracts.session_spine.enums import ActionCode
from watchdog.contracts.session_spine.models import WatchdogAction
from watchdog.services.session_service.service import SessionService
from watchdog.services.session_service.store import SessionServiceStore
from watchdog.services.session_spine.actions import execute_watchdog_action
from watchdog.settings import Settings
from watchdog.storage.action_receipts import ActionReceiptStore


class FakeAClient:
    def __init__(
        self,
        *,
        task: dict[str, object],
        approvals: list[dict[str, object]] | None = None,
    ) -> None:
        self._task = dict(task)
        self._approvals = [dict(approval) for approval in approvals or []]
        self.decision_calls: list[tuple[str, str, str, str]] = []
        self.handoff_calls: list[tuple[str, str]] = []
        self.resume_calls: list[tuple[str, str, str]] = []

    def get_envelope(self, project_id: str) -> dict[str, object]:
        assert project_id == self._task["project_id"]
        return {"success": True, "data": dict(self._task)}

    def list_approvals(
        self,
        *,
        status: str | None = None,
        project_id: str | None = None,
        decided_by: str | None = None,
        callback_status: str | None = None,
    ) -> list[dict[str, object]]:
        items = [dict(approval) for approval in self._approvals]
        if status:
            items = [item for item in items if item.get("status") == status]
        if project_id:
            items = [item for item in items if item.get("project_id") == project_id]
        if decided_by:
            items = [item for item in items if item.get("decided_by") == decided_by]
        if callback_status:
            items = [item for item in items if item.get("callback_status") == callback_status]
        return items

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
            "data": {
                "handoff_file": f"/tmp/{project_id}.handoff.md",
                "summary": f"handoff for {project_id}",
            },
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
            "data": {
                "project_id": project_id,
                "status": "running",
                "mode": mode,
            },
        }


def _receipt_store(tmp_path: Path) -> ActionReceiptStore:
    return ActionReceiptStore(tmp_path / "action_receipts.json")


def test_continue_session_is_idempotent_and_posts_steer_once(tmp_path: Path) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
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
    action = WatchdogAction(
        action_code=ActionCode.CONTINUE_SESSION,
        project_id="repo-a",
        operator="openclaw",
        idempotency_key="idem-continue-1",
        arguments={},
    )

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}
        first = execute_watchdog_action(
            action,
            settings=settings,
            client=client,
            receipt_store=_receipt_store(tmp_path),
        )
        second = execute_watchdog_action(
            action,
            settings=settings,
            client=client,
            receipt_store=_receipt_store(tmp_path),
        )

    assert steer_mock.call_count == 1
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.action_status == "completed"
    assert first.effect == "steer_posted"
    assert first.reply_code == "action_result"


def test_continue_session_is_not_available_for_completed_session(tmp_path: Path) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_done",
            "status": "waiting_human",
            "phase": "done",
            "pending_approval": False,
            "last_summary": "task complete",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    action = WatchdogAction(
        action_code=ActionCode.CONTINUE_SESSION,
        project_id="repo-a",
        operator="openclaw",
        idempotency_key="idem-continue-done",
        arguments={},
    )

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        result = execute_watchdog_action(
            action,
            settings=settings,
            client=client,
            receipt_store=_receipt_store(tmp_path),
        )

    assert steer_mock.call_count == 0
    assert result.action_status == "noop"
    assert result.effect == "noop"
    assert result.reply_code == "action_not_available"
    assert result.message == "session is already complete"
    assert [fact.fact_code for fact in result.facts] == ["task_completed"]


def test_continue_session_is_suppressed_when_continuation_identity_is_already_issued(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    session_service.record_continuation_identity_state(
        project_id="repo-a",
        session_id="session:repo-a",
        continuation_identity="repo-a:session:repo-a:thr_native_1:continue_current_branch",
        state="issued",
        decision_source="manual_action",
        decision_class="continue_current_branch",
        action_ref="continue_session",
        authoritative_snapshot_version="fact-v1",
        snapshot_epoch="session-seq:1",
        goal_contract_version="goal-contract:unknown",
        route_key="repo-a:session:repo-a:thr_native_1:continue_current_branch:fact-v1",
    )
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
    action = WatchdogAction(
        action_code=ActionCode.CONTINUE_SESSION,
        project_id="repo-a",
        operator="openclaw",
        idempotency_key="idem-continue-issued",
        arguments={},
    )

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        result = execute_watchdog_action(
            action,
            settings=settings,
            client=client,
            receipt_store=_receipt_store(tmp_path),
            session_service=session_service,
        )

    assert steer_mock.call_count == 0
    assert result.action_status == "noop"
    assert result.effect == "noop"
    assert result.reply_code == "action_not_available"
    assert result.message == "continuation is already in flight"
    gate_events = session_service.list_events(
        session_id="session:repo-a",
        event_type="continuation_gate_evaluated",
    )
    assert len(gate_events) == 1
    assert gate_events[0].payload["gate_status"] == "suppressed"
    assert gate_events[0].payload["suppression_reason"] == "continuation_identity_in_flight"


@pytest.mark.parametrize(
    ("action_code", "arguments", "task_status"),
    [
        (ActionCode.RESUME_SESSION, {"handoff_summary": "resume from packet"}, "paused"),
        (ActionCode.FORCE_HANDOFF, {"reason": "operator forced handoff"}, "running"),
        (ActionCode.RETRY_WITH_CONSERVATIVE_PATH, {}, "running"),
    ],
)
def test_recovery_direct_actions_are_suppressed_when_continuation_identity_is_already_issued(
    tmp_path: Path,
    action_code: ActionCode,
    arguments: dict[str, object],
    task_status: str,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    session_service.record_continuation_identity_state(
        project_id="repo-a",
        session_id="session:repo-a",
        continuation_identity="repo-a:session:repo-a:thr_native_1:recover_current_branch",
        state="issued",
        decision_source="manual_action",
        decision_class="recover_current_branch",
        action_ref="execute_recovery",
        authoritative_snapshot_version="fact-v1",
        snapshot_epoch="session-seq:1",
        goal_contract_version="goal-contract:unknown",
        route_key="repo-a:session:repo-a:thr_native_1:recover_current_branch:fact-v1",
    )
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": task_status,
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
    action = WatchdogAction(
        action_code=action_code,
        project_id="repo-a",
        operator="openclaw",
        idempotency_key=f"idem-{action_code.value}-issued",
        arguments=arguments,
    )

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        result = execute_watchdog_action(
            action,
            settings=settings,
            client=client,
            receipt_store=_receipt_store(tmp_path),
            session_service=session_service,
        )

    assert steer_mock.call_count == 0
    assert client.handoff_calls == []
    assert client.resume_calls == []
    assert result.action_status == "noop"
    assert result.effect == "noop"
    assert result.reply_code == "action_not_available"
    assert result.message == "continuation is already in flight"
    gate_events = session_service.list_events(
        session_id="session:repo-a",
        event_type="continuation_gate_evaluated",
    )
    assert len(gate_events) == 1
    assert gate_events[0].payload["gate_status"] == "suppressed"
    assert gate_events[0].payload["suppression_reason"] == "continuation_identity_in_flight"


def test_continue_session_uses_authoritative_project_state_when_live_task_omits_it(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
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
    action = WatchdogAction(
        action_code=ActionCode.CONTINUE_SESSION,
        project_id="repo-a",
        operator="openclaw",
        idempotency_key="idem-continue-authoritative-project-state",
        arguments={},
    )

    with patch(
        "watchdog.services.session_spine.service._authoritative_project_execution_state",
        return_value="completed",
    ), patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        result = execute_watchdog_action(
            action,
            settings=settings,
            client=client,
            receipt_store=_receipt_store(tmp_path),
        )

    assert steer_mock.call_count == 0
    assert result.action_status == "noop"
    assert result.effect == "noop"
    assert result.reply_code == "action_not_available"
    assert result.message == "project is not active for continuation"


def test_continue_session_uses_authoritative_project_state_on_session_event_read_path(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    session_service.record_event(
        event_type="notification_announced",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:event-path-project-state",
        payload={"message": "latest projection came from session events"},
        occurred_at="2026-04-05T05:21:00Z",
    )
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
    action = WatchdogAction(
        action_code=ActionCode.CONTINUE_SESSION,
        project_id="repo-a",
        operator="openclaw",
        idempotency_key="idem-continue-authoritative-event-path",
        arguments={},
    )

    with patch(
        "watchdog.services.session_spine.service._authoritative_project_execution_state",
        return_value="completed",
    ), patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        result = execute_watchdog_action(
            action,
            settings=settings,
            client=client,
            receipt_store=_receipt_store(tmp_path),
            session_service=session_service,
        )

    assert steer_mock.call_count == 0
    assert result.action_status == "noop"
    assert result.effect == "noop"
    assert result.reply_code == "action_not_available"
    assert result.message == "project is not active for continuation"


def test_continue_session_fails_closed_when_authoritative_project_state_is_unknown(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
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
    action = WatchdogAction(
        action_code=ActionCode.CONTINUE_SESSION,
        project_id="repo-a",
        operator="openclaw",
        idempotency_key="idem-continue-authoritative-project-state-unknown",
        arguments={},
    )

    with patch(
        "watchdog.services.session_spine.service._authoritative_project_execution_state",
        return_value="unknown",
    ), patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        result = execute_watchdog_action(
            action,
            settings=settings,
            client=client,
            receipt_store=_receipt_store(tmp_path),
        )

    assert steer_mock.call_count == 0
    assert result.action_status == "blocked"
    assert result.effect == "noop"
    assert result.reply_code == "action_not_available"
    assert result.message == "authoritative project state is unavailable"
    assert [fact.fact_code for fact in result.facts] == ["project_state_unavailable"]


@pytest.mark.parametrize(
    ("action_code", "arguments"),
    [
        (ActionCode.RESUME_SESSION, {"handoff_summary": "resume from packet"}),
        (ActionCode.FORCE_HANDOFF, {"reason": "operator forced handoff"}),
        (ActionCode.RETRY_WITH_CONSERVATIVE_PATH, {}),
    ],
)
def test_continuation_actions_are_not_available_for_non_active_projects(
    tmp_path: Path,
    action_code: ActionCode,
    arguments: dict[str, object],
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "paused",
            "phase": "editing_source",
            "project_execution_state": "completed",
            "pending_approval": False,
            "last_summary": "project already complete",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    action = WatchdogAction(
        action_code=action_code,
        project_id="repo-a",
        operator="openclaw",
        idempotency_key=f"idem-{action_code.value}-project-complete",
        arguments=arguments,
    )

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        result = execute_watchdog_action(
            action,
            settings=settings,
            client=client,
            receipt_store=_receipt_store(tmp_path),
        )

    assert steer_mock.call_count == 0
    assert client.handoff_calls == []
    assert client.resume_calls == []
    assert result.action_status == "noop"
    assert result.effect == "noop"
    assert result.reply_code == "action_not_available"
    assert result.message == "project is not active for continuation"


def test_resume_session_is_not_available_while_approval_is_pending(tmp_path: Path) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "paused",
            "phase": "editing_source",
            "pending_approval": True,
            "last_summary": "awaiting approval before resume",
            "files_touched": ["src/example.py"],
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
                "command": "execute_recovery",
                "reason": "resume requires approval",
                "alternative": "",
                "requested_at": "2026-04-05T05:21:00Z",
            }
        ],
    )
    action = WatchdogAction(
        action_code=ActionCode.RESUME_SESSION,
        project_id="repo-a",
        operator="openclaw",
        idempotency_key="idem-resume-pending-approval",
        arguments={"handoff_summary": "resume from packet"},
    )

    result = execute_watchdog_action(
        action,
        settings=settings,
        client=client,
        receipt_store=_receipt_store(tmp_path),
    )

    assert client.resume_calls == []
    assert result.action_status == "blocked"
    assert result.effect == "noop"
    assert result.reply_code == "action_not_available"
    assert result.message == "session is awaiting human approval"


def test_request_recovery_returns_advisory_only_result(tmp_path: Path) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
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
    action = WatchdogAction(
        action_code=ActionCode.REQUEST_RECOVERY,
        project_id="repo-a",
        operator="openclaw",
        idempotency_key="idem-recovery-1",
        arguments={},
    )

    result = execute_watchdog_action(
        action,
        settings=settings,
        client=client,
        receipt_store=_receipt_store(tmp_path),
    )

    assert result.action_status == "completed"
    assert result.effect == "advisory_only"
    assert result.reply_code == "recovery_availability"
    assert [fact.fact_code for fact in result.facts] == [
        "stuck_no_progress",
        "repeat_failure",
        "context_critical",
        "recovery_available",
    ]


def test_execute_recovery_returns_noop_when_not_critical(tmp_path: Path) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "steady progress",
            "files_touched": ["src/example.py"],
            "context_pressure": "medium",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    action = WatchdogAction(
        action_code=ActionCode.EXECUTE_RECOVERY,
        project_id="repo-a",
        operator="openclaw",
        idempotency_key="idem-execute-recovery-1",
        arguments={},
    )

    result = execute_watchdog_action(
        action,
        settings=settings,
        client=client,
        receipt_store=_receipt_store(tmp_path),
    )

    assert client.handoff_calls == []
    assert client.resume_calls == []
    assert result.action_status == "noop"
    assert result.effect == "noop"
    assert result.reply_code == "recovery_execution_result"
    assert result.message == "recovery not executed because context is not critical"


def test_execute_recovery_is_idempotent_and_can_resume_once(tmp_path: Path) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
        recover_auto_resume=True,
    )
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
    action = WatchdogAction(
        action_code=ActionCode.EXECUTE_RECOVERY,
        project_id="repo-a",
        operator="openclaw",
        idempotency_key="idem-execute-recovery-2",
        arguments={},
    )

    first = execute_watchdog_action(
        action,
        settings=settings,
        client=client,
        receipt_store=_receipt_store(tmp_path),
    )
    second = execute_watchdog_action(
        action,
        settings=settings,
        client=client,
        receipt_store=_receipt_store(tmp_path),
    )

    assert client.handoff_calls == [("repo-a", "context_critical")]
    assert client.resume_calls == [("repo-a", "resume_or_new_thread", "")]
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.action_status == "completed"
    assert first.effect == "handoff_and_resume"
    assert first.reply_code == "recovery_execution_result"


def test_post_operator_guidance_is_idempotent_and_posts_steer_once(tmp_path: Path) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
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
            "stuck_level": 1,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    action = WatchdogAction(
        action_code=ActionCode.POST_OPERATOR_GUIDANCE,
        project_id="repo-a",
        operator="openclaw",
        idempotency_key="idem-guidance-1",
        arguments={
            "message": "Please summarize the blocker and propose the next exact command.",
            "reason_code": "operator_guidance",
            "stuck_level": 2,
        },
    )

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}
        first = execute_watchdog_action(
            action,
            settings=settings,
            client=client,
            receipt_store=_receipt_store(tmp_path),
        )
        second = execute_watchdog_action(
            action,
            settings=settings,
            client=client,
            receipt_store=_receipt_store(tmp_path),
        )

    assert steer_mock.call_count == 1
    assert steer_mock.call_args.kwargs["message"] == (
        "Please summarize the blocker and propose the next exact command."
    )
    assert steer_mock.call_args.kwargs["reason"] == "operator_guidance"
    assert steer_mock.call_args.kwargs["stuck_level"] == 2
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.action_status == "completed"
    assert first.effect == "steer_posted"
    assert first.reply_code == "action_result"


def test_approval_action_uses_approval_id_in_idempotency_key(tmp_path: Path) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
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
    action = WatchdogAction(
        action_code=ActionCode.APPROVE_APPROVAL,
        project_id="repo-a",
        operator="openclaw",
        idempotency_key="idem-approval-1",
        arguments={"approval_id": "appr_001"},
    )

    first = execute_watchdog_action(
        action,
        settings=settings,
        client=client,
        receipt_store=_receipt_store(tmp_path),
    )
    second = execute_watchdog_action(
        action,
        settings=settings,
        client=client,
        receipt_store=_receipt_store(tmp_path),
    )

    assert client.decision_calls == [("appr_001", "approve", "openclaw", "")]
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.approval_id == "appr_001"
    assert first.effect == "approval_decided"
    assert first.reply_code == "approval_result"


def test_evaluate_supervision_is_idempotent_and_posts_steer_once(tmp_path: Path) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
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
    action = WatchdogAction(
        action_code=ActionCode.EVALUATE_SUPERVISION,
        project_id="repo-a",
        operator="openclaw",
        idempotency_key="idem-supervision-1",
        arguments={},
    )

    with patch("watchdog.services.session_spine.supervision.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}
        first = execute_watchdog_action(
            action,
            settings=settings,
            client=client,
            receipt_store=_receipt_store(tmp_path),
        )
        second = execute_watchdog_action(
            action,
            settings=settings,
            client=client,
            receipt_store=_receipt_store(tmp_path),
        )

    assert steer_mock.call_count == 1
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.reply_code == "supervision_evaluation"
    assert first.supervision_evaluation is not None
    assert first.supervision_evaluation.steer_sent is True
