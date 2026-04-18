from __future__ import annotations

from watchdog.services.session_service.service import SessionService
from watchdog.services.session_service.store import SessionServiceStore
from watchdog.services.future_worker.service import FutureWorkerExecutionService
from watchdog.services.session_spine.recovery import perform_recovery_execution
from watchdog.settings import Settings


class FakeAClient:
    def __init__(
        self,
        *,
        task: dict[str, object],
        resume_success: bool = True,
        handoff_data: dict[str, object] | None = None,
        resume_data: dict[str, object] | None = None,
    ) -> None:
        self._task = dict(task)
        self._resume_success = resume_success
        self._handoff_data = dict(handoff_data or {})
        self._resume_data = dict(resume_data or {})
        self.handoff_calls: list[tuple[str, str]] = []
        self.resume_calls: list[tuple[str, str, str]] = []

    def get_envelope(self, project_id: str) -> dict[str, object]:
        assert project_id == self._task["project_id"]
        return {"success": True, "data": dict(self._task)}

    def list_approvals(self, *, status: str | None = None) -> list[dict[str, object]]:
        _ = status
        return []

    def trigger_handoff(self, project_id: str, *, reason: str) -> dict[str, object]:
        self.handoff_calls.append((project_id, reason))
        handoff_data = {
            "handoff_file": f"/tmp/{project_id}.handoff.md",
            "summary": "handoff",
        }
        handoff_data.update(self._handoff_data)
        return {
            "success": True,
            "data": handoff_data,
        }

    def trigger_resume(
        self,
        project_id: str,
        *,
        mode: str,
        handoff_summary: str,
    ) -> dict[str, object]:
        self.resume_calls.append((project_id, mode, handoff_summary))
        if self._resume_success:
            resume_data = {
                "project_id": project_id,
                "status": "running",
                "mode": mode,
            }
            resume_data.update(self._resume_data)
            return {
                "success": True,
                "data": resume_data,
            }
        return {"success": False, "error": {"code": "RESUME_FAILED", "message": "bridge unavailable"}}


def test_perform_recovery_execution_returns_noop_without_side_effects(tmp_path) -> None:
    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        client=FakeAClient(
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
        ),
    )

    assert outcome.action == "noop"
    assert outcome.context_pressure == "medium"
    assert outcome.handoff is None
    assert outcome.resume is None
    assert outcome.resume_error is None


def test_perform_recovery_execution_preserves_handoff_when_resume_fails(tmp_path) -> None:
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
        },
        resume_success=False,
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
    )

    assert client.handoff_calls == [("repo-a", "context_critical")]
    assert client.resume_calls == [("repo-a", "resume_or_new_thread", "handoff")]
    assert outcome.action == "handoff_triggered"
    assert outcome.handoff is not None
    assert outcome.resume is None
    assert outcome.resume_error == "resume_call_failed"


def test_perform_recovery_execution_replays_handoff_summary_into_auto_resume(tmp_path) -> None:
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
        },
        handoff_data={"summary": "resume from saved handoff"},
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
    )

    assert outcome.action == "handoff_and_resume"
    assert outcome.resume_outcome == "same_thread_resume"
    assert client.resume_calls == [
        ("repo-a", "resume_or_new_thread", "resume from saved handoff")
    ]


def test_perform_recovery_execution_same_thread_resume_does_not_commit_lineage(
    tmp_path,
) -> None:
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
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
        },
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
        session_service=session_service,
    )

    assert outcome.action == "handoff_and_resume"
    assert outcome.resume_outcome == "same_thread_resume"
    assert session_service.list_lineage(parent_session_id="session:repo-a") == []
    recovery_records = session_service.list_recovery_transactions(
        parent_session_id="session:repo-a"
    )
    assert [record.status for record in recovery_records] == [
        "started",
        "packet_frozen",
        "completed",
    ]
    assert recovery_records[-1].metadata["resume_outcome"] == "same_thread_resume"


def test_perform_recovery_execution_persists_goal_contract_version_from_handoff(
    tmp_path,
) -> None:
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
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
        },
        handoff_data={"goal_contract_version": "goal-v9"},
        resume_data={
            "resume_outcome": "new_child_session",
            "session_id": "session:repo-a:child-v9",
        },
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
        session_service=session_service,
    )

    assert outcome.action == "handoff_and_resume"

    lineage_records = session_service.list_lineage(parent_session_id="session:repo-a")
    assert len(lineage_records) == 1
    assert lineage_records[0].goal_contract_version == "goal-v9"

    lineage_events = session_service.list_events(event_type="lineage_committed")
    assert len(lineage_events) == 1
    assert lineage_events[0].payload["goal_contract_version"] == "goal-v9"


def test_perform_recovery_execution_preserves_upstream_source_packet_id(
    tmp_path,
) -> None:
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
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
        },
        handoff_data={"source_packet_id": "packet:handoff-v9"},
        resume_data={
            "resume_outcome": "new_child_session",
            "session_id": "session:repo-a:child-v9",
        },
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
        session_service=session_service,
    )

    assert outcome.action == "handoff_and_resume"

    lineage_records = session_service.list_lineage(parent_session_id="session:repo-a")
    assert len(lineage_records) == 1
    assert lineage_records[0].source_packet_id == "packet:handoff-v9"

    frozen_events = session_service.list_events(event_type="handoff_packet_frozen")
    assert len(frozen_events) == 1
    assert frozen_events[0].related_ids["source_packet_id"] == "packet:handoff-v9"

    recovery_records = session_service.list_recovery_transactions(
        parent_session_id="session:repo-a"
    )
    assert recovery_records[-1].source_packet_id == "packet:handoff-v9"


def test_perform_recovery_execution_adopts_goal_contract_for_child_session(
    tmp_path,
) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    goal_contracts = GoalContractService(session_service)
    created = goal_contracts.bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="补 recovery 黄金路径测试",
        task_prompt="先把 recovery 写点找出来，再补最小黄金路径测试",
        last_user_instruction="继续按 recovery 顺序推进",
        phase="implementation",
        last_summary="正在补 recovery 红测",
        explicit_deliverables=["补 recovery/goal contract 接线测试"],
        completion_signals=["相关 pytest 通过"],
    )
    revised = goal_contracts.revise_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        expected_version=created.version,
        current_phase_goal="让 recovery 为 child session 写 adopt truth",
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
        },
        handoff_data={
            "goal_contract_version": revised.version,
            "source_packet_id": "packet:handoff-v9",
        },
        resume_data={
            "resume_outcome": "new_child_session",
            "session_id": "session:repo-a:child-v9",
        },
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
        session_service=session_service,
    )

    assert outcome.action == "handoff_and_resume"

    lineage_records = session_service.list_lineage(parent_session_id="session:repo-a")
    assert len(lineage_records) == 1
    child_session_id = lineage_records[0].child_session_id

    child_contract = goal_contracts.get_current_contract(
        project_id="repo-a",
        session_id=child_session_id,
    )
    assert child_contract is not None
    assert child_contract.version == revised.version
    assert child_contract.current_phase_goal == "让 recovery 为 child session 写 adopt truth"

    adoption_events = session_service.list_events(
        session_id=child_session_id,
        event_type="goal_contract_adopted_by_child_session",
    )
    assert len(adoption_events) == 1
    assert adoption_events[0].related_ids["goal_contract_version"] == revised.version
    assert adoption_events[0].related_ids["source_packet_id"] == "packet:handoff-v9"
    assert adoption_events[0].related_ids["recovery_transaction_id"].startswith("recovery-tx:")


def test_perform_recovery_execution_supersedes_parent_future_workers(tmp_path) -> None:
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    future_workers = FutureWorkerExecutionService(session_service)
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
        },
        handoff_data={"goal_contract_version": "goal-v9"},
        resume_data={
            "resume_outcome": "new_child_session",
            "session_id": "session:repo-a:child-v9",
        },
    )

    future_workers.request_worker(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        worker_task_ref="worker:task-running",
        decision_trace_ref="trace:running",
        goal_contract_version="goal-v9",
        scope="read_only",
        allowed_hands=["codex"],
        input_packet_refs=["packet:running"],
        retrieval_handles=["handle:running"],
        distilled_summary_ref="summary:running",
        execution_budget_ref="budget:running",
        occurred_at="2026-04-14T05:00:00Z",
    )
    future_workers.record_started(
        worker_task_ref="worker:task-running",
        project_id="repo-a",
        parent_session_id="session:repo-a",
        occurred_at="2026-04-14T05:01:00Z",
        worker_runtime_contract={"provider": "codex", "model": "gpt-5.4"},
    )
    future_workers.request_worker(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        worker_task_ref="worker:task-completed",
        decision_trace_ref="trace:completed",
        goal_contract_version="goal-v9",
        scope="read_only",
        allowed_hands=["codex"],
        input_packet_refs=["packet:completed"],
        retrieval_handles=["handle:completed"],
        distilled_summary_ref="summary:completed",
        execution_budget_ref="budget:completed",
        occurred_at="2026-04-14T05:02:00Z",
    )
    future_workers.record_started(
        worker_task_ref="worker:task-completed",
        project_id="repo-a",
        parent_session_id="session:repo-a",
        occurred_at="2026-04-14T05:03:00Z",
        worker_runtime_contract={"provider": "codex", "model": "gpt-5.4"},
    )
    future_workers.record_completed(
        worker_task_ref="worker:task-completed",
        project_id="repo-a",
        parent_session_id="session:repo-a",
        result_summary_ref="summary:worker:completed",
        artifact_refs=["artifact:completed"],
        input_contract_hash="sha256:input-completed",
        result_hash="sha256:result-completed",
        occurred_at="2026-04-14T05:04:00Z",
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
        session_service=session_service,
    )

    assert outcome.action == "handoff_and_resume"

    cancelled_events = session_service.list_events(
        session_id="session:repo-a",
        event_type="future_worker_cancelled",
    )
    rejected_events = session_service.list_events(
        session_id="session:repo-a",
        event_type="future_worker_result_rejected",
    )

    assert len(cancelled_events) == 1
    assert cancelled_events[0].related_ids["worker_task_ref"] == "worker:task-running"
    assert cancelled_events[0].payload["reason"] == "recovery_superseded_by_child_session"
    assert len(rejected_events) == 1
    assert rejected_events[0].related_ids["worker_task_ref"] == "worker:task-completed"
    assert rejected_events[0].payload["reason"] == "recovery_superseded_by_child_session"
