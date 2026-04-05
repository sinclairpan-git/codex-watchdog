from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import httpx

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
        self.decision_calls: list[tuple[str, str, str, str]] = []

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
        self.decision_calls.append((approval_id, decision, operator, note))
        return {
            "success": True,
            "data": {
                "approval_id": approval_id,
                "status": "approved" if decision == "approve" else "rejected",
            },
        }


class BrokenAClient:
    def get_envelope(self, project_id: str) -> dict[str, object]:
        raise httpx.ConnectError("refused", request=httpx.Request("GET", f"http://a.test/{project_id}"))

    def list_approvals(self, *, status: str | None = None) -> list[dict[str, object]]:
        _ = status
        return []

    def decide_approval(
        self,
        approval_id: str,
        *,
        decision: str,
        operator: str,
        note: str = "",
    ) -> dict[str, object]:
        _ = (approval_id, decision, operator, note)
        return {"success": False, "error": {"code": "CONTROL_LINK_ERROR", "message": "broken"}}


def _adapter(tmp_path: Path, client) -> OpenClawAdapter:
    return OpenClawAdapter(
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        client=client,
        receipt_store=ActionReceiptStore(tmp_path / "action_receipts.json"),
    )


def test_integration_continue_session_success(tmp_path: Path) -> None:
    adapter = _adapter(
        tmp_path,
        FakeAClient(
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
            }
        ),
    )

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}
        reply = adapter.handle_intent(
            "continue_session",
            project_id="repo-a",
            operator="openclaw",
            idempotency_key="idem-continue-1",
        )

    assert steer_mock.call_count == 1
    assert reply.reply_code == "action_result"
    assert reply.message == "continue request accepted"


def test_integration_continue_session_blocked_by_pending_approval(tmp_path: Path) -> None:
    adapter = _adapter(
        tmp_path,
        FakeAClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "waiting_human",
                "phase": "approval",
                "pending_approval": True,
                "last_summary": "waiting for approval",
                "files_touched": [],
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
                    "status": "pending",
                    "command": "uv run pytest",
                    "reason": "verify tests",
                    "alternative": "",
                    "requested_at": "2026-04-05T05:21:00Z",
                }
            ],
        ),
    )

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        reply = adapter.handle_intent(
            "continue_session",
            project_id="repo-a",
            operator="openclaw",
            idempotency_key="idem-continue-2",
        )

    assert steer_mock.call_count == 0
    assert reply.reply_code == "action_not_available"
    assert reply.message == "session is awaiting human approval"


def test_integration_continue_session_surfaces_control_link_error(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, BrokenAClient())

    reply = adapter.handle_intent(
        "continue_session",
        project_id="repo-a",
        operator="openclaw",
        idempotency_key="idem-continue-3",
    )

    assert reply.reply_code == "control_link_error"


def test_integration_request_recovery_is_advisory_only(tmp_path: Path) -> None:
    adapter = _adapter(
        tmp_path,
        FakeAClient(
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
            }
        ),
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


def test_integration_approval_actions_cover_approve_and_reject(tmp_path: Path) -> None:
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "waiting_human",
            "phase": "approval",
            "pending_approval": True,
            "last_summary": "waiting for approval",
            "files_touched": [],
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
                "status": "pending",
                "command": "uv run pytest",
                "reason": "verify tests",
                "alternative": "",
                "requested_at": "2026-04-05T05:21:00Z",
            }
        ],
    )
    adapter = _adapter(tmp_path, client)

    approve = adapter.handle_intent(
        "approve_approval",
        project_id="repo-a",
        operator="openclaw",
        approval_id="appr_001",
        idempotency_key="idem-approval-1",
    )
    reject = adapter.handle_intent(
        "reject_approval",
        project_id="repo-a",
        operator="openclaw",
        approval_id="appr_001",
        idempotency_key="idem-approval-2",
    )

    assert approve.reply_code == "approval_result"
    assert reject.reply_code == "approval_result"
    assert client.decision_calls == [
        ("appr_001", "approve", "openclaw", ""),
        ("appr_001", "reject", "openclaw", ""),
    ]
