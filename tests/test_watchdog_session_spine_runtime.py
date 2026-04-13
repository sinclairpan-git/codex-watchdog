from __future__ import annotations

import asyncio
import json
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from watchdog.main import _run_delivery_loop, create_app
from watchdog.contracts.session_spine.enums import ActionStatus, Effect, ReplyCode
from watchdog.contracts.session_spine.models import WatchdogActionResult
from watchdog.services.brain.models import DecisionIntent
from watchdog.services.approvals.service import materialize_canonical_approval
from watchdog.services.delivery.http_client import DeliveryAttemptResult
from watchdog.services.goal_contract.service import GoalContractService
from watchdog.services.policy.decisions import (
    CanonicalDecisionRecord,
    build_canonical_decision_record,
)
from watchdog.services.policy.engine import evaluate_persisted_session_policy
from watchdog.services.session_spine.orchestrator import _parse_iso
from watchdog.services.session_spine.service import build_approval_inbox_bundle, build_session_read_bundle
from watchdog.settings import Settings


SESSION_SPINE_STORE_FILENAME = "session_spine.json"


class FakeResidentAClient:
    def __init__(
        self,
        *,
        task: dict[str, object],
        approvals: list[dict[str, object]] | None = None,
    ) -> None:
        self._task = dict(task)
        self._approvals = [dict(approval) for approval in approvals or []]

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
        _ = (decided_by, callback_status)
        rows = [dict(approval) for approval in self._approvals]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if project_id:
            rows = [row for row in rows if row.get("project_id") == project_id]
        return rows


class CyclingResidentAClient(FakeResidentAClient):
    def __init__(self, *, tasks: list[dict[str, object]]) -> None:
        super().__init__(task=tasks[0])
        self._tasks = [dict(task) for task in tasks]
        self._calls = 0

    def list_tasks(self) -> list[dict[str, object]]:
        idx = min(self._calls, len(self._tasks) - 1)
        self._calls += 1
        return [dict(self._tasks[idx])]

    def get_envelope(self, project_id: str) -> dict[str, object]:
        tasks = self.list_tasks()
        assert len(tasks) == 1
        task = tasks[0]
        assert project_id == task["project_id"]
        return {"success": True, "data": dict(task)}

    def trigger_handoff(self, project_id: str, *, reason: str) -> dict[str, object]:
        raise AssertionError("trigger_handoff should not be called in this fixture")

    def trigger_resume(
        self,
        project_id: str,
        *,
        mode: str,
        handoff_summary: str,
    ) -> dict[str, object]:
        raise AssertionError("trigger_resume should not be called in this fixture")


class RecoveringResidentAClient(FakeResidentAClient):
    def __init__(self, *, task: dict[str, object]) -> None:
        super().__init__(task=task)
        self.handoff_calls: list[tuple[str, str]] = []
        self.resume_calls: list[tuple[str, str, str]] = []

    def trigger_handoff(self, project_id: str, *, reason: str) -> dict[str, object]:
        self.handoff_calls.append((project_id, reason))
        return {
            "success": True,
            "data": {"handoff_file": f"/tmp/{project_id}.handoff.md", "summary": "handoff"},
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


def _runtime_gate_pass_kwargs() -> dict[str, dict[str, object]]:
    return {
        "validator_verdict": {
            "status": "pass",
            "reason": "schema_and_risk_ok",
        },
        "release_gate_verdict": {
            "status": "pass",
            "decision_trace_ref": "trace:seed",
            "approval_read_ref": "approval:none",
            "report_id": "report-seed",
            "report_hash": "sha256:report-seed",
            "input_hash": "sha256:input-seed",
        },
    }


class RecordingDeliveryClient:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def deliver_record(self, record) -> DeliveryAttemptResult:
        self.records.append(dict(record.envelope_payload))
        return DeliveryAttemptResult(
            envelope_id=record.envelope_id,
            delivery_status="delivered",
            accepted=True,
            receipt_id=f"rcpt:{record.envelope_id}",
        )


class FlakyRuntime:
    def __init__(self, delegate) -> None:
        self._delegate = delegate
        self.calls = 0

    def refresh_all(self) -> None:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transient runtime failure")
        self._delegate.refresh_all()


class FlakyOrchestrator:
    def __init__(self, delegate) -> None:
        self._delegate = delegate
        self.calls = 0

    def orchestrate_all(self, *, now):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transient orchestrator failure")
        return self._delegate.orchestrate_all(now=now)


class FlakyDeliveryWorker:
    def __init__(self, delegate) -> None:
        self._delegate = delegate
        self.calls = 0

    def process_next_ready(self, *, now, session_id=None):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transient delivery failure")
        return self._delegate.process_next_ready(now=now, session_id=session_id)


class StaticBrainService:
    def __init__(self, *, intent: str, rationale: str = "test override") -> None:
        self.intent = intent
        self.rationale = rationale

    def evaluate_session(self, **kwargs) -> DecisionIntent:
        _ = kwargs
        return DecisionIntent(intent=self.intent, rationale=self.rationale)


def _store_path(root: Path) -> Path:
    return root / SESSION_SPINE_STORE_FILENAME


def _read_store(root: Path) -> dict[str, object]:
    return json.loads(_store_path(root).read_text(encoding="utf-8"))


def test_background_runtime_persists_session_spine_and_keeps_fact_snapshot_version_stable(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
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
            "last_progress_at": "2099-01-01T00:00:00Z",
        }
    )

    with TestClient(create_app(settings, a_client=a_client, start_background_workers=True)):
        pass

    first_store_path = _store_path(tmp_path)
    assert first_store_path.exists()
    first_snapshot = _read_store(tmp_path)
    first_version = first_snapshot["sessions"]["repo-a"]["fact_snapshot_version"]
    assert first_version
    assert first_snapshot["sessions"]["repo-a"]["session"]["thread_id"] == "session:repo-a"

    with TestClient(create_app(settings, a_client=a_client, start_background_workers=True)):
        pass

    second_snapshot = _read_store(tmp_path)
    assert second_snapshot["sessions"]["repo-a"]["fact_snapshot_version"] == first_version


def test_background_runtime_refreshes_session_spine_periodically_and_advances_session_seq(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
        session_spine_refresh_interval_seconds=0.01,
    )
    a_client = CyclingResidentAClient(
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
                "last_progress_at": "2099-01-01T00:00:00Z",
            },
            {
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
                "last_progress_at": "2099-01-01T00:01:00Z",
            },
        ]
    )
    a_client._approvals = [
        {
            "approval_id": "appr_001",
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "risk_level": "L2",
            "command": "uv run pytest",
            "reason": "verify tests",
            "alternative": "",
            "status": "pending",
            "requested_at": "2099-01-01T00:01:30Z",
        }
    ]

    with TestClient(create_app(settings, a_client=a_client, start_background_workers=True)):
        first_snapshot = _read_store(tmp_path)
        first_seq = int(first_snapshot["sessions"]["repo-a"]["session_seq"])
        assert first_seq >= 1

        refreshed_snapshot = first_snapshot
        for _ in range(5):
            time.sleep(0.01)
            refreshed_snapshot = _read_store(tmp_path)
            if int(refreshed_snapshot["sessions"]["repo-a"]["session_seq"]) > first_seq:
                break

    if first_snapshot["sessions"]["repo-a"]["session"]["session_state"] != "awaiting_approval":
        assert int(refreshed_snapshot["sessions"]["repo-a"]["session_seq"]) > first_seq
    assert refreshed_snapshot["sessions"]["repo-a"]["session"]["session_state"] == "awaiting_approval"
    assert refreshed_snapshot["sessions"]["repo-a"]["progress"]["activity_phase"] == "approval"


def test_resident_orchestrator_skips_phantom_approval_when_only_pending_flag_is_set(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
        progress_summary_max_age_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "waiting_human",
            "phase": "approval",
            "pending_approval": True,
            "last_summary": "waiting for approval",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, a_client=a_client, start_background_workers=False)

    app.state.session_spine_runtime.refresh_all()
    outcomes = app.state.resident_orchestrator.orchestrate_all(
        now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
    )
    snapshot = _read_store(tmp_path)

    assert [outcome.action_ref for outcome in outcomes] == [None]
    assert [outcome.decision_result for outcome in outcomes] == [None]
    assert snapshot["sessions"]["repo-a"]["session"]["session_state"] == "active"
    assert snapshot["sessions"]["repo-a"]["session"]["pending_approval_count"] == 0
    assert snapshot["sessions"]["repo-a"]["facts"] == []
    assert app.state.delivery_outbox_store.list_records() == []


def test_resident_orchestrator_does_not_execute_when_brain_observes_only(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
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
    )
    app = create_app(settings, a_client=a_client, start_background_workers=False)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="observe_only")
    app.state.session_spine_runtime.refresh_all()

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["block_and_alert"]
    decisions = app.state.policy_decision_store.list_records()
    assert len(decisions) == 1
    assert decisions[0].brain_intent == "observe_only"
    outbox = app.state.delivery_outbox_store.list_records()
    assert len(outbox) == 1
    assert outbox[0].envelope_type == "notification"
    assert app.state.canonical_approval_store.list_records() == []
    assert app.state.command_lease_store.list_events() == []
    steer_mock.assert_not_called()


def test_resident_orchestrator_routes_brain_require_approval_to_human_gate(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
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
    )
    app = create_app(settings, a_client=a_client, start_background_workers=False)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="require_approval")
    app.state.session_spine_runtime.refresh_all()

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["require_user_decision"]
    decisions = app.state.policy_decision_store.list_records()
    assert len(decisions) == 1
    assert decisions[0].brain_intent == "require_approval"
    approvals = app.state.canonical_approval_store.list_records()
    assert len(approvals) == 1
    assert approvals[0].requested_action == "continue_session"
    assert app.state.command_lease_store.list_events() == []
    steer_mock.assert_not_called()


def test_resident_orchestrator_routes_brain_propose_recovery_to_human_gate(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "context exhausted",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, a_client=a_client, start_background_workers=False)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="propose_recovery")
    app.state.session_spine_runtime.refresh_all()

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in outcomes] == ["execute_recovery"]
    assert [outcome.decision_result for outcome in outcomes] == ["require_user_decision"]
    decisions = app.state.policy_decision_store.list_records()
    assert len(decisions) == 1
    assert decisions[0].brain_intent == "propose_recovery"
    approvals = app.state.canonical_approval_store.list_records()
    assert len(approvals) == 1
    assert approvals[0].requested_action == "execute_recovery"
    assert app.state.command_lease_store.list_events() == []
    steer_mock.assert_not_called()


def test_resident_orchestrator_routes_brain_suggest_only_to_notification(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
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
    )
    app = create_app(settings, a_client=a_client, start_background_workers=False)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="suggest_only")
    app.state.session_spine_runtime.refresh_all()

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["block_and_alert"]
    decisions = app.state.policy_decision_store.list_records()
    assert len(decisions) == 1
    assert decisions[0].brain_intent == "suggest_only"
    outbox = app.state.delivery_outbox_store.list_records()
    assert len(outbox) == 1
    assert outbox[0].envelope_type == "notification"
    assert app.state.canonical_approval_store.list_records() == []
    assert app.state.command_lease_store.list_events() == []
    steer_mock.assert_not_called()


def test_resident_orchestrator_cooldown_only_suppresses_propose_execute(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=600.0,
    )
    a_client = FakeResidentAClient(
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
    )
    app = create_app(settings, a_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()
    app.state.resident_orchestration_state_store.put_auto_continue_checkpoint(
        project_id="repo-a",
        last_auto_continue_at="2026-04-07T00:00:00Z",
    )

    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="suggest_only")
    suggest_outcomes = app.state.resident_orchestrator.orchestrate_all(
        now=datetime(2026, 4, 7, 0, 5, 0, tzinfo=UTC)
    )

    app.state.policy_decision_store = type(app.state.policy_decision_store)(
        tmp_path / "policy_decisions_2.json"
    )
    app.state.delivery_outbox_store = type(app.state.delivery_outbox_store)(
        tmp_path / "delivery_outbox_2.json"
    )
    app.state.resident_orchestrator._decision_store = app.state.policy_decision_store
    app.state.resident_orchestrator._delivery_outbox_store = app.state.delivery_outbox_store
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="require_approval")
    require_outcomes = app.state.resident_orchestrator.orchestrate_all(
        now=datetime(2026, 4, 7, 0, 5, 0, tzinfo=UTC)
    )

    assert [outcome.action_ref for outcome in suggest_outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in suggest_outcomes] == ["block_and_alert"]
    assert [outcome.action_ref for outcome in require_outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in require_outcomes] == ["require_user_decision"]


def test_resident_orchestrator_routes_done_session_to_candidate_closure_review(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
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
    app = create_app(settings, a_client=a_client, start_background_workers=False)

    app.state.session_spine_runtime.refresh_all()
    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    snapshot = _read_store(tmp_path)
    assert [outcome.action_ref for outcome in outcomes] == ["post_operator_guidance"]
    assert [outcome.decision_result for outcome in outcomes] == ["require_user_decision"]
    assert len(snapshot["sessions"]["repo-a"]["facts"]) == 1
    assert snapshot["sessions"]["repo-a"]["facts"][0]["fact_id"] == "repo-a:task_completed"
    assert snapshot["sessions"]["repo-a"]["facts"][0]["fact_code"] == "task_completed"
    assert snapshot["sessions"]["repo-a"]["facts"][0]["detail"] == (
        "session reached a terminal completed state"
    )
    decisions = app.state.policy_decision_store.list_records()
    assert len(decisions) == 1
    assert decisions[0].brain_intent == "candidate_closure"
    assert decisions[0].runtime_disposition == "require_user_decision"
    assert decisions[0].action_ref == "post_operator_guidance"
    assert "task_completion_candidate" in decisions[0].matched_policy_rules
    approvals = app.state.canonical_approval_store.list_records()
    assert len(approvals) == 1
    assert approvals[0].requested_action == "post_operator_guidance"
    assert steer_mock.call_count == 0


def test_background_runtime_persists_last_local_manual_activity_from_a_side_task(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    app = create_app(
        settings,
        a_client=FakeResidentAClient(
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
                "last_progress_at": "2099-01-01T00:00:00Z",
                "last_local_manual_activity_at": "2026-04-07T00:05:00Z",
            }
        ),
        start_background_workers=False,
    )

    app.state.session_spine_runtime.refresh_all()
    snapshot = _read_store(tmp_path)

    assert snapshot["sessions"]["repo-a"]["last_local_manual_activity_at"] == (
        "2026-04-07T00:05:00Z"
    )


def test_background_runtime_routes_context_critical_session_to_approval_request(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
        recover_auto_resume=True,
        session_spine_refresh_interval_seconds=0.01,
        resident_orchestrator_interval_seconds=0.01,
        progress_summary_interval_seconds=0.0,
    )
    a_client = RecoveringResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "context exhausted",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2099-01-01T00:00:00Z",
        }
    )
    delivery_client = RecordingDeliveryClient()
    app = create_app(settings, a_client=a_client, start_background_workers=True)
    app.state.delivery_worker._delivery_client = delivery_client

    with TestClient(app):
        time.sleep(0.05)

    assert a_client.handoff_calls == []
    assert a_client.resume_calls == []
    assert any(
        record.get("envelope_type") == "approval"
        and record.get("requested_action") == "execute_recovery"
        and record.get("risk_level") == "L2"
        for record in delivery_client.records
    )


def test_resident_orchestrator_supersedes_stale_pending_approval_after_newer_auto_continue(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
        progress_summary_max_age_seconds=0.0,
    )
    a_client = CyclingResidentAClient(
        tasks=[
            {
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "context exhausted",
                "files_touched": ["src/example.py"],
                "context_pressure": "critical",
                "stuck_level": 2,
                "failure_count": 3,
                "last_progress_at": "2026-04-05T05:20:00Z",
            },
            {
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "progress resumed after recovery window",
                "files_touched": ["src/example.py"],
                "context_pressure": "low",
                "stuck_level": 2,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T05:25:00Z",
            },
        ]
    )
    app = create_app(settings, a_client=a_client, start_background_workers=False)

    app.state.session_spine_runtime.refresh_all()
    first = app.state.resident_orchestrator.orchestrate_all(
        now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
    )
    first_approvals = app.state.canonical_approval_store.list_records()

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}
        app.state.session_spine_runtime.refresh_all()
        second = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 1, 0, tzinfo=UTC)
        )

    approvals = app.state.canonical_approval_store.list_records()
    session_bundle = build_session_read_bundle(
        a_client,
        "repo-a",
        store=app.state.session_spine_store,
        approval_store=app.state.canonical_approval_store,
    )
    inbox_bundle = build_approval_inbox_bundle(
        a_client,
        project_id="repo-a",
        store=app.state.session_spine_store,
        approval_store=app.state.canonical_approval_store,
    )

    assert [outcome.action_ref for outcome in first] == ["execute_recovery"]
    assert [outcome.decision_result for outcome in first] == ["require_user_decision"]
    assert len(first_approvals) == 1
    assert first_approvals[0].status == "pending"
    assert [outcome.action_ref for outcome in second] == ["continue_session"]
    assert [outcome.decision_result for outcome in second] == ["auto_execute_and_notify"]
    assert steer_mock.call_count == 1
    assert len(approvals) == 1
    assert approvals[0].requested_action == "execute_recovery"
    assert approvals[0].status == "superseded"
    assert approvals[0].decided_by == "policy-supersede"
    assert any(
        note.startswith("approval_superseded_by_decision ")
        for note in approvals[0].operator_notes
    )
    assert session_bundle.session.session_state == "blocked"
    assert session_bundle.session.pending_approval_count == 0
    assert session_bundle.approvals == []
    assert inbox_bundle.approvals == []
    approval_delivery = app.state.delivery_outbox_store.get_delivery_record(first_approvals[0].envelope_id)
    assert approval_delivery is not None
    assert approval_delivery.delivery_status == "superseded"
    assert any(
        note.startswith("delivery_superseded reason=approval_superseded_by_decision ")
        for note in approval_delivery.operator_notes
    )
    assert [fact.fact_code for fact in session_bundle.facts] == [
        "stuck_no_progress",
        "recovery_available",
    ]


def test_resident_orchestrator_records_command_lease_for_auto_continue(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
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
    )
    app = create_app(settings, a_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["auto_execute_and_notify"]

    decision = app.state.policy_decision_store.list_records()[0]
    command_id = f"command:{decision.decision_id}"
    events = app.state.command_lease_store.list_events(command_id=command_id)
    assert [event.event_type for event in events] == [
        "command_claimed",
        "command_executed",
    ]
    state = app.state.command_lease_store.get_command(command_id)
    assert state is not None
    assert state.status == "executed"
    assert state.claim_seq == 1
    assert state.worker_id == "resident_orchestrator"
    session_events = app.state.session_service.list_events(
        session_id="session:repo-a",
        correlation_id=f"corr:decision:{decision.decision_id}",
    )
    assert [event.event_type for event in session_events] == [
        "decision_proposed",
        "decision_validated",
        "command_created",
    ]
    assert session_events[0].related_ids["decision_id"] == decision.decision_id
    assert session_events[0].payload["brain_intent"] == "propose_execute"
    assert session_events[1].payload["decision_result"] == "auto_execute_and_notify"
    assert session_events[1].payload["brain_intent"] == "propose_execute"
    assert session_events[1].payload["decision_trace"]["trace_id"].startswith("trace:")
    assert session_events[1].payload["validator_verdict"]["status"] == "pass"
    assert session_events[1].payload["release_gate_verdict"]["status"] == "pass"
    assert session_events[1].payload["release_gate_verdict"]["decision_trace_ref"] == (
        session_events[1].payload["decision_trace"]["trace_id"]
    )
    assert session_events[2].related_ids["command_id"] == command_id


def test_resident_orchestrator_requires_human_decision_for_incomplete_goal_contract(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
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
    )
    app = create_app(settings, a_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    GoalContractService(app.state.session_service).bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="Implement watchdog read-side goal contract",
        task_prompt="Implement watchdog read-side goal contract",
        last_user_instruction="Implement watchdog read-side goal contract",
        phase="editing_source",
        last_summary="still stuck",
        explicit_deliverables=[],
        completion_signals=[],
    )

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["require_user_decision"]
    steer_mock.assert_not_called()

    decisions = app.state.policy_decision_store.list_records()
    assert len(decisions) == 1
    assert "goal_contract_readiness_gate" in decisions[0].matched_policy_rules
    assert decisions[0].evidence["goal_contract_readiness"] == {
        "mode": "observe_only",
        "missing_fields": ["explicit_deliverables", "completion_signals"],
    }

    approvals = app.state.canonical_approval_store.list_records()
    assert len(approvals) == 1
    assert approvals[0].requested_action == "continue_session"
    approval_events = app.state.session_service.list_events(
        session_id="session:repo-a",
        event_type="approval_requested",
    )
    assert len(approval_events) == 1
    assert approval_events[0].related_ids["approval_id"] == approvals[0].approval_id
    assert approval_events[0].related_ids["decision_id"] == decisions[0].decision_id


def test_resident_orchestrator_records_release_gate_and_validator_verdict_in_session_events(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
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
    )
    app = create_app(settings, a_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    def _decision_with_gate(*args, **kwargs) -> CanonicalDecisionRecord:
        persisted_record = args[0]
        return build_canonical_decision_record(
            persisted_record=persisted_record,
            decision_result="auto_execute_and_notify",
            brain_intent="propose_execute",
            risk_class="none",
            action_ref="continue_session",
            matched_policy_rules=["registered_action"],
            decision_reason="registered action and complete evidence",
            why_not_escalated="policy_allows_auto_execution",
            why_escalated=None,
            uncertainty_reasons=[],
            policy_version="policy-v1",
            extra_evidence={
                "validator_verdict": {
                    "status": "pass",
                    "reason": "schema_and_risk_ok",
                },
                "release_gate_verdict": {
                    "status": "pass",
                    "decision_trace_ref": "trace:1",
                    "approval_read_ref": "approval:event:1",
                    "report_id": "report-1",
                    "report_hash": "sha256:report",
                    "input_hash": "sha256:input",
                },
            },
        )

    with patch(
        "watchdog.services.session_spine.orchestrator.evaluate_persisted_session_policy",
        side_effect=_decision_with_gate,
    ):
        with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
            steer_mock.return_value = {"success": True, "data": {"accepted": True}}
            app.state.resident_orchestrator.orchestrate_all(
                now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
            )

    decision = app.state.policy_decision_store.list_records()[0]
    session_events = app.state.session_service.list_events(
        session_id="session:repo-a",
        correlation_id=f"corr:decision:{decision.decision_id}",
    )
    assert session_events[0].payload["brain_intent"] == "propose_execute"
    assert session_events[1].payload["validator_verdict"]["status"] == "pass"
    assert session_events[1].payload["release_gate_verdict"]["decision_trace_ref"] == "trace:1"
    assert session_events[1].payload["release_gate_verdict"]["approval_read_ref"] == "approval:event:1"


def test_resident_orchestrator_does_not_execute_when_release_gate_or_validator_do_not_pass(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
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
    )
    app = create_app(settings, a_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    def _decision_with_degraded_gate(*args, **kwargs) -> CanonicalDecisionRecord:
        persisted_record = args[0]
        return build_canonical_decision_record(
            persisted_record=persisted_record,
            decision_result="auto_execute_and_notify",
            brain_intent="propose_execute",
            risk_class="none",
            action_ref="continue_session",
            matched_policy_rules=["registered_action"],
            decision_reason="registered action and complete evidence",
            why_not_escalated="policy_allows_auto_execution",
            why_escalated=None,
            uncertainty_reasons=[],
            policy_version="policy-v1",
            extra_evidence={
                "validator_verdict": {
                    "status": "degraded",
                    "reason": "memory_conflict",
                },
                "release_gate_verdict": {
                    "status": "degraded",
                    "decision_trace_ref": "trace:1",
                    "approval_read_ref": "approval:event:1",
                    "report_id": "report-1",
                    "report_hash": "sha256:report",
                    "input_hash": "sha256:input",
                    "degrade_reason": "approval_stale",
                },
            },
        )

    with patch(
        "watchdog.services.session_spine.orchestrator.evaluate_persisted_session_policy",
        side_effect=_decision_with_degraded_gate,
    ):
        with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
            outcomes = app.state.resident_orchestrator.orchestrate_all(
                now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
            )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["auto_execute_and_notify"]
    assert app.state.command_lease_store.list_events() == []
    steer_mock.assert_not_called()


def test_resident_orchestrator_fails_closed_when_auto_execute_decision_lacks_gate_evidence(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
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
    )
    app = create_app(settings, a_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    with patch.object(
        app.state.resident_orchestrator,
        "_decision_evidence_for_intent",
        return_value={"brain_rationale": "missing_runtime_gate"},
    ):
        with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
            outcomes = app.state.resident_orchestrator.orchestrate_all(
                now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
            )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["block_and_alert"]
    assert app.state.command_lease_store.list_events() == []
    steer_mock.assert_not_called()


def test_resident_orchestrator_fails_closed_when_decision_event_write_fails(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
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
    )
    app = create_app(settings, a_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    original_record_event = app.state.session_service.record_event

    def _failing_record_event(*args, **kwargs):
        if kwargs.get("event_type") == "decision_validated":
            raise RuntimeError("session event write failed")
        return original_record_event(*args, **kwargs)

    app.state.session_service.record_event = _failing_record_event

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        with pytest.raises(RuntimeError, match="session event write failed"):
            app.state.resident_orchestrator.orchestrate_all(
                now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
            )

    assert app.state.policy_decision_store.list_records() == []
    assert app.state.command_lease_store.list_events() == []
    steer_mock.assert_not_called()


def test_resident_orchestrator_skips_auto_execute_when_command_is_already_claimed(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
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
    )
    app = create_app(settings, a_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()
    record = app.state.session_spine_store.get("repo-a")
    assert record is not None
    decision = app.state.policy_decision_store.put(
        evaluate_persisted_session_policy(
            record,
            action_ref="continue_session",
            trigger="resident_orchestrator",
            brain_intent="propose_execute",
            **_runtime_gate_pass_kwargs(),
        )
    )
    command_id = f"command:{decision.decision_id}"
    app.state.command_lease_store.claim_command(
        command_id=command_id,
        session_id=decision.session_id,
        worker_id="worker:other",
        claimed_at="2026-04-07T00:00:00Z",
        lease_expires_at="2026-04-07T00:05:00Z",
    )

    with patch(
        "watchdog.services.session_spine.orchestrator.execute_canonical_decision"
    ) as execute_mock:
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 1, 0, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["auto_execute_and_notify"]
    execute_mock.assert_not_called()
    events = app.state.command_lease_store.list_events(command_id=command_id)
    assert [event.event_type for event in events] == ["command_claimed"]
    state = app.state.command_lease_store.get_command(command_id)
    assert state is not None
    assert state.status == "claimed"
    assert state.worker_id == "worker:other"
    assert state.claim_seq == 1


def test_resident_orchestrator_renews_its_active_claim_without_reexecuting_command(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
        resident_orchestrator_interval_seconds=3600,
    )
    a_client = FakeResidentAClient(
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
    )
    app = create_app(settings, a_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()
    record = app.state.session_spine_store.get("repo-a")
    assert record is not None
    decision = app.state.policy_decision_store.put(
        evaluate_persisted_session_policy(
            record,
            action_ref="continue_session",
            trigger="resident_orchestrator",
            brain_intent="propose_execute",
            **_runtime_gate_pass_kwargs(),
        )
    )
    command_id = f"command:{decision.decision_id}"
    app.state.command_lease_store.claim_command(
        command_id=command_id,
        session_id=decision.session_id,
        worker_id="resident_orchestrator",
        claimed_at="2026-04-07T00:00:00Z",
        lease_expires_at="2026-04-07T00:30:00Z",
    )

    with patch(
        "watchdog.services.session_spine.orchestrator.execute_canonical_decision"
    ) as execute_mock:
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 10, 0, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["auto_execute_and_notify"]
    execute_mock.assert_not_called()
    events = app.state.command_lease_store.list_events(command_id=command_id)
    assert [event.event_type for event in events] == [
        "command_claimed",
        "command_lease_renewed",
    ]
    assert [event.claim_seq for event in events] == [1, 1]
    state = app.state.command_lease_store.get_command(command_id)
    assert state is not None
    assert state.status == "claimed"
    assert state.worker_id == "resident_orchestrator"
    assert state.claim_seq == 1
    assert state.lease_expires_at == "2026-04-07T01:10:00Z"
    session_events = [
        event
        for event in app.state.session_service.list_events(session_id=decision.session_id)
        if event.related_ids.get("command_id") == command_id and event.event_type != "command_created"
    ]
    assert [event.event_type for event in session_events] == [
        "command_claimed",
        "command_lease_renewed",
    ]
    assert [event.related_ids["claim_seq"] for event in session_events] == ["1", "1"]
    assert session_events[-1].payload["lease_expires_at"] == "2026-04-07T01:10:00Z"


def test_resident_orchestrator_requeues_expired_claim_before_reexecuting_command(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
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
    )
    app = create_app(settings, a_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()
    record = app.state.session_spine_store.get("repo-a")
    assert record is not None
    decision = app.state.policy_decision_store.put(
        evaluate_persisted_session_policy(
            record,
            action_ref="continue_session",
            trigger="resident_orchestrator",
            brain_intent="propose_execute",
            **_runtime_gate_pass_kwargs(),
        )
    )
    command_id = f"command:{decision.decision_id}"
    app.state.command_lease_store.claim_command(
        command_id=command_id,
        session_id=decision.session_id,
        worker_id="worker:other",
        claimed_at="2026-04-07T00:00:00Z",
        lease_expires_at="2026-04-07T00:00:30Z",
    )

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 1, 0, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["auto_execute_and_notify"]
    assert steer_mock.call_count == 1
    events = app.state.command_lease_store.list_events(command_id=command_id)
    assert [event.event_type for event in events] == [
        "command_claimed",
        "command_claim_expired",
        "command_requeued",
        "command_claimed",
        "command_executed",
    ]
    assert [event.claim_seq for event in events] == [1, 1, 1, 2, 2]
    state = app.state.command_lease_store.get_command(command_id)
    assert state is not None
    assert state.status == "executed"
    assert state.claim_seq == 2
    assert state.worker_id == "resident_orchestrator"
    session_events = [
        event
        for event in app.state.session_service.list_events(session_id=decision.session_id)
        if event.related_ids.get("command_id") == command_id and event.event_type != "command_created"
    ]
    assert [event.event_type for event in session_events] == [
        "command_claimed",
        "command_claim_expired",
        "command_requeued",
        "command_claimed",
        "command_executed",
    ]
    assert [event.related_ids["claim_seq"] for event in session_events] == [
        "1",
        "1",
        "1",
        "2",
        "2",
    ]


def test_startup_reconciles_stale_pending_canonical_approval_against_later_auto_decision(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
        session_spine_refresh_interval_seconds=3600,
        resident_orchestrator_interval_seconds=3600,
        delivery_worker_interval_seconds=3600,
        progress_summary_max_age_seconds=0.0,
    )
    a_client = FakeResidentAClient(
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
            "last_progress_at": "2099-01-01T00:00:00Z",
        }
    )
    app = create_app(settings, a_client=a_client, start_background_workers=True)
    stale_decision = CanonicalDecisionRecord(
        decision_id="decision:repo-a:fact-v1:require_user_decision",
        decision_key="session:repo-a|fact-v1|policy-v1|require_user_decision|execute_recovery|",
        session_id="session:repo-a",
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="native:repo-a",
        approval_id=None,
        action_ref="execute_recovery",
        trigger="resident_orchestrator",
        decision_result="require_user_decision",
        risk_class="human_gate",
        decision_reason="manual approval required",
        matched_policy_rules=["recovery_human_gate"],
        why_not_escalated=None,
        why_escalated="manual decision required",
        uncertainty_reasons=[],
        policy_version="policy-v1",
        fact_snapshot_version="fact-v1",
        idempotency_key="session:repo-a|fact-v1|policy-v1|require_user_decision|execute_recovery|",
        created_at="2026-04-07T00:00:00Z",
        operator_notes=[],
        evidence={
            "decision": {
                "decision_result": "require_user_decision",
                "action_ref": "execute_recovery",
                "approval_id": None,
            }
        },
    )
    approval = materialize_canonical_approval(
        stale_decision,
        approval_store=app.state.canonical_approval_store,
    )
    app.state.policy_decision_store.put(
        CanonicalDecisionRecord(
            decision_id="decision:repo-a:fact-v2:auto_execute_and_notify",
            decision_key=(
                "session:repo-a|fact-v2|policy-v1|auto_execute_and_notify|continue_session|"
            ),
            session_id="session:repo-a",
            project_id="repo-a",
            thread_id="session:repo-a",
            native_thread_id="native:repo-a",
            approval_id=None,
            action_ref="continue_session",
            trigger="resident_orchestrator",
            decision_result="auto_execute_and_notify",
            risk_class="none",
            decision_reason="registered action and complete evidence",
            matched_policy_rules=["registered_action"],
            why_not_escalated="policy_allows_auto_execution",
            why_escalated=None,
            uncertainty_reasons=[],
            policy_version="policy-v1",
            fact_snapshot_version="fact-v2",
            idempotency_key=(
                "session:repo-a|fact-v2|policy-v1|auto_execute_and_notify|continue_session|"
            ),
            created_at="2026-04-07T00:05:00Z",
            operator_notes=[],
            evidence={
                "decision": {
                    "decision_result": "auto_execute_and_notify",
                    "action_ref": "continue_session",
                    "approval_id": None,
                }
            },
        )
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/watchdog/approval-inbox?project_id=repo-a",
            headers={"Authorization": "Bearer wt"},
        )

    persisted = app.state.canonical_approval_store.get(approval.envelope_id)

    assert response.status_code == 200
    assert response.json()["data"]["approvals"] == []
    assert persisted is not None
    assert persisted.status == "superseded"
    assert persisted.decided_by == "policy-startup-reconcile"


def test_resident_orchestrator_caches_auto_continue_control_link_error_per_decision(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "handoff",
            "pending_approval": False,
            "last_summary": "waiting for bridge recovery",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, a_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    with patch(
        "watchdog.services.session_spine.actions.post_steer",
        side_effect=RuntimeError("bridge unavailable"),
    ) as steer_mock:
        first = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )
        second = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 1, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in first] == ["continue_session"]
    assert [outcome.decision_result for outcome in first] == ["auto_execute_and_notify"]
    assert [outcome.action_ref for outcome in second] == ["continue_session"]
    assert [outcome.decision_result for outcome in second] == ["auto_execute_and_notify"]
    assert steer_mock.call_count == 1

    receipts = [result for _, result in app.state.action_receipt_store.list_items()]
    assert len(receipts) == 1
    assert receipts[0].action_code == "continue_session"
    assert receipts[0].action_status == "error"
    assert receipts[0].effect == "noop"
    assert receipts[0].reply_code == "control_link_error"
    assert receipts[0].message == "steer 调用失败：无法连接 A-Control-Agent"
    assert [fact.fact_code for fact in receipts[0].facts] == [
        "stuck_no_progress",
        "recovery_available",
    ]
    decision = app.state.policy_decision_store.list_records()[0]
    command_id = f"command:{decision.decision_id}"
    command_events = app.state.command_lease_store.list_events(command_id=command_id)
    assert [event.event_type for event in command_events] == [
        "command_claimed",
        "command_failed",
    ]
    command_state = app.state.command_lease_store.get_command(command_id)
    assert command_state is not None
    assert command_state.status == "failed"
    assert command_state.worker_id == "resident_orchestrator"
    session_events = [
        event
        for event in app.state.session_service.list_events(session_id=decision.session_id)
        if event.related_ids.get("command_id") == command_id and event.event_type != "command_created"
    ]
    assert [event.event_type for event in session_events] == [
        "command_claimed",
        "command_failed",
    ]
    assert app.state.delivery_outbox_store.list_records() == []


def test_resident_orchestrator_applies_cooldown_to_repeated_auto_continue(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=300.0,
    )
    a_client = CyclingResidentAClient(
        tasks=[
            {
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
            },
            {
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "still stuck after retry",
                "files_touched": ["src/example.py"],
                "context_pressure": "low",
                "stuck_level": 2,
                "failure_count": 3,
                "last_progress_at": "2026-04-05T05:25:00Z",
            },
        ]
    )
    app = create_app(settings, a_client=a_client, start_background_workers=False)

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}

        app.state.session_spine_runtime.refresh_all()
        first = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

        app.state.session_spine_runtime.refresh_all()
        second = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 2, 0, tzinfo=UTC)
        )

        app.state.session_spine_runtime.refresh_all()
        third = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 6, 0, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in first] == ["continue_session"]
    assert [outcome.decision_result for outcome in first] == ["auto_execute_and_notify"]
    assert [outcome.action_ref for outcome in second] == [None]
    assert [outcome.decision_result for outcome in second] == [None]
    assert [outcome.action_ref for outcome in third] == ["continue_session"]
    assert [outcome.decision_result for outcome in third] == ["auto_execute_and_notify"]
    assert steer_mock.call_count == 2


def test_resident_orchestrator_does_not_start_cooldown_after_cached_control_link_error(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=300.0,
    )
    a_client = CyclingResidentAClient(
        tasks=[
            {
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "handoff",
                "pending_approval": False,
                "last_summary": "waiting for bridge recovery",
                "files_touched": ["src/example.py"],
                "context_pressure": "low",
                "stuck_level": 2,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T05:20:00Z",
            },
            {
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "handoff",
                "pending_approval": False,
                "last_summary": "still waiting for bridge recovery",
                "files_touched": ["src/example.py"],
                "context_pressure": "low",
                "stuck_level": 3,
                "failure_count": 1,
                "last_progress_at": "2026-04-05T05:21:00Z",
            },
        ]
    )
    app = create_app(settings, a_client=a_client, start_background_workers=False)

    app.state.session_spine_runtime.refresh_all()
    with patch(
        "watchdog.services.session_spine.actions.post_steer",
        side_effect=RuntimeError("bridge unavailable"),
    ) as steer_mock:
        first = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )
        assert app.state.resident_orchestration_state_store.get_auto_continue_checkpoint("repo-a") is None

        app.state.session_spine_runtime.refresh_all()
        second = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 1, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in first] == ["continue_session"]
    assert [outcome.decision_result for outcome in first] == ["auto_execute_and_notify"]
    assert [outcome.action_ref for outcome in second] == ["continue_session"]
    assert [outcome.decision_result for outcome in second] == ["auto_execute_and_notify"]
    assert steer_mock.call_count == 2
    assert app.state.resident_orchestration_state_store.get_auto_continue_checkpoint("repo-a") is None


def test_resident_orchestrator_does_not_start_cooldown_after_cached_error_receipt(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=300.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "handoff",
            "pending_approval": False,
            "last_summary": "waiting for bridge recovery",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, a_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    cached_error = WatchdogActionResult(
        action_code="continue_session",
        project_id="repo-a",
        approval_id=None,
        idempotency_key="decision:cached-error",
        action_status=ActionStatus.ERROR,
        effect=Effect.NOOP,
        reply_code=ReplyCode.CONTROL_LINK_ERROR,
        message="cached control-link-error receipt",
        facts=[],
    )

    with patch(
        "watchdog.services.session_spine.orchestrator.execute_canonical_decision",
        return_value=cached_error,
    ) as execute_mock:
        first = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )
        second = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 1, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in first] == ["continue_session"]
    assert [outcome.decision_result for outcome in first] == ["auto_execute_and_notify"]
    assert [outcome.action_ref for outcome in second] == ["continue_session"]
    assert [outcome.decision_result for outcome in second] == ["auto_execute_and_notify"]
    assert execute_mock.call_count == 1
    assert app.state.resident_orchestration_state_store.get_auto_continue_checkpoint("repo-a") is None
    assert app.state.delivery_outbox_store.list_records() == []


def test_background_runtime_pushes_progress_summary_when_project_progress_changes(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
        session_spine_refresh_interval_seconds=0.01,
        resident_orchestrator_interval_seconds=0.01,
        progress_summary_interval_seconds=0.0,
    )
    a_client = CyclingResidentAClient(
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
                "last_progress_at": "2099-01-01T00:00:00Z",
            },
            {
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "running_tests",
                "pending_approval": False,
                "last_summary": "tests are running",
                "files_touched": ["src/example.py", "tests/test_example.py"],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2099-01-01T00:01:00Z",
            },
        ]
    )
    delivery_client = RecordingDeliveryClient()
    app = create_app(settings, a_client=a_client, start_background_workers=True)
    app.state.delivery_worker._delivery_client = delivery_client

    with TestClient(app):
        time.sleep(0.08)

    progress_notifications = [
        record
        for record in delivery_client.records
        if record.get("notification_kind") == "progress_summary"
    ]

    assert len(progress_notifications) >= 1
    assert progress_notifications[-1]["summary"] == "tests are running"


def test_background_runtime_skips_stale_progress_summary_even_when_project_progress_changes(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
        session_spine_refresh_interval_seconds=0.01,
        resident_orchestrator_interval_seconds=0.01,
        progress_summary_interval_seconds=0.0,
        progress_summary_max_age_seconds=600.0,
    )
    a_client = CyclingResidentAClient(
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
                "last_progress_at": "2026-04-06T00:00:00Z",
            },
            {
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "running_tests",
                "pending_approval": False,
                "last_summary": "tests are running",
                "files_touched": ["src/example.py", "tests/test_example.py"],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-06T00:01:00Z",
            },
        ]
    )
    delivery_client = RecordingDeliveryClient()
    app = create_app(settings, a_client=a_client, start_background_workers=True)
    app.state.delivery_worker._delivery_client = delivery_client

    with TestClient(app):
        time.sleep(0.08)

    progress_notifications = [
        record
        for record in delivery_client.records
        if record.get("notification_kind") == "progress_summary"
    ]

    assert progress_notifications == []


def test_parse_iso_treats_naive_timestamps_as_utc() -> None:
    parsed = _parse_iso("2026-04-08T08:00:00")

    assert parsed == datetime(2026, 4, 8, 8, 0, 0, tzinfo=UTC)


def test_background_workers_survive_transient_startup_and_loop_failures(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
        session_spine_refresh_interval_seconds=0.01,
        resident_orchestrator_interval_seconds=0.01,
        delivery_worker_interval_seconds=0.01,
        progress_summary_interval_seconds=0.0,
    )
    a_client = FakeResidentAClient(
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
            "last_progress_at": "2099-01-01T00:00:00Z",
        }
    )

    app = create_app(settings, a_client=a_client, start_background_workers=True)
    app.state.session_spine_runtime = FlakyRuntime(app.state.session_spine_runtime)
    app.state.resident_orchestrator = FlakyOrchestrator(app.state.resident_orchestrator)
    app.state.delivery_worker._delivery_client = RecordingDeliveryClient()
    app.state.delivery_worker = FlakyDeliveryWorker(app.state.delivery_worker)

    with TestClient(app):
        time.sleep(0.08)

    snapshot = _read_store(tmp_path)
    progress_notifications = [
        record
        for record in app.state.delivery_worker._delegate._delivery_client.records
        if record.get("notification_kind") == "progress_summary"
    ]

    assert snapshot["sessions"]["repo-a"]["session_seq"] >= 1
    assert app.state.session_spine_runtime.calls >= 2
    assert app.state.resident_orchestrator.calls >= 2
    assert app.state.delivery_worker.calls >= 2
    assert progress_notifications


@pytest.mark.asyncio
async def test_delivery_loop_runs_drain_outside_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
        delivery_worker_interval_seconds=3600,
    )
    a_client = FakeResidentAClient(
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
            "last_progress_at": "2099-01-01T00:00:00Z",
        }
    )
    app = create_app(settings, a_client=a_client, start_background_workers=False)

    def blocking_drain(_app, *, now=None) -> None:
        _ = now
        time.sleep(0.05)

    monkeypatch.setattr("watchdog.main._drain_delivery_outbox", blocking_drain)

    started = time.perf_counter()
    ticker = asyncio.create_task(asyncio.sleep(0.01))
    delivery_loop_task = asyncio.create_task(_run_delivery_loop(app))

    try:
        await ticker
    finally:
        delivery_loop_task.cancel()
        with suppress(asyncio.CancelledError):
            await delivery_loop_task

    assert time.perf_counter() - started < 0.03


@pytest.mark.asyncio
async def test_startup_drain_runs_outside_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
        session_spine_refresh_interval_seconds=3600,
        resident_orchestrator_interval_seconds=3600,
        delivery_worker_interval_seconds=3600,
    )
    a_client = FakeResidentAClient(
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
            "last_progress_at": "2099-01-01T00:00:00Z",
        }
    )
    app = create_app(settings, a_client=a_client, start_background_workers=True)

    def blocking_drain(_app, *, now=None) -> None:
        _ = now
        time.sleep(0.05)

    monkeypatch.setattr("watchdog.main._drain_delivery_outbox", blocking_drain)

    lifespan = app.router.lifespan_context(app)
    startup_task = asyncio.create_task(lifespan.__aenter__())
    started = time.perf_counter()
    ticker = asyncio.create_task(asyncio.sleep(0.01))

    try:
        await ticker
        assert time.perf_counter() - started < 0.03
        await startup_task
    finally:
        if startup_task.done() and not startup_task.cancelled():
            await lifespan.__aexit__(None, None, None)
        else:
            startup_task.cancel()
            with suppress(asyncio.CancelledError):
                await startup_task


@pytest.mark.asyncio
async def test_startup_does_not_wait_for_full_delivery_drain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
        session_spine_refresh_interval_seconds=3600,
        resident_orchestrator_interval_seconds=3600,
        delivery_worker_interval_seconds=3600,
    )
    a_client = FakeResidentAClient(
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
            "last_progress_at": "2099-01-01T00:00:00Z",
        }
    )
    app = create_app(settings, a_client=a_client, start_background_workers=True)

    def blocking_drain(_app, *, now=None) -> None:
        _ = (_app, now)
        time.sleep(0.2)

    monkeypatch.setattr("watchdog.main._drain_delivery_outbox", blocking_drain)

    lifespan = app.router.lifespan_context(app)
    startup_task = asyncio.create_task(lifespan.__aenter__())

    try:
        await asyncio.wait_for(startup_task, timeout=0.05)
    finally:
        if startup_task.done() and not startup_task.cancelled():
            await lifespan.__aexit__(None, None, None)
        else:
            startup_task.cancel()
            with suppress(asyncio.CancelledError):
                await startup_task
