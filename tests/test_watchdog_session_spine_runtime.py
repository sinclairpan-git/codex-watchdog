from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from watchdog.main import create_app
from watchdog.services.delivery.http_client import DeliveryAttemptResult
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

    with TestClient(create_app(settings, a_client=a_client, start_background_workers=True)):
        first_snapshot = _read_store(tmp_path)
        assert first_snapshot["sessions"]["repo-a"]["session_seq"] == 1

        time.sleep(0.05)

        refreshed_snapshot = _read_store(tmp_path)

    assert refreshed_snapshot["sessions"]["repo-a"]["session_seq"] == 2
    assert refreshed_snapshot["sessions"]["repo-a"]["session"]["session_state"] == "awaiting_approval"
    assert refreshed_snapshot["sessions"]["repo-a"]["progress"]["activity_phase"] == "approval"


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
        for record in delivery_client.records
    )


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
