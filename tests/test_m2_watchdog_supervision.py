from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

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


def test_evaluate_connection_error() -> None:
    app = create_app(Settings(api_token="wt", a_agent_base_url="http://127.0.0.1:9", data_dir="/tmp/wd"))
    c = TestClient(app)
    with patch("watchdog.services.a_client.client.httpx.Client") as m:
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
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path / "wd"),
        )
    )
    c = TestClient(app)
    with patch("watchdog.services.a_client.client.httpx.Client") as mcli:
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
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path / "wd"),
        ),
        a_client=FakeAClient(
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
