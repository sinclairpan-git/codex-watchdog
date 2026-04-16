from __future__ import annotations

import inspect
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from watchdog.main import create_app
from watchdog.settings import Settings
from watchdog.services.approvals.service import materialize_canonical_approval
from watchdog.services.delivery.envelopes import build_envelopes_for_decision
from watchdog.services.delivery.store import DeliveryOutboxStore
from watchdog.services.a_client.client import AControlAgentClient
from watchdog.services.policy.decisions import CanonicalDecisionRecord, PolicyDecisionStore
from watchdog.services.session_spine.facts import build_fact_records
from watchdog.services.session_spine.projection import (
    build_approval_projections,
    build_session_projection,
    build_task_progress_view,
    stable_thread_id_for_project,
)
from watchdog.services.session_spine.service import evaluate_session_policy_from_persisted_spine


_A_CLIENT_CONTRACT_METHODS = (
    "get_envelope",
    "get_envelope_by_thread",
    "list_tasks",
    "list_approvals",
    "decide_approval",
    "trigger_pause",
    "trigger_handoff",
    "trigger_resume",
    "get_workspace_activity_envelope",
)


def _assert_a_client_signature_compatibility(fake_client_cls: type[object]) -> None:
    for method_name in _A_CLIENT_CONTRACT_METHODS:
        assert hasattr(fake_client_cls, method_name), f"{fake_client_cls.__name__} missing {method_name}"
        fake_signature = inspect.signature(getattr(fake_client_cls, method_name))
        real_signature = inspect.signature(getattr(AControlAgentClient, method_name))
        assert tuple(fake_signature.parameters) == tuple(
            real_signature.parameters
        ), f"{fake_client_cls.__name__}.{method_name} parameter names drifted"
        for name, real_parameter in real_signature.parameters.items():
            fake_parameter = fake_signature.parameters[name]
            assert (
                fake_parameter.kind == real_parameter.kind
            ), f"{fake_client_cls.__name__}.{method_name} parameter kind drifted for {name}"
            assert (
                fake_parameter.default == real_parameter.default
            ), f"{fake_client_cls.__name__}.{method_name} default drifted for {name}"


class FakeAClient:
    def __init__(
        self,
        *,
        task: dict[str, object],
        tasks: list[dict[str, object]] | None = None,
        approvals: list[dict[str, object]] | None = None,
    ) -> None:
        self._task = dict(task)
        self._tasks = [dict(row) for row in tasks or [task]]
        self._approvals = [dict(approval) for approval in approvals or []]
        self.list_approvals_calls: list[dict[str, object | None]] = []
        self.pause_calls: list[str] = []
        self.handoff_calls: list[tuple[str, str]] = []
        self.resume_calls: list[tuple[str, str, str]] = []
        self.workspace_activity_calls: list[tuple[str, int]] = []

    def get_envelope(self, project_id: str) -> dict[str, object]:
        for task in self._tasks:
            if project_id == task["project_id"]:
                return {"success": True, "data": dict(task)}
        raise AssertionError(project_id)

    def get_envelope_by_thread(self, thread_id: str) -> dict[str, object]:
        for task in self._tasks:
            if thread_id == task["thread_id"]:
                return {"success": True, "data": dict(task)}
        raise AssertionError(thread_id)

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
        self.list_approvals_calls.append(
            {
                "status": status,
                "project_id": project_id,
                "decided_by": decided_by,
                "callback_status": callback_status,
            }
        )
        rows = [dict(approval) for approval in self._approvals]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if project_id:
            rows = [row for row in rows if row.get("project_id") == project_id]
        if decided_by:
            rows = [row for row in rows if row.get("decided_by") == decided_by]
        if callback_status:
            rows = [row for row in rows if row.get("callback_status") == callback_status]
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

    def trigger_pause(self, project_id: str) -> dict[str, object]:
        self.pause_calls.append(project_id)
        return {
            "success": True,
            "data": {"project_id": project_id, "status": "paused"},
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

    def get_workspace_activity_envelope(
        self,
        project_id: str,
        *,
        recent_minutes: int = 15,
    ) -> dict[str, object]:
        self.workspace_activity_calls.append((project_id, recent_minutes))
        return {
            "success": True,
            "data": {
                "project_id": project_id,
                "activity": {
                    "cwd_exists": True,
                    "files_scanned": 12,
                    "latest_mtime_iso": "2026-04-05T05:30:00Z",
                    "recent_change_count": 3,
                    "recent_window_minutes": recent_minutes,
                },
            },
        }


class BrokenAClient:
    def __init__(self) -> None:
        self.get_envelope_calls: list[str] = []
        self.get_envelope_by_thread_calls: list[str] = []
        self.list_approvals_calls: list[dict[str, object | None]] = []

    def get_envelope(self, project_id: str) -> dict[str, object]:
        self.get_envelope_calls.append(project_id)
        raise RuntimeError("a-side temporarily unavailable")

    def get_envelope_by_thread(self, thread_id: str) -> dict[str, object]:
        self.get_envelope_by_thread_calls.append(thread_id)
        raise RuntimeError("a-side temporarily unavailable")

    def list_approvals(
        self,
        *,
        status: str | None = None,
        project_id: str | None = None,
        decided_by: str | None = None,
        callback_status: str | None = None,
    ) -> list[dict[str, object]]:
        self.list_approvals_calls.append(
            {
                "status": status,
                "project_id": project_id,
                "decided_by": decided_by,
                "callback_status": callback_status,
            }
        )
        raise RuntimeError("a-side temporarily unavailable")

    def list_tasks(self) -> list[dict[str, object]]:
        raise RuntimeError("a-side temporarily unavailable")

    def decide_approval(
        self,
        approval_id: str,
        *,
        decision: str,
        operator: str,
        note: str = "",
    ) -> dict[str, object]:
        _ = (approval_id, decision, operator, note)
        raise RuntimeError("a-side temporarily unavailable")

    def trigger_pause(self, project_id: str) -> dict[str, object]:
        _ = project_id
        raise RuntimeError("a-side temporarily unavailable")

    def trigger_handoff(
        self,
        project_id: str,
        *,
        reason: str,
    ) -> dict[str, object]:
        _ = (project_id, reason)
        raise RuntimeError("a-side temporarily unavailable")

    def trigger_resume(
        self,
        project_id: str,
        *,
        mode: str,
        handoff_summary: str,
    ) -> dict[str, object]:
        _ = (project_id, mode, handoff_summary)
        raise RuntimeError("a-side temporarily unavailable")

    def get_workspace_activity_envelope(
        self,
        project_id: str,
        *,
        recent_minutes: int = 15,
    ) -> dict[str, object]:
        _ = (project_id, recent_minutes)
        raise RuntimeError("a-side temporarily unavailable")


def test_fake_a_client_matches_a_control_agent_client_core_signature_contract() -> None:
    _assert_a_client_signature_compatibility(FakeAClient)


def test_fake_a_client_broken_stub_matches_a_control_agent_client_core_signature_contract() -> None:
    _assert_a_client_signature_compatibility(BrokenAClient)


def _decision_record(
    *,
    project_id: str = "repo-a",
    session_id: str = "session:repo-a",
    fact_snapshot_version: str = "fact-v7",
) -> CanonicalDecisionRecord:
    return CanonicalDecisionRecord(
        decision_id=f"decision:{project_id}:{fact_snapshot_version}:require_user_decision",
        decision_key=(
            f"{session_id}|{fact_snapshot_version}|policy-v1|require_user_decision|execute_recovery|"
        ),
        session_id=session_id,
        project_id=project_id,
        thread_id=session_id,
        native_thread_id=f"native:{project_id}",
        approval_id=None,
        action_ref="execute_recovery",
        trigger="resident_supervision",
        decision_result="require_user_decision",
        risk_class="human_gate",
        decision_reason="manual approval required",
        matched_policy_rules=["registered_action"],
        why_not_escalated=None,
        why_escalated="manual decision required",
        uncertainty_reasons=[],
        policy_version="policy-v1",
        fact_snapshot_version=fact_snapshot_version,
        idempotency_key=(
            f"{session_id}|{fact_snapshot_version}|policy-v1|require_user_decision|execute_recovery|"
        ),
        created_at="2026-04-07T00:00:00Z",
        operator_notes=[],
        evidence={
            "facts": [
                {
                    "fact_id": "fact-1",
                    "fact_code": "recovery_available",
                    "fact_kind": "signal",
                    "severity": "info",
                    "summary": "recovery available",
                    "detail": "recovery available",
                    "source": "watchdog",
                    "observed_at": "2026-04-07T00:00:00Z",
                    "related_ids": {},
                }
            ],
            "matched_policy_rules": ["registered_action"],
            "decision": {
                "decision_result": "require_user_decision",
                "action_ref": "execute_recovery",
                "approval_id": None,
            },
        },
    )


def _seed_persisted_session_spine(
    root: Path,
    *,
    project_id: str = "repo-a",
    session_seq: int = 3,
    fact_snapshot_version: str = "fact-v1",
    last_refreshed_at: str = "2026-04-05T05:25:00Z",
) -> Path:
    task = {
        "project_id": project_id,
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
    }
    approvals = [
        {
            "approval_id": "appr_001",
            "project_id": project_id,
            "thread_id": "thr_native_1",
            "risk_level": "L2",
            "command": "uv run pytest",
            "reason": "verify tests",
            "alternative": "",
            "status": "pending",
            "requested_at": "2026-04-05T05:21:00Z",
        }
    ]
    facts = build_fact_records(project_id=project_id, task=task, approvals=approvals)
    session = build_session_projection(
        project_id=project_id,
        task=task,
        approvals=approvals,
        facts=facts,
    )
    progress = build_task_progress_view(
        project_id=project_id,
        task=task,
        facts=facts,
    )
    approval_queue = build_approval_projections(
        project_id=project_id,
        native_thread_id=str(task["thread_id"]),
        approvals=approvals,
    )

    payload = {
        "sessions": {
            project_id: {
                "project_id": project_id,
                "thread_id": stable_thread_id_for_project(project_id),
                "native_thread_id": task["thread_id"],
                "session_seq": session_seq,
                "fact_snapshot_version": fact_snapshot_version,
                "last_refreshed_at": last_refreshed_at,
                "session": session.model_dump(mode="json"),
                "progress": progress.model_dump(mode="json"),
                "facts": [fact.model_dump(mode="json") for fact in facts],
                "approval_queue": [
                    approval.model_dump(mode="json") for approval in approval_queue
                ],
            }
        }
    }
    path = root / "session_spine.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


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


def test_session_route_reads_seeded_persisted_spine_on_cold_start(tmp_path) -> None:
    _seed_persisted_session_spine(tmp_path)
    a_client = BrokenAClient()
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=a_client,
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions/repo-a", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    assert response.json()["success"] is True
    data = response.json()["data"]
    assert data["reply_code"] == "session_projection"
    assert data["session"]["thread_id"] == "session:repo-a"
    assert data["session"]["native_thread_id"] == "thr_native_1"
    assert [fact["fact_code"] for fact in data["facts"]] == [
        "approval_pending",
        "awaiting_human_direction",
    ]
    assert a_client.get_envelope_calls == []
    assert a_client.list_approvals_calls == []


def test_session_route_exposes_persisted_snapshot_freshness_semantics(tmp_path) -> None:
    _seed_persisted_session_spine(
        tmp_path,
        session_seq=7,
        fact_snapshot_version="fact-v7",
        last_refreshed_at="2000-01-01T00:00:00Z",
    )
    a_client = BrokenAClient()
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=a_client,
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions/repo-a", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["snapshot"]["read_source"] == "persisted_spine"
    assert data["snapshot"]["is_persisted"] is True
    assert data["snapshot"]["is_fresh"] is False
    assert data["snapshot"]["is_stale"] is True
    assert data["snapshot"]["session_seq"] == 7
    assert data["snapshot"]["fact_snapshot_version"] == "fact-v7"
    assert data["snapshot"]["last_refreshed_at"] == "2000-01-01T00:00:00Z"
    assert a_client.get_envelope_calls == []
    assert a_client.list_approvals_calls == []


def test_session_route_prefers_session_service_projection_over_persisted_spine(tmp_path) -> None:
    _seed_persisted_session_spine(tmp_path)
    a_client = BrokenAClient()
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=a_client,
    )
    approval = materialize_canonical_approval(
        _decision_record(project_id="repo-a", fact_snapshot_version="fact-v11"),
        approval_store=app.state.canonical_approval_store,
        session_service=app.state.session_service,
    )
    app.state.session_service.record_event(
        event_type="approval_approved",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id=f"corr:approval:{approval.approval_id}",
        causation_id=approval.decision.decision_id,
        related_ids={
            "approval_id": approval.approval_id,
            "decision_id": approval.decision.decision_id,
            "response_id": "approval-response:test",
        },
        payload={
            "response_action": "approve",
            "approval_status": "approved",
            "operator": "operator-1",
            "note": "approved via projected truth",
        },
        occurred_at="2026-04-12T01:02:00Z",
    )
    app.state.session_service.record_memory_conflict_detected(
        project_id="repo-a",
        session_id="session:repo-a",
        memory_scope="project",
        conflict_reason="goal_contract_version_mismatch",
        resolution="reference_only",
        causation_id="memory-sync:conflict",
        occurred_at="2026-04-12T01:03:00Z",
        related_ids={"goal_contract_version": "goal-v9"},
    )
    c = TestClient(app)

    session_response = c.get("/api/v1/watchdog/sessions/repo-a", headers={"Authorization": "Bearer wt"})
    facts_response = c.get(
        "/api/v1/watchdog/sessions/repo-a/facts",
        headers={"Authorization": "Bearer wt"},
    )
    inbox_response = c.get(
        "/api/v1/watchdog/approval-inbox?project_id=repo-a",
        headers={"Authorization": "Bearer wt"},
    )

    assert session_response.status_code == 200
    assert facts_response.status_code == 200
    assert inbox_response.status_code == 200

    session_data = session_response.json()["data"]
    facts_data = facts_response.json()["data"]
    inbox_data = inbox_response.json()["data"]

    assert session_data["snapshot"]["read_source"] == "session_events_projection"
    assert session_data["session"]["native_thread_id"] == "thr_native_1"
    assert session_data["session"]["session_state"] == "active"
    assert [fact["fact_code"] for fact in facts_data["facts"]] == ["memory_conflict_detected"]
    assert inbox_data["approvals"] == []
    assert a_client.get_envelope_calls == []
    assert a_client.list_approvals_calls == []


def test_session_route_projects_human_override_and_notification_status_from_session_events(
    tmp_path,
) -> None:
    _seed_persisted_session_spine(tmp_path)
    a_client = BrokenAClient()
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=a_client,
    )
    approval = materialize_canonical_approval(
        _decision_record(project_id="repo-a", fact_snapshot_version="fact-v11"),
        approval_store=app.state.canonical_approval_store,
        session_service=app.state.session_service,
    )
    app.state.session_service.record_event(
        event_type="approval_approved",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id=f"corr:approval:{approval.approval_id}",
        causation_id=approval.decision.decision_id,
        related_ids={
            "approval_id": approval.approval_id,
            "decision_id": approval.decision.decision_id,
            "response_id": "approval-response:test",
        },
        payload={
            "response_action": "approve",
            "approval_status": "approved",
            "operator": "operator-1",
            "note": "approved via projected truth",
        },
        occurred_at="2026-04-12T01:02:00Z",
    )
    app.state.session_service.record_event(
        event_type="human_override_recorded",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:override:approval-response:test",
        causation_id="approval-response:test",
        related_ids={
            "approval_id": approval.approval_id,
            "decision_id": approval.decision.decision_id,
            "response_id": "approval-response:test",
            "envelope_id": approval.envelope_id,
        },
        payload={
            "response_action": "approve",
            "approval_status": "approved",
            "operator": "operator-1",
            "note": "looks safe",
            "requested_action": approval.requested_action,
            "execution_status": "completed",
            "execution_effect": "handoff_triggered",
        },
        occurred_at="2026-04-12T01:03:00Z",
    )
    app.state.session_service.record_event(
        event_type="notification_receipt_recorded",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id=f"corr:notification:{approval.envelope_id}:receipt:receipt:test",
        causation_id=approval.envelope_id,
        related_ids={
            "envelope_id": approval.envelope_id,
            "notification_kind": "approval_result",
            "receipt_id": "receipt:test",
        },
        payload={
            "delivery_status": "delivered",
            "delivery_attempt": 1,
            "receipt_id": "receipt:test",
            "received_at": "2026-04-12T01:03:30Z",
        },
        occurred_at="2026-04-12T01:04:00Z",
    )
    c = TestClient(app)

    session_response = c.get("/api/v1/watchdog/sessions/repo-a", headers={"Authorization": "Bearer wt"})
    facts_response = c.get(
        "/api/v1/watchdog/sessions/repo-a/facts",
        headers={"Authorization": "Bearer wt"},
    )

    assert session_response.status_code == 200
    assert facts_response.status_code == 200

    session_data = session_response.json()["data"]
    facts_data = facts_response.json()["data"]

    assert session_data["snapshot"]["read_source"] == "session_events_projection"
    assert [fact["fact_code"] for fact in facts_data["facts"]] == [
        "human_override_recorded",
        "notification_receipt_recorded",
    ]
    assert session_data["facts"] == facts_data["facts"]
    assert facts_data["facts"][0]["related_ids"]["approval_id"] == approval.approval_id
    assert facts_data["facts"][1]["related_ids"]["receipt_id"] == "receipt:test"
    assert a_client.get_envelope_calls == []
    assert a_client.list_approvals_calls == []


def test_persisted_session_overlay_exposes_canonical_approval_across_stable_read_surfaces(
    tmp_path,
) -> None:
    a_client = BrokenAClient()
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=a_client,
    )
    task = {
        "project_id": "repo-a",
        "thread_id": "thr_native_1",
        "status": "running",
        "phase": "editing_source",
        "pending_approval": False,
        "last_summary": "waiting for bridge recovery",
        "files_touched": ["src/example.py"],
        "context_pressure": "critical",
        "stuck_level": 2,
        "failure_count": 3,
        "last_progress_at": "2026-04-05T05:20:00Z",
    }
    facts = build_fact_records(project_id="repo-a", task=task, approvals=[])
    session = build_session_projection(
        project_id="repo-a",
        task=task,
        approvals=[],
        facts=facts,
    )
    progress = build_task_progress_view(
        project_id="repo-a",
        task=task,
        facts=facts,
    )
    app.state.session_spine_store.put(
        project_id="repo-a",
        session=session,
        progress=progress,
        facts=facts,
        approval_queue=[],
        last_refreshed_at="2026-04-05T05:25:00Z",
    )
    decision = evaluate_session_policy_from_persisted_spine(
        "repo-a",
        action_ref="execute_recovery",
        trigger="resident_supervision",
        store=app.state.session_spine_store,
    )
    approval = materialize_canonical_approval(
        decision,
        approval_store=app.state.canonical_approval_store,
    )

    c = TestClient(app)

    session_resp = c.get("/api/v1/watchdog/sessions/repo-a", headers={"Authorization": "Bearer wt"})
    approvals_resp = c.get(
        "/api/v1/watchdog/sessions/repo-a/pending-approvals",
        headers={"Authorization": "Bearer wt"},
    )
    inbox_resp = c.get(
        "/api/v1/watchdog/approval-inbox?project_id=repo-a",
        headers={"Authorization": "Bearer wt"},
    )
    directory_resp = c.get("/api/v1/watchdog/sessions", headers={"Authorization": "Bearer wt"})

    assert session_resp.status_code == 200
    assert approvals_resp.status_code == 200
    assert inbox_resp.status_code == 200
    assert directory_resp.status_code == 200

    session_data = session_resp.json()["data"]
    approvals_data = approvals_resp.json()["data"]
    inbox_data = inbox_resp.json()["data"]
    directory_data = directory_resp.json()["data"]

    assert session_data["session"]["pending_approval_count"] == 1
    assert session_data["session"]["session_state"] == "awaiting_approval"
    assert "approve_approval" in session_data["session"]["available_intents"]
    assert [item["approval_id"] for item in approvals_data["approvals"]] == [approval.approval_id]
    assert approvals_data["approvals"][0]["command"] == "execute_recovery"
    assert [item["approval_id"] for item in inbox_data["approvals"]] == [approval.approval_id]
    assert directory_data["sessions"][0]["pending_approval_count"] == 1
    assert a_client.get_envelope_calls == []
    assert a_client.list_approvals_calls == []


def test_policy_evaluation_reads_only_persisted_session_spine_without_a_side_fallback(
    tmp_path,
) -> None:
    _seed_persisted_session_spine(tmp_path, fact_snapshot_version="fact-v9")
    a_client = BrokenAClient()
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=a_client,
    )

    decision = evaluate_session_policy_from_persisted_spine(
        "repo-a",
        action_ref="continue_session",
        trigger="resident_supervision",
        store=app.state.session_spine_store,
    )

    assert decision.decision_result == "require_user_decision"
    assert decision.risk_class == "human_gate"
    assert decision.fact_snapshot_version == "fact-v9"
    assert decision.matched_policy_rules == ["human_gate"]
    assert a_client.get_envelope_calls == []
    assert a_client.get_envelope_by_thread_calls == []
    assert a_client.list_approvals_calls == []


def test_policy_evaluation_reuses_canonical_decision_for_same_persisted_snapshot(
    tmp_path,
) -> None:
    _seed_persisted_session_spine(tmp_path, fact_snapshot_version="fact-v12")
    a_client = BrokenAClient()
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=a_client,
    )
    decision_store = PolicyDecisionStore(tmp_path / "policy_decisions.json")

    first = evaluate_session_policy_from_persisted_spine(
        "repo-a",
        action_ref="continue_session",
        trigger="resident_supervision",
        store=app.state.session_spine_store,
        decision_store=decision_store,
    )
    second = evaluate_session_policy_from_persisted_spine(
        "repo-a",
        action_ref="continue_session",
        trigger="resident_supervision",
        store=app.state.session_spine_store,
        decision_store=decision_store,
    )

    assert first.decision_key == second.decision_key
    assert first.decision_id == second.decision_id
    assert len(decision_store.list_records()) == 1
    assert a_client.get_envelope_calls == []
    assert a_client.get_envelope_by_thread_calls == []
    assert a_client.list_approvals_calls == []


def test_policy_evaluation_enqueues_delivery_envelopes_from_persisted_decision(
    tmp_path,
) -> None:
    _seed_persisted_session_spine(tmp_path, fact_snapshot_version="fact-v12")
    a_client = BrokenAClient()
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=a_client,
    )
    decision_store = PolicyDecisionStore(tmp_path / "policy_decisions.json")
    delivery_store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")

    decision = evaluate_session_policy_from_persisted_spine(
        "repo-a",
        action_ref="continue_session",
        trigger="resident_supervision",
        store=app.state.session_spine_store,
        decision_store=decision_store,
        delivery_outbox_store=delivery_store,
    )

    pending = delivery_store.list_pending_delivery_records(session_id=decision.session_id)

    assert decision.decision_result == "require_user_decision"
    assert [record.envelope_type for record in pending] == ["approval"]
    assert pending[0].envelope_payload["requested_action"] == "continue_session"


def test_session_spine_facts_route_returns_stable_truth_source_without_touching_explanations(
    tmp_path,
) -> None:
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=_client(),
    )
    c = TestClient(app)

    facts_response = c.get(
        "/api/v1/watchdog/sessions/repo-a/facts",
        headers={"Authorization": "Bearer wt"},
    )
    session_response = c.get(
        "/api/v1/watchdog/sessions/repo-a",
        headers={"Authorization": "Bearer wt"},
    )
    stuck_response = c.get(
        "/api/v1/watchdog/sessions/repo-a/stuck-explanation",
        headers={"Authorization": "Bearer wt"},
    )
    blocker_response = c.get(
        "/api/v1/watchdog/sessions/repo-a/blocker-explanation",
        headers={"Authorization": "Bearer wt"},
    )

    assert facts_response.status_code == 200
    assert session_response.status_code == 200
    assert stuck_response.status_code == 200
    assert blocker_response.status_code == 200

    facts_data = facts_response.json()["data"]
    session_data = session_response.json()["data"]
    stuck_data = stuck_response.json()["data"]
    blocker_data = blocker_response.json()["data"]

    assert facts_data["reply_kind"] == "facts"
    assert facts_data["reply_code"] == "session_facts"
    assert facts_data["intent_code"] == "list_session_facts"
    assert facts_data["message"] == "2 fact(s)"
    assert [fact["fact_code"] for fact in facts_data["facts"]] == [
        "approval_pending",
        "awaiting_human_direction",
    ]
    assert facts_data["facts"] == session_data["facts"]
    assert stuck_data["reply_code"] == "stuck_explanation"
    assert blocker_data["reply_code"] == "blocker_explanation"


def test_facts_and_blocker_reads_fall_back_to_persisted_spine_when_a_side_disconnects(
    tmp_path,
) -> None:
    _seed_persisted_session_spine(tmp_path)
    a_client = BrokenAClient()
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=a_client,
    )
    c = TestClient(app)

    facts_response = c.get(
        "/api/v1/watchdog/sessions/repo-a/facts",
        headers={"Authorization": "Bearer wt"},
    )
    blocker_response = c.get(
        "/api/v1/watchdog/sessions/repo-a/blocker-explanation",
        headers={"Authorization": "Bearer wt"},
    )

    assert facts_response.status_code == 200
    assert blocker_response.status_code == 200
    assert facts_response.json()["success"] is True
    assert blocker_response.json()["success"] is True

    facts_data = facts_response.json()["data"]
    blocker_data = blocker_response.json()["data"]

    assert facts_data["reply_code"] == "session_facts"
    assert facts_data["message"] == "2 fact(s)"
    assert [fact["fact_code"] for fact in facts_data["facts"]] == [
        "approval_pending",
        "awaiting_human_direction",
    ]
    assert blocker_data["reply_code"] == "blocker_explanation"
    assert blocker_data["session"]["thread_id"] == "session:repo-a"
    assert blocker_data["progress"]["thread_id"] == "session:repo-a"
    assert a_client.get_envelope_calls == []
    assert a_client.list_approvals_calls == []


def test_session_directory_route_returns_stable_session_projections(tmp_path) -> None:
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
            },
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
                    "last_progress_at": "2026-04-05T05:20:00Z",
                },
                {
                    "project_id": "repo-b",
                    "thread_id": "thr_native_2",
                    "status": "waiting_human",
                    "phase": "approval",
                    "pending_approval": True,
                    "approval_risk": "L2",
                    "last_summary": "waiting for approval",
                    "files_touched": [],
                    "context_pressure": "low",
                    "stuck_level": 0,
                    "failure_count": 0,
                    "last_progress_at": "2026-04-05T05:21:00Z",
                },
            ],
            approvals=[
                {
                    "approval_id": "appr_001",
                    "project_id": "repo-b",
                    "thread_id": "thr_native_2",
                    "risk_level": "L2",
                    "command": "uv run pytest",
                    "reason": "verify tests",
                    "alternative": "",
                    "status": "pending",
                    "requested_at": "2026-04-05T05:22:00Z",
                }
            ],
        ),
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["reply_code"] == "session_directory"
    assert [item["project_id"] for item in data["sessions"]] == ["repo-a", "repo-b"]
    assert [item["thread_id"] for item in data["sessions"]] == ["session:repo-a", "session:repo-b"]
    assert data["sessions"][1]["pending_approval_count"] == 1
    assert "list_pending_approvals" in data["sessions"][1]["available_intents"]


def test_session_by_native_thread_route_returns_stable_session_projection(tmp_path) -> None:
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=_client(),
    )
    c = TestClient(app)

    response = c.get(
        "/api/v1/watchdog/sessions/by-native-thread/thr_native_1",
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    data = response.json()["data"]
    assert data["reply_code"] == "session_projection"
    assert data["intent_code"] == "get_session_by_native_thread"
    assert data["session"]["project_id"] == "repo-a"
    assert data["session"]["thread_id"] == "session:repo-a"
    assert data["session"]["native_thread_id"] == "thr_native_1"
    assert [fact["fact_code"] for fact in data["facts"]] == [
        "approval_pending",
        "awaiting_human_direction",
    ]


def test_workspace_activity_route_returns_stable_workspace_activity_view(tmp_path) -> None:
    a_client = _client()
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=a_client,
    )
    c = TestClient(app)

    response = c.get(
        "/api/v1/watchdog/sessions/repo-a/workspace-activity?recent_minutes=30",
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["reply_code"] == "workspace_activity_view"
    assert data["intent_code"] == "get_workspace_activity"
    assert data["session"]["project_id"] == "repo-a"
    assert data["workspace_activity"]["recent_window_minutes"] == 30
    assert data["workspace_activity"]["recent_change_count"] == 3
    assert a_client.workspace_activity_calls == [("repo-a", 30)]


def test_session_event_snapshot_route_returns_stable_reply_model(tmp_path) -> None:
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=_client(),
    )
    c = TestClient(app)

    response = c.get(
        "/api/v1/watchdog/sessions/repo-a/event-snapshot",
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["reply_kind"] == "events"
    assert data["reply_code"] == "session_event_snapshot"
    assert data["intent_code"] == "list_session_events"
    assert len(data["events"]) == 1
    assert data["events"][0]["event_code"] == "session_updated"
    assert data["events"][0]["thread_id"] == "session:repo-a"
    assert "payload_json" not in data["events"][0]


def test_approval_inbox_route_returns_stable_reply_and_optional_project_filter(tmp_path) -> None:
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=FakeAClient(
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
                },
                {
                    "approval_id": "appr_002",
                    "project_id": "repo-b",
                    "thread_id": "thr_native_2",
                    "risk_level": "L3",
                    "command": "uv run ruff check",
                    "reason": "lint gate",
                    "alternative": "",
                    "status": "pending",
                    "requested_at": "2026-04-05T05:22:00Z",
                },
                {
                    "approval_id": "appr_003",
                    "project_id": "repo-c",
                    "thread_id": "thr_native_3",
                    "risk_level": "L1",
                    "command": "echo ok",
                    "reason": "already handled",
                    "alternative": "",
                    "status": "approved",
                    "requested_at": "2026-04-05T05:23:00Z",
                },
            ],
        ),
    )
    c = TestClient(app)

    inbox_resp = c.get("/api/v1/watchdog/approval-inbox", headers={"Authorization": "Bearer wt"})
    repo_a_resp = c.get(
        "/api/v1/watchdog/approval-inbox?project_id=repo-a",
        headers={"Authorization": "Bearer wt"},
    )

    assert inbox_resp.status_code == 200
    assert repo_a_resp.status_code == 200

    inbox_data = inbox_resp.json()["data"]
    repo_a_data = repo_a_resp.json()["data"]

    assert inbox_data["reply_code"] == "approval_inbox"
    assert [item["approval_id"] for item in inbox_data["approvals"]] == ["appr_001", "appr_002"]
    assert [item["project_id"] for item in inbox_data["approvals"]] == ["repo-a", "repo-b"]
    assert [item["thread_id"] for item in inbox_data["approvals"]] == ["session:repo-a", "session:repo-b"]

    assert repo_a_data["reply_code"] == "approval_inbox"
    assert [item["approval_id"] for item in repo_a_data["approvals"]] == ["appr_001"]
    assert repo_a_data["approvals"][0]["native_thread_id"] == "thr_native_1"


def test_deferred_policy_auto_approval_is_visible_across_stable_session_surfaces(tmp_path) -> None:
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=FakeAClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "callback delivery must be replayed",
                "files_touched": ["src/example.py"],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T05:20:00Z",
            },
            approvals=[
                {
                    "approval_id": "appr_deferred",
                    "project_id": "repo-a",
                    "thread_id": "thr_native_1",
                    "risk_level": "L1",
                    "command": "pytest -q",
                    "reason": "callback replay",
                    "alternative": "",
                    "status": "approved",
                    "decided_by": "policy-auto",
                    "callback_status": "deferred",
                    "requested_at": "2026-04-05T05:21:00Z",
                },
                {
                    "approval_id": "appr_delivered",
                    "project_id": "repo-a",
                    "thread_id": "thr_native_1",
                    "risk_level": "L1",
                    "command": "pytest -q",
                    "reason": "already delivered",
                    "alternative": "",
                    "status": "approved",
                    "decided_by": "policy-auto",
                    "callback_status": "delivered",
                    "requested_at": "2026-04-05T05:22:00Z",
                },
            ],
        ),
    )
    c = TestClient(app)

    session_resp = c.get("/api/v1/watchdog/sessions/repo-a", headers={"Authorization": "Bearer wt"})
    progress_resp = c.get("/api/v1/watchdog/sessions/repo-a/progress", headers={"Authorization": "Bearer wt"})
    approvals_resp = c.get(
        "/api/v1/watchdog/sessions/repo-a/pending-approvals",
        headers={"Authorization": "Bearer wt"},
    )
    inbox_resp = c.get(
        "/api/v1/watchdog/approval-inbox?project_id=repo-a",
        headers={"Authorization": "Bearer wt"},
    )

    assert session_resp.status_code == 200
    assert progress_resp.status_code == 200
    assert approvals_resp.status_code == 200
    assert inbox_resp.status_code == 200

    session_data = session_resp.json()["data"]
    progress_data = progress_resp.json()["data"]
    approvals_data = approvals_resp.json()["data"]
    inbox_data = inbox_resp.json()["data"]

    assert session_data["session"]["pending_approval_count"] == 1
    assert "approve_approval" in session_data["session"]["available_intents"]
    assert "reject_approval" not in session_data["session"]["available_intents"]
    assert [fact["fact_code"] for fact in session_data["facts"]] == [
        "approval_pending",
        "awaiting_human_direction",
    ]
    assert progress_data["progress"]["blocker_fact_codes"] == [
        "approval_pending",
        "awaiting_human_direction",
    ]
    assert [item["approval_id"] for item in approvals_data["approvals"]] == ["appr_deferred"]
    assert [item["approval_id"] for item in inbox_data["approvals"]] == ["appr_deferred"]


def test_session_spine_reads_only_targeted_actionable_approval_slices(tmp_path) -> None:
    a_client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "waiting for callback replay",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        approvals=[
            {
                "approval_id": "appr_pending",
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "risk_level": "L2",
                "command": "uv run pytest",
                "reason": "verify tests",
                "alternative": "",
                "status": "pending",
                "requested_at": "2026-04-05T05:21:00Z",
            },
            {
                "approval_id": "appr_deferred",
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "risk_level": "L1",
                "command": "pytest -q",
                "reason": "callback replay",
                "alternative": "",
                "status": "approved",
                "decided_by": "policy-auto",
                "callback_status": "deferred",
                "requested_at": "2026-04-05T05:22:00Z",
            },
            {
                "approval_id": "appr_delivered",
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "risk_level": "L1",
                "command": "pytest -q",
                "reason": "already delivered",
                "alternative": "",
                "status": "approved",
                "decided_by": "policy-auto",
                "callback_status": "delivered",
                "requested_at": "2026-04-05T05:23:00Z",
            },
        ],
    )
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=a_client,
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions/repo-a", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    assert a_client.list_approvals_calls == [
        {
            "status": "pending",
            "project_id": "repo-a",
            "decided_by": None,
            "callback_status": None,
        },
        {
            "status": "approved",
            "project_id": "repo-a",
            "decided_by": "policy-auto",
            "callback_status": "deferred",
        },
    ]


def test_session_spine_falls_back_to_pending_slice_when_deferred_retry_fetch_fails(tmp_path) -> None:
    class PartialFailureAClient(FakeAClient):
        def list_approvals(
            self,
            *,
            status: str | None = None,
            project_id: str | None = None,
            decided_by: str | None = None,
            callback_status: str | None = None,
        ) -> list[dict[str, object]]:
            if (
                status == "approved"
                and decided_by == "policy-auto"
                and callback_status == "deferred"
            ):
                raise RuntimeError("transient deferred slice failure")
            return super().list_approvals(
                status=status,
                project_id=project_id,
                decided_by=decided_by,
                callback_status=callback_status,
            )

    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=PartialFailureAClient(
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
                    "approval_id": "appr_pending",
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
        ),
    )
    c = TestClient(app)

    session_response = c.get("/api/v1/watchdog/sessions/repo-a", headers={"Authorization": "Bearer wt"})
    approvals_response = c.get(
        "/api/v1/watchdog/sessions/repo-a/pending-approvals",
        headers={"Authorization": "Bearer wt"},
    )

    assert session_response.status_code == 200
    assert approvals_response.status_code == 200
    session_data = session_response.json()["data"]
    approvals_data = approvals_response.json()["data"]
    assert session_data["session"]["pending_approval_count"] == 1
    assert [item["approval_id"] for item in approvals_data["approvals"]] == ["appr_pending"]


def test_session_spine_falls_back_to_project_approved_slice_when_targeted_deferred_retry_fails(
    tmp_path,
) -> None:
    class PartialDeferredSliceFailureAClient(FakeAClient):
        def list_approvals(
            self,
            *,
            status: str | None = None,
            project_id: str | None = None,
            decided_by: str | None = None,
            callback_status: str | None = None,
        ) -> list[dict[str, object]]:
            if (
                status == "approved"
                and decided_by == "policy-auto"
                and callback_status == "deferred"
            ):
                raise RuntimeError("transient targeted deferred slice failure")
            return super().list_approvals(
                status=status,
                project_id=project_id,
                decided_by=decided_by,
                callback_status=callback_status,
            )

    a_client = PartialDeferredSliceFailureAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "callback replay pending",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        approvals=[
            {
                "approval_id": "appr_deferred",
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "risk_level": "L1",
                "command": "pytest -q",
                "reason": "callback replay",
                "alternative": "",
                "status": "approved",
                "decided_by": "policy-auto",
                "callback_status": "deferred",
                "requested_at": "2026-04-05T05:21:00Z",
            },
            {
                "approval_id": "appr_delivered",
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "risk_level": "L1",
                "command": "pytest -q",
                "reason": "already delivered",
                "alternative": "",
                "status": "approved",
                "decided_by": "policy-auto",
                "callback_status": "delivered",
                "requested_at": "2026-04-05T05:22:00Z",
            },
        ],
    )
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=a_client,
    )
    c = TestClient(app)

    session_response = c.get("/api/v1/watchdog/sessions/repo-a", headers={"Authorization": "Bearer wt"})
    approvals_response = c.get(
        "/api/v1/watchdog/sessions/repo-a/pending-approvals",
        headers={"Authorization": "Bearer wt"},
    )

    assert session_response.status_code == 200
    assert approvals_response.status_code == 200
    session_data = session_response.json()["data"]
    approvals_data = approvals_response.json()["data"]
    assert session_data["session"]["pending_approval_count"] == 1
    assert [item["approval_id"] for item in approvals_data["approvals"]] == ["appr_deferred"]
    assert a_client.list_approvals_calls == [
        {
            "status": "pending",
            "project_id": "repo-a",
            "decided_by": None,
            "callback_status": None,
        },
        {
            "status": "approved",
            "project_id": "repo-a",
            "decided_by": None,
            "callback_status": None,
        },
        {
            "status": "pending",
            "project_id": "repo-a",
            "decided_by": None,
            "callback_status": None,
        },
        {
            "status": "approved",
            "project_id": "repo-a",
            "decided_by": None,
            "callback_status": None,
        },
    ]


def test_session_spine_reapplies_project_filter_when_upstream_ignores_it(tmp_path) -> None:
    class LegacyFilterAClient(FakeAClient):
        def list_approvals(
            self,
            *,
            status: str | None = None,
            project_id: str | None = None,
            decided_by: str | None = None,
            callback_status: str | None = None,
        ) -> list[dict[str, object]]:
            self.list_approvals_calls.append(
                {
                    "status": status,
                    "project_id": project_id,
                    "decided_by": decided_by,
                    "callback_status": callback_status,
                }
            )
            rows = [dict(approval) for approval in self._approvals]
            if status:
                rows = [row for row in rows if row.get("status") == status]
            if decided_by:
                rows = [row for row in rows if row.get("decided_by") == decided_by]
            if callback_status:
                rows = [row for row in rows if row.get("callback_status") == callback_status]
            return rows

    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=LegacyFilterAClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "waiting for callback replay",
                "files_touched": ["src/example.py"],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T05:20:00Z",
            },
            approvals=[
                {
                    "approval_id": "appr_pending_repo_a",
                    "project_id": "repo-a",
                    "thread_id": "thr_native_1",
                    "risk_level": "L2",
                    "command": "uv run pytest",
                    "reason": "verify tests",
                    "alternative": "",
                    "status": "pending",
                    "requested_at": "2026-04-05T05:21:00Z",
                },
                {
                    "approval_id": "appr_pending_repo_b",
                    "project_id": "repo-b",
                    "thread_id": "thr_native_2",
                    "risk_level": "L3",
                    "command": "uv run ruff check",
                    "reason": "other project",
                    "alternative": "",
                    "status": "pending",
                    "requested_at": "2026-04-05T05:22:00Z",
                },
                {
                    "approval_id": "appr_deferred_repo_a",
                    "project_id": "repo-a",
                    "thread_id": "thr_native_1",
                    "risk_level": "L1",
                    "command": "pytest -q",
                    "reason": "callback replay",
                    "alternative": "",
                    "status": "approved",
                    "decided_by": "policy-auto",
                    "callback_status": "deferred",
                    "requested_at": "2026-04-05T05:23:00Z",
                },
                {
                    "approval_id": "appr_deferred_repo_b",
                    "project_id": "repo-b",
                    "thread_id": "thr_native_2",
                    "risk_level": "L1",
                    "command": "pytest -q",
                    "reason": "other project replay",
                    "alternative": "",
                    "status": "approved",
                    "decided_by": "policy-auto",
                    "callback_status": "deferred",
                    "requested_at": "2026-04-05T05:24:00Z",
                },
            ],
        ),
    )
    c = TestClient(app)

    session_response = c.get("/api/v1/watchdog/sessions/repo-a", headers={"Authorization": "Bearer wt"})
    approvals_response = c.get(
        "/api/v1/watchdog/sessions/repo-a/pending-approvals",
        headers={"Authorization": "Bearer wt"},
    )
    inbox_response = c.get(
        "/api/v1/watchdog/approval-inbox?project_id=repo-a",
        headers={"Authorization": "Bearer wt"},
    )

    assert session_response.status_code == 200
    assert approvals_response.status_code == 200
    assert inbox_response.status_code == 200

    session_data = session_response.json()["data"]
    approvals_data = approvals_response.json()["data"]
    inbox_data = inbox_response.json()["data"]

    assert session_data["session"]["pending_approval_count"] == 2
    assert [item["approval_id"] for item in approvals_data["approvals"]] == [
        "appr_pending_repo_a",
        "appr_deferred_repo_a",
    ]
    assert [item["approval_id"] for item in inbox_data["approvals"]] == [
        "appr_pending_repo_a",
        "appr_deferred_repo_a",
    ]


def test_actionable_approvals_are_globally_sorted_by_requested_at(tmp_path) -> None:
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=FakeAClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "callback replay pending",
                "files_touched": ["src/example.py"],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T05:20:00Z",
            },
            approvals=[
                {
                    "approval_id": "appr_pending_oldest",
                    "project_id": "repo-a",
                    "thread_id": "thr_native_1",
                    "risk_level": "L2",
                    "command": "uv run pytest",
                    "reason": "verify tests",
                    "alternative": "",
                    "status": "pending",
                    "requested_at": "2026-04-05T05:21:00Z",
                },
                {
                    "approval_id": "appr_pending_newest",
                    "project_id": "repo-a",
                    "thread_id": "thr_native_1",
                    "risk_level": "L2",
                    "command": "uv run ruff check",
                    "reason": "lint gate",
                    "alternative": "",
                    "status": "pending",
                    "requested_at": "2026-04-05T05:23:00Z",
                },
                {
                    "approval_id": "appr_deferred_middle",
                    "project_id": "repo-a",
                    "thread_id": "thr_native_1",
                    "risk_level": "L1",
                    "command": "pytest -q",
                    "reason": "callback replay",
                    "alternative": "",
                    "status": "approved",
                    "decided_by": "policy-auto",
                    "callback_status": "deferred",
                    "requested_at": "2026-04-05T05:22:00Z",
                },
            ],
        ),
    )
    c = TestClient(app)

    response = c.get(
        "/api/v1/watchdog/approval-inbox?project_id=repo-a",
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert [item["approval_id"] for item in data["approvals"]] == [
        "appr_pending_oldest",
        "appr_deferred_middle",
        "appr_pending_newest",
    ]


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


def test_session_spine_continue_retries_after_rejected_steer_without_caching_receipt(tmp_path) -> None:
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
        steer_mock.side_effect = [
            {
                "success": False,
                "error": {"code": "STEER_REJECTED", "message": "A side rejected steer"},
            },
            {"success": True, "data": {"accepted": True}},
        ]
        first = c.post(
            "/api/v1/watchdog/actions",
            json={
                "action_code": "continue_session",
                "project_id": "repo-a",
                "operator": "openclaw",
                "idempotency_key": "idem-continue-rejected-1",
                "arguments": {},
            },
            headers={"Authorization": "Bearer wt"},
        )
        second = c.post(
            "/api/v1/watchdog/actions",
            json={
                "action_code": "continue_session",
                "project_id": "repo-a",
                "operator": "openclaw",
                "idempotency_key": "idem-continue-rejected-1",
                "arguments": {},
            },
            headers={"Authorization": "Bearer wt"},
        )

    assert first.status_code == 200
    assert first.json()["success"] is False
    assert first.json()["error"] == {
        "code": "STEER_REJECTED",
        "message": "A side rejected steer",
    }
    assert second.status_code == 200
    assert second.json()["success"] is True
    assert second.json()["data"]["effect"] == "steer_posted"
    assert steer_mock.call_count == 2


def test_session_spine_operator_guidance_canonical_and_alias_share_the_same_result(tmp_path) -> None:
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
                "stuck_level": 1,
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
                "action_code": "post_operator_guidance",
                "project_id": "repo-a",
                "operator": "openclaw",
                "idempotency_key": "idem-guidance-api-1",
                "arguments": {
                    "message": "Summarize the current blocker and next command.",
                    "reason_code": "operator_guidance",
                    "stuck_level": 2,
                },
            },
            headers={"Authorization": "Bearer wt"},
        )
        alias = c.post(
            "/api/v1/watchdog/sessions/repo-a/actions/post-guidance",
            json={
                "operator": "openclaw",
                "idempotency_key": "idem-guidance-api-1",
                "message": "Summarize the current blocker and next command.",
                "reason_code": "operator_guidance",
                "stuck_level": 2,
            },
            headers={"Authorization": "Bearer wt"},
        )

    assert canonical.status_code == 200
    assert alias.status_code == 200
    assert steer_mock.call_count == 1
    assert canonical.json()["data"] == alias.json()["data"]
    assert canonical.json()["data"]["action_code"] == "post_operator_guidance"
    assert canonical.json()["data"]["effect"] == "steer_posted"


def test_session_spine_operator_guidance_surfaces_rejected_steer_envelope(tmp_path) -> None:
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
                "stuck_level": 1,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T05:20:00Z",
            }
        ),
    )
    c = TestClient(app)

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        steer_mock.return_value = {
            "success": False,
            "error": {"code": "STEER_REJECTED", "message": "A side rejected guidance"},
        }
        response = c.post(
            "/api/v1/watchdog/actions",
            json={
                "action_code": "post_operator_guidance",
                "project_id": "repo-a",
                "operator": "openclaw",
                "idempotency_key": "idem-guidance-rejected-1",
                "arguments": {
                    "message": "Summarize the blocker.",
                    "reason_code": "operator_guidance",
                },
            },
            headers={"Authorization": "Bearer wt"},
        )

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["error"] == {
        "code": "STEER_REJECTED",
        "message": "A side rejected guidance",
    }
    assert steer_mock.call_count == 1


def test_session_spine_operator_guidance_requires_non_empty_message(tmp_path) -> None:
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=_client(),
    )
    c = TestClient(app)

    canonical = c.post(
        "/api/v1/watchdog/actions",
        json={
            "action_code": "post_operator_guidance",
            "project_id": "repo-a",
            "operator": "openclaw",
            "idempotency_key": "idem-guidance-api-2",
            "arguments": {},
        },
        headers={"Authorization": "Bearer wt"},
    )
    alias = c.post(
        "/api/v1/watchdog/sessions/repo-a/actions/post-guidance",
        json={"operator": "openclaw", "idempotency_key": "idem-guidance-api-3"},
        headers={"Authorization": "Bearer wt"},
    )

    assert canonical.status_code == 200
    assert canonical.json()["success"] is True
    assert canonical.json()["data"]["action_status"] == "error"
    assert canonical.json()["data"]["reply_code"] == "action_not_available"
    assert alias.status_code == 200
    assert alias.json()["success"] is True
    assert alias.json()["data"]["action_status"] == "error"
    assert alias.json()["data"]["reply_code"] == "action_not_available"


def test_session_spine_alias_route_rejects_non_object_arguments_without_500(tmp_path) -> None:
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=_client(),
    )
    c = TestClient(app)

    response = c.post(
        "/api/v1/watchdog/sessions/repo-a/actions/continue",
        json={
            "operator": "openclaw",
            "idempotency_key": "idem-alias-invalid-args-1",
            "arguments": "not-an-object",
        },
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["error"] == {
        "code": "INVALID_ARGUMENT",
        "message": "body must satisfy WatchdogAction",
    }


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


def test_watchdog_restart_preserves_pending_approvals_on_stable_read_surfaces(tmp_path: Path) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    first_app = create_app(settings, a_client=BrokenAClient())
    task = {
        "project_id": "repo-a",
        "thread_id": "thr_native_1",
        "status": "running",
        "phase": "editing_source",
        "pending_approval": False,
        "last_summary": "waiting for recovery approval",
        "files_touched": ["src/example.py"],
        "context_pressure": "critical",
        "stuck_level": 2,
        "failure_count": 1,
        "last_progress_at": "2026-04-05T05:20:00Z",
    }
    facts = build_fact_records(project_id="repo-a", task=task, approvals=[])
    session = build_session_projection(
        project_id="repo-a",
        task=task,
        approvals=[],
        facts=facts,
    )
    progress = build_task_progress_view(
        project_id="repo-a",
        task=task,
        facts=facts,
    )
    first_app.state.session_spine_store.put(
        project_id="repo-a",
        session=session,
        progress=progress,
        facts=facts,
        approval_queue=[],
        last_refreshed_at="2026-04-05T05:25:00Z",
    )
    approval = materialize_canonical_approval(
        _decision_record(project_id="repo-a", fact_snapshot_version="fact-v10"),
        approval_store=first_app.state.canonical_approval_store,
    )

    restarted = create_app(settings, a_client=BrokenAClient())
    c = TestClient(restarted)

    session_resp = c.get("/api/v1/watchdog/sessions/repo-a", headers={"Authorization": "Bearer wt"})
    approvals_resp = c.get(
        "/api/v1/watchdog/sessions/repo-a/pending-approvals",
        headers={"Authorization": "Bearer wt"},
    )
    inbox_resp = c.get(
        "/api/v1/watchdog/approval-inbox?project_id=repo-a",
        headers={"Authorization": "Bearer wt"},
    )

    assert session_resp.status_code == 200
    assert approvals_resp.status_code == 200
    assert inbox_resp.status_code == 200
    assert session_resp.json()["data"]["session"]["pending_approval_count"] == 1
    assert [item["approval_id"] for item in approvals_resp.json()["data"]["approvals"]] == [
        approval.approval_id
    ]
    assert [item["approval_id"] for item in inbox_resp.json()["data"]["approvals"]] == [
        approval.approval_id
    ]


def test_watchdog_restart_preserves_action_receipt_lookup_without_reexecution(tmp_path: Path) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    first_app = create_app(
        settings,
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
    first_client = TestClient(first_app)

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}
        create_receipt = first_client.post(
            "/api/v1/watchdog/actions",
            json={
                "action_code": "continue_session",
                "project_id": "repo-a",
                "operator": "openclaw",
                "idempotency_key": "idem-restart-receipt-1",
                "arguments": {},
            },
            headers={"Authorization": "Bearer wt"},
        )

    assert create_receipt.status_code == 200
    assert create_receipt.json()["success"] is True

    restarted = create_app(settings, a_client=BrokenAClient())
    c = TestClient(restarted)

    with patch("watchdog.services.session_spine.actions.post_steer") as query_steer_mock:
        response = c.get(
            "/api/v1/watchdog/action-receipts",
            params={
                "action_code": "continue_session",
                "project_id": "repo-a",
                "idempotency_key": "idem-restart-receipt-1",
            },
            headers={"Authorization": "Bearer wt"},
        )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["data"]["reply_code"] == "action_receipt"
    assert response.json()["data"]["action_result"]["effect"] == "steer_posted"
    assert query_steer_mock.call_count == 0


def test_seam_smoke_deferred_approval_delivery_survives_restart_and_updates_stable_reads(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    first_app = create_app(settings, a_client=BrokenAClient())
    task = {
        "project_id": "repo-a",
        "thread_id": "thr_native_1",
        "status": "running",
        "phase": "editing_source",
        "pending_approval": False,
        "last_summary": "waiting for callback replay",
        "files_touched": ["src/example.py"],
        "context_pressure": "critical",
        "stuck_level": 2,
        "failure_count": 1,
        "last_progress_at": "2026-04-05T05:20:00Z",
    }
    facts = build_fact_records(project_id="repo-a", task=task, approvals=[])
    session = build_session_projection(
        project_id="repo-a",
        task=task,
        approvals=[],
        facts=facts,
    )
    progress = build_task_progress_view(
        project_id="repo-a",
        task=task,
        facts=facts,
    )
    first_app.state.session_spine_store.put(
        project_id="repo-a",
        session=session,
        progress=progress,
        facts=facts,
        approval_queue=[],
        last_refreshed_at="2026-04-05T05:25:00Z",
    )
    approval = materialize_canonical_approval(
        _decision_record(project_id="repo-a", fact_snapshot_version="fact-v13"),
        approval_store=first_app.state.canonical_approval_store,
    )
    first_client = TestClient(first_app)

    pending_before = first_client.get(
        "/api/v1/watchdog/sessions/repo-a/pending-approvals",
        headers={"Authorization": "Bearer wt"},
    )
    assert pending_before.status_code == 200
    assert [item["approval_id"] for item in pending_before.json()["data"]["approvals"]] == [
        approval.approval_id
    ]

    first_app.state.canonical_approval_store.update(
        approval.model_copy(
            update={
                "status": "approved",
                "decided_at": "2026-04-12T01:02:00Z",
                "decided_by": "operator-1",
            }
        )
    )
    first_app.state.session_service.record_event(
        event_type="approval_approved",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id=f"corr:approval:{approval.approval_id}",
        causation_id=approval.decision.decision_id,
        related_ids={
            "approval_id": approval.approval_id,
            "decision_id": approval.decision.decision_id,
            "response_id": "approval-response:smoke",
        },
        payload={
            "response_action": "approve",
            "approval_status": "approved",
            "operator": "operator-1",
            "note": "callback retry delivered",
        },
        occurred_at="2026-04-12T01:02:00Z",
    )
    first_app.state.session_service.record_event(
        event_type="human_override_recorded",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:override:approval-response:smoke",
        causation_id="approval-response:smoke",
        related_ids={
            "approval_id": approval.approval_id,
            "decision_id": approval.decision.decision_id,
            "response_id": "approval-response:smoke",
            "envelope_id": approval.envelope_id,
        },
        payload={
            "response_action": "approve",
            "approval_status": "approved",
            "operator": "operator-1",
            "note": "callback retry delivered",
            "requested_action": approval.requested_action,
            "execution_status": "completed",
            "execution_effect": "handoff_triggered",
        },
        occurred_at="2026-04-12T01:03:00Z",
    )
    first_app.state.session_service.record_event(
        event_type="notification_receipt_recorded",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id=f"corr:notification:{approval.envelope_id}:receipt:receipt:smoke",
        causation_id=approval.envelope_id,
        related_ids={
            "envelope_id": approval.envelope_id,
            "notification_kind": "approval_result",
            "receipt_id": "receipt:smoke",
        },
        payload={
            "delivery_status": "delivered",
            "delivery_attempt": 1,
            "receipt_id": "receipt:smoke",
            "received_at": "2026-04-12T01:03:30Z",
        },
        occurred_at="2026-04-12T01:04:00Z",
    )

    restarted = create_app(settings, a_client=BrokenAClient())
    c = TestClient(restarted)

    session_response = c.get("/api/v1/watchdog/sessions/repo-a", headers={"Authorization": "Bearer wt"})
    approvals_response = c.get(
        "/api/v1/watchdog/sessions/repo-a/pending-approvals",
        headers={"Authorization": "Bearer wt"},
    )
    facts_response = c.get(
        "/api/v1/watchdog/sessions/repo-a/facts",
        headers={"Authorization": "Bearer wt"},
    )

    assert session_response.status_code == 200
    assert approvals_response.status_code == 200
    assert facts_response.status_code == 200
    assert session_response.json()["data"]["session"]["pending_approval_count"] == 0
    assert approvals_response.json()["data"]["approvals"] == []
    assert [fact["fact_code"] for fact in facts_response.json()["data"]["facts"]] == [
        "human_override_recorded",
        "notification_receipt_recorded",
    ]


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


def test_session_spine_pause_canonical_and_alias_share_the_same_result(tmp_path) -> None:
    client = FakeAClient(
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
    )
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=client,
    )
    c = TestClient(app)

    canonical = c.post(
        "/api/v1/watchdog/actions",
        json={
            "action_code": "pause_session",
            "project_id": "repo-a",
            "operator": "openclaw",
            "idempotency_key": "idem-pause-1",
            "arguments": {},
        },
        headers={"Authorization": "Bearer wt"},
    )
    alias = c.post(
        "/api/v1/watchdog/sessions/repo-a/actions/pause",
        json={"operator": "openclaw", "idempotency_key": "idem-pause-1"},
        headers={"Authorization": "Bearer wt"},
    )

    assert canonical.status_code == 200
    assert alias.status_code == 200
    assert client.pause_calls == ["repo-a"]
    assert canonical.json()["data"] == alias.json()["data"]
    assert canonical.json()["data"]["effect"] == "session_paused"


def test_session_spine_resume_canonical_and_alias_share_the_same_result(tmp_path) -> None:
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "paused",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "waiting for resume",
            "files_touched": ["src/example.py"],
            "context_pressure": "medium",
            "stuck_level": 1,
            "failure_count": 0,
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
            "action_code": "resume_session",
            "project_id": "repo-a",
            "operator": "openclaw",
            "idempotency_key": "idem-resume-1",
            "arguments": {"handoff_summary": "resume from saved handoff"},
        },
        headers={"Authorization": "Bearer wt"},
    )
    alias = c.post(
        "/api/v1/watchdog/sessions/repo-a/actions/resume",
        json={
            "operator": "openclaw",
            "idempotency_key": "idem-resume-1",
            "handoff_summary": "resume from saved handoff",
        },
        headers={"Authorization": "Bearer wt"},
    )

    assert canonical.status_code == 200
    assert alias.status_code == 200
    assert client.resume_calls == [("repo-a", "resume_or_new_thread", "resume from saved handoff")]
    assert canonical.json()["data"] == alias.json()["data"]
    assert canonical.json()["data"]["effect"] == "session_resumed"


def test_session_spine_summarize_canonical_and_alias_share_the_same_result(tmp_path) -> None:
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
                "files_touched": ["src/example.py", "tests/test_example.py"],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T05:20:00Z",
            }
        ),
    )
    c = TestClient(app)

    canonical = c.post(
        "/api/v1/watchdog/actions",
        json={
            "action_code": "summarize_session",
            "project_id": "repo-a",
            "operator": "openclaw",
            "idempotency_key": "idem-summarize-1",
            "arguments": {},
        },
        headers={"Authorization": "Bearer wt"},
    )
    alias = c.post(
        "/api/v1/watchdog/sessions/repo-a/actions/summarize",
        json={"operator": "openclaw", "idempotency_key": "idem-summarize-1"},
        headers={"Authorization": "Bearer wt"},
    )

    assert canonical.status_code == 200
    assert alias.status_code == 200
    assert canonical.json()["data"] == alias.json()["data"]
    assert canonical.json()["data"]["effect"] == "summary_generated"
    assert canonical.json()["data"]["message"] == "editing files"


def test_session_spine_force_handoff_canonical_and_alias_share_the_same_result(tmp_path) -> None:
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "looping on the same failure",
            "files_touched": ["src/example.py"],
            "context_pressure": "high",
            "stuck_level": 3,
            "failure_count": 4,
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
            "action_code": "force_handoff",
            "project_id": "repo-a",
            "operator": "openclaw",
            "idempotency_key": "idem-force-handoff-1",
            "arguments": {},
        },
        headers={"Authorization": "Bearer wt"},
    )
    alias = c.post(
        "/api/v1/watchdog/sessions/repo-a/actions/force-handoff",
        json={"operator": "openclaw", "idempotency_key": "idem-force-handoff-1"},
        headers={"Authorization": "Bearer wt"},
    )

    assert canonical.status_code == 200
    assert alias.status_code == 200
    assert client.handoff_calls == [("repo-a", "force_handoff")]
    assert canonical.json()["data"] == alias.json()["data"]
    assert canonical.json()["data"]["effect"] == "handoff_triggered"


def test_session_spine_retry_conservative_canonical_and_alias_share_the_same_result(tmp_path) -> None:
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=FakeAClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "repeating the same failing command",
                "files_touched": ["src/example.py"],
                "context_pressure": "medium",
                "stuck_level": 2,
                "failure_count": 3,
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
                "action_code": "retry_with_conservative_path",
                "project_id": "repo-a",
                "operator": "openclaw",
                "idempotency_key": "idem-retry-conservative-1",
                "arguments": {},
            },
            headers={"Authorization": "Bearer wt"},
        )
        alias = c.post(
            "/api/v1/watchdog/sessions/repo-a/actions/retry-with-conservative-path",
            json={"operator": "openclaw", "idempotency_key": "idem-retry-conservative-1"},
            headers={"Authorization": "Bearer wt"},
        )

    assert canonical.status_code == 200
    assert alias.status_code == 200
    assert steer_mock.call_count == 1
    assert canonical.json()["data"] == alias.json()["data"]
    assert canonical.json()["data"]["effect"] == "conservative_retry_requested"


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


def test_legacy_approvals_proxy_fails_closed_on_runtime_error(tmp_path: Path) -> None:
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=_client(),
    )
    c = TestClient(app, raise_server_exceptions=False)

    with patch("watchdog.api.approvals_proxy.httpx.Client") as approvals_http:
        approvals_http.return_value.__enter__.side_effect = RuntimeError("upstream bootstrap failed")
        response = c.get("/api/v1/watchdog/approvals", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["error"]["code"] == "CONTROL_LINK_ERROR"


def test_legacy_approval_decision_proxy_fails_closed_on_runtime_error(tmp_path: Path) -> None:
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=_client(),
    )
    c = TestClient(app, raise_server_exceptions=False)

    with patch("watchdog.api.approvals_proxy.httpx.Client") as approvals_http:
        approvals_http.return_value.__enter__.side_effect = RuntimeError("upstream bootstrap failed")
        response = c.post(
            "/api/v1/watchdog/approvals/appr_001/decision",
            headers={"Authorization": "Bearer wt"},
            json={"decision": "approve", "operator": "operator-1"},
        )

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["error"]["code"] == "CONTROL_LINK_ERROR"


def test_bootstrap_openclaw_webhook_persists_latest_public_endpoint(tmp_path: Path) -> None:
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=_client(),
    )
    c = TestClient(app)

    response = c.post(
        "/api/v1/watchdog/bootstrap/openclaw-webhook",
        headers={"Authorization": "Bearer wt"},
        json={
            "event_type": "openclaw_webhook_base_url_changed",
            "openclaw_webhook_base_url": "https://updated-openclaw.trycloudflare.com",
            "changed_at": "2026-04-07T19:00:00+08:00",
            "source": "b-host-openclaw",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["accepted"] is True
    persisted = json.loads((tmp_path / "openclaw_webhook_endpoint.json").read_text(encoding="utf-8"))
    assert persisted["openclaw_webhook_base_url"] == "https://updated-openclaw.trycloudflare.com"
    assert persisted["changed_at"] == "2026-04-07T19:00:00+08:00"
    assert persisted["source"] == "b-host-openclaw"
