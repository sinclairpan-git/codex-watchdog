from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from watchdog.contracts.session_spine.enums import (
    ActionCode,
    ActionStatus,
    Effect,
    ReplyCode,
)
from watchdog.contracts.session_spine.models import FactRecord, WatchdogActionResult
from watchdog.services.adapters.openclaw.adapter import OpenClawAdapter
from watchdog.services.policy.decisions import CanonicalDecisionRecord, PolicyDecisionStore
from watchdog.services.session_service import SessionService
from watchdog.settings import Settings
from watchdog.storage.action_receipts import ActionReceiptStore, receipt_key


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
        return {
            "success": True,
            "data": {
                "approval_id": approval_id,
                "status": "approved" if decision == "approve" else "rejected",
                "operator": operator,
                "note": note,
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
        yield (
            'id: evt_002\n'
            "event: resume\n"
            'data: {"event_id":"evt_002","project_id":"repo-a","thread_id":"thr_native_1","event_type":"resume","event_source":"a_control_agent","payload_json":{"mode":"resume_or_new_thread","status":"running","phase":"editing_source"},"created_at":"2026-04-05T10:01:00Z"}\n\n'
        )

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
                    "files_scanned": 10,
                    "latest_mtime_iso": "2026-04-05T05:30:00Z",
                    "recent_change_count": 2,
                    "recent_window_minutes": recent_minutes,
                },
            },
        }


def _adapter(
    tmp_path: Path,
    *,
    task: dict[str, object],
    tasks: list[dict[str, object]] | None = None,
    approvals: list[dict[str, object]] | None = None,
) -> OpenClawAdapter:
    return OpenClawAdapter(
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        client=FakeAClient(task=task, tasks=tasks, approvals=approvals),
        receipt_store=ActionReceiptStore(tmp_path / "action_receipts.json"),
    )


def _provider_invalid_decision_record(
    *,
    project_id: str = "repo-a",
    session_id: str = "session:repo-a",
    native_thread_id: str = "thr_native_1",
) -> CanonicalDecisionRecord:
    return CanonicalDecisionRecord(
        decision_id=f"decision:{project_id}:provider-invalid",
        decision_key=f"{session_id}|fact-v7|policy-v1|require_user_decision|execute_recovery|",
        session_id=session_id,
        project_id=project_id,
        thread_id=session_id,
        native_thread_id=native_thread_id,
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
        fact_snapshot_version="fact-v7",
        idempotency_key=f"{session_id}|fact-v7|policy-v1|require_user_decision|execute_recovery|",
        created_at="2026-04-07T00:05:00Z",
        operator_notes=[],
        evidence={
            "facts": [
                {
                    "fact_id": "fact-1",
                    "fact_code": "approval_pending",
                    "fact_kind": "blocker",
                    "severity": "warning",
                    "summary": "approval pending",
                    "detail": "approval pending",
                    "source": "watchdog",
                    "observed_at": "2026-04-07T00:05:00Z",
                    "related_ids": {},
                }
            ],
            "matched_policy_rules": ["registered_action"],
            "decision": {
                "decision_result": "require_user_decision",
                "action_ref": "execute_recovery",
                "approval_id": None,
            },
            "decision_trace": {
                "trace_id": f"trace:{project_id}-provider-invalid",
                "provider": "openai-compatible",
                "model": "gpt-4.1-mini",
                "prompt_schema_ref": "prompt:decision-v2",
                "output_schema_ref": "schema:decision-trace-v1",
                "provider_output_schema_ref": "schema:provider-decision-v2",
                "degrade_reason": "provider_output_invalid",
                "goal_contract_version": "goal-v1",
                "policy_ruleset_hash": "policy-hash-v1",
                "memory_packet_input_ids": [],
                "memory_packet_input_hashes": [],
            },
        },
    )


def test_adapter_get_session_returns_stable_session_projection(tmp_path: Path) -> None:
    adapter = _adapter(
        tmp_path,
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
        },
    )

    reply = adapter.handle_intent("get_session", project_id="repo-a")

    assert reply.reply_code == "session_projection"
    assert reply.session is not None
    assert reply.session.thread_id == "session:repo-a"
    assert reply.session.native_thread_id == "thr_native_1"


def test_adapter_get_session_surfaces_operator_next_steps_for_pending_approval(
    tmp_path: Path,
) -> None:
    adapter = _adapter(
        tmp_path,
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
                "risk_level": "L2",
                "command": "uv run pytest",
                "reason": "verify tests",
                "alternative": "",
                "status": "pending",
                "requested_at": "2026-04-05T05:21:00Z",
            }
        ],
    )

    reply = adapter.handle_intent("get_session", project_id="repo-a")

    assert reply.reply_code == "session_projection"
    assert reply.message == "waiting for approval | 下一步=审批列表、回复同意/拒绝、卡在哪里"


def test_adapter_get_session_by_native_thread_returns_stable_session_projection(tmp_path: Path) -> None:
    adapter = _adapter(
        tmp_path,
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
        },
    )

    reply = adapter.handle_intent(
        "get_session_by_native_thread",
        arguments={"native_thread_id": "thr_native_1"},
    )

    assert reply.reply_code == "session_projection"
    assert reply.intent_code == "get_session_by_native_thread"
    assert reply.session is not None
    assert reply.session.project_id == "repo-a"
    assert reply.session.thread_id == "session:repo-a"
    assert reply.session.native_thread_id == "thr_native_1"


def test_adapter_get_workspace_activity_returns_stable_workspace_activity_view(tmp_path: Path) -> None:
    adapter = _adapter(
        tmp_path,
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
        },
    )

    reply = adapter.handle_intent(
        "get_workspace_activity",
        project_id="repo-a",
        arguments={"recent_minutes": 30},
    )

    assert reply.reply_code == "workspace_activity_view"
    assert reply.intent_code == "get_workspace_activity"
    assert reply.session is not None
    assert reply.session.project_id == "repo-a"
    assert reply.workspace_activity is not None
    assert reply.workspace_activity.recent_window_minutes == 30
    assert reply.workspace_activity.recent_change_count == 2
    assert adapter._client.workspace_activity_calls == [("repo-a", 30)]


def test_adapter_why_stuck_is_built_from_fact_records(tmp_path: Path) -> None:
    adapter = _adapter(
        tmp_path,
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
        },
    )

    reply = adapter.handle_intent("why_stuck", project_id="repo-a")

    assert reply.reply_code == "stuck_explanation"
    assert [fact.fact_code for fact in reply.facts] == [
        "stuck_no_progress",
        "repeat_failure",
        "context_critical",
        "recovery_available",
    ]
    assert (
        reply.message
        == "session appears stuck; repeated failures detected; context pressure is critical"
        " | 下一步=卡在哪里"
    )


def test_adapter_progress_surfaces_decision_degradation_annotations(tmp_path: Path) -> None:
    adapter = _adapter(
        tmp_path,
        task={
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
        },
    )
    PolicyDecisionStore(tmp_path / "policy_decisions.json").put(
        _provider_invalid_decision_record()
    )

    reply = adapter.handle_intent("get_progress", project_id="repo-a")

    assert reply.reply_code == "task_progress_view"
    assert reply.message == "waiting for approval | 决策=provider降级(schema:provider-decision-v2)"
    assert reply.progress is not None
    assert reply.progress.decision_trace_ref == "trace:repo-a-provider-invalid"


def test_adapter_explain_blocker_uses_fact_records_and_stable_read_model(tmp_path: Path) -> None:
    adapter = _adapter(
        tmp_path,
        task={
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
        },
        approvals=[
            {
                "approval_id": "appr_001",
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "risk_level": "L2",
                "command": "uv run pytest",
                "reason": "verify tests",
                "alternative": "",
                "status": "pending",
                "requested_at": "2026-04-05T05:21:00Z",
            }
        ],
    )

    reply = adapter.handle_intent("explain_blocker", project_id="repo-a")

    assert reply.reply_code == "blocker_explanation"
    assert [fact.fact_code for fact in reply.facts] == [
        "approval_pending",
        "awaiting_human_direction",
    ]
    assert "approval required" in reply.message


def test_adapter_list_session_facts_returns_stable_truth_source(tmp_path: Path) -> None:
    adapter = _adapter(
        tmp_path,
        task={
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
        },
        approvals=[
            {
                "approval_id": "appr_001",
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "risk_level": "L2",
                "command": "uv run pytest",
                "reason": "verify tests",
                "alternative": "",
                "status": "pending",
                "requested_at": "2026-04-05T05:21:00Z",
            }
        ],
    )

    facts_reply = adapter.handle_intent("list_session_facts", project_id="repo-a")
    session_reply = adapter.handle_intent("get_session", project_id="repo-a")
    blocker_reply = adapter.handle_intent("explain_blocker", project_id="repo-a")

    assert facts_reply.reply_kind == "facts"
    assert facts_reply.reply_code == "session_facts"
    assert facts_reply.intent_code == "list_session_facts"
    assert facts_reply.message == "2 fact(s)"
    assert [fact.fact_code for fact in facts_reply.facts] == [
        "approval_pending",
        "awaiting_human_direction",
    ]
    assert [fact.fact_code for fact in facts_reply.facts] == [
        fact.fact_code for fact in session_reply.facts
    ]
    assert blocker_reply.reply_code == "blocker_explanation"


def test_adapter_list_approval_inbox_returns_stable_global_pending_queue(tmp_path: Path) -> None:
    adapter = _adapter(
        tmp_path,
        task={
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
        },
        approvals=[
            {
                "approval_id": "appr_001",
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "risk_level": "L2",
                "command": "uv run pytest",
                "reason": "verify tests",
                "alternative": "",
                "status": "pending",
                "requested_at": "2026-04-05T05:21:00Z",
            },
            {
                "approval_id": "appr_002",
                "project_id": "repo-b",
                "thread_id": "thr_native_2",
                "risk_level": "L3",
                "command": "uv run ruff check",
                "reason": "lint gate",
                "alternative": "",
                "status": "pending",
                "requested_at": "2026-04-05T05:22:00Z",
            },
        ],
    )

    reply = adapter.handle_intent("list_approval_inbox")

    assert reply.reply_code == "approval_inbox"
    assert [approval.project_id for approval in reply.approvals] == ["repo-a", "repo-b"]
    assert [approval.thread_id for approval in reply.approvals] == ["session:repo-a", "session:repo-b"]


def test_adapter_list_sessions_returns_stable_session_directory(tmp_path: Path) -> None:
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
    adapter = _adapter(
        tmp_path,
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
        },
        tasks=[
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
                "approval_risk": "L2",
                "last_summary": "waiting for approval",
                "files_touched": [],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T05:21:00Z",
            },
        ],
        approvals=[
            {
                "approval_id": "appr_001",
                "project_id": "repo-b",
                "thread_id": "thr_native_2",
                "risk_level": "L2",
                "command": "uv run pytest",
                "reason": "verify tests",
                "alternative": "",
                "status": "pending",
                "requested_at": "2026-04-05T05:22:00Z",
            },
        ],
    )

    reply = adapter.handle_intent("list_sessions")

    assert reply.reply_code == "session_directory"
    assert [session.project_id for session in reply.sessions] == ["repo-a", "repo-b"]
    assert [session.thread_id for session in reply.sessions] == ["session:repo-a", "session:repo-b"]
    assert reply.sessions[1].pending_approval_count == 1
    assert [progress.project_id for progress in reply.progresses] == ["repo-a", "repo-b"]
    assert reply.progresses[0].recovery_outcome == "same_thread_resume"
    assert reply.progresses[0].recovery_child_session_id is None
    assert reply.progresses[1].recovery_outcome == "new_child_session"
    assert reply.progresses[1].recovery_child_session_id == "session:repo-b:child-v1"
    assert reply.message == (
        "多项目进展（2） | 状态=进行中1、待审批1 | 先处理=repo-b:待审批\n"
        "- repo-b | approval | waiting for approval | 上下文=low | 恢复=新子会话 repo-b:child-v1"
        " | 关注=待审批 | 下一步=审批列表、回复同意/拒绝、卡在哪里\n"
        "- repo-a | editing_source | editing files | 上下文=low | 恢复=原线程续跑"
    )


def test_adapter_list_sessions_prioritizes_recovery_failures_before_approval_and_provider_degrade(
    tmp_path: Path,
) -> None:
    session_service = SessionService.from_data_dir(tmp_path)
    session_service.record_recovery_execution(
        project_id="repo-c",
        parent_session_id="session:repo-c",
        parent_native_thread_id="thr_native_3",
        recovery_reason="context_critical",
        failure_family="context_pressure",
        failure_signature="critical",
        handoff={
            "handoff_file": "/tmp/repo-c.handoff.md",
            "summary": "handoff",
        },
        resume_error="resume timeout",
    )
    PolicyDecisionStore(tmp_path / "policy_decisions.json").put(
        _provider_invalid_decision_record(
            project_id="repo-a",
            session_id="session:repo-a",
            native_thread_id="thr_native_1",
        )
    )
    adapter = _adapter(
        tmp_path,
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
        },
        tasks=[
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
                "approval_risk": "L2",
                "last_summary": "waiting for approval",
                "files_touched": [],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T05:21:00Z",
            },
            {
                "project_id": "repo-c",
                "thread_id": "thr_native_3",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "retrying recovery",
                "files_touched": ["src/recovery.py"],
                "context_pressure": "critical",
                "stuck_level": 2,
                "failure_count": 3,
                "last_progress_at": "2026-04-05T05:22:00Z",
            },
            {
                "project_id": "repo-d",
                "thread_id": "thr_native_4",
                "status": "running",
                "phase": "planning",
                "pending_approval": False,
                "last_summary": "waiting",
                "files_touched": [],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T05:23:00Z",
            },
        ],
        approvals=[
            {
                "approval_id": "appr_001",
                "project_id": "repo-b",
                "thread_id": "thr_native_2",
                "risk_level": "L2",
                "command": "uv run pytest",
                "reason": "verify tests",
                "alternative": "",
                "status": "pending",
                "requested_at": "2026-04-05T05:22:00Z",
            },
        ],
    )

    reply = adapter.handle_intent("list_sessions")

    assert reply.message.startswith(
        "多项目进展（4） | 状态=进行中2、待审批1、受阻1"
        " | 先处理=repo-c:恢复失败、repo-b:待审批、repo-a:provider降级\n"
    )
    assert reply.message.index("- repo-c ") < reply.message.index("- repo-b ")
    assert reply.message.index("- repo-b ") < reply.message.index("- repo-a ")
    assert reply.message.index("- repo-a ") < reply.message.index("- repo-d ")
    assert (
        "- repo-a | editing_source | editing files | 上下文=low"
        " | 决策=provider降级(schema:provider-decision-v2) | 关注=provider降级"
    ) in reply.message
    assert (
        "- repo-b | approval | waiting for approval | 上下文=low | 关注=待审批"
        " | 下一步=审批列表、回复同意/拒绝、卡在哪里"
    ) in reply.message
    assert (
        "- repo-c | editing_source | retrying recovery | 上下文=critical"
        " | 恢复=恢复失败(failed_retryable) | 关注=恢复失败"
    ) in reply.message


def test_adapter_list_session_events_returns_stable_reply_model(tmp_path: Path) -> None:
    adapter = _adapter(
        tmp_path,
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
        },
    )

    reply = adapter.handle_intent("list_session_events", project_id="repo-a")

    assert reply.reply_code == "session_event_snapshot"
    assert reply.reply_kind == "events"
    assert len(reply.events) == 1
    assert reply.events[0].event_code == "session_created"
    assert reply.events[0].thread_id == "session:repo-a"


def test_adapter_request_recovery_maps_advisory_action_result_to_reply_model(tmp_path: Path) -> None:
    adapter = _adapter(
        tmp_path,
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
        },
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


def test_adapter_execute_recovery_maps_stable_action_result_to_reply_model(tmp_path: Path) -> None:
    adapter = _adapter(
        tmp_path,
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
        },
    )

    reply = adapter.handle_intent(
        "execute_recovery",
        project_id="repo-a",
        operator="openclaw",
        idempotency_key="idem-execute-recovery-1",
    )

    assert reply.reply_code == "recovery_execution_result"
    assert reply.message == "recovery handoff triggered"


def test_adapter_post_operator_guidance_maps_stable_action_result_to_reply_model(
    tmp_path: Path,
) -> None:
    adapter = _adapter(
        tmp_path,
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
        },
    )

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}
        reply = adapter.handle_intent(
            "post_operator_guidance",
            project_id="repo-a",
            operator="openclaw",
            idempotency_key="idem-guidance-adapter-1",
            arguments={
                "message": "Summarize the blocker and next smallest step.",
                "reason_code": "operator_guidance",
                "stuck_level": 2,
            },
        )

    assert steer_mock.call_count == 1
    assert reply.reply_code == "action_result"
    assert reply.action_result is not None
    assert reply.action_result.action_code == "post_operator_guidance"
    assert reply.action_result.effect == "steer_posted"
    assert reply.message == "operator guidance posted"


def test_adapter_evaluate_supervision_maps_stable_action_result_to_reply_model(tmp_path: Path) -> None:
    adapter = _adapter(
        tmp_path,
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
        },
    )

    with patch("watchdog.services.session_spine.supervision.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}
        reply = adapter.handle_intent(
            "evaluate_supervision",
            project_id="repo-a",
            operator="openclaw",
            idempotency_key="idem-supervision-1",
        )

    assert steer_mock.call_count == 1
    assert reply.reply_code == "supervision_evaluation"
    assert reply.action_result is not None
    assert reply.action_result.supervision_evaluation is not None
    assert reply.action_result.supervision_evaluation.reason_code == "stuck_soft"
    assert reply.action_result.supervision_evaluation.steer_sent is True


def test_adapter_get_action_receipt_uses_stable_receipt_store_without_upstream_reads(
    tmp_path: Path,
) -> None:
    receipt_store = ActionReceiptStore(tmp_path / "action_receipts.json")
    result = WatchdogActionResult(
        action_code=ActionCode.CONTINUE_SESSION,
        project_id="repo-a",
        approval_id=None,
        idempotency_key="idem-continue-lookup-1",
        action_status=ActionStatus.COMPLETED,
        effect=Effect.STEER_POSTED,
        reply_code=ReplyCode.ACTION_RESULT,
        message="continue request accepted",
        facts=[
            FactRecord(
                fact_id="fact_continue_posted",
                fact_code="steer_posted",
                fact_kind="action",
                severity="info",
                summary="continue posted",
                detail="continue request accepted",
                source="watchdog_action",
                observed_at="2026-04-05T05:23:00Z",
            )
        ],
    )
    receipt_store.put(
        receipt_key(
            action_code=result.action_code,
            project_id=result.project_id,
            approval_id=result.approval_id,
            idempotency_key=result.idempotency_key,
        ),
        result,
    )

    class NoReadAClient:
        def get_envelope(self, project_id: str) -> dict[str, object]:
            raise AssertionError(f"unexpected upstream read for {project_id}")

        def list_approvals(
            self,
            *,
            status: str | None = None,
            project_id: str | None = None,
            decided_by: str | None = None,
            callback_status: str | None = None,
        ) -> list[dict[str, object]]:
            _ = (status, project_id, decided_by, callback_status)
            raise AssertionError("unexpected approval read")

    adapter = OpenClawAdapter(
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        client=NoReadAClient(),
        receipt_store=receipt_store,
    )

    reply = adapter.handle_intent(
        "get_action_receipt",
        project_id="repo-a",
        idempotency_key="idem-continue-lookup-1",
        arguments={"action_code": "continue_session"},
    )

    assert reply.reply_code == "action_receipt"
    assert reply.action_result is not None
    assert reply.action_result.effect == "steer_posted"


def test_adapter_returns_unsupported_intent_for_unknown_request(tmp_path: Path) -> None:
    adapter = _adapter(
        tmp_path,
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
        },
    )

    reply = adapter.handle_intent("summon_supervisor", project_id="repo-a")

    assert reply.reply_code == "unsupported_intent"


def test_adapter_routes_natural_language_progress_message_to_canonical_reply(
    tmp_path: Path,
) -> None:
    adapter = _adapter(
        tmp_path,
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
        },
    )

    reply = adapter.handle_message(
        "现在进展",
        project_id="repo-a",
    )

    assert reply.intent_code == "get_progress"
    assert reply.reply_code == "task_progress_view"
    assert reply.progress is not None
    assert reply.progress.project_id == "repo-a"


def test_adapter_routes_natural_language_pause_message_to_canonical_action(
    tmp_path: Path,
) -> None:
    adapter = _adapter(
        tmp_path,
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
        },
    )

    reply = adapter.handle_message(
        "暂停",
        project_id="repo-a",
        idempotency_key="idem-pause-1",
    )

    assert reply.intent_code == "pause_session"
    assert reply.reply_code == "action_result"
    assert reply.action_result is not None
    assert reply.action_result.effect == "session_paused"
    assert adapter._client.pause_calls == ["repo-a"]


def test_adapter_routes_natural_language_message_by_native_thread(
    tmp_path: Path,
) -> None:
    adapter = _adapter(
        tmp_path,
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
        },
    )

    reply = adapter.handle_message(
        "任务状态",
        arguments={"native_thread_id": "thr_native_1"},
    )

    assert reply.intent_code == "get_session"
    assert reply.reply_code == "session_projection"
    assert reply.session is not None
    assert reply.session.project_id == "repo-a"
    assert reply.session.native_thread_id == "thr_native_1"


def test_adapter_lists_stable_session_events(tmp_path: Path) -> None:
    adapter = _adapter(
        tmp_path,
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
        },
    )

    events = adapter.list_session_events("repo-a")

    assert len(events) == 1
    assert events[0].event_code == "session_created"
    assert events[0].thread_id == "session:repo-a"
    assert "payload_json" not in events[0].model_dump(mode="json")


def test_adapter_iterates_stable_session_events(tmp_path: Path) -> None:
    adapter = _adapter(
        tmp_path,
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
        },
    )

    events = list(adapter.iter_session_events("repo-a"))

    assert len(events) == 1
    assert events[0].event_code == "session_resumed"
    assert events[0].attributes["mode"] == "resume_or_new_thread"
