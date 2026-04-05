from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from watchdog.services.adapters.openclaw.adapter import OpenClawAdapter
from watchdog.settings import Settings
from watchdog.storage.action_receipts import ActionReceiptStore


class FakeAClient:
    def __init__(
        self,
        *,
        task: dict[str, object],
        approvals: list[dict[str, object]] | None = None,
    ) -> None:
        self._task = dict(task)
        self._approvals = [dict(approval) for approval in approvals or []]

    def get_envelope(self, project_id: str) -> dict[str, object]:
        assert project_id == self._task["project_id"]
        return {"success": True, "data": dict(self._task)}

    def list_approvals(self, *, status: str | None = None) -> list[dict[str, object]]:
        rows = [dict(approval) for approval in self._approvals]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        return rows

    def decide_approval(
        self,
        approval_id: str,
        *,
        decision: str,
        operator: str,
        note: str = "",
    ) -> dict[str, object]:
        return {
            "success": True,
            "data": {
                "approval_id": approval_id,
                "status": "approved" if decision == "approve" else "rejected",
                "operator": operator,
                "note": note,
            },
        }


def _adapter(tmp_path: Path, *, task: dict[str, object], approvals: list[dict[str, object]] | None = None) -> OpenClawAdapter:
    return OpenClawAdapter(
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        client=FakeAClient(task=task, approvals=approvals),
        receipt_store=ActionReceiptStore(tmp_path / "action_receipts.json"),
    )


def test_adapter_get_session_returns_stable_session_projection(tmp_path: Path) -> None:
    adapter = _adapter(
        tmp_path,
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
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
    )

    reply = adapter.handle_intent("get_session", project_id="repo-a")

    assert reply.reply_code == "session_projection"
    assert reply.session is not None
    assert reply.session.thread_id == "session:repo-a"
    assert reply.session.native_thread_id == "thr_native_1"


def test_adapter_why_stuck_is_built_from_fact_records(tmp_path: Path) -> None:
    adapter = _adapter(
        tmp_path,
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
    )

    reply = adapter.handle_intent("why_stuck", project_id="repo-a")

    assert reply.reply_code == "stuck_explanation"
    assert [fact.fact_code for fact in reply.facts] == [
        "stuck_no_progress",
        "repeat_failure",
        "context_critical",
        "recovery_available",
    ]
    assert "session appears stuck" in reply.message
    assert "repeated failures detected" in reply.message


def test_adapter_explain_blocker_uses_fact_records_and_stable_read_model(tmp_path: Path) -> None:
    adapter = _adapter(
        tmp_path,
        task={
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
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        approvals=[
            {
                "approval_id": "appr_001",
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "risk_level": "L2",
                "command": "uv run pytest",
                "reason": "verify tests",
                "alternative": "",
                "status": "pending",
                "requested_at": "2026-04-05T05:21:00Z",
            }
        ],
    )

    reply = adapter.handle_intent("explain_blocker", project_id="repo-a")

    assert reply.reply_code == "blocker_explanation"
    assert [fact.fact_code for fact in reply.facts] == [
        "approval_pending",
        "awaiting_human_direction",
    ]
    assert "approval required" in reply.message


def test_adapter_request_recovery_maps_advisory_action_result_to_reply_model(tmp_path: Path) -> None:
    adapter = _adapter(
        tmp_path,
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
    )

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        reply = adapter.handle_intent(
            "request_recovery",
            project_id="repo-a",
            operator="openclaw",
            idempotency_key="idem-recovery-1",
        )

    assert steer_mock.call_count == 0
    assert reply.reply_code == "recovery_availability"
    assert reply.message == "recovery is available"


def test_adapter_returns_unsupported_intent_for_unknown_request(tmp_path: Path) -> None:
    adapter = _adapter(
        tmp_path,
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
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
    )

    reply = adapter.handle_intent("summon_supervisor", project_id="repo-a")

    assert reply.reply_code == "unsupported_intent"
