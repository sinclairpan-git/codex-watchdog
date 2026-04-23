from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from watchdog.api.supervision import post_steer_thread, run_background_supervision
from watchdog.main import create_app
from watchdog.settings import Settings


class FakeAClient:
    def __init__(self, tasks: list[dict[str, object]]) -> None:
        self._tasks = tasks

    def get_envelope(self, project_id: str) -> dict[str, object]:
        for task in self._tasks:
            if task.get("project_id") == project_id:
                return {"success": True, "data": dict(task)}
        return {"success": False, "error": {"code": "NOT_FOUND", "message": project_id}}

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
        _ = (status, project_id, decided_by, callback_status)
        return []


def test_evaluate_connection_error() -> None:
    app = create_app(Settings(api_token="wt", codex_runtime_base_url="http://127.0.0.1:9", data_dir="/tmp/wd"))
    c = TestClient(app)
    with patch("watchdog.services.runtime_client.client.httpx.Client") as m:
        mock_inst = MagicMock()
        m.return_value.__enter__.return_value = mock_inst
        import httpx

        mock_inst.get.side_effect = httpx.ConnectError("x", request=MagicMock())
        r = c.post(
            "/api/v1/watchdog/tasks/x/evaluate",
            headers={"Authorization": "Bearer wt"},
        )
    assert r.status_code == 200
    assert r.json()["success"] is False
    assert r.json()["error"]["code"] == "CONTROL_LINK_ERROR"


def test_evaluate_steer_path(tmp_path) -> None:
    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    task_data = {
        "status": "running",
        "phase": "planning",
        "last_summary": "",
        "files_touched": [],
        "pending_approval": False,
        "context_pressure": "low",
        "last_progress_at": old,
        "stuck_level": 0,
    }
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path / "wd"),
        )
    )
    c = TestClient(app)
    with patch("watchdog.services.runtime_client.client.httpx.Client") as mcli:
        mock_inst = MagicMock()
        mcli.return_value.__enter__.return_value = mock_inst
        mock_inst.get.return_value.json.return_value = {"success": True, "data": task_data}
        mock_inst.post.return_value.json.return_value = {"success": True, "data": {"status": "running"}}
        mock_inst.post.return_value.raise_for_status = MagicMock()
        r = c.post(
            "/api/v1/watchdog/tasks/p1/evaluate",
            headers={"Authorization": "Bearer wt"},
        )
    assert r.status_code == 200
    b = r.json()
    assert b["success"] is True
    assert b["data"]["steer_sent"] is True
    mock_inst.post.assert_called_once()


def test_background_supervision_scans_running_and_waiting_threads(tmp_path) -> None:
    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    fresh = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path / "wd"),
        ),
        runtime_client=FakeAClient(
            [
                {
                    "project_id": "proj-a",
                    "thread_id": "thr_run",
                    "status": "running",
                    "phase": "coding",
                    "cwd": "",
                    "last_progress_at": old,
                    "stuck_level": 0,
                },
                {
                    "project_id": "proj-a",
                    "thread_id": "thr_wait",
                    "status": "waiting_human",
                    "phase": "approval",
                    "cwd": "",
                    "last_progress_at": old,
                    "stuck_level": 0,
                },
                {
                    "project_id": "proj-b",
                    "thread_id": "thr_done",
                    "status": "completed",
                    "phase": "done",
                    "cwd": "",
                    "last_progress_at": old,
                    "stuck_level": 0,
                },
                {
                    "project_id": "proj-d",
                    "thread_id": "thr_done_waiting",
                    "status": "waiting_human",
                    "phase": "done",
                    "cwd": "",
                    "last_progress_at": old,
                    "stuck_level": 0,
                },
                {
                    "project_id": "proj-c",
                    "thread_id": "thr_fresh",
                    "status": "running",
                    "phase": "coding",
                    "cwd": "",
                    "last_progress_at": fresh,
                    "stuck_level": 0,
                },
            ]
        ),
        start_background_workers=True,
    )
    with patch("watchdog.api.supervision.post_steer_thread") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"status": "running"}}
        with TestClient(app):
            pass
    called_threads = [call.args[2] for call in steer_mock.call_args_list]
    assert called_threads == ["thr_run", "thr_wait"]


def test_background_supervision_prefers_explicit_native_thread_id(tmp_path: Path) -> None:
    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        runtime_client=FakeAClient(
            tasks=[
                {
                    "project_id": "proj-a",
                    "thread_id": "session:proj-a",
                    "native_thread_id": "thr_run",
                    "status": "running",
                    "phase": "coding",
                    "cwd": "",
                    "last_progress_at": old,
                    "stuck_level": 0,
                }
            ]
        ),
        start_background_workers=True,
    )
    with patch("watchdog.api.supervision.post_steer_thread") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"status": "running"}}
        with TestClient(app):
            pass

    called_threads = [call.args[2] for call in steer_mock.call_args_list]
    assert called_threads == ["thr_run"]


def test_background_supervision_scans_canonical_waiting_for_direction_status(tmp_path: Path) -> None:
    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        runtime_client=FakeAClient(
            tasks=[
                {
                    "project_id": "proj-a",
                    "thread_id": "thr_wait",
                    "status": "waiting_for_direction",
                    "phase": "planning",
                    "cwd": "",
                    "last_progress_at": old,
                    "stuck_level": 0,
                }
            ]
        ),
        start_background_workers=True,
    )
    with patch("watchdog.api.supervision.post_steer_thread") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"status": "running"}}
        with TestClient(app):
            pass

    called_threads = [call.args[2] for call in steer_mock.call_args_list]
    assert called_threads == ["thr_wait"]


def test_background_supervision_falls_back_to_stable_session_thread_id(tmp_path: Path) -> None:
    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        runtime_client=FakeAClient(
            tasks=[
                {
                    "project_id": "proj-a",
                    "thread_id": "session:proj-a",
                    "status": "running",
                    "phase": "coding",
                    "cwd": "",
                    "last_progress_at": old,
                    "stuck_level": 0,
                }
            ]
        ),
        start_background_workers=True,
    )
    with patch("watchdog.api.supervision.post_steer_thread") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"status": "running"}}
        with TestClient(app):
            pass

    called_threads = [call.args[2] for call in steer_mock.call_args_list]
    assert called_threads == ["session:proj-a"]


def test_background_supervision_scans_created_and_resuming_threads(tmp_path: Path) -> None:
    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        runtime_client=FakeAClient(
            tasks=[
                {
                    "project_id": "proj-created",
                    "thread_id": "thr_created",
                    "status": "created",
                    "phase": "planning",
                    "cwd": "",
                    "last_progress_at": old,
                    "stuck_level": 0,
                },
                {
                    "project_id": "proj-resuming",
                    "thread_id": "thr_resuming",
                    "status": "resuming",
                    "phase": "resume",
                    "cwd": "",
                    "last_progress_at": old,
                    "stuck_level": 0,
                },
            ]
        ),
        start_background_workers=True,
    )
    with patch("watchdog.api.supervision.post_steer_thread") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"status": "running"}}
        with TestClient(app):
            pass

    called_threads = [call.args[2] for call in steer_mock.call_args_list]
    assert called_threads == ["thr_created", "thr_resuming"]


def test_post_steer_thread_forwards_timeout() -> None:
    with patch("watchdog.api.supervision.post_steer") as post_steer_mock:
        post_steer_mock.return_value = {"success": True}

        result = post_steer_thread(
            "http://a.test",
            "token",
            "thr-1",
            "proj-1",
            message="probe",
            reason="stuck_soft",
            stuck_level=2,
            timeout=0.25,
        )

    assert result == {"success": True}
    post_steer_mock.assert_called_once_with(
        "http://a.test",
        "token",
        "proj-1",
        message="probe",
        reason="stuck_soft",
        stuck_level=2,
        timeout=0.25,
    )


def test_background_supervision_bounds_total_runtime_by_http_timeout(tmp_path: Path) -> None:
    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        http_timeout_s=0.05,
    )
    client = FakeAClient(
        [
            {
                "project_id": f"proj-{idx}",
                "thread_id": f"thr-{idx}",
                "status": "running",
                "phase": "coding",
                "cwd": "",
                "last_progress_at": old,
                "stuck_level": 0,
            }
            for idx in range(5)
        ]
    )
    seen_timeouts: list[float] = []

    def fake_post_steer_thread(*args, timeout: float, **kwargs):
        _ = (args, kwargs)
        seen_timeouts.append(timeout)
        time.sleep(0.06)
        raise httpx.ReadTimeout("timed out")

    started_at = time.perf_counter()
    with patch("watchdog.api.supervision.post_steer_thread", side_effect=fake_post_steer_thread):
        run_background_supervision(settings, client)
    elapsed = time.perf_counter() - started_at

    assert seen_timeouts
    assert seen_timeouts[0] == pytest.approx(0.05, abs=0.02)
    assert len(seen_timeouts) == 1
    assert elapsed < 0.2
