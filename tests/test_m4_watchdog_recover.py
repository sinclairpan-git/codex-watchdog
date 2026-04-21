from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from watchdog.main import create_app
from watchdog.settings import Settings


def test_recover_noop_when_not_critical(tmp_path) -> None:
    task_data = {
        "project_id": "p1",
        "thread_id": "thr_native_1",
        "status": "running",
        "phase": "planning",
        "pending_approval": False,
        "context_pressure": "medium",
        "cwd": "/",
        "last_summary": "still working",
        "files_touched": [],
        "stuck_level": 0,
        "failure_count": 0,
        "last_progress_at": "2026-04-05T05:20:00Z",
    }
    app = create_app(
        Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path / "wd"),
        )
    )
    app.state.a_client.get_envelope = lambda _project_id: {"success": True, "data": dict(task_data)}  # type: ignore[method-assign]
    app.state.a_client.list_approvals = lambda **_: []  # type: ignore[method-assign]
    app.state.a_client.trigger_handoff = MagicMock()  # type: ignore[method-assign]
    c = TestClient(app)
    r = c.post(
        "/api/v1/watchdog/tasks/p1/recover",
        headers={"Authorization": "Bearer wt"},
    )
    assert r.status_code == 200
    b = r.json()
    assert b["success"] is True
    assert b["data"]["action"] == "noop"
    app.state.a_client.trigger_handoff.assert_not_called()  # type: ignore[union-attr]


def test_recover_handoff_on_critical(tmp_path) -> None:
    task_data = {
        "project_id": "p1",
        "thread_id": "thr_native_1",
        "status": "running",
        "phase": "coding",
        "pending_approval": False,
        "context_pressure": "critical",
        "cwd": "/",
        "last_summary": "context exhausted",
        "files_touched": ["src/watchdog/api/recover_watchdog.py"],
        "stuck_level": 2,
        "failure_count": 1,
        "last_progress_at": "2026-04-05T05:20:00Z",
    }
    app = create_app(
        Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path / "wd"),
        )
    )
    app.state.a_client.get_envelope = lambda _project_id: {"success": True, "data": dict(task_data)}  # type: ignore[method-assign]
    app.state.a_client.list_approvals = lambda **_: []  # type: ignore[method-assign]
    app.state.a_client.trigger_handoff = MagicMock(  # type: ignore[method-assign]
        return_value={
            "success": True,
            "data": {"handoff_file": "/tmp/h.md"},
        }
    )
    c = TestClient(app)
    r = c.post(
        "/api/v1/watchdog/tasks/p1/recover",
        headers={"Authorization": "Bearer wt"},
    )
    assert r.status_code == 200
    b = r.json()
    assert b["success"] is True
    assert b["data"]["action"] == "handoff_triggered"
    app.state.a_client.trigger_handoff.assert_called_once_with(  # type: ignore[union-attr]
        "p1",
        reason="context_critical",
        continuation_packet=app.state.a_client.trigger_handoff.call_args.kwargs["continuation_packet"],  # type: ignore[union-attr]
    )
    assert (
        app.state.a_client.trigger_handoff.call_args.kwargs["continuation_packet"]["decision_class"]  # type: ignore[union-attr]
        == "recover_current_branch"
    )


def test_recover_get_error(tmp_path) -> None:
    app = create_app(
        Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://127.0.0.1:9",
            data_dir=str(tmp_path / "wd"),
        )
    )
    c = TestClient(app)
    with patch("watchdog.services.a_client.client.httpx.Client") as mcli:
        mock_inst = MagicMock()
        mcli.return_value.__enter__.return_value = mock_inst
        import httpx

        mock_inst.get.side_effect = httpx.ConnectError("x", request=MagicMock())
        r = c.post(
            "/api/v1/watchdog/tasks/x/recover",
            headers={"Authorization": "Bearer wt"},
        )
    assert r.json()["success"] is False
    assert r.json()["error"]["code"] == "CONTROL_LINK_ERROR"
