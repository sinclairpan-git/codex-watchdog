from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from a_control_agent.main import create_app
from a_control_agent.settings import Settings
from watchdog.main import create_app as create_watchdog_app
from watchdog.settings import Settings as WSettings


def test_steer_persists_stuck_level(tmp_path: Path) -> None:
    s = Settings(api_token="t", data_dir=str(tmp_path / "d"))
    c = TestClient(create_app(s))
    h = {"Authorization": "Bearer t"}
    c.post(
        "/api/v1/tasks",
        json={"project_id": "p1", "cwd": "/", "task_title": "x"},
        headers=h,
    )
    c.post(
        "/api/v1/tasks/p1/steer",
        json={
            "message": "m",
            "reason": "stuck_soft",
            "stuck_level": 2,
        },
        headers=h,
    )
    r = c.get("/api/v1/tasks/p1", headers=h)
    assert r.json()["data"]["stuck_level"] == 2


def test_handoff_sets_stuck_level_4(tmp_path: Path) -> None:
    s = Settings(api_token="t", data_dir=str(tmp_path / "d"))
    c = TestClient(create_app(s))
    h = {"Authorization": "Bearer t"}
    c.post(
        "/api/v1/tasks",
        json={"project_id": "p1", "cwd": "/", "task_title": "x"},
        headers=h,
    )
    c.post("/api/v1/tasks/p1/handoff", json={"reason": "r"}, headers=h)
    r = c.get("/api/v1/tasks/p1", headers=h)
    assert r.json()["data"]["stuck_level"] == 4


def test_evaluate_suppressed_when_repo_activity(tmp_path: Path) -> None:
    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    task_data = {
        "status": "running",
        "phase": "planning",
        "cwd": str(tmp_path / "repo"),
        "last_summary": "",
        "files_touched": [],
        "pending_approval": False,
        "context_pressure": "low",
        "last_progress_at": old,
        "stuck_level": 0,
    }
    (tmp_path / "repo").mkdir()
    app = create_watchdog_app(
        WSettings(
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
        with patch(
            "watchdog.services.session_spine.supervision.summarize_workspace_activity",
            return_value={"recent_change_count": 2, "cwd_exists": True},
        ):
            r = c.post(
                "/api/v1/watchdog/tasks/p1/evaluate",
                headers={"Authorization": "Bearer wt"},
            )
    b = r.json()
    assert b["success"] is True
    assert b["data"]["evaluation"]["reason"] == "filesystem_activity_recent"
    assert b["data"]["steer_sent"] is False


def test_recover_handoff_and_resume_when_enabled(tmp_path: Path) -> None:
    app = create_watchdog_app(
        WSettings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path / "wd"),
            recover_auto_resume=True,
        )
    )

    def _env(_pid: str) -> dict:
        return {
            "success": True,
            "data": {
                "project_id": "p1",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "context_pressure": "critical",
                "cwd": "/",
                "last_summary": "context exhausted",
                "files_touched": ["src/watchdog/api/recover_watchdog.py"],
                "stuck_level": 2,
                "failure_count": 1,
                "last_progress_at": "2026-04-05T05:20:00Z",
            },
        }

    app.state.runtime_client.get_envelope = _env  # type: ignore[method-assign]
    app.state.runtime_client.list_approvals = lambda **_: []  # type: ignore[method-assign]
    handoff_calls: list[tuple[str, str, dict[str, object] | None]] = []
    resume_calls: list[tuple[str, str, str, dict[str, object] | None]] = []

    def _trigger_handoff(
        project_id: str,
        *,
        reason: str,
        continuation_packet: dict[str, object] | None = None,
    ) -> dict[str, object]:
        handoff_calls.append((project_id, reason, continuation_packet))
        return {"success": True, "data": {"handoff_file": "/h.md", "continuation_packet": continuation_packet}}

    def _trigger_resume(
        project_id: str,
        *,
        mode: str,
        handoff_summary: str,
        continuation_packet: dict[str, object] | None = None,
    ) -> dict[str, object]:
        resume_calls.append((project_id, mode, handoff_summary, continuation_packet))
        return {"success": True, "data": {"status": "running", "resume_outcome": "same_thread_resume"}}

    app.state.runtime_client.trigger_handoff = _trigger_handoff  # type: ignore[method-assign]
    app.state.runtime_client.trigger_resume = _trigger_resume  # type: ignore[method-assign]
    c = TestClient(app)
    r = c.post(
        "/api/v1/watchdog/tasks/p1/recover",
        headers={"Authorization": "Bearer wt"},
    )
    out = r.json()
    assert out["success"] is True
    assert out["data"]["action"] == "handoff_and_resume"
    assert len(handoff_calls) == 1
    assert len(resume_calls) == 1
    assert handoff_calls[0][0:2] == ("p1", "context_critical")
    assert handoff_calls[0][2] is not None
    assert resume_calls[0][0:3] == ("p1", "resume_or_new_thread", "")
    assert resume_calls[0][3] == handoff_calls[0][2]
