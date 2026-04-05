from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from watchdog.contracts.session_spine.enums import ActionCode
from watchdog.contracts.session_spine.models import WatchdogAction
from watchdog.services.session_spine.supervision import execute_supervision_evaluation
from watchdog.settings import Settings


class FakeAClient:
    def __init__(self, *, task: dict[str, object]) -> None:
        self._task = dict(task)

    def get_envelope(self, project_id: str) -> dict[str, object]:
        assert project_id == self._task["project_id"]
        return {"success": True, "data": dict(self._task)}

    def list_approvals(self, *, status: str | None = None) -> list[dict[str, object]]:
        _ = status
        return []


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
    )


def test_execute_supervision_evaluation_posts_steer_and_returns_stable_result(tmp_path: Path) -> None:
    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "cwd": "",
            "pending_approval": False,
            "last_summary": "editing files",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": old,
        }
    )
    action = WatchdogAction(
        action_code=ActionCode.EVALUATE_SUPERVISION,
        project_id="repo-a",
        operator="openclaw",
        idempotency_key="idem-supervision-1",
        arguments={},
    )

    with patch("watchdog.services.session_spine.supervision.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}
        result = execute_supervision_evaluation(action, settings=_settings(tmp_path), client=client)

    assert steer_mock.call_count == 1
    assert result.reply_code == "supervision_evaluation"
    assert result.effect == "steer_posted"
    assert result.supervision_evaluation is not None
    assert result.supervision_evaluation.thread_id == "session:repo-a"
    assert result.supervision_evaluation.native_thread_id == "thr_native_1"
    assert result.supervision_evaluation.reason_code == "stuck_soft"
    assert result.supervision_evaluation.current_stuck_level == 0
    assert result.supervision_evaluation.next_stuck_level == 2
    assert result.supervision_evaluation.steer_sent is True


def test_execute_supervision_evaluation_suppresses_steer_when_repo_activity_recent(
    tmp_path: Path,
) -> None:
    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    repo = tmp_path / "repo"
    repo.mkdir()
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "cwd": str(repo),
            "pending_approval": False,
            "last_summary": "editing files",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": old,
        }
    )
    action = WatchdogAction(
        action_code=ActionCode.EVALUATE_SUPERVISION,
        project_id="repo-a",
        operator="openclaw",
        idempotency_key="idem-supervision-2",
        arguments={},
    )

    with patch(
        "watchdog.services.session_spine.supervision.summarize_workspace_activity",
        return_value={"recent_change_count": 2, "cwd_exists": True},
    ), patch("watchdog.services.session_spine.supervision.post_steer") as steer_mock:
        result = execute_supervision_evaluation(action, settings=_settings(tmp_path), client=client)

    assert steer_mock.call_count == 0
    assert result.effect == "noop"
    assert result.supervision_evaluation is not None
    assert result.supervision_evaluation.reason_code == "filesystem_activity_recent"
    assert result.supervision_evaluation.repo_recent_change_count == 2
    assert result.supervision_evaluation.steer_sent is False
