from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from watchdog.main import create_app
from watchdog.services.brain.models import DecisionTrace
from watchdog.services.future_worker.models import FutureWorkerExecutionRequest
from watchdog.settings import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        api_token="watchdog-token",
        codex_runtime_token="a-agent-token",
        codex_runtime_base_url="http://a-control.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )


class _ResidentAClient:
    def __init__(self, *, task: dict[str, object]) -> None:
        self._task = dict(task)

    def list_tasks(self) -> list[dict[str, object]]:
        return [dict(self._task)]

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
        _ = (status, project_id, decided_by, callback_status)
        return []


def _worker_trace() -> DecisionTrace:
    return DecisionTrace(
        trace_id="trace:e2e-worker",
        session_event_cursor="cursor:e2e-worker",
        goal_contract_version="goal:v1",
        policy_ruleset_hash="sha256:policy-worker",
        memory_packet_input_ids=["packet:e2e-worker"],
        memory_packet_input_hashes=["sha256:packet-e2e-worker"],
        provider="provider-a",
        model="model-a",
        prompt_schema_ref="prompt:v1",
        output_schema_ref="schema:v1",
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
    assert events[1].related_ids["decision_trace_ref"] == "trace:1"
    assert events[2].related_ids["decision_trace_ref"] == "trace:1"
    assert events[3].payload["decision_trace_ref"] == "trace:1"
    assert events[3].payload["worker_runtime_contract"] == {
        "provider": "codex",
        "model": "gpt-5.4",
    }
    assert events[-1].related_ids["worker_task_ref"] == "worker:task-1"
    assert events[-1].related_ids["decision_id"] == "decision:2"
    assert events[-1].related_ids["decision_trace_ref"] == "trace:1"


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
    assert events[1].related_ids["decision_trace_ref"] == "trace:late"
    assert events[-2].related_ids["decision_trace_ref"] == "trace:late"
    assert events[-2].payload["reason"] == "late_result"
    assert events[-1].related_ids["decision_trace_ref"] == "trace:late"
    assert events[-1].payload["reason"] == "terminal_state:rejected"


def test_resident_orchestrator_materializes_and_consumes_future_worker_chain(
    tmp_path: Path,
) -> None:
    app = create_app(
        _settings(tmp_path),
        runtime_client=_ResidentAClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "still stuck",
                "files_touched": ["src/example.py"],
                "context_pressure": "low",
                "stuck_level": 2,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T05:20:00Z",
            }
        ),
        start_background_workers=False,
    )
    app.state.session_spine_runtime.refresh_all()

    trace = _worker_trace()
    request = FutureWorkerExecutionRequest(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        worker_task_ref="worker:e2e-chain",
        decision_trace_ref=trace.trace_id,
        goal_contract_version=trace.goal_contract_version,
        scope="read_only",
        allowed_hands=["codex"],
        input_packet_refs=["packet:e2e-chain"],
        retrieval_handles=["handle:e2e-chain"],
        distilled_summary_ref="summary:e2e-chain",
        execution_budget_ref="budget:e2e-chain",
    )

    patched_evidence = {
        "brain_rationale": "materialize_and_consume_worker_chain",
        "decision_trace": trace.model_dump(mode="json"),
        "validator_verdict": {"status": "pass", "reason": "schema_and_risk_ok"},
        "release_gate_verdict": {
            "status": "pass",
            "decision_trace_ref": trace.trace_id,
            "approval_read_ref": "approval:none",
            "report_id": "report:e2e-worker",
            "report_hash": "sha256:e2e-worker",
            "input_hash": "sha256:e2e-worker-input",
        },
        "release_gate_evidence_bundle": {
            "certification_packet_corpus": {
                "artifact_ref": "artifacts/certification-packets.jsonl"
            },
            "shadow_decision_ledger": {
                "artifact_ref": "artifacts/shadow-ledger.jsonl"
            },
            "release_gate_report_ref": "artifacts/release-gate-report.json",
            "label_manifest_ref": "tests/fixtures/release_gate_label_manifest.json",
            "generated_by": "codex",
            "report_approved_by": "operator-a",
            "report_id": "report:e2e-worker",
            "report_hash": "sha256:e2e-worker",
            "input_hash": "sha256:e2e-worker-input",
        },
        "future_worker_requests": [request.model_dump(mode="json")],
    }

    with patch.object(
        app.state.resident_orchestrator,
        "_decision_evidence_for_intent",
        return_value=patched_evidence,
    ):
        with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
            steer_mock.return_value = {"success": True, "data": {"accepted": True}}
            app.state.resident_orchestrator.orchestrate_all(
                now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
            )

        app.state.future_worker_service.record_started(
            worker_task_ref="worker:e2e-chain",
            project_id="repo-a",
            parent_session_id="session:repo-a",
            occurred_at="2026-04-14T07:01:00Z",
            worker_runtime_contract={"provider": "codex", "model": "gpt-5.4"},
        )
        app.state.future_worker_service.record_summary_published(
            worker_task_ref="worker:e2e-chain",
            project_id="repo-a",
            parent_session_id="session:repo-a",
            summary_ref="summary:worker:e2e-chain",
            occurred_at="2026-04-14T07:02:00Z",
        )
        app.state.future_worker_service.record_completed(
            worker_task_ref="worker:e2e-chain",
            project_id="repo-a",
            parent_session_id="session:repo-a",
            result_summary_ref="summary:worker:e2e-chain",
            artifact_refs=["artifact:e2e-chain"],
            input_contract_hash="sha256:e2e-chain-input",
            result_hash="sha256:e2e-chain-result",
            occurred_at="2026-04-14T07:03:00Z",
        )

        app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 1, tzinfo=UTC)
        )

    decisions = app.state.policy_decision_store.list_records()
    assert len(decisions) == 1
    events = [
        event
        for event in app.state.session_service.list_events(session_id="session:repo-a")
        if event.related_ids.get("worker_task_ref") == "worker:e2e-chain"
    ]

    assert [event.event_type for event in events] == [
        "future_worker_requested",
        "future_worker_started",
        "future_worker_summary_published",
        "future_worker_completed",
        "future_worker_result_consumed",
    ]
    assert events[0].payload["execution_budget_ref"] == "budget:e2e-chain"
    assert events[-1].related_ids["decision_id"] == decisions[0].decision_id
    assert events[-1].related_ids["decision_trace_ref"] == trace.trace_id
