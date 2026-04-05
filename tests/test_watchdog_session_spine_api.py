from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from watchdog.main import create_app
from watchdog.settings import Settings


class FakeAClient:
    def __init__(
        self,
        *,
        task: dict[str, object],
        approvals: list[dict[str, object]] | None = None,
    ) -> None:
        self._task = dict(task)
        self._approvals = [dict(approval) for approval in approvals or []]
        self.handoff_calls: list[tuple[str, str]] = []
        self.resume_calls: list[tuple[str, str, str]] = []

    def get_envelope(self, project_id: str) -> dict[str, object]:
        assert project_id == self._task["project_id"]
        return {"success": True, "data": dict(self._task)}

    def list_tasks(self) -> list[dict[str, object]]:
        return [dict(self._task)]

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

    def trigger_handoff(
        self,
        project_id: str,
        *,
        reason: str,
    ) -> dict[str, object]:
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

    def get_events_snapshot(
        self,
        project_id: str,
        *,
        poll_interval: float = 0.5,
    ) -> tuple[str, str]:
        assert project_id == self._task["project_id"]
        _ = poll_interval
        return ('event: task_updated\ndata: {"project_id":"repo-a"}\n\n', "text/event-stream")


def _client() -> FakeAClient:
    return FakeAClient(
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


def test_session_spine_read_routes_return_stable_reply_models(tmp_path) -> None:
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=_client(),
    )
    c = TestClient(app)

    session_resp = c.get("/api/v1/watchdog/sessions/repo-a", headers={"Authorization": "Bearer wt"})
    progress_resp = c.get("/api/v1/watchdog/sessions/repo-a/progress", headers={"Authorization": "Bearer wt"})
    approvals_resp = c.get(
        "/api/v1/watchdog/sessions/repo-a/pending-approvals",
        headers={"Authorization": "Bearer wt"},
    )

    assert session_resp.status_code == 200
    assert progress_resp.status_code == 200
    assert approvals_resp.status_code == 200

    session_data = session_resp.json()["data"]
    progress_data = progress_resp.json()["data"]
    approvals_data = approvals_resp.json()["data"]

    assert session_data["reply_code"] == "session_projection"
    assert session_data["session"]["thread_id"] == "session:repo-a"
    assert session_data["session"]["native_thread_id"] == "thr_native_1"
    assert progress_data["reply_code"] == "task_progress_view"
    assert progress_data["progress"]["blocker_fact_codes"] == [
        "approval_pending",
        "awaiting_human_direction",
    ]
    assert approvals_data["reply_code"] == "approval_queue"
    assert approvals_data["approvals"][0]["thread_id"] == "session:repo-a"


def test_session_spine_stuck_explanation_route_returns_stable_reply_model(tmp_path) -> None:
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=FakeAClient(
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
    c = TestClient(app)

    response = c.get(
        "/api/v1/watchdog/sessions/repo-a/stuck-explanation",
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    data = response.json()["data"]
    assert data["reply_code"] == "stuck_explanation"
    assert data["progress"]["thread_id"] == "session:repo-a"
    assert data["session"]["native_thread_id"] == "thr_native_1"
    assert [fact["fact_code"] for fact in data["facts"]] == [
        "stuck_no_progress",
        "repeat_failure",
        "context_critical",
        "recovery_available",
    ]


def test_session_spine_blocker_explanation_route_returns_stable_reply_model(tmp_path) -> None:
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=_client(),
    )
    c = TestClient(app)

    response = c.get(
        "/api/v1/watchdog/sessions/repo-a/blocker-explanation",
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    data = response.json()["data"]
    assert data["reply_code"] == "blocker_explanation"
    assert data["progress"]["thread_id"] == "session:repo-a"
    assert data["session"]["native_thread_id"] == "thr_native_1"
    assert [fact["fact_code"] for fact in data["facts"]] == [
        "approval_pending",
        "awaiting_human_direction",
    ]


def test_session_spine_canonical_and_alias_actions_share_the_same_result(tmp_path) -> None:
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=FakeAClient(
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
    c = TestClient(app)

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}
        canonical = c.post(
            "/api/v1/watchdog/actions",
            json={
                "action_code": "continue_session",
                "project_id": "repo-a",
                "operator": "openclaw",
                "idempotency_key": "idem-continue-1",
                "arguments": {},
            },
            headers={"Authorization": "Bearer wt"},
        )
        alias = c.post(
            "/api/v1/watchdog/sessions/repo-a/actions/continue",
            json={"operator": "openclaw", "idempotency_key": "idem-continue-1"},
            headers={"Authorization": "Bearer wt"},
        )

    assert canonical.status_code == 200
    assert alias.status_code == 200
    assert steer_mock.call_count == 1
    assert canonical.json()["data"] == alias.json()["data"]
    assert canonical.json()["data"]["effect"] == "steer_posted"


def test_session_spine_action_routes_reject_empty_idempotency_key(tmp_path) -> None:
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=_client(),
    )
    c = TestClient(app)

    canonical = c.post(
        "/api/v1/watchdog/actions",
        json={
            "action_code": "continue_session",
            "project_id": "repo-a",
            "operator": "openclaw",
            "idempotency_key": "",
            "arguments": {},
        },
        headers={"Authorization": "Bearer wt"},
    )
    alias = c.post(
        "/api/v1/watchdog/sessions/repo-a/actions/continue",
        json={"operator": "openclaw", "idempotency_key": ""},
        headers={"Authorization": "Bearer wt"},
    )

    assert canonical.status_code == 200
    assert canonical.json()["success"] is False
    assert canonical.json()["error"]["code"] == "INVALID_ARGUMENT"
    assert alias.status_code == 200
    assert alias.json()["success"] is False
    assert alias.json()["error"]["code"] == "INVALID_ARGUMENT"


def test_session_spine_receipt_query_routes_share_same_stable_reply_without_reexecution(tmp_path) -> None:
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=FakeAClient(
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
    c = TestClient(app)

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}
        create_receipt = c.post(
            "/api/v1/watchdog/actions",
            json={
                "action_code": "continue_session",
                "project_id": "repo-a",
                "operator": "openclaw",
                "idempotency_key": "idem-continue-lookup-1",
                "arguments": {},
            },
            headers={"Authorization": "Bearer wt"},
        )

    assert create_receipt.status_code == 200
    assert create_receipt.json()["success"] is True
    assert steer_mock.call_count == 1

    with patch("watchdog.services.session_spine.actions.post_steer") as query_steer_mock:
        canonical = c.get(
            "/api/v1/watchdog/action-receipts",
            params={
                "action_code": "continue_session",
                "project_id": "repo-a",
                "idempotency_key": "idem-continue-lookup-1",
            },
            headers={"Authorization": "Bearer wt"},
        )
        alias = c.get(
            "/api/v1/watchdog/sessions/repo-a/action-receipts/continue_session/idem-continue-lookup-1",
            headers={"Authorization": "Bearer wt"},
        )

    assert canonical.status_code == 200
    assert alias.status_code == 200
    assert query_steer_mock.call_count == 0
    assert canonical.json()["data"] == alias.json()["data"]
    assert canonical.json()["data"]["reply_code"] == "action_receipt"
    assert canonical.json()["data"]["action_result"]["effect"] == "steer_posted"


def test_session_spine_receipt_query_route_returns_stable_not_found_reply(tmp_path) -> None:
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=_client(),
    )
    c = TestClient(app)

    response = c.get(
        "/api/v1/watchdog/action-receipts",
        params={
            "action_code": "continue_session",
            "project_id": "repo-a",
            "idempotency_key": "missing-idem",
        },
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["data"]["reply_code"] == "action_receipt_not_found"
    assert response.json()["data"]["action_result"] is None


def test_session_spine_execute_recovery_canonical_and_alias_share_the_same_result(tmp_path) -> None:
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
        }
    )
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=client,
    )
    c = TestClient(app)

    canonical = c.post(
        "/api/v1/watchdog/actions",
        json={
            "action_code": "execute_recovery",
            "project_id": "repo-a",
            "operator": "openclaw",
            "idempotency_key": "idem-execute-recovery-1",
            "arguments": {},
        },
        headers={"Authorization": "Bearer wt"},
    )
    alias = c.post(
        "/api/v1/watchdog/sessions/repo-a/actions/execute-recovery",
        json={"operator": "openclaw", "idempotency_key": "idem-execute-recovery-1"},
        headers={"Authorization": "Bearer wt"},
    )

    assert canonical.status_code == 200
    assert alias.status_code == 200
    assert client.handoff_calls == [("repo-a", "context_critical")]
    assert canonical.json()["data"] == alias.json()["data"]
    assert canonical.json()["data"]["effect"] == "handoff_triggered"
    assert canonical.json()["data"]["reply_code"] == "recovery_execution_result"


def test_session_spine_evaluate_supervision_canonical_and_alias_share_the_same_result(tmp_path) -> None:
    old = "2026-04-05T05:20:00Z"
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=FakeAClient(
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
                "last_progress_at": old,
            }
        ),
    )
    c = TestClient(app)

    with patch("watchdog.services.session_spine.supervision.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}
        canonical = c.post(
            "/api/v1/watchdog/actions",
            json={
                "action_code": "evaluate_supervision",
                "project_id": "repo-a",
                "operator": "openclaw",
                "idempotency_key": "idem-supervision-1",
                "arguments": {},
            },
            headers={"Authorization": "Bearer wt"},
        )
        alias = c.post(
            "/api/v1/watchdog/sessions/repo-a/actions/evaluate-supervision",
            json={"operator": "openclaw", "idempotency_key": "idem-supervision-1"},
            headers={"Authorization": "Bearer wt"},
        )

    assert canonical.status_code == 200
    assert alias.status_code == 200
    assert steer_mock.call_count == 1
    assert canonical.json()["data"] == alias.json()["data"]
    assert canonical.json()["data"]["reply_code"] == "supervision_evaluation"
    assert canonical.json()["data"]["supervision_evaluation"]["reason_code"] == "stuck_soft"
    assert canonical.json()["data"]["supervision_evaluation"]["steer_sent"] is True


def test_legacy_routes_remain_registered_and_basic_behaviour_is_compatible(tmp_path) -> None:
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=FakeAClient(
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
    c = TestClient(app)

    with patch("watchdog.api.approvals_proxy.httpx.Client") as approvals_http:
        approvals_inst = MagicMock()
        approvals_http.return_value.__enter__.return_value = approvals_inst
        approvals_inst.get.return_value.json.return_value = {"success": True, "data": {"items": [], "count": 0}}
        progress = c.get("/api/v1/watchdog/tasks/repo-a/progress", headers={"Authorization": "Bearer wt"})
        evaluate = c.post("/api/v1/watchdog/tasks/repo-a/evaluate", headers={"Authorization": "Bearer wt"})
        approvals = c.get("/api/v1/watchdog/approvals", headers={"Authorization": "Bearer wt"})
        recover = c.post("/api/v1/watchdog/tasks/repo-a/recover", headers={"Authorization": "Bearer wt"})
        events = c.get(
            "/api/v1/watchdog/tasks/repo-a/events?follow=false",
            headers={"Authorization": "Bearer wt"},
        )

    assert progress.status_code == 200
    assert progress.json()["success"] is True
    assert evaluate.status_code == 200
    assert evaluate.json()["success"] is True
    assert approvals.status_code == 200
    assert approvals.json()["success"] is True
    assert recover.status_code == 200
    assert recover.json()["data"]["action"] == "noop"
    assert events.status_code == 200
    assert events.headers["content-type"].startswith("text/event-stream")
