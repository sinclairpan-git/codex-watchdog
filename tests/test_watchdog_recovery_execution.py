from __future__ import annotations

from watchdog.services.session_spine.recovery import perform_recovery_execution
from watchdog.settings import Settings


class FakeAClient:
    def __init__(self, *, task: dict[str, object], resume_success: bool = True) -> None:
        self._task = dict(task)
        self._resume_success = resume_success
        self.handoff_calls: list[tuple[str, str]] = []
        self.resume_calls: list[tuple[str, str, str]] = []

    def get_envelope(self, project_id: str) -> dict[str, object]:
        assert project_id == self._task["project_id"]
        return {"success": True, "data": dict(self._task)}

    def list_approvals(self, *, status: str | None = None) -> list[dict[str, object]]:
        _ = status
        return []

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
        if self._resume_success:
            return {
                "success": True,
                "data": {"project_id": project_id, "status": "running", "mode": mode},
            }
        return {"success": False, "error": {"code": "RESUME_FAILED", "message": "bridge unavailable"}}


def test_perform_recovery_execution_returns_noop_without_side_effects(tmp_path) -> None:
    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        client=FakeAClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "steady progress",
                "files_touched": ["src/example.py"],
                "context_pressure": "medium",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T05:20:00Z",
            }
        ),
    )

    assert outcome.action == "noop"
    assert outcome.context_pressure == "medium"
    assert outcome.handoff is None
    assert outcome.resume is None
    assert outcome.resume_error is None


def test_perform_recovery_execution_preserves_handoff_when_resume_fails(tmp_path) -> None:
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "repeated failures",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        resume_success=False,
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
    )

    assert client.handoff_calls == [("repo-a", "context_critical")]
    assert client.resume_calls == [("repo-a", "resume_or_new_thread", "")]
    assert outcome.action == "handoff_triggered"
    assert outcome.handoff is not None
    assert outcome.resume is None
    assert outcome.resume_error == "resume_call_failed"
