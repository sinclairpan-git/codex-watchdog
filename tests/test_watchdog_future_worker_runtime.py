from __future__ import annotations

from pathlib import Path

import pytest

from watchdog.services.session_service.models import CONTROLLED_SESSION_EVENT_TYPES
from watchdog.services.session_service.service import SessionService
from watchdog.services.session_service.store import SessionServiceStore


def test_session_service_registers_future_worker_lifecycle_event_types() -> None:
    expected = {
        "future_worker_requested",
        "future_worker_started",
        "future_worker_heartbeat",
        "future_worker_summary_published",
        "future_worker_completed",
        "future_worker_failed",
        "future_worker_cancelled",
        "future_worker_transition_rejected",
        "future_worker_result_consumed",
        "future_worker_result_rejected",
    }

    missing = expected.difference(CONTROLLED_SESSION_EVENT_TYPES)

    assert missing == set()


def test_session_service_persists_future_worker_lifecycle_events(tmp_path: Path) -> None:
    service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))

    service.record_event(
        event_type="future_worker_requested",
        project_id="repo-a",
        session_id="session:repo-a",
        occurred_at="2026-04-14T03:00:00Z",
        correlation_id="corr:worker:task-1",
        related_ids={
            "worker_task_ref": "worker:task-1",
            "decision_trace_ref": "trace:1",
        },
        payload={
            "scope": "read_only",
            "goal_contract_version": "goal-contract:v1",
            "execution_budget_ref": "budget:worker:1",
        },
    )
    service.record_event(
        event_type="future_worker_started",
        project_id="repo-a",
        session_id="session:repo-a",
        occurred_at="2026-04-14T03:01:00Z",
        correlation_id="corr:worker:task-1",
        related_ids={"worker_task_ref": "worker:task-1"},
        payload={"worker_runtime_contract": {"provider": "codex", "model": "gpt-5.4"}},
    )
    service.record_event(
        event_type="future_worker_result_rejected",
        project_id="repo-a",
        session_id="session:repo-a",
        occurred_at="2026-04-14T03:02:00Z",
        correlation_id="corr:worker:task-1",
        related_ids={"worker_task_ref": "worker:task-1"},
        payload={"reason": "late_result"},
    )

    events = service.list_events(session_id="session:repo-a")

    assert [event.event_type for event in events] == [
        "future_worker_requested",
        "future_worker_started",
        "future_worker_result_rejected",
    ]
    assert events[-1].payload["reason"] == "late_result"


def test_future_worker_service_emits_heartbeat_failed_and_cancelled_events(tmp_path: Path) -> None:
    from watchdog.main import create_app
    from watchdog.settings import Settings

    app = create_app(
        Settings(
            api_token="watchdog-token",
            a_agent_token="a-agent-token",
            a_agent_base_url="http://a-control.test",
            data_dir=str(tmp_path),
        ),
        start_background_workers=False,
    )

    service = app.state.future_worker_service
    service.request_worker(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        worker_task_ref="worker:task-2",
        decision_trace_ref="trace:2",
        goal_contract_version="goal-contract:v1",
        scope="read_only",
        allowed_hands=["codex"],
        input_packet_refs=["packet:2"],
        retrieval_handles=["handle:2"],
        distilled_summary_ref="summary:2",
        execution_budget_ref="budget:2",
        occurred_at="2026-04-14T03:59:00Z",
    )
    service.request_worker(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        worker_task_ref="worker:task-3",
        decision_trace_ref="trace:3",
        goal_contract_version="goal-contract:v1",
        scope="read_only",
        allowed_hands=["codex"],
        input_packet_refs=["packet:3"],
        retrieval_handles=["handle:3"],
        distilled_summary_ref="summary:3",
        execution_budget_ref="budget:3",
        occurred_at="2026-04-14T03:59:30Z",
    )
    service.record_heartbeat(
        worker_task_ref="worker:task-2",
        project_id="repo-a",
        parent_session_id="session:repo-a",
        occurred_at="2026-04-14T04:00:00Z",
        heartbeat={"progress": "indexing", "stuck_level": 0},
    )
    service.record_failed(
        worker_task_ref="worker:task-2",
        project_id="repo-a",
        parent_session_id="session:repo-a",
        occurred_at="2026-04-14T04:01:00Z",
        reason="runtime_error",
    )
    service.record_cancelled(
        worker_task_ref="worker:task-3",
        project_id="repo-a",
        parent_session_id="session:repo-a",
        occurred_at="2026-04-14T04:02:00Z",
        reason="superseded_by_new_worker",
    )

    events = app.state.session_service.list_events(session_id="session:repo-a")

    assert [event.event_type for event in events] == [
        "future_worker_requested",
        "future_worker_requested",
        "future_worker_heartbeat",
        "future_worker_failed",
        "future_worker_cancelled",
    ]
    assert events[2].related_ids["decision_trace_ref"] == "trace:2"
    assert events[2].payload["heartbeat"]["progress"] == "indexing"
    assert events[3].related_ids["decision_trace_ref"] == "trace:2"
    assert events[3].payload["reason"] == "runtime_error"
    assert events[4].related_ids["decision_trace_ref"] == "trace:3"
    assert events[4].payload["reason"] == "superseded_by_new_worker"


def test_future_worker_service_carries_parent_native_thread_id_across_lifecycle_events(
    tmp_path: Path,
) -> None:
    from watchdog.main import create_app
    from watchdog.settings import Settings

    app = create_app(
        Settings(
            api_token="watchdog-token",
            a_agent_token="a-agent-token",
            a_agent_base_url="http://a-control.test",
            data_dir=str(tmp_path),
        ),
        start_background_workers=False,
    )

    service = app.state.future_worker_service
    service.request_worker(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        parent_native_thread_id="thr_native_1",
        worker_task_ref="worker:task-native",
        decision_trace_ref="trace:native",
        goal_contract_version="goal-contract:v1",
        scope="read_only",
        allowed_hands=["codex"],
        input_packet_refs=["packet:native"],
        retrieval_handles=["handle:native"],
        distilled_summary_ref="summary:native",
        execution_budget_ref="budget:native",
        occurred_at="2026-04-14T05:00:00Z",
    )
    service.record_started(
        worker_task_ref="worker:task-native",
        project_id="repo-a",
        parent_session_id="session:repo-a",
        occurred_at="2026-04-14T05:01:00Z",
        worker_runtime_contract={"provider": "codex", "model": "gpt-5.4"},
    )
    service.record_completed(
        worker_task_ref="worker:task-native",
        project_id="repo-a",
        parent_session_id="session:repo-a",
        result_summary_ref="summary:worker:native",
        artifact_refs=["artifact:patch:native"],
        input_contract_hash="sha256:input-contract-native",
        result_hash="sha256:result-native",
        occurred_at="2026-04-14T05:02:00Z",
    )

    events = [
        event
        for event in app.state.session_service.list_events(session_id="session:repo-a")
        if event.related_ids.get("worker_task_ref") == "worker:task-native"
    ]

    assert [event.event_type for event in events] == [
        "future_worker_requested",
        "future_worker_started",
        "future_worker_completed",
    ]
    assert events[0].related_ids["parent_native_thread_id"] == "thr_native_1"
    assert events[0].payload["parent_native_thread_id"] == "thr_native_1"
    assert events[1].related_ids["parent_native_thread_id"] == "thr_native_1"
    assert events[2].related_ids["parent_native_thread_id"] == "thr_native_1"


def test_future_worker_service_rejects_lifecycle_without_request_context(tmp_path: Path) -> None:
    from watchdog.main import create_app
    from watchdog.settings import Settings

    app = create_app(
        Settings(
            api_token="watchdog-token",
            a_agent_token="a-agent-token",
            a_agent_base_url="http://a-control.test",
            data_dir=str(tmp_path),
        ),
        start_background_workers=False,
    )

    with pytest.raises(ValueError, match="unknown future worker request"):
        app.state.future_worker_service.record_started(
            worker_task_ref="worker:task-orphan",
            project_id="repo-a",
            parent_session_id="session:repo-a",
            occurred_at="2026-04-14T04:10:00Z",
        )


def test_future_worker_completed_event_reuses_frozen_trace_and_runtime_contract(
    tmp_path: Path,
) -> None:
    from watchdog.main import create_app
    from watchdog.settings import Settings

    app = create_app(
        Settings(
            api_token="watchdog-token",
            a_agent_token="a-agent-token",
            a_agent_base_url="http://a-control.test",
            data_dir=str(tmp_path),
        ),
        start_background_workers=False,
    )

    service = app.state.future_worker_service
    service.request_worker(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        worker_task_ref="worker:task-4",
        decision_trace_ref="trace:4",
        goal_contract_version="goal-contract:v1",
        scope="read_only",
        allowed_hands=["codex"],
        input_packet_refs=["packet:4"],
        retrieval_handles=["handle:4"],
        distilled_summary_ref="summary:4",
        execution_budget_ref="budget:4",
        occurred_at="2026-04-14T04:20:00Z",
    )
    service.record_started(
        worker_task_ref="worker:task-4",
        project_id="repo-a",
        parent_session_id="session:repo-a",
        occurred_at="2026-04-14T04:21:00Z",
        worker_runtime_contract={"provider": "codex", "model": "gpt-5.4"},
    )
    service.record_completed(
        worker_task_ref="worker:task-4",
        project_id="repo-a",
        parent_session_id="session:repo-a",
        result_summary_ref="summary:worker:4",
        artifact_refs=["artifact:patch:4"],
        input_contract_hash="sha256:input-contract-4",
        result_hash="sha256:result-4",
        occurred_at="2026-04-14T04:22:00Z",
    )

    completed = [
        event
        for event in app.state.session_service.list_events(session_id="session:repo-a")
        if event.event_type == "future_worker_completed"
    ]

    assert len(completed) == 1
    assert completed[0].payload["decision_trace_ref"] == "trace:4"
    assert completed[0].payload["worker_runtime_contract"] == {
        "provider": "codex",
        "model": "gpt-5.4",
    }


def test_future_worker_service_rejects_consume_before_completed(tmp_path: Path) -> None:
    from watchdog.main import create_app
    from watchdog.settings import Settings

    app = create_app(
        Settings(
            api_token="watchdog-token",
            a_agent_token="a-agent-token",
            a_agent_base_url="http://a-control.test",
            data_dir=str(tmp_path),
        ),
        start_background_workers=False,
    )

    service = app.state.future_worker_service
    service.request_worker(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        worker_task_ref="worker:task-5",
        decision_trace_ref="trace:5",
        goal_contract_version="goal-contract:v1",
        scope="read_only",
        allowed_hands=["codex"],
        input_packet_refs=["packet:5"],
        retrieval_handles=["handle:5"],
        distilled_summary_ref="summary:5",
        execution_budget_ref="budget:5",
        occurred_at="2026-04-14T04:30:00Z",
    )
    service.record_started(
        worker_task_ref="worker:task-5",
        project_id="repo-a",
        parent_session_id="session:repo-a",
        occurred_at="2026-04-14T04:31:00Z",
        worker_runtime_contract={"provider": "codex", "model": "gpt-5.4"},
    )

    with pytest.raises(ValueError, match="missing future worker completed event"):
        service.consume_result(
            worker_task_ref="worker:task-5",
            project_id="repo-a",
            parent_session_id="session:repo-a",
            consumed_by_decision_id="decision:5",
            occurred_at="2026-04-14T04:32:00Z",
        )


@pytest.mark.parametrize(
    ("terminal_event", "terminal_reason", "terminal_at", "expected_status"),
    [
        ("failed", "runtime_error", "2026-04-14T04:42:00Z", "failed"),
        ("cancelled", "superseded_by_new_worker", "2026-04-14T04:43:00Z", "cancelled"),
    ],
)
def test_future_worker_service_rejects_completion_after_terminal_state(
    tmp_path: Path,
    terminal_event: str,
    terminal_reason: str,
    terminal_at: str,
    expected_status: str,
) -> None:
    from watchdog.main import create_app
    from watchdog.settings import Settings

    app = create_app(
        Settings(
            api_token="watchdog-token",
            a_agent_token="a-agent-token",
            a_agent_base_url="http://a-control.test",
            data_dir=str(tmp_path),
        ),
        start_background_workers=False,
    )

    service = app.state.future_worker_service
    service.request_worker(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        worker_task_ref="worker:task-6",
        decision_trace_ref="trace:6",
        goal_contract_version="goal-contract:v1",
        scope="read_only",
        allowed_hands=["codex"],
        input_packet_refs=["packet:6"],
        retrieval_handles=["handle:6"],
        distilled_summary_ref="summary:6",
        execution_budget_ref="budget:6",
        occurred_at="2026-04-14T04:40:00Z",
    )
    service.record_started(
        worker_task_ref="worker:task-6",
        project_id="repo-a",
        parent_session_id="session:repo-a",
        occurred_at="2026-04-14T04:41:00Z",
        worker_runtime_contract={"provider": "codex", "model": "gpt-5.4"},
    )
    if terminal_event == "failed":
        service.record_failed(
            worker_task_ref="worker:task-6",
            project_id="repo-a",
            parent_session_id="session:repo-a",
            occurred_at=terminal_at,
            reason=terminal_reason,
        )
    else:
        service.record_cancelled(
            worker_task_ref="worker:task-6",
            project_id="repo-a",
            parent_session_id="session:repo-a",
            occurred_at=terminal_at,
            reason=terminal_reason,
        )

    with pytest.raises(
        ValueError,
        match=f"terminal future worker state: {expected_status}",
    ):
        service.record_completed(
            worker_task_ref="worker:task-6",
            project_id="repo-a",
            parent_session_id="session:repo-a",
            result_summary_ref="summary:worker:6",
            artifact_refs=["artifact:patch:6"],
            input_contract_hash="sha256:input-contract-6",
            result_hash="sha256:result-6",
            occurred_at="2026-04-14T04:44:00Z",
        )


def test_future_worker_service_audits_duplicate_start_and_completion_attempts(
    tmp_path: Path,
) -> None:
    from watchdog.main import create_app
    from watchdog.settings import Settings

    app = create_app(
        Settings(
            api_token="watchdog-token",
            a_agent_token="a-agent-token",
            a_agent_base_url="http://a-control.test",
            data_dir=str(tmp_path),
        ),
        start_background_workers=False,
    )

    service = app.state.future_worker_service
    service.request_worker(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        worker_task_ref="worker:task-7",
        decision_trace_ref="trace:7",
        goal_contract_version="goal-contract:v1",
        scope="read_only",
        allowed_hands=["codex"],
        input_packet_refs=["packet:7"],
        retrieval_handles=["handle:7"],
        distilled_summary_ref="summary:7",
        execution_budget_ref="budget:7",
        occurred_at="2026-04-14T04:50:00Z",
    )
    service.record_started(
        worker_task_ref="worker:task-7",
        project_id="repo-a",
        parent_session_id="session:repo-a",
        occurred_at="2026-04-14T04:51:00Z",
        worker_runtime_contract={"provider": "codex", "model": "gpt-5.4"},
    )

    with pytest.raises(ValueError, match="invalid future worker transition: running -> running"):
        service.record_started(
            worker_task_ref="worker:task-7",
            project_id="repo-a",
            parent_session_id="session:repo-a",
            occurred_at="2026-04-14T04:52:00Z",
            worker_runtime_contract={"provider": "codex", "model": "gpt-5.4"},
        )

    service.record_completed(
        worker_task_ref="worker:task-7",
        project_id="repo-a",
        parent_session_id="session:repo-a",
        result_summary_ref="summary:worker:7",
        artifact_refs=["artifact:patch:7"],
        input_contract_hash="sha256:input-contract-7",
        result_hash="sha256:result-7",
        occurred_at="2026-04-14T04:53:00Z",
    )

    with pytest.raises(ValueError, match="invalid future worker transition: completed -> completed"):
        service.record_completed(
            worker_task_ref="worker:task-7",
            project_id="repo-a",
            parent_session_id="session:repo-a",
            result_summary_ref="summary:worker:7-dup",
            artifact_refs=["artifact:patch:7-dup"],
            input_contract_hash="sha256:input-contract-7-dup",
            result_hash="sha256:result-7-dup",
            occurred_at="2026-04-14T04:54:00Z",
        )

    transition_rejections = [
        event
        for event in app.state.session_service.list_events(session_id="session:repo-a")
        if event.event_type == "future_worker_transition_rejected"
    ]

    assert len(transition_rejections) == 2
    assert transition_rejections[0].related_ids["decision_trace_ref"] == "trace:7"
    assert transition_rejections[0].payload["attempted_event_type"] == "future_worker_started"
    assert transition_rejections[0].payload["reason"] == "invalid_transition:running->running"
    assert transition_rejections[1].related_ids["decision_trace_ref"] == "trace:7"
    assert transition_rejections[1].payload["attempted_event_type"] == "future_worker_completed"
    assert transition_rejections[1].payload["reason"] == "invalid_transition:completed->completed"
