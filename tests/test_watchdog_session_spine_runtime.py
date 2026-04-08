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
from watchdog.services.delivery.http_client import DeliveryAttemptResult
from watchdog.services.session_spine.orchestrator import _parse_iso
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

        time.sleep(0.05)

        refreshed_snapshot = _read_store(tmp_path)

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


def test_resident_orchestrator_skips_auto_continue_for_done_session(
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
    assert [outcome.action_ref for outcome in outcomes] == [None]
    assert [outcome.decision_result for outcome in outcomes] == [None]
    assert len(snapshot["sessions"]["repo-a"]["facts"]) == 1
    assert snapshot["sessions"]["repo-a"]["facts"][0]["fact_id"] == "repo-a:task_completed"
    assert snapshot["sessions"]["repo-a"]["facts"][0]["fact_code"] == "task_completed"
    assert snapshot["sessions"]["repo-a"]["facts"][0]["detail"] == (
        "session reached a terminal completed state"
    )
    assert app.state.delivery_outbox_store.list_records() == []
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


def test_background_runtime_orchestrates_context_critical_session_into_auto_recovery(
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

    assert a_client.handoff_calls == [("repo-a", "context_critical")]
    assert a_client.resume_calls == [("repo-a", "resume_or_new_thread", "")]
    assert any(
        record.get("notification_kind") == "decision_result"
        and record.get("decision_result") == "auto_execute_and_notify"
        and record.get("action_name") == "execute_recovery"
        for record in delivery_client.records
    )


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
    deliveries = app.state.delivery_outbox_store.list_records()
    assert [record.envelope_type for record in deliveries] == ["decision", "notification"]
    assert [record.envelope_payload.get("decision_result") for record in deliveries] == [
        "auto_execute_and_notify",
        "auto_execute_and_notify",
    ]
    assert [record.envelope_payload.get("action_name") for record in deliveries] == [
        "continue_session",
        "continue_session",
    ]


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
