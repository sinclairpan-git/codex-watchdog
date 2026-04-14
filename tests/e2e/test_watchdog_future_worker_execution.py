from __future__ import annotations

from pathlib import Path

import pytest

from watchdog.main import create_app
from watchdog.settings import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        api_token="watchdog-token",
        a_agent_token="a-agent-token",
        a_agent_base_url="http://a-control.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )


def test_future_worker_service_writes_requested_to_consumed_canonical_chain(
    tmp_path: Path,
) -> None:
    app = create_app(_settings(tmp_path), start_background_workers=False)

    service = app.state.future_worker_service
    service.request_worker(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        worker_task_ref="worker:task-1",
        decision_trace_ref="trace:1",
        goal_contract_version="goal-contract:v1",
        scope="read_only",
        allowed_hands=["codex"],
        input_packet_refs=["packet:1"],
        retrieval_handles=["handle:1"],
        distilled_summary_ref="summary:1",
        execution_budget_ref="budget:1",
        occurred_at="2026-04-14T03:00:00Z",
    )
    service.record_started(
        worker_task_ref="worker:task-1",
        project_id="repo-a",
        parent_session_id="session:repo-a",
        occurred_at="2026-04-14T03:01:00Z",
        worker_runtime_contract={"provider": "codex", "model": "gpt-5.4"},
    )
    service.record_summary_published(
        worker_task_ref="worker:task-1",
        project_id="repo-a",
        parent_session_id="session:repo-a",
        summary_ref="summary:worker:1",
        occurred_at="2026-04-14T03:02:00Z",
    )
    service.record_completed(
        worker_task_ref="worker:task-1",
        project_id="repo-a",
        parent_session_id="session:repo-a",
        result_summary_ref="summary:worker:1",
        artifact_refs=["artifact:patch:1"],
        input_contract_hash="sha256:input-contract",
        result_hash="sha256:result",
        occurred_at="2026-04-14T03:03:00Z",
    )
    service.consume_result(
        worker_task_ref="worker:task-1",
        project_id="repo-a",
        parent_session_id="session:repo-a",
        consumed_by_decision_id="decision:2",
        occurred_at="2026-04-14T03:04:00Z",
    )

    events = app.state.session_service.list_events(session_id="session:repo-a")

    assert [event.event_type for event in events] == [
        "future_worker_requested",
        "future_worker_started",
        "future_worker_summary_published",
        "future_worker_completed",
        "future_worker_result_consumed",
    ]
    assert events[3].payload["decision_trace_ref"] == "trace:1"
    assert events[3].payload["worker_runtime_contract"] == {
        "provider": "codex",
        "model": "gpt-5.4",
    }
    assert events[-1].related_ids["worker_task_ref"] == "worker:task-1"
    assert events[-1].related_ids["decision_id"] == "decision:2"


def test_future_worker_service_rejects_late_result_before_parent_consume(
    tmp_path: Path,
) -> None:
    app = create_app(_settings(tmp_path), start_background_workers=False)

    service = app.state.future_worker_service
    service.request_worker(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        worker_task_ref="worker:task-late",
        decision_trace_ref="trace:late",
        goal_contract_version="goal-contract:v1",
        scope="read_only",
        allowed_hands=["codex"],
        input_packet_refs=["packet:late"],
        retrieval_handles=["handle:late"],
        distilled_summary_ref="summary:late",
        execution_budget_ref="budget:late",
        occurred_at="2026-04-14T03:10:00Z",
    )
    service.record_started(
        worker_task_ref="worker:task-late",
        project_id="repo-a",
        parent_session_id="session:repo-a",
        occurred_at="2026-04-14T03:11:00Z",
        worker_runtime_contract={"provider": "codex", "model": "gpt-5.4"},
    )
    service.record_completed(
        worker_task_ref="worker:task-late",
        project_id="repo-a",
        parent_session_id="session:repo-a",
        result_summary_ref="summary:worker:late",
        artifact_refs=["artifact:patch:late"],
        input_contract_hash="sha256:input-late",
        result_hash="sha256:result-late",
        occurred_at="2026-04-14T03:12:00Z",
    )
    service.reject_result(
        worker_task_ref="worker:task-late",
        project_id="repo-a",
        parent_session_id="session:repo-a",
        reason="late_result",
        occurred_at="2026-04-14T03:13:00Z",
    )

    with pytest.raises(ValueError, match="terminal future worker state: rejected"):
        service.consume_result(
            worker_task_ref="worker:task-late",
            project_id="repo-a",
            parent_session_id="session:repo-a",
            consumed_by_decision_id="decision:late",
            occurred_at="2026-04-14T03:14:00Z",
        )

    events = app.state.session_service.list_events(session_id="session:repo-a")

    assert [event.event_type for event in events] == [
        "future_worker_requested",
        "future_worker_started",
        "future_worker_completed",
        "future_worker_result_rejected",
        "future_worker_transition_rejected",
    ]
    assert events[-2].payload["reason"] == "late_result"
    assert events[-1].payload["reason"] == "terminal_state:rejected"
