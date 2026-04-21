from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from watchdog.contracts.session_spine.enums import (
    ActionCode,
    ActionStatus,
    Effect,
    ReplyCode,
)
from watchdog.contracts.session_spine.models import FactRecord, WatchdogActionResult
from watchdog.services.approvals.service import materialize_canonical_approval
from watchdog.services.adapters.openclaw.adapter import OpenClawAdapter
from watchdog.services.policy.decisions import CanonicalDecisionRecord, PolicyDecisionStore
from watchdog.services.resident_experts.service import ResidentExpertRuntimeService
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
    assert reply.progress is not None
    assert reply.progress.project_id == "repo-a"
    assert reply.progress.native_thread_id == "thr_native_1"
    assert reply.progress.summary == "editing files"


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


def test_adapter_get_session_surfaces_active_recovery_suppression(tmp_path: Path) -> None:
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="recovery_execution_suppressed",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:recovery-suppressed:repo-a",
        related_ids={"recovery_transaction_id": "recovery-tx:repo-a"},
        payload={
            "suppression_reason": "reentry_without_newer_progress",
            "suppression_source": "resident_orchestrator",
            "context_pressure": "critical",
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        occurred_at="2026-04-05T05:21:00Z",
    )
    adapter = _adapter(
        tmp_path,
        task={
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
        },
    )

    reply = adapter.handle_intent("get_session", project_id="repo-a")

    assert reply.reply_code == "session_projection"
    assert reply.message == "editing recovery path | 恢复抑制=等待新进展 | 下一步=卡在哪里"


def test_adapter_get_session_surfaces_goal_contract_context(tmp_path: Path) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    adapter = _adapter(
        tmp_path,
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "editing files",
            "files_touched": ["src/recovery.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
    )
    goal_contracts = GoalContractService(adapter._session_service)
    goal_contracts.bootstrap_contract(
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

    reply = adapter.handle_intent("get_session", project_id="repo-a")

    assert reply.reply_code == "session_projection"
    assert (
        reply.message
        == "editing files | 当前目标=继续把 recovery 自动重入收口到 child continuation"
    )
    assert reply.progress is not None
    assert reply.progress.goal_contract_version == "goal-v1"
    assert reply.progress.current_phase_goal == "继续把 recovery 自动重入收口到 child continuation"
    assert reply.progress.last_user_instruction == "继续把 recovery 自动重入收口到 child continuation"


def test_adapter_list_sessions_surfaces_goal_contract_context(tmp_path: Path) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    adapter = _adapter(
        tmp_path,
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "editing files",
            "files_touched": ["src/recovery.py"],
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
                "files_touched": ["src/recovery.py"],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T05:20:00Z",
            }
        ],
    )
    GoalContractService(adapter._session_service).bootstrap_contract(
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

    reply = adapter.handle_intent("list_sessions")

    assert reply.reply_code == "session_directory"
    assert reply.progresses is not None
    assert reply.progresses[0].goal_contract_version == "goal-v1"
    assert reply.progresses[0].current_phase_goal == "继续把 recovery 自动重入收口到 child continuation"
    assert reply.message == (
        "多项目进展（1） | 状态=进行中1\n"
        "- repo-a | editing_source | editing files | 上下文=low"
        " | 当前目标=继续把 recovery 自动重入收口到 child continuation"
    )


def test_adapter_get_session_renders_recovery_in_flight_suppression(tmp_path: Path) -> None:
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="recovery_execution_suppressed",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:recovery-suppressed:repo-a:in-flight",
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
    adapter = _adapter(
        tmp_path,
        task={
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
        },
    )

    reply = adapter.handle_intent("get_session", project_id="repo-a")

    assert reply.reply_code == "session_projection"
    assert reply.message == "handoff drafted | 恢复抑制=恢复进行中"


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


def test_adapter_get_session_by_native_thread_surfaces_active_recovery_suppression(
    tmp_path: Path,
) -> None:
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="recovery_execution_suppressed",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:recovery-suppressed:repo-a:native-thread",
        related_ids={"recovery_transaction_id": "recovery-tx:repo-a"},
        payload={
            "suppression_reason": "reentry_without_newer_progress",
            "suppression_source": "resident_orchestrator",
            "context_pressure": "critical",
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        occurred_at="2026-04-05T05:21:00Z",
    )
    adapter = _adapter(
        tmp_path,
        task={
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
        },
    )

    reply = adapter.handle_intent(
        "get_session_by_native_thread",
        arguments={"native_thread_id": "thr_native_1"},
    )

    assert reply.reply_code == "session_projection"
    assert reply.intent_code == "get_session_by_native_thread"
    assert reply.message == "editing recovery path | 恢复抑制=等待新进展 | 下一步=卡在哪里"


def test_adapter_get_session_by_native_thread_renders_recovery_cooldown_suppression(
    tmp_path: Path,
) -> None:
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="recovery_execution_suppressed",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:recovery-suppressed:repo-a:native-thread:cooldown",
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
    adapter = _adapter(
        tmp_path,
        task={
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
        },
    )

    reply = adapter.handle_intent(
        "get_session_by_native_thread",
        arguments={"native_thread_id": "thr_native_1"},
    )

    assert reply.reply_code == "session_projection"
    assert reply.intent_code == "get_session_by_native_thread"
    assert reply.message == "editing recovery path | 恢复抑制=恢复冷却中 | 下一步=卡在哪里"


def test_adapter_get_session_by_native_thread_renders_recovery_in_flight_suppression(
    tmp_path: Path,
) -> None:
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="recovery_execution_suppressed",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:recovery-suppressed:repo-a:native-thread:in-flight",
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
    adapter = _adapter(
        tmp_path,
        task={
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
        },
    )

    reply = adapter.handle_intent(
        "get_session_by_native_thread",
        arguments={"native_thread_id": "thr_native_1"},
    )

    assert reply.reply_code == "session_projection"
    assert reply.intent_code == "get_session_by_native_thread"
    assert reply.message == "handoff drafted | 恢复抑制=恢复进行中"


def test_adapter_get_session_by_native_thread_projects_goal_contract_adoption_from_session_events_without_live_control(
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

    class BrokenThreadAClient(FakeAClient):
        def get_envelope_by_thread(self, thread_id: str) -> dict[str, object]:
            raise RuntimeError(f"a-side temporarily unavailable for {thread_id}")

    adapter = OpenClawAdapter(
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        client=BrokenThreadAClient(
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
        receipt_store=ActionReceiptStore(tmp_path / "action_receipts.json"),
    )

    reply = adapter.handle_intent(
        "get_session_by_native_thread",
        arguments={"native_thread_id": "thr_child_v1"},
    )

    assert reply.reply_code == "session_projection"
    assert reply.intent_code == "get_session_by_native_thread"
    assert reply.message == "editing files | 当前目标=继续把 recovery 自动重入收口到 child continuation"
    assert reply.session is not None
    assert reply.session.thread_id == "session:repo-a"
    assert reply.session.native_thread_id == "thr_child_v1"
    assert reply.progress is not None
    assert reply.progress.goal_contract_version == created.version
    assert reply.progress.native_thread_id == "thr_child_v1"


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


def test_adapter_get_workspace_activity_prefers_explicit_native_thread_id(tmp_path: Path) -> None:
    adapter = _adapter(
        tmp_path,
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
        },
    )

    reply = adapter.handle_intent(
        "get_workspace_activity",
        project_id="repo-a",
        arguments={"recent_minutes": 30},
    )

    assert reply.reply_code == "workspace_activity_view"
    assert reply.workspace_activity is not None
    assert reply.workspace_activity.thread_id == "session:repo-a"
    assert reply.workspace_activity.native_thread_id == "thr_native_1"


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


def test_adapter_why_stuck_surfaces_goal_contract_context(tmp_path: Path) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

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
    GoalContractService(adapter._session_service).bootstrap_contract(
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

    reply = adapter.handle_intent("why_stuck", project_id="repo-a")

    assert reply.reply_code == "stuck_explanation"
    assert (
        reply.message
        == "session appears stuck; repeated failures detected; context pressure is critical"
        " | 当前目标=继续把 recovery 自动重入收口到 child continuation | 下一步=卡在哪里"
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


def test_adapter_progress_surfaces_goal_contract_context(tmp_path: Path) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    adapter = _adapter(
        tmp_path,
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "editing files",
            "files_touched": ["src/recovery.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
    )
    GoalContractService(adapter._session_service).bootstrap_contract(
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

    reply = adapter.handle_intent("get_progress", project_id="repo-a")

    assert reply.reply_code == "task_progress_view"
    assert (
        reply.message
        == "editing files | 当前目标=继续把 recovery 自动重入收口到 child continuation"
    )
    assert reply.progress is not None
    assert reply.progress.goal_contract_version == "goal-v1"
    assert reply.progress.current_phase_goal == "继续把 recovery 自动重入收口到 child continuation"


def test_adapter_progress_surfaces_revised_latest_user_instruction(tmp_path: Path) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

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
    contracts = GoalContractService(adapter._session_service)
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

    reply = adapter.handle_intent("get_progress", project_id="repo-a")

    assert reply.reply_code == "task_progress_view"
    assert reply.message == "editing files | 当前目标=继续把 recovery 自动重入收口到 child continuation"
    assert reply.progress is not None
    assert reply.progress.goal_contract_version == "goal-v2"
    assert reply.progress.current_phase_goal == "继续把 recovery 自动重入收口到 child continuation"
    assert reply.progress.last_user_instruction == "继续把 recovery 自动重入收口到 child continuation"


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


def test_adapter_explain_blocker_surfaces_goal_contract_context(tmp_path: Path) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

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
    GoalContractService(adapter._session_service).bootstrap_contract(
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

    reply = adapter.handle_intent("explain_blocker", project_id="repo-a")

    assert reply.reply_code == "blocker_explanation"
    assert (
        reply.message
        == "approval required; awaiting operator direction"
        " | 当前目标=继续把 recovery 自动重入收口到 child continuation"
        " | 下一步=审批列表、回复同意/拒绝、为什么卡住"
    )


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


def test_adapter_list_sessions_renders_current_child_session_id_resume_shape(tmp_path: Path) -> None:
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
    adapter = _adapter(
        tmp_path,
        task={
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
        },
        tasks=[
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
            },
        ],
    )

    reply = adapter.handle_intent("list_sessions")

    assert reply.progresses[0].recovery_outcome == "new_child_session"
    assert reply.progresses[0].recovery_child_session_id == "session:repo-b:thr_child_v1"
    assert reply.message == (
        "多项目进展（1） | 状态=进行中1\n"
        "- repo-b | editing_source | editing files | 上下文=low | 恢复=新子会话 repo-b:thr_child_v1"
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


def test_adapter_list_sessions_prioritizes_active_recovery_suppression_before_approval_and_provider_degrade(
    tmp_path: Path,
) -> None:
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="recovery_execution_suppressed",
        project_id="repo-c",
        session_id="session:repo-c",
        correlation_id="corr:recovery-suppressed:repo-c",
        related_ids={"recovery_transaction_id": "recovery-tx:repo-c"},
        payload={
            "suppression_reason": "reentry_without_newer_progress",
            "suppression_source": "resident_orchestrator",
            "context_pressure": "critical",
            "last_progress_at": "2026-04-05T05:22:00Z",
        },
        occurred_at="2026-04-05T05:23:00Z",
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
                "last_summary": "editing recovery path",
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
        " | 先处理=repo-c:恢复抑制、repo-b:待审批、repo-a:provider降级\n"
    )
    assert reply.message.index("- repo-c ") < reply.message.index("- repo-b ")
    assert reply.message.index("- repo-b ") < reply.message.index("- repo-a ")
    assert reply.message.index("- repo-a ") < reply.message.index("- repo-d ")
    assert (
        "- repo-c | editing_source | editing recovery path | 上下文=critical"
        " | 恢复抑制=等待新进展 | 关注=恢复抑制"
    ) in reply.message


def test_adapter_list_sessions_renders_recovery_cooldown_suppression(tmp_path: Path) -> None:
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
    adapter = _adapter(
        tmp_path,
        task=task,
        tasks=[task],
    )
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="recovery_execution_suppressed",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:recovery-suppressed:repo-a:list:cooldown",
        related_ids={"recovery_transaction_id": "recovery-tx:repo-a"},
        payload={
            "suppression_reason": "cooldown_window_active",
            "suppression_source": "resident_orchestrator",
            "task_status": "running",
            "context_pressure": "critical",
            "last_progress_at": "2026-04-05T05:20:00Z",
            "cooldown_seconds": "300",
        },
        occurred_at="2026-04-05T05:21:00Z",
    )

    reply = adapter.handle_intent("list_sessions")

    assert reply.message.startswith(
        "多项目进展（1） | 状态=受阻1 | 先处理=repo-a:恢复抑制\n"
    )
    assert (
        "- repo-a | editing_source | editing recovery path | 上下文=critical"
        " | 恢复抑制=恢复冷却中 | 关注=恢复抑制"
    ) in reply.message


def test_adapter_list_sessions_renders_recovery_in_flight_suppression(tmp_path: Path) -> None:
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
    adapter = _adapter(
        tmp_path,
        task=task,
        tasks=[task],
    )
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="recovery_execution_suppressed",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:recovery-suppressed:repo-a:list:in-flight",
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

    reply = adapter.handle_intent("list_sessions")

    assert reply.message.startswith(
        "多项目进展（1） | 状态=进行中1 | 先处理=repo-a:恢复抑制\n"
    )
    assert (
        "- repo-a | handoff | handoff drafted | 上下文=critical"
        " | 恢复抑制=恢复进行中 | 关注=恢复抑制"
    ) in reply.message


def test_adapter_list_sessions_surfaces_relative_freshness_buckets(tmp_path: Path) -> None:
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
                "status": "running",
                "phase": "planning",
                "pending_approval": False,
                "last_summary": "waiting",
                "files_touched": [],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T04:35:00Z",
            },
            {
                "project_id": "repo-c",
                "thread_id": "thr_native_3",
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
                "last_progress_at": "",
            },
        ],
    )

    reply = adapter.handle_intent("list_sessions")

    assert "多项目进展（4） | 状态=进行中4" in reply.message
    assert "- repo-a | editing_source | editing files | 上下文=low" in reply.message
    assert "- repo-b | planning | waiting | 上下文=low | 更新=较早" in reply.message
    assert "- repo-c | planning | waiting | 上下文=low | 更新=静默" in reply.message
    assert "- repo-d | planning | waiting | 上下文=low | 更新=未知" in reply.message


def test_adapter_list_sessions_merges_live_tasks_with_event_only_child_interaction_event(
    tmp_path: Path,
) -> None:
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="interaction_window_expired",
        project_id="repo-c",
        session_id="session:repo-c:thr_child_1",
        correlation_id="corr:interaction:repo-c:adapter-live-merge",
        related_ids={
            "interaction_context_id": "ctx-child-1",
            "interaction_family_id": "family-child-1",
            "actor_id": "user:alice",
            "native_thread_id": "thr_child_1",
        },
        payload={
            "channel_kind": "dm",
            "expired_at": "2026-04-07T00:30:00Z",
            "received_at": "2026-04-07T00:40:00Z",
        },
        occurred_at="2026-04-07T00:40:00Z",
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
                "last_summary": "editing recovery path",
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

    assert reply.message.startswith("多项目进展（4）")
    assert "- repo-a | editing_source | editing files | 上下文=low" in reply.message
    assert (
        "- repo-b | approval | waiting for approval | 上下文=low"
        " | 关注=待审批 | 下一步=审批列表、回复同意/拒绝、卡在哪里"
    ) in reply.message
    assert (
        "- repo-c | editing_source | editing recovery path | 上下文=critical"
    ) in reply.message
    assert "- repo-d | planning | waiting | 上下文=low" in reply.message


def test_adapter_list_sessions_falls_back_to_canonical_approvals_when_live_approval_read_fails(
    tmp_path: Path,
) -> None:
    class ApprovalFailureAClient(FakeAClient):
        def list_approvals(
            self,
            *,
            status: str | None = None,
            project_id: str | None = None,
            decided_by: str | None = None,
            callback_status: str | None = None,
        ) -> list[dict[str, object]]:
            raise RuntimeError("approval list unavailable")

    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    receipt_store = ActionReceiptStore(tmp_path / "action_receipts.json")
    adapter = OpenClawAdapter(
        settings=settings,
        client=ApprovalFailureAClient(
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
        ),
        receipt_store=receipt_store,
    )
    materialize_canonical_approval(
        _provider_invalid_decision_record(
            project_id="repo-b",
            session_id="session:repo-b",
            native_thread_id="thr_native_2",
        ).model_copy(
            update={
                "approval_id": "appr_001",
                "action_ref": "continue_session",
                "decision_key": (
                    "session:repo-b|fact-v7|policy-v1|require_user_decision|continue_session|appr_001"
                ),
                "idempotency_key": (
                    "session:repo-b|fact-v7|policy-v1|require_user_decision|continue_session|appr_001"
                ),
            }
        ),
        approval_store=adapter._approval_store,
        session_service=adapter._session_service,
    )

    reply = adapter.handle_intent("list_sessions")

    assert reply.reply_code == "session_directory"
    assert [session.project_id for session in reply.sessions] == ["repo-a", "repo-b"]
    sessions_by_project = {session.project_id: session for session in reply.sessions}
    assert sessions_by_project["repo-b"].pending_approval_count == 1
    assert "repo-b:待审批" in reply.message


def test_adapter_list_sessions_keeps_live_tasks_when_live_approval_read_fails_without_canonical_fallback(
    tmp_path: Path,
) -> None:
    class ApprovalFailureAClient(FakeAClient):
        def list_approvals(
            self,
            *,
            status: str | None = None,
            project_id: str | None = None,
            decided_by: str | None = None,
            callback_status: str | None = None,
        ) -> list[dict[str, object]]:
            raise RuntimeError("approval list unavailable")

    adapter = OpenClawAdapter(
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        client=ApprovalFailureAClient(
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
                    "status": "running",
                    "phase": "planning",
                    "pending_approval": False,
                    "last_summary": "waiting",
                    "files_touched": [],
                    "context_pressure": "low",
                    "stuck_level": 0,
                    "failure_count": 0,
                    "last_progress_at": "2026-04-05T05:21:00Z",
                },
            ],
        ),
        receipt_store=ActionReceiptStore(tmp_path / "action_receipts.json"),
    )

    reply = adapter.handle_intent("list_sessions")

    assert reply.reply_code == "session_directory"
    assert [session.project_id for session in reply.sessions] == ["repo-a", "repo-b"]
    sessions_by_project = {session.project_id: session for session in reply.sessions}
    assert sessions_by_project["repo-a"].pending_approval_count == 0
    assert sessions_by_project["repo-b"].pending_approval_count == 0


def test_adapter_list_sessions_appends_supplemental_event_only_project_not_present_in_live_tasks(
    tmp_path: Path,
) -> None:
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="recovery_execution_suppressed",
        project_id="repo-c",
        session_id="session:repo-c",
        correlation_id="corr:recovery-suppressed:repo-c:adapter-supplemental",
        related_ids={"recovery_transaction_id": "recovery-tx:repo-c"},
        payload={
            "suppression_reason": "reentry_without_newer_progress",
            "suppression_source": "resident_orchestrator",
            "task_status": "running",
            "context_pressure": "critical",
            "last_progress_at": "2026-04-05T05:22:00Z",
        },
        occurred_at="2026-04-05T05:23:00Z",
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
                "status": "planning",
                "phase": "planning",
                "pending_approval": False,
                "last_summary": "waiting",
                "files_touched": [],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T05:21:00Z",
            },
        ],
        approvals=[],
    )

    reply = adapter.handle_intent("list_sessions")

    assert reply.reply_code == "session_directory"
    assert [session.project_id for session in reply.sessions] == ["repo-a", "repo-b", "repo-c"]
    progress_by_project = {progress.project_id: progress for progress in reply.progresses}
    assert progress_by_project["repo-c"].recovery_suppression_reason == (
        "reentry_without_newer_progress"
    )


def test_adapter_list_sessions_appends_supplemental_goal_contract_project_not_present_in_live_tasks(
    tmp_path: Path,
) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

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
                "status": "planning",
                "phase": "planning",
                "pending_approval": False,
                "last_summary": "waiting",
                "files_touched": [],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T05:21:00Z",
            },
        ],
        approvals=[],
    )
    GoalContractService(adapter._session_service).bootstrap_contract(
        project_id="repo-c",
        session_id="session:repo-c",
        task_title="收口 recovery 自动重入",
        task_prompt="收口 recovery 自动重入",
        last_user_instruction="继续把 recovery 自动重入收口到 child continuation",
        phase="editing_source",
        last_summary="editing files",
        current_phase_goal="继续把 recovery 自动重入收口到 child continuation",
        explicit_deliverables=["避免重复 handoff"],
        completion_signals=["child continuation 稳定"],
    )

    reply = adapter.handle_intent("list_sessions")

    assert reply.reply_code == "session_directory"
    assert [session.project_id for session in reply.sessions] == ["repo-a", "repo-b", "repo-c"]
    progress_by_project = {progress.project_id: progress for progress in reply.progresses}
    assert progress_by_project["repo-c"].goal_contract_version == "goal-v1"
    assert progress_by_project["repo-c"].summary == "editing files"
    assert progress_by_project["repo-c"].current_phase_goal == (
        "继续把 recovery 自动重入收口到 child continuation"
    )
    assert (
        "- repo-c | editing_source | editing files | 上下文=low"
        " | 当前目标=继续把 recovery 自动重入收口到 child continuation"
    ) in reply.message


def test_adapter_list_sessions_appends_supplemental_persisted_project_not_present_in_live_tasks(
    tmp_path: Path,
) -> None:
    payload = {
        "sessions": {
            "repo-c": {
                "project_id": "repo-c",
                "thread_id": "session:repo-c",
                "native_thread_id": "thr_native_1",
                "session_seq": 3,
                "fact_snapshot_version": "fact-v1",
                "last_refreshed_at": "2026-04-05T05:25:00Z",
                    "session": {
                        "project_id": "repo-c",
                        "thread_id": "session:repo-c",
                        "native_thread_id": "thr_native_1",
                        "session_state": "awaiting_approval",
                        "activity_phase": "approval",
                        "attention_state": "needs_human",
                        "headline": "waiting for approval",
                        "pending_approval_count": 1,
                        "available_intents": ["get_progress", "list_pending_approvals"],
                    },
                "progress": {
                    "project_id": "repo-c",
                    "thread_id": "session:repo-c",
                    "native_thread_id": "thr_native_1",
                    "summary": "waiting for approval",
                    "activity_phase": "approval",
                    "files_touched": ["src/example.py"],
                    "context_pressure": "low",
                    "stuck_level": 0,
                    "decision_trace_ref": None,
                    "decision_degrade_reason": None,
                    "provider_output_schema_ref": None,
                    "recovery_status": None,
                    "recovery_outcome": None,
                    "recovery_child_session_id": None,
                    "recovery_suppression_reason": None,
                    "recovery_suppression_source": None,
                    "recovery_suppression_observed_at": None,
                    "last_progress_at": "2026-04-05T05:20:00Z",
                },
                "facts": [
                    {
                        "fact_id": "fact-1",
                        "fact_code": "approval_pending",
                        "fact_kind": "blocker",
                        "severity": "warning",
                        "summary": "approval pending",
                        "detail": "approval pending",
                        "source": "watchdog",
                        "observed_at": "2026-04-05T05:20:00Z",
                        "related_ids": {},
                    }
                ],
                "approval_queue": [
                        {
                            "approval_id": "appr_001",
                            "project_id": "repo-c",
                            "thread_id": "session:repo-c",
                            "native_thread_id": "thr_native_1",
                            "command": "uv run pytest",
                            "reason": "verify tests",
                        "alternative": "",
                        "status": "pending",
                        "requested_at": "2026-04-05T05:21:00Z",
                        "decided_at": None,
                        "decided_by": None,
                        "risk_level": "L2",
                    }
                ],
            }
        }
    }
    (tmp_path / "session_spine.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
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
                "status": "planning",
                "phase": "planning",
                "pending_approval": False,
                "last_summary": "waiting",
                "files_touched": [],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T05:21:00Z",
            },
        ],
        approvals=[],
    )

    reply = adapter.handle_intent("list_sessions")

    assert reply.reply_code == "session_directory"
    assert [session.project_id for session in reply.sessions] == ["repo-a", "repo-b", "repo-c"]
    sessions_by_project = {session.project_id: session for session in reply.sessions}
    assert sessions_by_project["repo-c"].thread_id == "session:repo-c"


def test_adapter_list_sessions_surfaces_resident_expert_coverage_summary(tmp_path: Path) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    stale_seen_at = (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    fresh_seen_at = now.isoformat().replace("+00:00", "Z")
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
            "last_progress_at": fresh_seen_at,
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
                "last_progress_at": fresh_seen_at,
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
                "last_progress_at": fresh_seen_at,
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
                "requested_at": fresh_seen_at,
            },
        ],
        resident_expert_stale_after_seconds=60.0,
    )
    resident_expert_runtime_service = ResidentExpertRuntimeService.from_data_dir(
        tmp_path,
        stale_after_seconds=60.0,
    )
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
        consultation_ref="consult:repo-b:resident-experts",
        observed_runtime_handles={"hermes-agent-expert": "agent://hegel"},
        consulted_at=fresh_seen_at,
    )

    reply = adapter.handle_intent("list_sessions")

    assert reply.resident_expert_coverage is not None
    assert reply.resident_expert_coverage.coverage_status == "degraded"
    assert reply.resident_expert_coverage.latest_consultation_ref == "consult:repo-b:resident-experts"
    assert reply.message.startswith(
        "多项目进展（2） | 监督=在线1、过期1 | 最近合议=consult:repo-b:resident-experts"
        " | 状态=进行中1、待审批1 | 先处理=repo-b:待审批\n"
    )


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


def test_adapter_list_session_events_prefers_explicit_native_thread_id(tmp_path: Path) -> None:
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

    adapter = OpenClawAdapter(
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        client=EventsClient(
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
        receipt_store=ActionReceiptStore(tmp_path / "action_receipts.json"),
    )

    reply = adapter.handle_intent("list_session_events", project_id="repo-a")

    assert reply.reply_code == "session_event_snapshot"
    assert len(reply.events) == 1
    assert reply.events[0].event_code == "session_resumed"
    assert reply.events[0].thread_id == "session:repo-a"
    assert reply.events[0].native_thread_id == "thr_native_1"


def test_adapter_list_session_events_falls_back_to_session_service_child_adoption_event(
    tmp_path: Path,
) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    class BrokenEventsClient(FakeAClient):
        def get_events_snapshot(
            self,
            project_id: str,
            *,
            poll_interval: float = 0.5,
        ) -> tuple[str, str]:
            _ = (project_id, poll_interval)
            raise RuntimeError("a-side temporarily unavailable")

    adapter = OpenClawAdapter(
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        client=BrokenEventsClient(
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
        receipt_store=ActionReceiptStore(tmp_path / "action_receipts.json"),
    )
    goal_contracts = GoalContractService(adapter._session_service)
    created = goal_contracts.bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="继续 recovery",
        task_prompt="把 child session adoption 暴露到 stable events",
        last_user_instruction="继续补 stable events child adoption",
        phase="implementation",
        last_summary="正在补 stable event fallback",
        explicit_deliverables=["stable events 暴露 child adoption"],
        completion_signals=["相关 pytest 通过"],
    )
    goal_contracts.adopt_contract_for_child_session(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        child_session_id="session:repo-a:thr_child_1",
        child_native_thread_id="thr_child_1",
        expected_version=created.version,
        recovery_transaction_id="recovery-tx:1",
        source_packet_id="packet:handoff-1",
    )

    events = adapter.list_session_events("repo-a")

    assert len(events) == 2
    assert events[-1].event_code == "session_resumed"
    assert events[-1].thread_id == "session:repo-a:thr_child_1"
    assert events[-1].native_thread_id == "thr_child_1"
    assert events[-1].related_ids["child_session_id"] == "session:repo-a:thr_child_1"
    assert events[-1].related_ids["recovery_transaction_id"] == "recovery-tx:1"


def test_adapter_handle_intent_list_session_events_falls_back_to_session_service_child_adoption_event(
    tmp_path: Path,
) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    class BrokenEventsClient(FakeAClient):
        def get_events_snapshot(
            self,
            project_id: str,
            *,
            poll_interval: float = 0.5,
        ) -> tuple[str, str]:
            _ = (project_id, poll_interval)
            raise RuntimeError("a-side temporarily unavailable")

    adapter = OpenClawAdapter(
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        client=BrokenEventsClient(
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
        receipt_store=ActionReceiptStore(tmp_path / "action_receipts.json"),
    )
    goal_contracts = GoalContractService(adapter._session_service)
    created = goal_contracts.bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="继续 recovery",
        task_prompt="把 child session adoption 暴露到 stable events",
        last_user_instruction="继续补 stable events child adoption",
        phase="implementation",
        last_summary="正在补 stable event fallback",
        explicit_deliverables=["stable events 暴露 child adoption"],
        completion_signals=["相关 pytest 通过"],
    )
    goal_contracts.adopt_contract_for_child_session(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        child_session_id="session:repo-a:thr_child_1",
        child_native_thread_id="thr_child_1",
        expected_version=created.version,
        recovery_transaction_id="recovery-tx:1",
        source_packet_id="packet:handoff-1",
    )

    reply = adapter.handle_intent("list_session_events", project_id="repo-a")

    assert reply.reply_code == "session_event_snapshot"
    assert reply.events is not None
    assert len(reply.events) == 2
    assert reply.events[-1].event_code == "session_resumed"
    assert reply.events[-1].thread_id == "session:repo-a:thr_child_1"
    assert reply.events[-1].native_thread_id == "thr_child_1"


def test_adapter_handle_intent_list_session_events_merges_raw_and_session_service_events(
    tmp_path: Path,
) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

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
    goal_contracts = GoalContractService(adapter._session_service)
    created = goal_contracts.bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="继续 recovery",
        task_prompt="把 child session adoption 暴露到 stable events",
        last_user_instruction="继续补 stable events child adoption",
        phase="implementation",
        last_summary="正在补 stable event merge",
        explicit_deliverables=["stable events 合并 child adoption"],
        completion_signals=["相关 pytest 通过"],
    )
    goal_contracts.adopt_contract_for_child_session(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        child_session_id="session:repo-a:thr_child_1",
        child_native_thread_id="thr_child_1",
        expected_version=created.version,
        recovery_transaction_id="recovery-tx:1",
        source_packet_id="packet:handoff-1",
    )

    reply = adapter.handle_intent("list_session_events", project_id="repo-a")

    assert reply.reply_code == "session_event_snapshot"
    assert reply.events is not None
    assert len(reply.events) == 3
    assert reply.events[0].event_code == "session_created"
    assert reply.events[1].event_code == "session_updated"
    assert reply.events[2].event_code == "session_resumed"
    assert reply.events[2].thread_id == "session:repo-a:thr_child_1"


def test_adapter_iter_session_events_prepends_session_service_child_adoption_event(
    tmp_path: Path,
) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

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
    goal_contracts = GoalContractService(adapter._session_service)
    created = goal_contracts.bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="继续 recovery",
        task_prompt="adapter follow 流预置 canonical child adoption",
        last_user_instruction="继续补 adapter follow stream canonical bootstrap",
        phase="implementation",
        last_summary="正在补 adapter follow stream canonical bootstrap",
        explicit_deliverables=["adapter follow 流预置 canonical child adoption"],
        completion_signals=["相关 pytest 通过"],
    )
    goal_contracts.adopt_contract_for_child_session(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        child_session_id="session:repo-a:thr_child_1",
        child_native_thread_id="thr_child_1",
        expected_version=created.version,
        recovery_transaction_id="recovery-tx:1",
        source_packet_id="packet:handoff-1",
    )

    events = list(adapter.iter_session_events("repo-a"))

    assert len(events) == 3
    assert events[0].event_code == "session_created"
    assert events[1].thread_id == "session:repo-a:thr_child_1"
    assert events[1].related_ids["recovery_transaction_id"] == "recovery-tx:1"
    assert events[2].event_code == "session_resumed"


def test_adapter_iter_session_events_falls_back_when_first_stream_pull_fails(
    tmp_path: Path,
) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    class DeferredBrokenEventsClient(FakeAClient):
        def iter_events(
            self,
            project_id: str,
            *,
            poll_interval: float = 0.5,
        ):
            _ = (project_id, poll_interval)

            def _iter():
                raise RuntimeError("a-side stream broke before first event")
                yield ""

            return _iter()

    adapter = OpenClawAdapter(
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        client=DeferredBrokenEventsClient(
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
        receipt_store=ActionReceiptStore(tmp_path / "action_receipts.json"),
    )
    goal_contracts = GoalContractService(adapter._session_service)
    created = goal_contracts.bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="继续 recovery",
        task_prompt="adapter deferred follow 流 fallback 到 canonical child adoption",
        last_user_instruction="继续补 adapter deferred follow stream fallback",
        phase="implementation",
        last_summary="正在补 adapter deferred follow stream fallback",
        explicit_deliverables=["adapter deferred follow 流 fallback 到 canonical child adoption"],
        completion_signals=["相关 pytest 通过"],
    )
    goal_contracts.adopt_contract_for_child_session(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        child_session_id="session:repo-a:thr_child_1",
        child_native_thread_id="thr_child_1",
        expected_version=created.version,
        recovery_transaction_id="recovery-tx:1",
        source_packet_id="packet:handoff-1",
    )

    events = list(adapter.iter_session_events("repo-a"))

    assert len(events) == 2
    assert events[0].event_code == "session_created"
    assert events[1].thread_id == "session:repo-a:thr_child_1"
    assert events[1].related_ids["recovery_transaction_id"] == "recovery-tx:1"


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


def test_adapter_routes_natural_language_event_stream_message_to_session_events(
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
        "事件流",
        project_id="repo-a",
    )

    assert reply.intent_code == "list_session_events"
    assert reply.reply_code == "session_event_snapshot"
    assert reply.events is not None
    assert len(reply.events) == 1
    assert reply.events[0].event_code == "session_created"


def test_adapter_routes_natural_language_session_events_message_by_native_thread(
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
        "会话事件",
        arguments={"native_thread_id": "thr_native_1"},
    )

    assert reply.intent_code == "list_session_events"
    assert reply.reply_code == "session_event_snapshot"
    assert reply.events is not None
    assert len(reply.events) == 1
    assert reply.events[0].project_id == "repo-a"
    assert reply.events[0].thread_id == "session:repo-a"


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


def test_adapter_list_session_events_dedupes_duplicate_raw_snapshot_event_ids(tmp_path: Path) -> None:
    class DuplicateSnapshotClient(FakeAClient):
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
                'data: {"event_id":"evt_001","project_id":"repo-a","thread_id":"thr_native_1","event_type":"task_created","event_source":"a_control_agent","payload_json":{"status":"running","phase":"planning"},"created_at":"2026-04-05T10:00:00Z"}\n\n'
                'id: evt_001\n'
                "event: task_created\n"
                'data: {"event_id":"evt_001","project_id":"repo-a","thread_id":"thr_native_1","event_type":"task_created","event_source":"a_control_agent","payload_json":{"status":"running","phase":"planning"},"created_at":"2026-04-05T10:00:00Z"}\n\n',
                "text/event-stream",
            )

    adapter = OpenClawAdapter(
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        client=DuplicateSnapshotClient(
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
        receipt_store=ActionReceiptStore(tmp_path / "action_receipts.json"),
    )

    events = adapter.list_session_events("repo-a")

    assert len(events) == 1
    assert events[0].event_code == "session_created"


def test_adapter_list_session_events_dedupes_duplicate_raw_snapshot_events_without_event_id(
    tmp_path: Path,
) -> None:
    class MissingEventIdSnapshotClient(FakeAClient):
        def get_events_snapshot(
            self,
            project_id: str,
            *,
            poll_interval: float = 0.5,
        ) -> tuple[str, str]:
            assert project_id == self._task["project_id"]
            _ = poll_interval
            return (
                "event: resume\n"
                'data: {"project_id":"repo-a","thread_id":"thr_native_1","event_type":"resume","event_source":"a_control_agent","payload_json":{"mode":"resume_or_new_thread"},"created_at":"2026-04-05T10:00:00Z"}\n\n'
                "event: resume\n"
                'data: {"project_id":"repo-a","thread_id":"thr_native_1","event_type":"resume","event_source":"a_control_agent","payload_json":{"mode":"resume_or_new_thread"},"created_at":"2026-04-05T10:00:00Z"}\n\n',
                "text/event-stream",
            )

    adapter = OpenClawAdapter(
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        client=MissingEventIdSnapshotClient(
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
        receipt_store=ActionReceiptStore(tmp_path / "action_receipts.json"),
    )

    events = adapter.list_session_events("repo-a")

    assert len(events) == 1
    assert events[0].event_code == "session_resumed"
    assert events[0].event_id.startswith("synthetic:")


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

    assert len(events) == 2
    assert events[0].event_code == "session_created"
    assert events[1].event_code == "session_resumed"
    assert events[1].attributes["mode"] == "resume_or_new_thread"


def test_adapter_iter_session_events_dedupes_replayed_snapshot_events_without_event_id(
    tmp_path: Path,
) -> None:
    class MissingEventIdFollowClient(FakeAClient):
        def get_events_snapshot(
            self,
            project_id: str,
            *,
            poll_interval: float = 0.5,
        ) -> tuple[str, str]:
            assert project_id == self._task["project_id"]
            _ = poll_interval
            return (
                "event: resume\n"
                'data: {"project_id":"repo-a","thread_id":"thr_native_1","event_type":"resume","event_source":"a_control_agent","payload_json":{"mode":"resume_or_new_thread"},"created_at":"2026-04-05T10:00:00Z"}\n\n',
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
                "event: resume\n"
                'data: {"project_id":"repo-a","thread_id":"thr_native_1","event_type":"resume","event_source":"a_control_agent","payload_json":{"mode":"resume_or_new_thread"},"created_at":"2026-04-05T10:00:00Z"}\n\n'
            )
            yield (
                "event: steer\n"
                'data: {"project_id":"repo-a","thread_id":"thr_native_1","event_type":"steer","event_source":"watchdog","payload_json":{"message":"stay focused","reason":"policy"},"created_at":"2026-04-05T10:01:00Z"}\n\n'
            )

    adapter = OpenClawAdapter(
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        client=MissingEventIdFollowClient(
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
        receipt_store=ActionReceiptStore(tmp_path / "action_receipts.json"),
    )

    events = list(adapter.iter_session_events("repo-a"))

    assert len(events) == 2
    assert events[0].event_code == "session_resumed"
    assert events[0].event_id.startswith("synthetic:")
    assert events[1].event_code == "guidance_posted"
