from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from watchdog.main import create_app
from watchdog.settings import Settings
from watchdog.services.approvals.service import materialize_canonical_approval
from watchdog.services.delivery.store import DeliveryOutboxStore
from watchdog.services.runtime_client.client import CodexRuntimeClient
from watchdog.services.policy.decisions import CanonicalDecisionRecord, PolicyDecisionStore
from watchdog.services.session_service import SessionService
from watchdog.services.session_spine.facts import build_fact_records
from watchdog.services.session_spine.projection import (
    build_approval_projections,
    build_session_projection,
    build_task_progress_view,
    stable_thread_id_for_project,
)
from watchdog.services.session_spine.service import (
    build_session_directory_bundle,
    evaluate_session_policy_from_persisted_spine,
)
from watchdog.services.session_spine.store import SessionSpineStore


_A_CLIENT_CONTRACT_METHODS = (
    "get_envelope",
    "get_envelope_by_thread",
    "list_tasks",
    "list_approvals",
    "decide_approval",
    "trigger_pause",
    "trigger_handoff",
    "trigger_resume",
    "get_events_snapshot",
    "iter_events",
    "get_workspace_activity_envelope",
)


def _assert_a_client_signature_compatibility(fake_client_cls: type[object]) -> None:
    for method_name in _A_CLIENT_CONTRACT_METHODS:
        assert hasattr(fake_client_cls, method_name), f"{fake_client_cls.__name__} missing {method_name}"
        fake_signature = inspect.signature(getattr(fake_client_cls, method_name))
        real_signature = inspect.signature(getattr(CodexRuntimeClient, method_name))
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


def _fresh_iso_z() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
        continuation_packet: dict[str, object] | None = None,
    ) -> dict[str, object]:
        _ = continuation_packet
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
        continuation_packet: dict[str, object] | None = None,
    ) -> dict[str, object]:
        _ = continuation_packet
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

    def iter_events(
        self,
        project_id: str,
        *,
        poll_interval: float = 0.5,
    ):
        assert project_id == self._task["project_id"]
        _ = poll_interval
        if False:
            yield ""

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
        continuation_packet: dict[str, object] | None = None,
    ) -> dict[str, object]:
        _ = (project_id, reason, continuation_packet)
        raise RuntimeError("a-side temporarily unavailable")

    def trigger_resume(
        self,
        project_id: str,
        *,
        mode: str,
        handoff_summary: str,
        continuation_packet: dict[str, object] | None = None,
    ) -> dict[str, object]:
        _ = (project_id, mode, handoff_summary, continuation_packet)
        raise RuntimeError("a-side temporarily unavailable")

    def get_events_snapshot(
        self,
        project_id: str,
        *,
        poll_interval: float = 0.5,
    ) -> tuple[str, str]:
        _ = (project_id, poll_interval)
        raise RuntimeError("a-side temporarily unavailable")

    def iter_events(
        self,
        project_id: str,
        *,
        poll_interval: float = 0.5,
    ):
        _ = (project_id, poll_interval)
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
    last_local_manual_activity_at: str | None = None,
) -> Path:
    last_local_manual_activity_at = (
        last_local_manual_activity_at
        or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
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
                "last_local_manual_activity_at": last_local_manual_activity_at,
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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=_client(),
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
    assert session_data["progress"]["project_id"] == "repo-a"
    assert session_data["progress"]["thread_id"] == "session:repo-a"
    assert session_data["progress"]["native_thread_id"] == "thr_native_1"
    assert session_data["progress"]["summary"] == "waiting for approval"
    assert progress_data["reply_code"] == "task_progress_view"
    assert progress_data["progress"]["blocker_fact_codes"] == [
        "approval_pending",
        "awaiting_human_direction",
    ]
    assert session_data["progress"] == progress_data["progress"]
    assert approvals_data["reply_code"] == "approval_queue"
    assert approvals_data["approvals"][0]["thread_id"] == "session:repo-a"


def test_session_spine_progress_route_surfaces_goal_contract_context(tmp_path) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeAClient(
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
    GoalContractService(app.state.session_service).bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="收口 recovery 自动重入",
        task_prompt="收口 recovery 自动重入",
        last_user_instruction="继续把 recovery 自动重入收口到 child continuation",
        phase="editing_source",
        last_summary="editing files",
        current_phase_goal="继续把 recovery 自动重入收口到 child continuation",
        explicit_deliverables=["避免重复 handoff"],
        completion_signals=["child continuation 稳定"],
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions/repo-a/progress", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["reply_code"] == "task_progress_view"
    assert data["message"] == "editing files | 当前目标=继续把 recovery 自动重入收口到 child continuation"
    assert data["progress"]["goal_contract_version"] == "goal-v1"
    assert data["progress"]["current_phase_goal"] == "继续把 recovery 自动重入收口到 child continuation"


def test_session_spine_progress_route_surfaces_revised_latest_user_instruction(tmp_path) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeAClient(
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
    contracts = GoalContractService(app.state.session_service)
    created = contracts.bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="收口 recovery 自动重入",
        task_prompt="收口 recovery 自动重入",
        last_user_instruction="旧指令",
        phase="editing_source",
        last_summary="editing files",
        current_phase_goal="旧阶段目标",
        explicit_deliverables=["避免重复 handoff"],
        completion_signals=["child continuation 稳定"],
    )
    contracts.revise_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        expected_version=created.version,
        current_phase_goal="继续把 recovery 自动重入收口到 child continuation",
        last_user_instruction="继续把 recovery 自动重入收口到 child continuation",
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions/repo-a/progress", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["progress"]["goal_contract_version"] == "goal-v2"
    assert data["progress"]["current_phase_goal"] == "继续把 recovery 自动重入收口到 child continuation"
    assert data["progress"]["last_user_instruction"] == "继续把 recovery 自动重入收口到 child continuation"
    assert data["message"] == "editing files | 当前目标=继续把 recovery 自动重入收口到 child continuation"


def test_session_spine_single_session_explanations_surface_decision_degradation(tmp_path) -> None:
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=_client(),
    )
    app.state.policy_decision_store.put(
        _decision_record(project_id="repo-a", session_id="session:repo-a").model_copy(
            update={
                "evidence": {
                    "facts": [
                        {
                            "fact_id": "fact-1",
                            "fact_code": "approval_pending",
                            "fact_kind": "blocker",
                            "severity": "warning",
                            "summary": "approval pending",
                            "detail": "approval pending",
                            "source": "watchdog",
                            "observed_at": "2026-04-07T00:05:00Z",
                            "related_ids": {},
                        }
                    ],
                    "matched_policy_rules": ["registered_action"],
                    "decision": {
                        "decision_result": "require_user_decision",
                        "action_ref": "execute_recovery",
                        "approval_id": None,
                    },
                    "decision_trace": {
                        "trace_id": "trace:repo-a-provider-invalid",
                        "provider": "openai-compatible",
                        "model": "gpt-4.1-mini",
                        "prompt_schema_ref": "prompt:decision-v2",
                        "output_schema_ref": "schema:decision-trace-v1",
                        "provider_output_schema_ref": "schema:provider-decision-v2",
                        "degrade_reason": "provider_output_invalid",
                        "goal_contract_version": "goal-v1",
                        "policy_ruleset_hash": "policy-hash-v1",
                        "memory_packet_input_ids": [],
                        "memory_packet_input_hashes": [],
                    },
                },
            }
        )
    )
    c = TestClient(app)

    progress_response = c.get(
        "/api/v1/watchdog/sessions/repo-a/progress",
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

    assert progress_response.status_code == 200
    assert stuck_response.status_code == 200
    assert blocker_response.status_code == 200

    expected_suffix = " | 决策=provider降级(schema:provider-decision-v2)"
    progress_data = progress_response.json()["data"]
    stuck_data = stuck_response.json()["data"]
    blocker_data = blocker_response.json()["data"]

    assert progress_data["message"] == f"waiting for approval{expected_suffix}"
    assert progress_data["progress"]["decision_trace_ref"] == "trace:repo-a-provider-invalid"
    assert stuck_data["message"] == f"no current stuck signals{expected_suffix}"
    assert blocker_data["message"] == (
        "approval required; awaiting operator direction"
        f"{expected_suffix}"
    )


def test_session_route_reads_seeded_persisted_spine_on_cold_start(tmp_path) -> None:
    _seed_persisted_session_spine(tmp_path)
    a_client = BrokenAClient()
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=a_client,
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions/repo-a", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    assert response.json()["success"] is True
    data = response.json()["data"]
    assert data["reply_code"] == "session_projection"
    assert data["session"]["thread_id"] == "session:repo-a"
    assert data["session"]["native_thread_id"] == "thr_native_1"
    assert data["progress"]["project_id"] == "repo-a"
    assert data["progress"]["thread_id"] == "session:repo-a"
    assert data["progress"]["native_thread_id"] == "thr_native_1"
    assert data["progress"]["summary"] == "waiting for approval"
    assert [fact["fact_code"] for fact in data["facts"]] == [
        "approval_pending",
        "awaiting_human_direction",
    ]
    assert a_client.get_envelope_calls == []
    assert a_client.list_approvals_calls == []


def test_session_route_ignores_stale_event_only_approval_without_canonical_pending_record(
    tmp_path,
) -> None:
    store = SessionSpineStore(tmp_path / "session_spine.json")
    task = {
        "project_id": "repo-a",
        "thread_id": "thr_native_1",
        "status": "running",
        "phase": "editing_source",
        "pending_approval": False,
        "last_summary": "browser download still running",
        "files_touched": ["src/example.py"],
        "context_pressure": "critical",
        "stuck_level": 4,
        "failure_count": 0,
        "last_progress_at": "2026-04-05T05:20:00Z",
    }
    facts = build_fact_records(project_id="repo-a", task=task, approvals=[])
    store.put(
        project_id="repo-a",
        session=build_session_projection(
            project_id="repo-a",
            task=task,
            approvals=[],
            facts=facts,
        ),
        progress=build_task_progress_view(
            project_id="repo-a",
            task=task,
            facts=facts,
        ),
        facts=facts,
        approval_queue=[],
        last_refreshed_at="2026-04-05T05:21:00Z",
    )
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        runtime_client=BrokenAClient(),
    )
    app.state.session_service.record_event(
        event_type="approval_requested",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:approval:approval:stale-event-only",
        related_ids={
            "approval_id": "approval:stale-event-only",
            "decision_id": "decision:stale-event-only",
            "native_thread_id": "thr_native_1",
        },
        payload={
            "requested_action": "continue_session",
            "requested_action_args": {},
            "decision_options": ["approve", "reject", "execute_action"],
            "fact_snapshot_version": "fact-v1",
            "goal_contract_version": "goal-v1",
            "policy_version": "policy-v1",
        },
        occurred_at="2026-04-05T05:22:00Z",
    )
    c = TestClient(app)

    session_response = c.get(
        "/api/v1/watchdog/sessions/repo-a",
        headers={"Authorization": "Bearer wt"},
    )
    approvals_response = c.get(
        "/api/v1/watchdog/sessions/repo-a/pending-approvals",
        headers={"Authorization": "Bearer wt"},
    )

    assert session_response.status_code == 200
    assert approvals_response.status_code == 200
    session_data = session_response.json()["data"]
    approvals_data = approvals_response.json()["data"]

    assert session_data["session"]["session_state"] != "awaiting_approval"
    assert session_data["session"]["pending_approval_count"] == 0
    assert "approval_pending" not in [fact["fact_code"] for fact in session_data["facts"]]
    assert "awaiting_human_direction" not in [
        fact["fact_code"] for fact in session_data["facts"]
    ]
    assert approvals_data["approvals"] == []


def test_session_route_prefers_runtime_over_optional_interaction_events(tmp_path) -> None:
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        runtime_client=FakeAClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "runtime remains authoritative",
                "files_touched": ["src/example.py"],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-24T05:00:00Z",
            },
            approvals=[],
        ),
    )
    app.state.session_service.record_event(
        event_type="interaction_window_expired",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:interaction-window-expired:repo-a",
        related_ids={"native_thread_id": "thr_native_1"},
        payload={"reason": "operator window expired"},
        occurred_at="2026-04-24T04:55:00Z",
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions/repo-a", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    assert response.json()["success"] is True
    data = response.json()["data"]
    assert data["session"]["session_state"] == "active"
    assert data["session"]["pending_approval_count"] == 0
    assert data["progress"]["summary"] == "runtime remains authoritative"
    assert data["snapshot"]["read_source"] == "live_query_fallback"


def test_persisted_session_and_approval_reads_prefer_live_runtime_over_orphaned_persisted_approval(
    tmp_path,
) -> None:
    _seed_persisted_session_spine(tmp_path)
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        runtime_client=FakeAClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "runtime already cleared the stale approval",
                "files_touched": ["src/example.py"],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-24T05:00:00Z",
            },
            approvals=[],
        ),
    )
    app.state.session_service.record_event(
        event_type="notification_delivery_succeeded",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:notification-delivered:repo-a",
        related_ids={
            "native_thread_id": "thr_native_1",
            "envelope_id": "notification-envelope:repo-a",
            "notification_event_id": "event:notification-delivered:repo-a",
        },
        payload={
            "notification_kind": "decision_result",
            "delivery_status": "delivered",
        },
        occurred_at="2026-04-24T05:01:00Z",
    )
    c = TestClient(app)

    session_response = c.get(
        "/api/v1/watchdog/sessions/repo-a",
        headers={"Authorization": "Bearer wt"},
    )
    approvals_response = c.get(
        "/api/v1/watchdog/sessions/repo-a/pending-approvals",
        headers={"Authorization": "Bearer wt"},
    )

    assert session_response.status_code == 200
    assert approvals_response.status_code == 200

    session_data = session_response.json()["data"]
    approvals_data = approvals_response.json()["data"]

    assert session_data["session"]["session_state"] == "active"
    assert session_data["session"]["pending_approval_count"] == 0
    assert session_data["progress"]["summary"] == "runtime already cleared the stale approval"
    assert session_data["snapshot"]["read_source"] == "live_query_fallback"
    assert "approval_pending" not in [fact["fact_code"] for fact in session_data["facts"]]

    assert approvals_data["approvals"] == []


def test_session_directory_route_marks_runtime_pending_approval_without_queue_as_inconsistent(
    tmp_path,
) -> None:
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        runtime_client=FakeAClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "waiting_for_approval",
                "phase": "planning",
                "pending_approval": True,
                "approval_risk": "L2",
                "last_summary": "Awaiting approval: git tag -a v0.7.0 -m \"AI-SDLC v0.7.0\"",
                "files_touched": [],
                "context_pressure": "medium",
                "stuck_level": 4,
                "failure_count": 0,
                "last_progress_at": "2026-04-24T06:21:10Z",
            },
            approvals=[],
        ),
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    session = data["sessions"][0]
    progress = data["progresses"][0]

    assert session["project_id"] == "repo-a"
    assert session["session_state"] == "blocked"
    assert session["attention_state"] == "critical"
    assert session["pending_approval_count"] == 0
    assert "approve_approval" not in session["available_intents"]
    assert progress["blocker_fact_codes"] == ["approval_state_unavailable"]


def test_persisted_session_route_merges_recovery_suppression_fact_from_session_events(tmp_path) -> None:
    _seed_persisted_session_spine(tmp_path)
    a_client = BrokenAClient()
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=a_client,
    )
    app.state.session_service.record_event(
        event_type="recovery_execution_suppressed",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:recovery-suppressed:repo-a:persisted",
        related_ids={
            "recovery_transaction_id": "recovery-tx:repo-a",
            "native_thread_id": "thr_native_1",
        },
        payload={
            "suppression_reason": "reentry_without_newer_progress",
            "suppression_source": "resident_orchestrator",
            "task_status": "waiting_human",
            "context_pressure": "critical",
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        occurred_at="2026-04-05T05:21:00Z",
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

    assert session_data["snapshot"]["read_source"] == "persisted_spine"
    assert session_data["progress"]["recovery_suppression_reason"] == "reentry_without_newer_progress"
    assert session_data["progress"]["recovery_suppression_source"] == "resident_orchestrator"
    assert session_data["progress"]["recovery_suppression_observed_at"] == "2026-04-05T05:21:00Z"
    assert [fact["fact_code"] for fact in facts_data["facts"]] == [
        "approval_pending",
        "awaiting_human_direction",
        "recovery_execution_suppressed",
    ]
    assert a_client.get_envelope_calls == []
    assert a_client.list_approvals_calls == []


def test_session_route_surfaces_continuation_control_plane_and_dispatch_cooldown(tmp_path) -> None:
    _seed_persisted_session_spine(tmp_path)
    a_client = BrokenAClient()
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        runtime_client=a_client,
    )
    continuation_identity = "repo-a:session:repo-a:thr_native_1:branch_complete_switch"
    route_key = f"{continuation_identity}:fact-v1"
    decision_id = "decision:branch-switch:repo-a"
    command_id = "command:branch-switch:repo-a"
    observed_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    app.state.session_service.record_continuation_gate_verdict(
        project_id="repo-a",
        session_id="session:repo-a",
        gate_kind="continuation_governance",
        gate_status="eligible",
        decision_source="external_model",
        decision_class="branch_complete_switch",
        action_ref="post_operator_guidance",
        authoritative_snapshot_version="fact-v1",
        snapshot_epoch="session-seq:1",
        goal_contract_version="goal-v7",
        continuation_identity=continuation_identity,
        route_key=route_key,
        branch_switch_token="branch-switch:repo-a:86:fact-v1",
        source_packet_id="packet:handoff-v9",
        causation_id=decision_id,
        correlation_id="corr:continuation-gate:repo-a",
        occurred_at="2026-04-05T05:21:00Z",
    )
    app.state.session_service.record_continuation_identity_state(
        project_id="repo-a",
        session_id="session:repo-a",
        continuation_identity=continuation_identity,
        state="consumed",
        decision_source="external_model",
        decision_class="branch_complete_switch",
        action_ref="post_operator_guidance",
        authoritative_snapshot_version="fact-v1",
        snapshot_epoch="session-seq:1",
        goal_contract_version="goal-v7",
        route_key=route_key,
        source_packet_id="packet:handoff-v9",
        consumed_at="2026-04-05T05:22:00Z",
        causation_id=decision_id,
        correlation_id="corr:continuation-identity:repo-a",
        occurred_at="2026-04-05T05:22:00Z",
    )
    app.state.session_service.record_branch_switch_token_state(
        project_id="repo-a",
        session_id="session:repo-a",
        branch_switch_token="branch-switch:repo-a:86:fact-v1",
        state="consumed",
        decision_source="external_model",
        decision_class="branch_complete_switch",
        authoritative_snapshot_version="fact-v1",
        snapshot_epoch="session-seq:1",
        goal_contract_version="goal-v7",
        continuation_identity=continuation_identity,
        route_key=route_key,
        consumed_at="2026-04-05T05:22:00Z",
        causation_id=decision_id,
        correlation_id="corr:branch-switch-token:repo-a",
        occurred_at="2026-04-05T05:22:00Z",
    )
    app.state.session_service.record_event(
        event_type="command_created",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:command-created:repo-a",
        causation_id=decision_id,
        related_ids={
            "decision_id": decision_id,
            "action_ref": "post_operator_guidance",
            "command_id": command_id,
        },
        occurred_at="2026-04-05T05:22:00Z",
        payload={
            "command_id": command_id,
            "action_ref": "post_operator_guidance",
            "action_args": {
                "message": "切换到 WI-086，并开始下一分支。",
            },
            "decision_result": "auto_execute_and_notify",
            "policy_version": "resident-policy-v1",
            "fact_snapshot_version": "fact-v1",
        },
    )
    app.state.session_service.record_event(
        event_type="command_executed",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:command-executed:repo-a",
        causation_id=command_id,
        related_ids={
            "command_id": command_id,
            "claim_seq": "1",
        },
        occurred_at="2026-04-05T05:22:10Z",
        payload={
            "completion_judgment": {
                "status": "completed",
                "action_status": "completed",
                "reply_code": "action_result",
                "decision_trace_ref": "trace:branch-switch",
                "goal_contract_version": "goal-v7",
                "receipt_ref": "receipt:branch-switch",
            },
            "metrics_summary": {
                "decision_result": "auto_execute_and_notify",
            },
        },
    )
    app.state.session_service.record_event(
        event_type="handoff_packet_frozen",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:handoff-packet:repo-a",
        causation_id=decision_id,
        related_ids={
            "source_packet_id": "packet:handoff-v9",
            "continuation_identity": continuation_identity,
            "route_key": route_key,
        },
        occurred_at="2026-04-05T05:21:30Z",
        payload={
            "decision_source": "external_model",
            "decision_class": "branch_complete_switch",
            "authoritative_snapshot_version": "fact-v1",
            "snapshot_epoch": "session-seq:1",
            "packet_hash": "sha256:packet-v9",
            "rendered_markdown_hash": "sha256:render-v9",
            "rendered_from_packet_id": "packet:handoff-v9",
            "continuation_packet": {
                "packet_id": "packet:handoff-v9",
                "packet_version": "continuation-packet/v1",
            },
        },
    )
    app.state.resident_orchestration_state_store.put_auto_dispatch_checkpoint(
        project_id="repo-a",
        continuation_identity=continuation_identity,
        route_key=route_key,
        action_ref="post_operator_guidance",
        last_auto_dispatch_at=observed_at,
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions/repo-a", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    control_plane = response.json()["data"]["progress"]["continuation_control_plane"]
    assert control_plane["continuation_identity"] == continuation_identity
    assert control_plane["identity_state"] == "consumed"
    assert control_plane["branch_switch_token"] == "branch-switch:repo-a:86:fact-v1"
    assert control_plane["token_state"] == "consumed"
    assert control_plane["consumed_at"] == "2026-04-05T05:22:00Z"
    assert control_plane["route_key"] == route_key
    assert control_plane["packet_id"] == "packet:handoff-v9"
    assert control_plane["packet_hash"] == "sha256:packet-v9"
    assert control_plane["rendered_from_packet_id"] == "packet:handoff-v9"
    assert control_plane["rendered_from_packet_hash"] == "sha256:render-v9"
    assert control_plane["decision_source"] == "external_model"
    assert control_plane["snapshot_version"] == "fact-v1"
    assert control_plane["snapshot_epoch"] == "session-seq:1"
    assert control_plane["last_dispatch_result"]["action_ref"] == "post_operator_guidance"
    assert control_plane["last_dispatch_result"]["status"] == "completed"
    assert control_plane["last_dispatch_result"]["reply_code"] == "action_result"
    assert control_plane["dispatch_cooldown"]["active"] is True
    assert control_plane["dispatch_cooldown"]["action_ref"] == "post_operator_guidance"
    assert control_plane["dispatch_cooldown"]["last_dispatched_at"] == observed_at
    assert control_plane["dispatch_cooldown"]["remaining_seconds"] > 0


def test_persisted_session_route_updates_native_thread_from_child_event_only_fallback(tmp_path) -> None:
    _seed_persisted_session_spine(tmp_path)
    a_client = BrokenAClient()
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=a_client,
    )
    app.state.session_service.record_event(
        event_type="interaction_window_expired",
        project_id="repo-a",
        session_id="session:repo-a:thr_child_1",
        correlation_id="corr:interaction:repo-a:persisted-child",
        related_ids={
            "interaction_context_id": "ctx-child-1",
            "interaction_family_id": "family-child-1",
            "actor_id": "user:alice",
            "native_thread_id": "thr_child_1",
        },
        payload={
            "channel_kind": "dm",
            "expired_at": "2026-04-07T00:30:00Z",
            "received_at": "2026-04-07T00:40:00Z",
        },
        occurred_at="2026-04-07T00:40:00Z",
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

    assert session_data["snapshot"]["read_source"] == "persisted_spine"
    assert session_data["session"]["native_thread_id"] == "thr_child_1"
    assert session_data["progress"]["native_thread_id"] == "thr_child_1"
    assert [fact["fact_code"] for fact in facts_data["facts"]] == [
        "interaction_window_expired",
    ]
    assert a_client.get_envelope_calls == []
    assert a_client.list_approvals_calls == []


@pytest.mark.parametrize("session_state", ["active", "unavailable"])
def test_persisted_session_event_only_fallback_keeps_nonterminal_task_status(tmp_path, session_state: str) -> None:
    path = _seed_persisted_session_spine(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    session_record = payload["sessions"]["repo-a"]
    session_record["session"]["session_state"] = session_state
    session_record["session"]["headline"] = "session active"
    session_record["progress"]["summary"] = "session active"
    session_record["approval_queue"] = []
    session_record["facts"] = []
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    a_client = BrokenAClient()
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=a_client,
    )
    app.state.session_service.record_event(
        event_type="interaction_window_expired",
        project_id="repo-a",
        session_id="session:repo-a:thr_child_1",
        correlation_id=f"corr:interaction:repo-a:{session_state}",
        related_ids={
            "interaction_context_id": "ctx-child-1",
            "interaction_family_id": "family-child-1",
            "actor_id": "user:alice",
            "native_thread_id": "thr_child_1",
        },
        payload={
            "channel_kind": "dm",
            "expired_at": "2026-04-07T00:30:00Z",
            "received_at": "2026-04-07T00:40:00Z",
        },
        occurred_at="2026-04-07T00:40:00Z",
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
    fact_codes = [fact["fact_code"] for fact in facts_response.json()["data"]["facts"]]

    assert session_data["snapshot"]["read_source"] == "persisted_spine"
    assert session_data["session"]["native_thread_id"] == "thr_child_1"
    assert session_data["progress"]["native_thread_id"] == "thr_child_1"
    assert session_data["session"]["session_state"] == "active"
    assert "continue_session" in session_data["session"]["available_intents"]
    assert "task_completed" not in fact_codes
    assert fact_codes == ["interaction_window_expired"]
    assert a_client.get_envelope_calls == []
    assert a_client.list_approvals_calls == []


def test_persisted_session_projection_facts_preserve_source_state_summary_and_context(tmp_path) -> None:
    path = _seed_persisted_session_spine(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    session_record = payload["sessions"]["repo-a"]
    session_record["session"]["session_state"] = "active"
    session_record["session"]["activity_phase"] = "editing_source"
    session_record["session"]["attention_state"] = "normal"
    session_record["session"]["headline"] = "editing recovery path"
    session_record["session"]["pending_approval_count"] = 0
    session_record["session"]["available_intents"] = ["get_session", "continue_session"]
    session_record["progress"]["activity_phase"] = "editing_source"
    session_record["progress"]["summary"] = "editing recovery path"
    session_record["progress"]["context_pressure"] = "medium"
    session_record["progress"]["stuck_level"] = 1
    session_record["progress"]["last_progress_at"] = "2026-04-05T05:20:00Z"
    session_record["approval_queue"] = []
    session_record["facts"] = []
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        runtime_client=BrokenAClient(),
    )
    app.state.session_service.record_event(
        event_type="notification_delivery_failed",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:notification:repo-a:failed",
        related_ids={
            "notification_event_id": "event:notification-failed",
            "native_thread_id": "thr_native_1",
        },
        payload={
            "delivery_status": "delivery_failed",
            "notification_kind": "decision_result",
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        occurred_at="2026-04-05T05:21:00Z",
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions/repo-a", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["snapshot"]["read_source"] == "persisted_spine"
    assert data["session"]["headline"] == "editing recovery path"
    assert data["progress"]["summary"] == "editing recovery path"
    assert data["progress"]["context_pressure"] == "medium"
    assert "notification_delivery_failed" in [fact["fact_code"] for fact in data["facts"]]


def test_session_spine_store_sanitizes_dirty_persisted_summary_and_headline(tmp_path) -> None:
    store = SessionSpineStore(tmp_path / "session_spine.json")
    task = {
        "project_id": "repo-a",
        "thread_id": "thr_native_1",
        "status": "running",
        "phase": "editing_source",
        "pending_approval": False,
        "last_summary": "editing files",
        "files_touched": ["src/example.py"],
        "context_pressure": "medium",
        "stuck_level": 1,
        "failure_count": 0,
        "last_progress_at": "2026-04-05T05:20:00Z",
    }
    facts = build_fact_records(project_id="repo-a", task=task, approvals=[])
    store.put(
        project_id="repo-a",
        session=build_session_projection(
            project_id="repo-a",
            task=task,
            approvals=[],
            facts=facts,
        ),
        progress=build_task_progress_view(
            project_id="repo-a",
            task=task,
            facts=facts,
        ),
        facts=facts,
        approval_queue=[],
        last_refreshed_at="2026-04-05T05:21:00Z",
    )

    path = tmp_path / "session_spine.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    dirty_summary = (
        "[steer:rule_based_continue] 下一步建议：继续推进 "
        "[steer:rule_based_continue] 下一步建议：继续推进 "
        "codex开发进度，并优先验证最近改动。，并优先验证最近改动。"
    )
    payload["sessions"]["repo-a"]["session"]["headline"] = dirty_summary
    payload["sessions"]["repo-a"]["progress"]["summary"] = dirty_summary
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    record = store.get("repo-a")

    assert record is not None
    assert record.session.headline == "codex开发进度，并优先验证最近改动。"
    assert record.progress.summary == "codex开发进度，并优先验证最近改动。"

    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["sessions"]["repo-a"]["session"]["headline"] == "codex开发进度，并优先验证最近改动。"
    assert persisted["sessions"]["repo-a"]["progress"]["summary"] == "codex开发进度，并优先验证最近改动。"


def test_session_spine_store_rewrites_continue_progress_template_summary(tmp_path) -> None:
    store = SessionSpineStore(tmp_path / "session_spine.json")
    task = {
        "project_id": "repo-a",
        "thread_id": "thr_native_1",
        "status": "running",
        "phase": "handoff",
        "pending_approval": False,
        "last_summary": "handoff drafted",
        "files_touched": [],
        "context_pressure": "medium",
        "stuck_level": 1,
        "failure_count": 0,
        "last_progress_at": "2026-04-05T05:20:00Z",
    }
    facts = build_fact_records(project_id="repo-a", task=task, approvals=[])
    store.put(
        project_id="repo-a",
        session=build_session_projection(
            project_id="repo-a",
            task=task,
            approvals=[],
            facts=facts,
        ),
        progress=build_task_progress_view(
            project_id="repo-a",
            task=task,
            facts=facts,
        ),
        facts=facts,
        approval_queue=[],
        last_refreshed_at="2026-04-05T05:21:00Z",
    )

    path = tmp_path / "session_spine.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    dirty_summary = (
        "[steer:openclaw_continue_session] 请汇总当前进展：\n"
        "1. 已完成内容\n"
        "2. 当前阻塞点\n"
        "3. 下一步最小动作\n"
        "如果无阻塞，请立即继续执行。，并优先验证最近改动。"
    )
    payload["sessions"]["repo-a"]["session"]["headline"] = dirty_summary
    payload["sessions"]["repo-a"]["progress"]["summary"] = dirty_summary
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    record = store.get("repo-a")

    assert record is not None
    assert record.session.headline == "当前进展待汇总；需要先返回已完成内容、阻塞点和下一步动作。"
    assert record.progress.summary == "当前进展待汇总；需要先返回已完成内容、阻塞点和下一步动作。"


@pytest.mark.parametrize(
    ("dirty_summary", "expected"),
    [
        (
            "All project files removed; `ls -la` now shows only `.` and `..` in `/Users/sinclairpan/Codex/portal`. "
            "The earlier `find` reported a harmless `sysconf` warning but still completed deletion.\n\n"
            "Next steps: 1) scaffold your new project (e.g., `npm create vite@latest`), 2) reinstall dependencies as needed.",
            "项目目录已清空；下一步需重新 scaffold 项目并重装依赖。",
        ),
        (
            "因为这个聊天界面对“文件链接”的支持比“文件夹链接”稳定，`zip/html/svg` 这类具体文件通常能点开，但目录路径不一定会触发 Finder 或文件管理器跳转。\n\n"
            "你的两个目录实际是：\n\n"
            "- 工程目录：`/tmp/project`\n"
            "- 离线目录：`/tmp/project/offline_bundle`\n\n"
            "如果你要，我下一条可以只给你：\n- 可直接点开的 `zip`",
            "已确认工程目录和离线目录位置；可直接打开 zip、index.html 或工程目录。",
        ),
        (
            "我已经把离线安装包重建回来了。\n\n目录：\n[dist/pkg](/tmp/pkg)\n\nzip：\n[pkg.zip](/tmp/pkg.zip)\n\n"
            "这次我不再动 `dist/`。如果你后面要我清理，我会先明确避开安装包产物。",
            "已重建离线安装包并产出 zip；dist 安装包产物已保留，暂不再清理。",
        ),
        (
            "我已经单独整理出一份给业务方确认的清单，文件在 `/tmp/OQ.md`。这份文档只保留当前还没关闭的 10 个 OQ。"
            "建议先收 `OQ-017 / OQ-018 / OQ-021`，它们最影响 UX 出图和本期范围冻结。",
            "已整理业务确认清单；当前保留未关闭 OQ，建议优先确认 OQ-017 / OQ-018 / OQ-021。",
        ),
    ],
)
def test_session_spine_store_compacts_conversational_longform_summaries(
    tmp_path, dirty_summary, expected
) -> None:
    store = SessionSpineStore(tmp_path / "session_spine.json")
    task = {
        "project_id": "repo-a",
        "thread_id": "thr_native_1",
        "status": "running",
        "phase": "editing_source",
        "pending_approval": False,
        "last_summary": "editing files",
        "files_touched": ["src/example.py"],
        "context_pressure": "medium",
        "stuck_level": 1,
        "failure_count": 0,
        "last_progress_at": "2026-04-05T05:20:00Z",
    }
    facts = build_fact_records(project_id="repo-a", task=task, approvals=[])
    store.put(
        project_id="repo-a",
        session=build_session_projection(
            project_id="repo-a",
            task=task,
            approvals=[],
            facts=facts,
        ),
        progress=build_task_progress_view(
            project_id="repo-a",
            task=task,
            facts=facts,
        ),
        facts=facts,
        approval_queue=[],
        last_refreshed_at="2026-04-05T05:21:00Z",
    )

    path = tmp_path / "session_spine.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["sessions"]["repo-a"]["session"]["headline"] = dirty_summary
    payload["sessions"]["repo-a"]["progress"]["summary"] = dirty_summary
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    record = store.get("repo-a")

    assert record is not None
    assert record.session.headline == expected
    assert record.progress.summary == expected


def test_session_route_projects_native_thread_from_approval_requested_event_without_persisted_spine(
    tmp_path,
) -> None:
    a_client = BrokenAClient()
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=a_client,
    )
    approval = materialize_canonical_approval(
        _decision_record(project_id="repo-a").model_copy(update={"native_thread_id": "thr_native_1"}),
        approval_store=app.state.canonical_approval_store,
        session_service=app.state.session_service,
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

    assert session_data["snapshot"]["read_source"] == "session_events_projection"
    assert session_data["session"]["thread_id"] == "session:repo-a"
    assert session_data["session"]["native_thread_id"] == "thr_native_1"
    assert session_data["progress"]["thread_id"] == "session:repo-a"
    assert session_data["progress"]["native_thread_id"] == "thr_native_1"
    assert approvals_data["approvals"][0]["approval_id"] == approval.approval_id
    assert approvals_data["approvals"][0]["thread_id"] == "session:repo-a"
    assert approvals_data["approvals"][0]["native_thread_id"] == "thr_native_1"
    assert a_client.get_envelope_calls == []
    assert a_client.list_approvals_calls == []


def test_session_directory_route_falls_back_to_session_events_without_persisted_spine(
    tmp_path,
) -> None:
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=BrokenAClient(),
    )
    approval = materialize_canonical_approval(
        _decision_record(project_id="repo-a").model_copy(update={"native_thread_id": "thr_native_1"}),
        approval_store=app.state.canonical_approval_store,
        session_service=app.state.session_service,
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert [item["project_id"] for item in data["sessions"]] == ["repo-a"]
    assert data["sessions"][0]["thread_id"] == "session:repo-a"
    assert data["sessions"][0]["native_thread_id"] == "thr_native_1"
    assert data["progresses"][0]["thread_id"] == "session:repo-a"
    assert data["progresses"][0]["native_thread_id"] == "thr_native_1"
    assert data["sessions"][0]["pending_approval_count"] == 1
    assert data["message"] == "多项目进展（1）\n- repo-a | unknown | waiting for approval | 上下文=low"
    assert approval.approval_id


def test_progress_route_uses_effective_native_thread_from_legacy_decision_record_for_decision_trace(
    tmp_path,
) -> None:
    _seed_persisted_session_spine(tmp_path)
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=BrokenAClient(),
    )
    decision_store = PolicyDecisionStore(tmp_path / "policy_decisions.json")
    decision = _decision_record(project_id="repo-a").model_copy(
        update={
            "native_thread_id": None,
            "created_at": "2026-04-07T00:05:00Z",
            "evidence": {
                **_decision_record(project_id="repo-a").evidence,
                "target": {
                    "session_id": "session:repo-a",
                    "project_id": "repo-a",
                    "thread_id": "session:repo-a",
                    "native_thread_id": "native:repo-a",
                    "approval_id": None,
                },
                "decision_trace": {
                    "trace_id": "trace:repo-a-legacy-native",
                    "provider": "resident_orchestrator",
                    "model": "rule-based-brain",
                    "prompt_schema_ref": "prompt:none",
                    "output_schema_ref": "schema:decision-trace-v1",
                    "provider_output_schema_ref": "schema:provider-decision-v2",
                    "degrade_reason": "provider_output_invalid",
                    "goal_contract_version": "goal-v1",
                    "policy_ruleset_hash": "policy-hash-v1",
                    "memory_packet_input_ids": [],
                    "memory_packet_input_hashes": [],
                },
            },
        }
    )
    decision_store.put(decision)
    c = TestClient(app)

    progress_response = c.get(
        "/api/v1/watchdog/sessions/repo-a/progress",
        headers={"Authorization": "Bearer wt"},
    )

    assert progress_response.status_code == 200
    progress_data = progress_response.json()["data"]
    assert progress_data["progress"]["decision_trace_ref"] == "trace:repo-a-legacy-native"


def test_pending_approvals_route_uses_effective_native_thread_from_legacy_canonical_approval(
    tmp_path,
) -> None:
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=BrokenAClient(),
    )
    approval = materialize_canonical_approval(
        _decision_record(project_id="repo-a").model_copy(update={"native_thread_id": "thr_native_1"}),
        approval_store=app.state.canonical_approval_store,
        session_service=app.state.session_service,
    )
    path = tmp_path / "canonical_approvals.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload[approval.envelope_id]["native_thread_id"] = None
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    c = TestClient(app)

    approvals_response = c.get(
        "/api/v1/watchdog/sessions/repo-a/pending-approvals",
        headers={"Authorization": "Bearer wt"},
    )

    assert approvals_response.status_code == 200
    approvals_data = approvals_response.json()["data"]
    assert [item["approval_id"] for item in approvals_data["approvals"]] == [approval.approval_id]
    assert approvals_data["approvals"][0]["native_thread_id"] == "thr_native_1"


def test_session_route_projects_native_thread_from_post_approval_session_events_without_persisted_spine(
    tmp_path,
) -> None:
    live_app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeAClient(
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
            }
        ),
    )
    approval = materialize_canonical_approval(
        _decision_record(project_id="repo-a").model_copy(update={"native_thread_id": "thr_native_1"}),
        approval_store=live_app.state.canonical_approval_store,
        session_service=live_app.state.session_service,
    )
    live_client = TestClient(live_app)

    response = live_client.post(
        "/api/v1/watchdog/feishu/control",
        json={
            "event_type": "approval_response",
            "interaction_context_id": "ctx-approval-native-1",
            "interaction_family_id": "family-approval-native-1",
            "actor_id": "user:carol",
            "channel_kind": "dm",
            "occurred_at": "2026-04-07T00:10:00Z",
            "action_window_expires_at": "2026-04-07T00:30:00Z",
            "envelope_id": approval.envelope_id,
            "approval_id": approval.approval_id,
            "decision_id": approval.decision.decision_id,
            "response_action": "reject",
            "response_token": approval.approval_token,
            "client_request_id": "req-native-event-only-reject",
            "note": "reject for projection test",
            "project_id": "repo-a",
            "session_id": "session:repo-a",
            "native_thread_id": "thr_native_1",
        },
        headers={"Authorization": "Bearer wt"},
    )
    assert response.status_code == 200
    assert response.json()["success"] is True

    restarted = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=BrokenAClient(),
    )
    c = TestClient(restarted)

    session_response = c.get("/api/v1/watchdog/sessions/repo-a", headers={"Authorization": "Bearer wt"})
    facts_response = c.get(
        "/api/v1/watchdog/sessions/repo-a/facts",
        headers={"Authorization": "Bearer wt"},
    )
    approvals_response = c.get(
        "/api/v1/watchdog/sessions/repo-a/pending-approvals",
        headers={"Authorization": "Bearer wt"},
    )

    assert session_response.status_code == 200
    assert facts_response.status_code == 200
    assert approvals_response.status_code == 200
    session_data = session_response.json()["data"]
    facts_data = facts_response.json()["data"]
    approvals_data = approvals_response.json()["data"]

    assert session_data["snapshot"]["read_source"] == "session_events_projection"
    assert session_data["session"]["thread_id"] == "session:repo-a"
    assert session_data["session"]["native_thread_id"] == "thr_native_1"
    assert session_data["progress"]["thread_id"] == "session:repo-a"
    assert session_data["progress"]["native_thread_id"] == "thr_native_1"
    assert approvals_data["approvals"] == []
    assert [fact["fact_code"] for fact in facts_data["facts"]] == [
        "notification_receipt_recorded",
        "human_override_recorded",
    ]


def test_session_route_projects_native_thread_from_parent_native_related_ids_without_persisted_spine(
    tmp_path,
) -> None:
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=BrokenAClient(),
    )
    app.state.session_service.record_event(
        event_type="memory_unavailable_degraded",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:memory-degraded:repo-a",
        causation_id="cause:memory-degraded",
        related_ids={"memory_scope": "project"},
        payload={
            "fallback_mode": "degraded",
            "degradation_reason": "index unavailable",
            "reason_code": "memory_unavailable",
        },
        occurred_at="2026-04-12T01:00:00Z",
    )
    app.state.session_service.record_event(
        event_type="future_worker_transition_rejected",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:future-worker:rejected",
        causation_id="worker:task-1",
        related_ids={
            "worker_task_ref": "worker:task-1",
            "attempted_event_type": "future_worker_completed",
            "decision_trace_ref": "trace:1",
            "parent_native_thread_id": "thr_native_1",
        },
        payload={
            "attempted_event_type": "future_worker_completed",
            "current_state": "requested",
            "reason": "invalid_transition:requested->completed",
            "worker_task_ref": "worker:task-1",
            "decision_trace_ref": "trace:1",
        },
        occurred_at="2026-04-12T01:01:00Z",
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
    assert session_data["session"]["thread_id"] == "session:repo-a"
    assert session_data["session"]["native_thread_id"] == "thr_native_1"
    assert session_data["progress"]["native_thread_id"] == "thr_native_1"
    assert [fact["fact_code"] for fact in facts_data["facts"]] == ["memory_unavailable_degraded"]


def test_session_route_exposes_persisted_snapshot_freshness_semantics(tmp_path) -> None:
    _seed_persisted_session_spine(
        tmp_path,
        session_seq=7,
        fact_snapshot_version="fact-v7",
        last_refreshed_at="2000-01-01T00:00:00Z",
    )
    a_client = BrokenAClient()
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=a_client,
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


def test_session_route_overlays_session_service_projection_onto_persisted_spine(tmp_path) -> None:
    _seed_persisted_session_spine(tmp_path)
    a_client = BrokenAClient()
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=a_client,
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

    assert session_data["snapshot"]["read_source"] == "persisted_spine"
    assert session_data["session"]["native_thread_id"] == "thr_native_1"
    assert session_data["session"]["session_state"] == "active"
    assert session_data["progress"]["project_id"] == "repo-a"
    assert session_data["progress"]["thread_id"] == "session:repo-a"
    assert session_data["progress"]["native_thread_id"] == "thr_native_1"
    assert session_data["progress"]["summary"] == session_data["message"]
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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=a_client,
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

    assert session_data["snapshot"]["read_source"] == "persisted_spine"
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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=a_client,
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
        last_local_manual_activity_at=(
            datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        ),
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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=a_client,
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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=a_client,
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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=a_client,
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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=_client(),
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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=a_client,
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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeAClient(
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
                {
                    "project_id": "repo-c",
                    "thread_id": "thr_native_3",
                    "status": "running",
                    "phase": "editing_source",
                    "pending_approval": False,
                    "last_summary": "resuming after overflow",
                    "files_touched": ["src/recovery.py"],
                    "context_pressure": "high",
                    "stuck_level": 1,
                    "failure_count": 1,
                    "last_progress_at": "2026-04-05T05:23:00Z",
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
    app.state.session_service.record_recovery_execution(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        parent_native_thread_id="thr_native_1",
        recovery_reason="context_critical",
        failure_family="context_pressure",
        failure_signature="critical",
        handoff={
            "handoff_file": "/tmp/repo-a.handoff.md",
            "summary": "handoff",
        },
        resume={
            "project_id": "repo-a",
            "status": "running",
            "mode": "resume_or_new_thread",
            "thread_id": "thr_native_1",
        },
        resume_outcome="same_thread_resume",
    )
    app.state.session_service.record_recovery_execution(
        project_id="repo-b",
        parent_session_id="session:repo-b",
        parent_native_thread_id="thr_native_2",
        recovery_reason="context_critical",
        failure_family="context_pressure",
        failure_signature="critical",
        handoff={
            "handoff_file": "/tmp/repo-b.handoff.md",
            "summary": "handoff",
        },
        resume={
            "project_id": "repo-b",
            "status": "running",
            "mode": "resume_or_new_thread",
            "resume_outcome": "new_child_session",
            "session_id": "session:repo-b:child-v1",
        },
    )
    app.state.session_service.record_recovery_execution(
        project_id="repo-c",
        parent_session_id="session:repo-c",
        parent_native_thread_id="thr_native_3",
        recovery_reason="context_critical",
        failure_family="context_pressure",
        failure_signature="critical",
        handoff={
            "handoff_file": "/tmp/repo-c.handoff.md",
            "summary": "handoff",
        },
        resume=None,
        resume_error="resume_call_failed",
    )
    app.state.policy_decision_store.put(
        _decision_record(project_id="repo-b", session_id="session:repo-b").model_copy(
            update={
                "created_at": "2026-04-07T00:05:00Z",
                "evidence": {
                    "facts": [
                        {
                            "fact_id": "fact-1",
                            "fact_code": "approval_pending",
                            "fact_kind": "blocker",
                            "severity": "warning",
                            "summary": "approval pending",
                            "detail": "approval pending",
                            "source": "watchdog",
                            "observed_at": "2026-04-07T00:05:00Z",
                            "related_ids": {},
                        }
                    ],
                    "matched_policy_rules": ["registered_action"],
                    "decision": {
                        "decision_result": "require_user_decision",
                        "action_ref": "execute_recovery",
                        "approval_id": None,
                    },
                    "decision_trace": {
                        "trace_id": "trace:repo-b-provider-invalid",
                        "provider": "openai-compatible",
                        "model": "gpt-4.1-mini",
                        "prompt_schema_ref": "prompt:decision-v2",
                        "output_schema_ref": "schema:decision-trace-v1",
                        "provider_output_schema_ref": "schema:provider-decision-v2",
                        "degrade_reason": "provider_output_invalid",
                        "goal_contract_version": "goal-v1",
                        "policy_ruleset_hash": "policy-hash-v1",
                        "memory_packet_input_ids": [],
                        "memory_packet_input_hashes": [],
                    },
                },
            }
        )
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["reply_code"] == "session_directory"
    assert [item["project_id"] for item in data["sessions"]] == ["repo-a", "repo-b", "repo-c"]
    assert [item["thread_id"] for item in data["sessions"]] == [
        "session:repo-a",
        "session:repo-b",
        "session:repo-c",
    ]
    assert data["sessions"][1]["pending_approval_count"] == 1
    assert "list_pending_approvals" in data["sessions"][1]["available_intents"]
    assert [item["project_id"] for item in data["progresses"]] == ["repo-a", "repo-b", "repo-c"]
    assert data["progresses"][0]["recovery_outcome"] == "same_thread_resume"
    assert data["progresses"][0]["recovery_status"] == "completed"
    assert data["progresses"][0]["recovery_child_session_id"] is None
    assert data["progresses"][1]["recovery_outcome"] == "new_child_session"
    assert data["progresses"][1]["recovery_status"] == "completed"
    assert data["progresses"][1]["recovery_child_session_id"] == "session:repo-b:child-v1"
    assert data["progresses"][1]["decision_trace_ref"] == "trace:repo-b-provider-invalid"
    assert data["progresses"][1]["decision_degrade_reason"] == "provider_output_invalid"
    assert data["progresses"][1]["provider_output_schema_ref"] == "schema:provider-decision-v2"
    assert data["progresses"][2]["recovery_outcome"] == "resume_failed"
    assert data["progresses"][2]["recovery_status"] == "failed_retryable"
    assert data["progresses"][2]["recovery_child_session_id"] is None
    assert data["message"] == (
        "多项目进展（3）\n"
        "- repo-a | editing_source | editing files | 上下文=low | 恢复=原线程续跑\n"
        "- repo-b | approval | waiting for approval | 上下文=low | 恢复=新子会话 repo-b:child-v1"
        " | 决策=provider降级(schema:provider-decision-v2)\n"
        "- repo-c | editing_source | resuming after overflow | 上下文=high | 恢复=恢复失败(failed_retryable)"
    )


def test_session_directory_bundle_filters_inactive_projects_with_stale_runtime_activity(
    tmp_path,
) -> None:
    current = datetime(2026, 4, 23, 0, 0, 0, tzinfo=UTC)
    bundle = build_session_directory_bundle(
        FakeAClient(
            task={
                "project_id": "repo-active",
                "thread_id": "thr_active",
                "native_thread_id": "thr_native_active",
                "created_at": "2026-04-22T00:00:00Z",
                "status": "running",
                "phase": "planning",
                "pending_approval": False,
                "last_summary": "recent work",
                "files_touched": [],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-22T00:00:00Z",
            },
            tasks=[
                {
                    "project_id": "repo-stale",
                    "thread_id": "thr_stale",
                    "native_thread_id": "thr_native_stale",
                    "created_at": "2026-04-10T00:00:00Z",
                    "status": "running",
                    "phase": "planning",
                    "pending_approval": False,
                    "last_summary": "old work",
                    "files_touched": [],
                    "context_pressure": "low",
                    "stuck_level": 0,
                    "failure_count": 0,
                    "last_progress_at": "2026-04-10T00:00:00Z",
                },
                {
                    "project_id": "repo-active",
                    "thread_id": "thr_active",
                    "native_thread_id": "thr_native_active",
                    "created_at": "2026-04-22T00:00:00Z",
                    "status": "running",
                    "phase": "planning",
                    "pending_approval": False,
                    "last_summary": "recent work",
                    "files_touched": [],
                    "context_pressure": "low",
                    "stuck_level": 0,
                    "failure_count": 0,
                    "last_progress_at": "2026-04-22T00:00:00Z",
                },
            ],
        ),
        liveness_now=current,
    )

    assert [session.project_id for session in bundle.sessions] == ["repo-active"]
    assert [progress.project_id for progress in bundle.progresses] == ["repo-active"]


def test_session_directory_bundle_filters_terminal_runtime_tasks_without_execution_state(
    tmp_path,
) -> None:
    current = datetime(2026, 4, 23, 0, 0, 0, tzinfo=UTC)
    bundle = build_session_directory_bundle(
        FakeAClient(
            task={
                "project_id": "repo-active",
                "thread_id": "thr_active",
                "native_thread_id": "thr_native_active",
                "created_at": "2026-04-23T00:00:00Z",
                "status": "running",
                "phase": "planning",
                "pending_approval": False,
                "last_summary": "current work",
                "files_touched": [],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-23T00:00:00Z",
            },
            tasks=[
                {
                    "project_id": "repo-paused",
                    "thread_id": "thr_paused",
                    "native_thread_id": "thr_native_paused",
                    "created_at": "2026-04-23T00:00:00Z",
                    "status": "paused",
                    "phase": "planning",
                    "pending_approval": False,
                    "last_summary": "paused work",
                    "files_touched": [],
                    "context_pressure": "low",
                    "stuck_level": 0,
                    "failure_count": 0,
                    "last_progress_at": "2026-04-23T00:00:00Z",
                },
                {
                    "project_id": "repo-active",
                    "thread_id": "thr_active",
                    "native_thread_id": "thr_native_active",
                    "created_at": "2026-04-23T00:00:00Z",
                    "status": "running",
                    "phase": "planning",
                    "pending_approval": False,
                    "last_summary": "current work",
                    "files_touched": [],
                    "context_pressure": "low",
                    "stuck_level": 0,
                    "failure_count": 0,
                    "last_progress_at": "2026-04-23T00:00:00Z",
                },
            ],
        ),
        liveness_now=current,
    )

    assert [session.project_id for session in bundle.sessions] == ["repo-active"]
    assert [progress.project_id for progress in bundle.progresses] == ["repo-active"]


def test_session_directory_route_filters_stale_event_only_fallback_without_native_thread(
    tmp_path,
) -> None:
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="recovery_execution_suppressed",
        project_id="repo-stale",
        session_id="session:repo-stale",
        correlation_id="corr:recovery-suppressed:repo-stale",
        related_ids={"recovery_transaction_id": "recovery-tx:repo-stale"},
        payload={
            "suppression_reason": "reentry_without_newer_progress",
            "suppression_source": "resident_orchestrator",
            "task_status": "running",
            "context_pressure": "critical",
            "last_progress_at": "2026-04-07T00:00:00Z",
        },
        occurred_at="2026-04-07T00:02:00Z",
    )
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        runtime_client=BrokenAClient(),
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["sessions"] == []
    assert data["progresses"] == []


def test_session_directory_route_returns_empty_when_degraded_fallback_filters_every_project(
    tmp_path,
) -> None:
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="approval_requested",
        project_id="watchdog-smoke-degraded",
        session_id="session:watchdog-smoke-degraded",
        correlation_id="corr:watchdog-smoke-degraded:approval",
        related_ids={"approval_id": "approval:watchdog-smoke-degraded"},
        payload={
            "approval_id": "approval:watchdog-smoke-degraded",
            "status": "pending",
            "requested_at": _fresh_iso_z(),
        },
        occurred_at=_fresh_iso_z(),
    )
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        runtime_client=BrokenAClient(),
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["sessions"] == []
    assert data["progresses"] == []


def test_session_directory_bundle_ignores_recent_watchdog_handoff_as_project_activity(
    tmp_path,
) -> None:
    current = datetime(2026, 4, 23, 12, 0, 0, tzinfo=UTC)
    bundle = build_session_directory_bundle(
        FakeAClient(
            task={
                "project_id": "repo-active",
                "thread_id": "thr_active",
                "native_thread_id": "thr_native_active",
                "created_at": "2026-04-22T00:00:00Z",
                "status": "running",
                "phase": "planning",
                "pending_approval": False,
                "last_summary": "recent user work",
                "files_touched": [],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-22T00:05:00Z",
                "last_substantive_user_input_at": "2026-04-22T00:00:00Z",
            },
            tasks=[
                {
                    "project_id": "repo-stale-handoff",
                    "thread_id": "thr_stale_handoff",
                    "native_thread_id": "thr_native_stale_handoff",
                    "created_at": "2026-04-09T00:00:00Z",
                    "status": "running",
                    "phase": "handoff",
                    "pending_approval": False,
                    "last_summary": "watchdog generated handoff",
                    "files_touched": [],
                    "context_pressure": "medium",
                    "stuck_level": 4,
                    "failure_count": 0,
                    "last_progress_at": "2026-04-22T13:00:00Z",
                    "last_substantive_user_input_at": "2026-04-09T12:00:00Z",
                    "last_local_manual_activity_at": "2026-04-09T12:00:00Z",
                },
                {
                    "project_id": "repo-active",
                    "thread_id": "thr_active",
                    "native_thread_id": "thr_native_active",
                    "created_at": "2026-04-22T00:00:00Z",
                    "status": "running",
                    "phase": "planning",
                    "pending_approval": False,
                    "last_summary": "recent user work",
                    "files_touched": [],
                    "context_pressure": "low",
                    "stuck_level": 0,
                    "failure_count": 0,
                    "last_progress_at": "2026-04-22T00:05:00Z",
                    "last_substantive_user_input_at": "2026-04-22T00:00:00Z",
                },
            ],
        ),
        liveness_now=current,
    )

    assert [session.project_id for session in bundle.sessions] == ["repo-active"]
    assert [progress.project_id for progress in bundle.progresses] == ["repo-active"]


def test_session_directory_bundle_filters_smoke_and_home_name_pseudo_projects(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "sinclairpan"))
    current = datetime(2026, 4, 23, 12, 0, 0, tzinfo=UTC)
    bundle = build_session_directory_bundle(
        FakeAClient(
            task={
                "project_id": "repo-active",
                "thread_id": "thr_active",
                "native_thread_id": "thr_native_active",
                "created_at": "2026-04-23T00:00:00Z",
                "status": "running",
                "phase": "planning",
                "pending_approval": False,
                "last_summary": "recent user work",
                "files_touched": [],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-23T00:05:00Z",
                "last_substantive_user_input_at": "2026-04-23T00:00:00Z",
            },
            tasks=[
                {
                    "project_id": "watchdog-smoke-feishu-control-20260419-012852",
                    "thread_id": "thr_smoke",
                    "native_thread_id": "thr_native_smoke",
                    "created_at": "2026-04-23T00:00:00Z",
                    "status": "running",
                    "phase": "planning",
                    "pending_approval": False,
                    "last_summary": "smoke project",
                    "files_touched": [],
                    "context_pressure": "low",
                    "stuck_level": 0,
                    "failure_count": 0,
                    "last_progress_at": "2026-04-23T00:05:00Z",
                    "last_substantive_user_input_at": "2026-04-23T00:00:00Z",
                },
                {
                    "project_id": "sinclairpan",
                    "thread_id": "thr_home_name",
                    "native_thread_id": "thr_native_home_name",
                    "created_at": "2026-04-23T00:00:00Z",
                    "status": "running",
                    "phase": "planning",
                    "pending_approval": False,
                    "last_summary": "home directory pseudo project",
                    "files_touched": [],
                    "context_pressure": "low",
                    "stuck_level": 0,
                    "failure_count": 0,
                    "last_progress_at": "2026-04-23T00:05:00Z",
                    "last_substantive_user_input_at": "2026-04-23T00:00:00Z",
                },
                {
                    "project_id": "repo-active",
                    "thread_id": "thr_active",
                    "native_thread_id": "thr_native_active",
                    "created_at": "2026-04-23T00:00:00Z",
                    "status": "running",
                    "phase": "planning",
                    "pending_approval": False,
                    "last_summary": "recent user work",
                    "files_touched": [],
                    "context_pressure": "low",
                    "stuck_level": 0,
                    "failure_count": 0,
                    "last_progress_at": "2026-04-23T00:05:00Z",
                    "last_substantive_user_input_at": "2026-04-23T00:00:00Z",
                },
            ],
        ),
        liveness_now=current,
    )

    assert [session.project_id for session in bundle.sessions] == ["repo-active"]
    assert [progress.project_id for progress in bundle.progresses] == ["repo-active"]


def test_session_directory_route_progresses_surface_current_child_session_id_resume_shape(
    tmp_path,
) -> None:
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        runtime_client=FakeAClient(
            task={
                "project_id": "repo-b",
                "thread_id": "thr_native_2",
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
    app.state.session_service.record_recovery_execution(
        project_id="repo-b",
        parent_session_id="session:repo-b",
        parent_native_thread_id="thr_native_2",
        recovery_reason="context_critical",
        failure_family="context_pressure",
        failure_signature="critical",
        handoff={
            "handoff_file": "/tmp/repo-b.handoff.md",
            "summary": "handoff",
        },
        resume={
            "project_id": "repo-b",
            "status": "running",
            "mode": "resume_or_new_thread",
            "resume_outcome": "new_child_session",
            "child_session_id": "session:repo-b:thr_child_v1",
            "thread_id": "thr_child_v1",
            "native_thread_id": "thr_child_v1",
        },
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["progresses"][0]["recovery_outcome"] == "new_child_session"
    assert data["progresses"][0]["recovery_child_session_id"] == "session:repo-b:thr_child_v1"
    assert data["message"] == (
        "多项目进展（1）\n"
        "- repo-b | editing_source | editing files | 上下文=low | 恢复=新子会话 repo-b:thr_child_v1"
    )


def test_session_directory_route_progresses_surface_goal_contract_context(tmp_path) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeAClient(
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
                }
            ],
        ),
    )
    GoalContractService(app.state.session_service).bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="收口 recovery 自动重入",
        task_prompt="收口 recovery 自动重入",
        last_user_instruction="继续把 recovery 自动重入收口到 child continuation",
        phase="editing_source",
        last_summary="editing files",
        current_phase_goal="继续把 recovery 自动重入收口到 child continuation",
        explicit_deliverables=["避免重复 handoff"],
        completion_signals=["child continuation 稳定"],
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    progress = next(item for item in data["progresses"] if item["project_id"] == "repo-a")
    assert progress["goal_contract_version"] == "goal-v1"
    assert progress["current_phase_goal"] == "继续把 recovery 自动重入收口到 child continuation"
    assert progress["last_user_instruction"] == "继续把 recovery 自动重入收口到 child continuation"
    assert data["message"] == (
        "多项目进展（1）\n"
        "- repo-a | editing_source | editing files | 上下文=low"
        " | 当前目标=继续把 recovery 自动重入收口到 child continuation"
    )


def test_session_directory_route_surfaces_active_recovery_suppression(tmp_path) -> None:
    active_at = _fresh_iso_z()
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        )
    )
    task = {
        "project_id": "repo-a",
        "thread_id": "thr_native_1",
        "status": "running",
        "phase": "editing_source",
        "pending_approval": False,
        "last_summary": "editing files",
        "files_touched": ["src/example.py"],
        "context_pressure": "critical",
        "stuck_level": 2,
        "failure_count": 3,
        "last_progress_at": active_at,
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
        last_refreshed_at=active_at,
    )
    app.state.session_service.record_event(
        event_type="recovery_execution_suppressed",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:recovery-suppressed:repo-a",
        related_ids={"recovery_transaction_id": "recovery-tx:repo-a"},
        payload={
            "suppression_reason": "reentry_without_newer_progress",
            "suppression_source": "resident_orchestrator",
            "task_status": "active",
            "context_pressure": "critical",
            "last_progress_at": active_at,
        },
        occurred_at=active_at,
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["progresses"][0]["recovery_suppression_reason"] == "reentry_without_newer_progress"
    assert data["progresses"][0]["recovery_suppression_source"] == "resident_orchestrator"
    assert data["progresses"][0]["recovery_suppression_observed_at"] == active_at
    assert data["message"] == (
        "多项目进展（1）\n"
        "- repo-a | editing_source | editing files | 上下文=critical | 恢复抑制=等待新进展"
    )


def test_session_directory_route_surfaces_recovery_cooldown_suppression(tmp_path) -> None:
    active_at = _fresh_iso_z()
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        runtime_client=BrokenAClient(),
    )
    task = {
        "project_id": "repo-a",
        "thread_id": "thr_native_1",
        "status": "running",
        "phase": "editing_source",
        "pending_approval": False,
        "last_summary": "editing files",
        "files_touched": ["src/example.py"],
        "context_pressure": "critical",
        "stuck_level": 2,
        "failure_count": 3,
        "last_progress_at": active_at,
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
        last_refreshed_at=active_at,
    )
    app.state.session_service.record_event(
        event_type="recovery_execution_suppressed",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:recovery-suppressed:repo-a:cooldown",
        related_ids={"recovery_transaction_id": "recovery-tx:repo-a"},
        payload={
            "suppression_reason": "cooldown_window_active",
            "suppression_source": "resident_orchestrator",
            "task_status": "active",
            "context_pressure": "critical",
            "last_progress_at": active_at,
            "cooldown_seconds": "300",
        },
        occurred_at=active_at,
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["progresses"][0]["recovery_suppression_reason"] == "cooldown_window_active"
    assert data["progresses"][0]["recovery_suppression_source"] == "resident_orchestrator"
    assert data["progresses"][0]["recovery_suppression_observed_at"] == active_at
    assert data["message"] == (
        "多项目进展（1）\n"
        "- repo-a | editing_source | editing files | 上下文=critical | 恢复抑制=恢复冷却中"
    )


def test_session_directory_route_surfaces_recovery_in_flight_suppression(tmp_path) -> None:
    active_at = _fresh_iso_z()
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        runtime_client=BrokenAClient(),
    )
    task = {
        "project_id": "repo-a",
        "thread_id": "thr_native_1",
        "status": "handoff_in_progress",
        "phase": "handoff",
        "pending_approval": False,
        "last_summary": "handoff drafted",
        "files_touched": ["src/example.py"],
        "context_pressure": "critical",
        "stuck_level": 2,
        "failure_count": 3,
        "last_progress_at": active_at,
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
        last_refreshed_at=active_at,
    )
    app.state.session_service.record_event(
        event_type="recovery_execution_suppressed",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:recovery-suppressed:repo-a:directory:in-flight",
        related_ids={"recovery_transaction_id": "recovery-tx:repo-a"},
        payload={
            "suppression_reason": "recovery_in_flight",
            "suppression_source": "resident_orchestrator",
            "task_status": "handoff_in_progress",
            "context_pressure": "critical",
            "last_progress_at": active_at,
        },
        occurred_at=active_at,
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["progresses"][0]["recovery_suppression_reason"] == "recovery_in_flight"
    assert data["progresses"][0]["recovery_suppression_source"] == "resident_orchestrator"
    assert data["progresses"][0]["recovery_suppression_observed_at"] == active_at
    assert data["message"] == (
        "多项目进展（1）\n"
        "- repo-a | handoff | handoff drafted | 上下文=critical | 恢复抑制=恢复进行中"
    )


def test_session_directory_route_projects_recovery_suppression_from_session_events_without_live_control(
    tmp_path,
) -> None:
    active_at = _fresh_iso_z()
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="recovery_execution_suppressed",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:recovery-suppressed:repo-a:directory-event-only",
        related_ids={
            "recovery_transaction_id": "recovery-tx:repo-a",
            "native_thread_id": "thr_native_1",
        },
        payload={
            "suppression_reason": "reentry_without_newer_progress",
            "suppression_source": "resident_orchestrator",
            "task_status": "running",
            "context_pressure": "critical",
            "last_progress_at": active_at,
        },
        occurred_at=active_at,
    )
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        runtime_client=BrokenAClient(),
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert [item["project_id"] for item in data["sessions"]] == ["repo-a"]
    assert data["sessions"][0]["thread_id"] == "session:repo-a"
    assert data["sessions"][0]["native_thread_id"] == "thr_native_1"
    assert data["progresses"][0]["recovery_suppression_reason"] == "reentry_without_newer_progress"
    assert data["progresses"][0]["recovery_suppression_source"] == "resident_orchestrator"
    assert data["progresses"][0]["recovery_suppression_observed_at"] == active_at


def test_session_directory_route_merges_live_tasks_with_event_only_recovery_suppression(
    tmp_path,
) -> None:
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="recovery_execution_suppressed",
        project_id="repo-c",
        session_id="session:repo-c",
        correlation_id="corr:recovery-suppressed:repo-c:directory-live-merge",
        related_ids={"recovery_transaction_id": "recovery-tx:repo-c"},
        payload={
            "suppression_reason": "reentry_without_newer_progress",
            "suppression_source": "resident_orchestrator",
            "task_status": "running",
            "context_pressure": "critical",
            "last_progress_at": "2026-04-07T00:00:00Z",
        },
        occurred_at="2026-04-07T00:02:00Z",
    )
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        runtime_client=FakeAClient(
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
                "last_progress_at": "2026-04-07T00:00:00Z",
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
                    "last_progress_at": "2026-04-07T00:00:00Z",
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
                    "last_progress_at": "2026-04-07T00:01:00Z",
                },
                {
                    "project_id": "repo-c",
                    "thread_id": "thr_native_3",
                    "status": "running",
                    "phase": "editing_source",
                    "pending_approval": False,
                    "last_summary": "editing recovery path",
                    "files_touched": ["src/recovery.py"],
                    "context_pressure": "critical",
                    "stuck_level": 2,
                    "failure_count": 3,
                    "last_progress_at": "2026-04-07T00:00:00Z",
                },
                {
                    "project_id": "repo-d",
                    "thread_id": "thr_native_4",
                    "status": "running",
                    "phase": "planning",
                    "pending_approval": False,
                    "last_summary": "waiting",
                    "files_touched": [],
                    "context_pressure": "low",
                    "stuck_level": 0,
                    "failure_count": 0,
                    "last_progress_at": "2026-04-07T00:03:00Z",
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
                    "requested_at": "2026-04-07T00:01:30Z",
                }
            ],
        ),
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert [item["project_id"] for item in data["sessions"]] == [
        "repo-a",
        "repo-b",
        "repo-c",
        "repo-d",
    ]
    progress_by_project = {item["project_id"]: item for item in data["progresses"]}
    assert progress_by_project["repo-c"]["recovery_suppression_reason"] == (
        "reentry_without_newer_progress"
    )
    assert progress_by_project["repo-c"]["recovery_suppression_source"] == (
        "resident_orchestrator"
    )
    assert progress_by_project["repo-c"]["recovery_suppression_observed_at"] == (
        "2026-04-07T00:02:00Z"
    )


def test_session_directory_route_projects_child_interaction_event_without_live_control(
    tmp_path,
) -> None:
    active_at = _fresh_iso_z()
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="interaction_window_expired",
        project_id="repo-a",
        session_id="session:repo-a:thr_child_1",
        correlation_id="corr:interaction:repo-a:directory-child:event-only",
        related_ids={
            "interaction_context_id": "ctx-child-1",
            "interaction_family_id": "family-child-1",
            "actor_id": "user:alice",
            "native_thread_id": "thr_child_1",
        },
        payload={
            "channel_kind": "dm",
            "expired_at": active_at,
            "received_at": active_at,
        },
        occurred_at=active_at,
    )
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        runtime_client=BrokenAClient(),
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert [item["project_id"] for item in data["sessions"]] == ["repo-a"]
    assert data["sessions"][0]["thread_id"] == "session:repo-a"
    assert data["sessions"][0]["native_thread_id"] == "thr_child_1"
    assert data["progresses"][0]["native_thread_id"] == "thr_child_1"


def test_session_directory_route_merges_live_tasks_with_event_only_child_interaction_event(
    tmp_path,
) -> None:
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="interaction_window_expired",
        project_id="repo-c",
        session_id="session:repo-c:thr_child_1",
        correlation_id="corr:interaction:repo-c:directory-live-merge",
        related_ids={
            "interaction_context_id": "ctx-child-1",
            "interaction_family_id": "family-child-1",
            "actor_id": "user:alice",
            "native_thread_id": "thr_child_1",
        },
        payload={
            "channel_kind": "dm",
            "expired_at": "2026-04-07T00:30:00Z",
            "received_at": "2026-04-07T00:40:00Z",
        },
        occurred_at="2026-04-07T00:40:00Z",
    )
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        runtime_client=FakeAClient(
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
                "last_progress_at": "2026-04-07T00:00:00Z",
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
                    "last_progress_at": "2026-04-07T00:00:00Z",
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
                    "last_progress_at": "2026-04-07T00:01:00Z",
                },
                {
                    "project_id": "repo-c",
                    "thread_id": "thr_native_3",
                    "status": "running",
                    "phase": "editing_source",
                    "pending_approval": False,
                    "last_summary": "editing recovery path",
                    "files_touched": ["src/recovery.py"],
                    "context_pressure": "critical",
                    "stuck_level": 2,
                    "failure_count": 3,
                    "last_progress_at": "2026-04-07T00:00:00Z",
                },
                {
                    "project_id": "repo-d",
                    "thread_id": "thr_native_4",
                    "status": "running",
                    "phase": "planning",
                    "pending_approval": False,
                    "last_summary": "waiting",
                    "files_touched": [],
                    "context_pressure": "low",
                    "stuck_level": 0,
                    "failure_count": 0,
                    "last_progress_at": "2026-04-07T00:03:00Z",
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
                    "requested_at": "2026-04-07T00:01:30Z",
                }
            ],
        ),
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert [item["project_id"] for item in data["sessions"]] == [
        "repo-a",
        "repo-b",
        "repo-c",
        "repo-d",
    ]
    progress_by_project = {item["project_id"]: item for item in data["progresses"]}
    assert progress_by_project["repo-c"]["thread_id"] == "session:repo-c"
    assert progress_by_project["repo-c"]["native_thread_id"] == "thr_native_3"


def test_session_directory_route_falls_back_to_canonical_approvals_when_live_approval_read_fails(
    tmp_path,
) -> None:
    class ApprovalFailureAClient(FakeAClient):
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
            raise RuntimeError("approval list unavailable")

    a_client = ApprovalFailureAClient(
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
            "last_progress_at": "2026-04-07T00:00:00Z",
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
                "last_progress_at": "2026-04-07T00:00:00Z",
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
                "last_progress_at": "2026-04-07T00:01:00Z",
            },
        ],
    )
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        runtime_client=a_client,
    )
    materialize_canonical_approval(
        _decision_record(project_id="repo-b", session_id="session:repo-b").model_copy(
            update={
                "native_thread_id": "thr_native_2",
                "approval_id": "appr_001",
                "action_ref": "continue_session",
                "decision_key": (
                    "session:repo-b|fact-v7|policy-v1|require_user_decision|continue_session|appr_001"
                ),
                "idempotency_key": (
                    "session:repo-b|fact-v7|policy-v1|require_user_decision|continue_session|appr_001"
                ),
            }
        ),
        approval_store=app.state.canonical_approval_store,
        session_service=app.state.session_service,
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert [item["project_id"] for item in data["sessions"]] == ["repo-a", "repo-b"]
    sessions_by_project = {item["project_id"]: item for item in data["sessions"]}
    assert sessions_by_project["repo-b"]["pending_approval_count"] == 1


def test_session_directory_route_keeps_live_tasks_when_live_approval_read_fails_without_canonical_fallback(
    tmp_path,
) -> None:
    class ApprovalFailureAClient(FakeAClient):
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
            raise RuntimeError("approval list unavailable")

    a_client = ApprovalFailureAClient(
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
            "last_progress_at": "2026-04-07T00:00:00Z",
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
                "last_progress_at": "2026-04-07T00:00:00Z",
            },
            {
                "project_id": "repo-b",
                "thread_id": "thr_native_2",
                "status": "running",
                "phase": "planning",
                "pending_approval": False,
                "last_summary": "waiting",
                "files_touched": [],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-07T00:01:00Z",
            },
        ],
    )
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        runtime_client=a_client,
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert [item["project_id"] for item in data["sessions"]] == ["repo-a", "repo-b"]
    sessions_by_project = {item["project_id"]: item for item in data["sessions"]}
    assert sessions_by_project["repo-a"]["pending_approval_count"] == 0
    assert sessions_by_project["repo-b"]["pending_approval_count"] == 0


def test_session_directory_route_appends_supplemental_event_only_project_not_present_in_live_tasks(
    tmp_path,
) -> None:
    active_at = _fresh_iso_z()
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="recovery_execution_suppressed",
        project_id="repo-c",
        session_id="session:repo-c",
        correlation_id="corr:recovery-suppressed:repo-c:supplemental",
        related_ids={"recovery_transaction_id": "recovery-tx:repo-c"},
        payload={
            "suppression_reason": "reentry_without_newer_progress",
            "suppression_source": "resident_orchestrator",
            "task_status": "running",
            "context_pressure": "critical",
            "last_progress_at": active_at,
        },
        occurred_at=active_at,
    )
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        runtime_client=FakeAClient(
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
                "last_progress_at": "2026-04-07T00:00:00Z",
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
                    "last_progress_at": "2026-04-07T00:00:00Z",
                },
                {
                    "project_id": "repo-b",
                    "thread_id": "thr_native_2",
                    "status": "planning",
                    "phase": "planning",
                    "pending_approval": False,
                    "last_summary": "waiting",
                    "files_touched": [],
                    "context_pressure": "low",
                    "stuck_level": 0,
                    "failure_count": 0,
                    "last_progress_at": "2026-04-07T00:01:00Z",
                },
            ],
            approvals=[],
        ),
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert [item["project_id"] for item in data["sessions"]] == ["repo-a", "repo-b", "repo-c"]
    progress_by_project = {item["project_id"]: item for item in data["progresses"]}
    assert progress_by_project["repo-c"]["recovery_suppression_reason"] == (
        "reentry_without_newer_progress"
    )
    assert progress_by_project["repo-c"]["recovery_suppression_source"] == (
        "resident_orchestrator"
    )


def test_session_directory_route_preserves_dispatch_cooldown_for_supplemental_persisted_project(
    tmp_path,
) -> None:
    _seed_persisted_session_spine(tmp_path, project_id="repo-c")
    SessionService.from_data_dir(tmp_path).record_continuation_gate_verdict(
        project_id="repo-c",
        session_id="session:repo-c",
        gate_kind="continuation_governance",
        gate_status="eligible",
        decision_source="external_model",
        decision_class="branch_complete_switch",
        action_ref="post_operator_guidance",
        authoritative_snapshot_version="fact-v9",
        snapshot_epoch="session-seq:3",
        goal_contract_version="goal-v7",
        continuation_identity="repo-c:session:repo-c:thr_native_3:branch_complete_switch",
        route_key="repo-c:session:repo-c:thr_native_3:branch_complete_switch:fact-v9",
        branch_switch_token="branch-switch:repo-c:87:fact-v9",
        source_packet_id="packet:handoff-v9",
        causation_id="decision:repo-c",
        correlation_id="corr:continuation-gate:repo-c",
        occurred_at="2026-04-07T00:03:00Z",
    )
    observed_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        runtime_client=FakeAClient(
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
                "last_progress_at": "2026-04-07T00:00:00Z",
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
                    "last_progress_at": "2026-04-07T00:00:00Z",
                }
            ],
            approvals=[],
        ),
    )
    app.state.resident_orchestration_state_store.put_auto_dispatch_checkpoint(
        project_id="repo-c",
        continuation_identity="repo-c:session:repo-c:thr_native_3:branch_complete_switch",
        route_key="repo-c:session:repo-c:thr_native_3:branch_complete_switch:fact-v9",
        action_ref="post_operator_guidance",
        last_auto_dispatch_at=observed_at,
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    progress_by_project = {item["project_id"]: item for item in response.json()["data"]["progresses"]}
    control_plane = progress_by_project["repo-c"]["continuation_control_plane"]
    assert control_plane["dispatch_cooldown"]["active"] is True
    assert control_plane["dispatch_cooldown"]["action_ref"] == "post_operator_guidance"
    assert control_plane["dispatch_cooldown"]["last_dispatched_at"] == observed_at
    assert control_plane["dispatch_cooldown"]["remaining_seconds"] > 0


def test_session_directory_route_appends_supplemental_goal_contract_project_not_present_in_live_tasks(
    tmp_path,
) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    GoalContractService(SessionService.from_data_dir(tmp_path)).bootstrap_contract(
        project_id="repo-c",
        session_id="session:repo-c",
        task_title="收口 recovery 自动重入",
        task_prompt="收口 recovery 自动重入",
        last_user_instruction="继续把 recovery 自动重入收口到 child continuation",
        phase="editing_source",
        last_summary="editing files",
        current_phase_goal="继续把 recovery 自动重入收口到 child continuation",
        explicit_deliverables=["避免重复 handoff"],
        completion_signals=["child continuation 稳定"],
    )
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        runtime_client=FakeAClient(
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
                "last_progress_at": "2026-04-07T00:00:00Z",
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
                    "last_progress_at": "2026-04-07T00:00:00Z",
                },
                {
                    "project_id": "repo-b",
                    "thread_id": "thr_native_2",
                    "status": "planning",
                    "phase": "planning",
                    "pending_approval": False,
                    "last_summary": "waiting",
                    "files_touched": [],
                    "context_pressure": "low",
                    "stuck_level": 0,
                    "failure_count": 0,
                    "last_progress_at": "2026-04-07T00:01:00Z",
                },
            ],
            approvals=[],
        ),
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert [item["project_id"] for item in data["sessions"]] == ["repo-a", "repo-b", "repo-c"]
    progress_by_project = {item["project_id"]: item for item in data["progresses"]}
    assert progress_by_project["repo-c"]["goal_contract_version"] == "goal-v1"
    assert progress_by_project["repo-c"]["summary"] == "editing files"
    assert progress_by_project["repo-c"]["current_phase_goal"] == (
        "继续把 recovery 自动重入收口到 child continuation"
    )
    assert (
        "- repo-c | editing_source | editing files | 上下文=low"
        " | 当前目标=继续把 recovery 自动重入收口到 child continuation"
    ) in data["message"]


def test_session_directory_route_projects_goal_contract_only_events_without_live_control(
    tmp_path,
) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    GoalContractService(SessionService.from_data_dir(tmp_path)).bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="收口 recovery 自动重入",
        task_prompt="收口 recovery 自动重入",
        last_user_instruction="继续把 recovery 自动重入收口到 child continuation",
        phase="editing_source",
        last_summary="editing files",
        current_phase_goal="继续把 recovery 自动重入收口到 child continuation",
        explicit_deliverables=["避免重复 handoff"],
        completion_signals=["child continuation 稳定"],
    )
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        runtime_client=BrokenAClient(),
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert [item["project_id"] for item in data["sessions"]] == ["repo-a"]
    assert data["progresses"][0]["goal_contract_version"] == "goal-v1"
    assert data["progresses"][0]["summary"] == "editing files"
    assert data["message"] == (
        "多项目进展（1）\n"
        "- repo-a | editing_source | editing files | 上下文=low"
        " | 当前目标=继续把 recovery 自动重入收口到 child continuation"
    )


def test_session_directory_route_appends_supplemental_persisted_project_not_present_in_live_tasks(
    tmp_path,
) -> None:
    _seed_persisted_session_spine(tmp_path, project_id="repo-c")
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        runtime_client=FakeAClient(
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
                "last_progress_at": "2026-04-07T00:00:00Z",
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
                    "last_progress_at": "2026-04-07T00:00:00Z",
                },
                {
                    "project_id": "repo-b",
                    "thread_id": "thr_native_2",
                    "status": "planning",
                    "phase": "planning",
                    "pending_approval": False,
                    "last_summary": "waiting",
                    "files_touched": [],
                    "context_pressure": "low",
                    "stuck_level": 0,
                    "failure_count": 0,
                    "last_progress_at": "2026-04-07T00:01:00Z",
                },
            ],
            approvals=[],
        ),
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert [item["project_id"] for item in data["sessions"]] == ["repo-a", "repo-b", "repo-c"]
    sessions_by_project = {item["project_id"]: item for item in data["sessions"]}
    assert sessions_by_project["repo-c"]["thread_id"] == "session:repo-c"
    assert sessions_by_project["repo-c"]["native_thread_id"] == "thr_native_1"


def test_session_directory_route_surfaces_resident_expert_coverage(tmp_path) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    stale_seen_at = (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    fresh_seen_at = now.isoformat().replace("+00:00", "Z")
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
            resident_expert_stale_after_seconds=60.0,
        ),
        runtime_client=_client(),
    )
    resident_expert_runtime_service = app.state.resident_expert_runtime_service
    resident_expert_runtime_service.bind_runtime_handle(
        expert_id="managed-agent-expert",
        runtime_handle="agent://james",
        observed_at=stale_seen_at,
    )
    resident_expert_runtime_service.bind_runtime_handle(
        expert_id="hermes-agent-expert",
        runtime_handle="agent://hegel",
        observed_at=fresh_seen_at,
    )
    resident_expert_runtime_service.consult_or_restore(
        expert_ids=["managed-agent-expert", "hermes-agent-expert"],
        consultation_ref="consult:repo-a:resident-experts",
        observed_runtime_handles={"hermes-agent-expert": "agent://hegel"},
        consulted_at=fresh_seen_at,
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    coverage = response.json()["data"]["resident_expert_coverage"]
    assert coverage["coverage_status"] == "degraded"
    assert coverage["available_expert_count"] == 1
    assert coverage["bound_expert_count"] == 0
    assert coverage["restoring_expert_count"] == 0
    assert coverage["stale_expert_count"] == 1
    assert coverage["unavailable_expert_count"] == 0
    assert coverage["degraded_expert_ids"] == ["managed-agent-expert"]
    assert coverage["latest_consultation_ref"] == "consult:repo-a:resident-experts"
    assert coverage["latest_consulted_at"] == fresh_seen_at


def test_session_by_native_thread_route_returns_stable_session_projection(tmp_path) -> None:
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=_client(),
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


def test_session_by_native_thread_route_reads_legacy_persisted_native_thread_from_nested_snapshot(
    tmp_path,
) -> None:
    path = _seed_persisted_session_spine(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["sessions"]["repo-a"]["native_thread_id"] = None
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=BrokenAClient(),
    )
    c = TestClient(app)

    response = c.get(
        "/api/v1/watchdog/sessions/by-native-thread/thr_native_1",
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["reply_code"] == "session_projection"
    assert data["snapshot"]["read_source"] == "persisted_spine"
    assert data["session"]["thread_id"] == "session:repo-a"
    assert data["session"]["native_thread_id"] == "thr_native_1"
    assert data["progress"]["native_thread_id"] == "thr_native_1"


def test_session_by_native_thread_route_preserves_lookup_native_thread_when_envelope_omits_it(
    tmp_path,
) -> None:
    class MissingNativeThreadClient(FakeAClient):
        def get_envelope_by_thread(self, thread_id: str) -> dict[str, object]:
            assert thread_id == "thr_native_1"
            return {
                "success": True,
                "data": {
                    "project_id": "repo-a",
                    "thread_id": "session:repo-a",
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
            }

    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=MissingNativeThreadClient(
            task={
                "project_id": "repo-a",
                "thread_id": "session:repo-a",
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

    response = c.get(
        "/api/v1/watchdog/sessions/by-native-thread/thr_native_1",
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["snapshot"]["read_source"] == "session_events_projection"
    assert data["session"]["thread_id"] == "session:repo-a"
    assert data["session"]["native_thread_id"] == "thr_native_1"
    assert data["progress"]["thread_id"] == "session:repo-a"
    assert data["progress"]["native_thread_id"] == "thr_native_1"


def test_session_by_native_thread_route_surfaces_active_recovery_suppression(tmp_path) -> None:
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="recovery_execution_suppressed",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:recovery-suppressed:repo-a:native-thread",
        related_ids={"recovery_transaction_id": "recovery-tx:repo-a"},
        payload={
            "suppression_reason": "reentry_without_newer_progress",
            "suppression_source": "resident_orchestrator",
            "context_pressure": "critical",
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        occurred_at="2026-04-05T05:21:00Z",
    )
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeAClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "editing recovery path",
                "files_touched": ["src/recovery.py"],
                "context_pressure": "critical",
                "stuck_level": 2,
                "failure_count": 3,
                "last_progress_at": "2026-04-05T05:20:00Z",
            }
        ),
    )
    c = TestClient(app)

    response = c.get(
        "/api/v1/watchdog/sessions/by-native-thread/thr_native_1",
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["reply_code"] == "session_projection"
    assert data["intent_code"] == "get_session_by_native_thread"
    assert data["message"] == "editing recovery path | 恢复抑制=等待新进展"
    assert data["progress"]["recovery_suppression_reason"] == "reentry_without_newer_progress"
    assert data["progress"]["recovery_suppression_source"] == "resident_orchestrator"
    assert data["progress"]["recovery_suppression_observed_at"] == "2026-04-05T05:21:00Z"


def test_session_by_native_thread_route_projects_recovery_suppression_from_session_events_without_live_control(
    tmp_path,
) -> None:
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="recovery_execution_suppressed",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:recovery-suppressed:repo-a:native-thread:event-only",
        related_ids={
            "recovery_transaction_id": "recovery-tx:repo-a",
            "native_thread_id": "thr_native_1",
        },
        payload={
            "suppression_reason": "reentry_without_newer_progress",
            "suppression_source": "resident_orchestrator",
            "task_status": "running",
            "context_pressure": "critical",
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        occurred_at="2026-04-05T05:21:00Z",
    )
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=BrokenAClient(),
    )
    c = TestClient(app)

    response = c.get(
        "/api/v1/watchdog/sessions/by-native-thread/thr_native_1",
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["reply_code"] == "session_projection"
    assert data["intent_code"] == "get_session_by_native_thread"
    assert data["snapshot"]["read_source"] == "session_events_projection"
    assert data["session"]["thread_id"] == "session:repo-a"
    assert data["session"]["native_thread_id"] == "thr_native_1"
    assert data["progress"]["native_thread_id"] == "thr_native_1"
    assert data["progress"]["recovery_suppression_reason"] == "reentry_without_newer_progress"
    assert [fact["fact_code"] for fact in data["facts"]] == ["recovery_execution_suppressed"]


def test_session_by_native_thread_route_projects_goal_contract_adoption_from_session_events_without_live_control(
    tmp_path,
) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    service = GoalContractService(SessionService.from_data_dir(tmp_path))
    created = service.bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="收口 recovery 自动重入",
        task_prompt="收口 recovery 自动重入",
        last_user_instruction="继续把 recovery 自动重入收口到 child continuation",
        phase="editing_source",
        last_summary="editing files",
        current_phase_goal="继续把 recovery 自动重入收口到 child continuation",
        explicit_deliverables=["避免重复 handoff"],
        completion_signals=["child continuation 稳定"],
    )
    service.adopt_contract_for_child_session(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        child_session_id="session:repo-a:child-v1",
        child_native_thread_id="thr_child_v1",
        expected_version=created.version,
        recovery_transaction_id="recovery-tx:repo-a",
    )
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=BrokenAClient(),
    )
    c = TestClient(app)

    response = c.get(
        "/api/v1/watchdog/sessions/by-native-thread/thr_child_v1",
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["reply_code"] == "session_projection"
    assert data["intent_code"] == "get_session_by_native_thread"
    assert data["snapshot"]["read_source"] == "session_events_projection"
    assert data["session"]["headline"] == "editing files"
    assert data["session"]["native_thread_id"] == "thr_child_v1"
    assert data["message"] == "editing files | 当前目标=继续把 recovery 自动重入收口到 child continuation"
    assert data["progress"]["goal_contract_version"] == created.version
    assert data["progress"]["native_thread_id"] == "thr_child_v1"


def test_session_by_native_thread_route_renders_recovery_cooldown_suppression_summary(
    tmp_path,
) -> None:
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="recovery_execution_suppressed",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:recovery-suppressed:repo-a:native-thread:cooldown",
        related_ids={"recovery_transaction_id": "recovery-tx:repo-a"},
        payload={
            "suppression_reason": "cooldown_window_active",
            "suppression_source": "resident_orchestrator",
            "context_pressure": "critical",
            "last_progress_at": "2026-04-05T05:20:00Z",
            "cooldown_seconds": "300",
        },
        occurred_at="2026-04-05T05:21:00Z",
    )
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeAClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "editing recovery path",
                "files_touched": ["src/recovery.py"],
                "context_pressure": "critical",
                "stuck_level": 2,
                "failure_count": 3,
                "last_progress_at": "2026-04-05T05:20:00Z",
            }
        ),
    )
    c = TestClient(app)

    response = c.get(
        "/api/v1/watchdog/sessions/by-native-thread/thr_native_1",
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["message"] == "editing recovery path | 恢复抑制=恢复冷却中"
    assert data["progress"]["recovery_suppression_reason"] == "cooldown_window_active"
    recovery_fact = next(
        fact for fact in data["facts"] if fact["fact_code"] == "recovery_execution_suppressed"
    )
    assert recovery_fact["detail"] == (
        "suppression_reason=恢复冷却中 suppression_source=resident_orchestrator"
    )


def test_session_by_native_thread_route_renders_recovery_in_flight_suppression_summary(
    tmp_path,
) -> None:
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="recovery_execution_suppressed",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:recovery-suppressed:repo-a:native-thread:in-flight",
        related_ids={"recovery_transaction_id": "recovery-tx:repo-a"},
        payload={
            "suppression_reason": "recovery_in_flight",
            "suppression_source": "resident_orchestrator",
            "task_status": "handoff_in_progress",
            "context_pressure": "critical",
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        occurred_at="2026-04-05T05:21:00Z",
    )
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeAClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "handoff_in_progress",
                "phase": "handoff",
                "pending_approval": False,
                "last_summary": "handoff drafted",
                "files_touched": ["src/recovery.py"],
                "context_pressure": "critical",
                "stuck_level": 2,
                "failure_count": 3,
                "last_progress_at": "2026-04-05T05:20:00Z",
            }
        ),
    )
    c = TestClient(app)

    response = c.get(
        "/api/v1/watchdog/sessions/by-native-thread/thr_native_1",
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["message"] == "handoff drafted | 恢复抑制=恢复进行中"
    assert data["progress"]["recovery_suppression_reason"] == "recovery_in_flight"
    recovery_fact = next(
        fact for fact in data["facts"] if fact["fact_code"] == "recovery_execution_suppressed"
    )
    assert recovery_fact["detail"] == (
        "suppression_reason=恢复进行中 suppression_source=resident_orchestrator"
    )


def test_session_by_native_thread_route_projects_child_session_interaction_event_without_live_control(
    tmp_path,
) -> None:
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="interaction_window_expired",
        project_id="repo-a",
        session_id="session:repo-a:thr_child_1",
        correlation_id="corr:interaction:repo-a:child:event-only",
        related_ids={
            "interaction_context_id": "ctx-child-1",
            "interaction_family_id": "family-child-1",
            "actor_id": "user:alice",
            "native_thread_id": "thr_child_1",
        },
        payload={
            "channel_kind": "dm",
            "expired_at": "2026-04-07T00:30:00Z",
            "received_at": "2026-04-07T00:40:00Z",
        },
        occurred_at="2026-04-07T00:40:00Z",
    )
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=BrokenAClient(),
    )
    c = TestClient(app)

    response = c.get(
        "/api/v1/watchdog/sessions/by-native-thread/thr_child_1",
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["reply_code"] == "session_projection"
    assert data["intent_code"] == "get_session_by_native_thread"
    assert data["snapshot"]["read_source"] == "session_events_projection"
    assert data["session"]["project_id"] == "repo-a"
    assert data["session"]["thread_id"] == "session:repo-a"
    assert data["session"]["native_thread_id"] == "thr_child_1"
    assert [fact["fact_code"] for fact in data["facts"]] == ["interaction_window_expired"]


def test_session_route_projects_child_interaction_event_without_live_control(
    tmp_path,
) -> None:
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="interaction_window_expired",
        project_id="repo-a",
        session_id="session:repo-a:thr_child_1",
        correlation_id="corr:interaction:repo-a:project-child:event-only",
        related_ids={
            "interaction_context_id": "ctx-child-1",
            "interaction_family_id": "family-child-1",
            "actor_id": "user:alice",
            "native_thread_id": "thr_child_1",
        },
        payload={
            "channel_kind": "dm",
            "expired_at": "2026-04-07T00:30:00Z",
            "received_at": "2026-04-07T00:40:00Z",
        },
        occurred_at="2026-04-07T00:40:00Z",
    )
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=BrokenAClient(),
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions/repo-a", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["snapshot"]["read_source"] == "session_events_projection"
    assert data["session"]["thread_id"] == "session:repo-a"
    assert data["session"]["native_thread_id"] == "thr_child_1"
    assert data["progress"]["native_thread_id"] == "thr_child_1"
    assert [fact["fact_code"] for fact in data["facts"]] == ["interaction_window_expired"]


def test_session_route_surfaces_active_recovery_suppression(tmp_path) -> None:
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="recovery_execution_suppressed",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:recovery-suppressed:repo-a:session-route",
        related_ids={"recovery_transaction_id": "recovery-tx:repo-a"},
        payload={
            "suppression_reason": "reentry_without_newer_progress",
            "suppression_source": "resident_orchestrator",
            "context_pressure": "critical",
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        occurred_at="2026-04-05T05:21:00Z",
    )
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeAClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "editing recovery path",
                "files_touched": ["src/recovery.py"],
                "context_pressure": "critical",
                "stuck_level": 2,
                "failure_count": 3,
                "last_progress_at": "2026-04-05T05:20:00Z",
            }
        ),
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions/repo-a", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["reply_code"] == "session_projection"
    assert data["message"] == "editing recovery path | 恢复抑制=等待新进展"
    assert "recovery_execution_suppressed" in [fact["fact_code"] for fact in data["facts"]]
    assert data["progress"]["recovery_suppression_reason"] == "reentry_without_newer_progress"
    assert data["progress"]["recovery_suppression_source"] == "resident_orchestrator"
    assert data["progress"]["recovery_suppression_observed_at"] == "2026-04-05T05:21:00Z"


def test_session_route_surfaces_goal_contract_context_from_latest_child_adoption(tmp_path) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeAClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_child_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "editing files",
                "files_touched": ["src/recovery.py"],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T05:20:00Z",
            }
        ),
    )
    goal_contracts = GoalContractService(app.state.session_service)
    created = goal_contracts.bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="收口 recovery 自动重入",
        task_prompt="收口 recovery 自动重入",
        last_user_instruction="继续把 recovery 自动重入收口到 child continuation",
        phase="editing_source",
        last_summary="editing files",
        current_phase_goal="继续把 recovery 自动重入收口到 child continuation",
        explicit_deliverables=["避免重复 handoff"],
        completion_signals=["child continuation 稳定"],
    )
    goal_contracts.adopt_contract_for_child_session(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        child_session_id="session:repo-a:thr_child_1",
        child_native_thread_id="thr_child_1",
        expected_version=created.version,
        recovery_transaction_id="recovery-tx:repo-a",
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions/repo-a", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["message"] == "editing files | 当前目标=继续把 recovery 自动重入收口到 child continuation"
    assert data["progress"]["goal_contract_version"] == "goal-v1"
    assert data["progress"]["current_phase_goal"] == "继续把 recovery 自动重入收口到 child continuation"
    assert data["progress"]["last_user_instruction"] == "继续把 recovery 自动重入收口到 child continuation"


def test_session_route_renders_recovery_in_flight_suppression(tmp_path) -> None:
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="recovery_execution_suppressed",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:recovery-suppressed:repo-a:session-route:in-flight",
        related_ids={"recovery_transaction_id": "recovery-tx:repo-a"},
        payload={
            "suppression_reason": "recovery_in_flight",
            "suppression_source": "resident_orchestrator",
            "task_status": "handoff_in_progress",
            "context_pressure": "critical",
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        occurred_at="2026-04-05T05:21:00Z",
    )
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeAClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "handoff_in_progress",
                "phase": "handoff",
                "pending_approval": False,
                "last_summary": "handoff drafted",
                "files_touched": ["src/recovery.py"],
                "context_pressure": "critical",
                "stuck_level": 2,
                "failure_count": 3,
                "last_progress_at": "2026-04-05T05:20:00Z",
            }
        ),
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions/repo-a", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["message"] == "handoff drafted | 恢复抑制=恢复进行中"
    assert data["progress"]["recovery_suppression_reason"] == "recovery_in_flight"
    recovery_fact = next(
        fact for fact in data["facts"] if fact["fact_code"] == "recovery_execution_suppressed"
    )
    assert recovery_fact["detail"] == (
        "suppression_reason=恢复进行中 suppression_source=resident_orchestrator"
    )


def test_session_route_projects_recovery_suppression_from_session_events_without_live_control(
    tmp_path,
) -> None:
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="recovery_execution_suppressed",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:recovery-suppressed:repo-a:event-only",
        related_ids={
            "recovery_transaction_id": "recovery-tx:repo-a",
            "native_thread_id": "thr_native_1",
        },
        payload={
            "suppression_reason": "reentry_without_newer_progress",
            "suppression_source": "resident_orchestrator",
            "task_status": "running",
            "context_pressure": "critical",
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        occurred_at="2026-04-05T05:21:00Z",
    )
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=BrokenAClient(),
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions/repo-a", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["snapshot"]["read_source"] == "session_events_projection"
    assert data["session"]["thread_id"] == "session:repo-a"
    assert data["session"]["native_thread_id"] == "thr_native_1"
    assert data["progress"]["native_thread_id"] == "thr_native_1"
    assert data["progress"]["recovery_suppression_reason"] == "reentry_without_newer_progress"
    assert data["progress"]["recovery_suppression_source"] == "resident_orchestrator"
    assert data["progress"]["recovery_suppression_observed_at"] == "2026-04-05T05:21:00Z"
    assert [fact["fact_code"] for fact in data["facts"]] == ["recovery_execution_suppressed"]


def test_session_route_projects_goal_contract_context_from_session_events_without_live_control(
    tmp_path,
) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    GoalContractService(SessionService.from_data_dir(tmp_path)).bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="收口 recovery 自动重入",
        task_prompt="收口 recovery 自动重入",
        last_user_instruction="继续把 recovery 自动重入收口到 child continuation",
        phase="editing_source",
        last_summary="editing files",
        current_phase_goal="继续把 recovery 自动重入收口到 child continuation",
        explicit_deliverables=["避免重复 handoff"],
        completion_signals=["child continuation 稳定"],
    )
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=BrokenAClient(),
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions/repo-a", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["snapshot"]["read_source"] == "session_events_projection"
    assert data["session"]["activity_phase"] == "editing_source"
    assert data["session"]["headline"] == "editing files"
    assert data["message"] == "editing files | 当前目标=继续把 recovery 自动重入收口到 child continuation"
    assert data["progress"]["goal_contract_version"] == "goal-v1"
    assert data["progress"]["current_phase_goal"] == "继续把 recovery 自动重入收口到 child continuation"
    assert data["progress"]["summary"] == "editing files"


def test_session_route_projects_revised_goal_contract_summary_from_session_events_without_live_control(
    tmp_path,
) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    contracts = GoalContractService(SessionService.from_data_dir(tmp_path))
    created = contracts.bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="旧目标",
        task_prompt="旧目标",
        last_user_instruction="旧目标",
        phase="editing_source",
        last_summary="旧摘要",
        current_phase_goal="旧阶段目标",
        explicit_deliverables=["避免重复 handoff"],
        completion_signals=["child continuation 稳定"],
    )
    contracts.revise_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        expected_version=created.version,
        current_phase_goal="继续把 recovery 自动重入收口到 child continuation",
        last_user_instruction="继续把 recovery 自动重入收口到 child continuation",
        last_summary="继续把 recovery 自动重入收口到 child continuation",
    )
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=BrokenAClient(),
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions/repo-a", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["snapshot"]["read_source"] == "session_events_projection"
    assert data["session"]["headline"] == "继续把 recovery 自动重入收口到 child continuation"
    assert data["message"] == "继续把 recovery 自动重入收口到 child continuation | 当前目标=继续把 recovery 自动重入收口到 child continuation"
    assert data["progress"]["goal_contract_version"] == "goal-v2"
    assert data["progress"]["summary"] == "继续把 recovery 自动重入收口到 child continuation"
    assert data["progress"]["last_user_instruction"] == "继续把 recovery 自动重入收口到 child continuation"


def test_session_route_projects_interaction_expired_from_session_events_without_live_control(
    tmp_path,
) -> None:
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="interaction_window_expired",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:interaction:repo-a:event-only",
        related_ids={
            "interaction_context_id": "ctx-approval-1",
            "interaction_family_id": "family-approval-1",
            "actor_id": "user:alice",
            "native_thread_id": "thr_native_1",
        },
        payload={
            "channel_kind": "dm",
            "expired_at": "2026-04-07T00:30:00Z",
            "received_at": "2026-04-07T00:40:00Z",
        },
        occurred_at="2026-04-07T00:40:00Z",
    )
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=BrokenAClient(),
    )
    c = TestClient(app)

    response = c.get("/api/v1/watchdog/sessions/repo-a", headers={"Authorization": "Bearer wt"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["snapshot"]["read_source"] == "session_events_projection"
    assert data["session"]["thread_id"] == "session:repo-a"
    assert data["session"]["native_thread_id"] == "thr_native_1"
    assert data["progress"]["native_thread_id"] == "thr_native_1"
    assert [fact["fact_code"] for fact in data["facts"]] == ["interaction_window_expired"]
    assert data["facts"][0]["related_ids"]["interaction_context_id"] == "ctx-approval-1"


def test_workspace_activity_route_returns_stable_workspace_activity_view(tmp_path) -> None:
    a_client = _client()
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=a_client,
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


def test_workspace_activity_route_prefers_explicit_native_thread_id(tmp_path) -> None:
    a_client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "session:repo-a",
            "native_thread_id": "thr_native_1",
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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=a_client,
    )
    c = TestClient(app)

    response = c.get(
        "/api/v1/watchdog/sessions/repo-a/workspace-activity?recent_minutes=30",
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["reply_code"] == "workspace_activity_view"
    assert data["workspace_activity"]["thread_id"] == "session:repo-a"
    assert data["workspace_activity"]["native_thread_id"] == "thr_native_1"


def test_session_event_snapshot_route_returns_stable_reply_model(tmp_path) -> None:
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=_client(),
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


def test_session_event_snapshot_route_dedupes_duplicate_raw_snapshot_event_ids(tmp_path) -> None:
    class DuplicateEventsClient(FakeAClient):
        def get_events_snapshot(
            self,
            project_id: str,
            *,
            poll_interval: float = 0.5,
        ) -> tuple[str, str]:
            assert project_id == "repo-a"
            _ = poll_interval
            return (
                'id: evt_001\n'
                "event: resume\n"
                'data: {"event_id":"evt_001","project_id":"repo-a","thread_id":"session:repo-a","native_thread_id":"thr_native_1","event_type":"resume","event_source":"a_control_agent","payload_json":{"mode":"resume_or_new_thread"},"created_at":"2026-04-05T10:00:00Z"}\n\n'
                'id: evt_001\n'
                "event: resume\n"
                'data: {"event_id":"evt_001","project_id":"repo-a","thread_id":"session:repo-a","native_thread_id":"thr_native_1","event_type":"resume","event_source":"a_control_agent","payload_json":{"mode":"resume_or_new_thread"},"created_at":"2026-04-05T10:00:00Z"}\n\n',
                "text/event-stream",
            )

    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=DuplicateEventsClient(
            task={
                "project_id": "repo-a",
                "thread_id": "session:repo-a",
                "native_thread_id": "thr_native_1",
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

    response = c.get(
        "/api/v1/watchdog/sessions/repo-a/event-snapshot",
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["reply_code"] == "session_event_snapshot"
    assert len(data["events"]) == 1
    assert data["events"][0]["event_code"] == "session_resumed"


def test_session_event_snapshot_route_keeps_distinct_legacy_raw_events_without_event_id(
    tmp_path,
) -> None:
    class MissingEventIdClient(FakeAClient):
        def get_events_snapshot(
            self,
            project_id: str,
            *,
            poll_interval: float = 0.5,
        ) -> tuple[str, str]:
            assert project_id == "repo-a"
            _ = poll_interval
            return (
                "event: resume\n"
                'data: {"project_id":"repo-a","thread_id":"thr_native_1","event_type":"resume","event_source":"a_control_agent","payload_json":{"mode":"resume_or_new_thread"},"created_at":"2026-04-05T10:02:00Z"}\n\n'
                "event: resume\n"
                'data: {"project_id":"repo-a","thread_id":"thr_native_1","event_type":"resume","event_source":"a_control_agent","payload_json":{"mode":"resume_or_new_thread"},"created_at":"2026-04-05T10:02:00Z"}\n\n',
                "text/event-stream",
            )

    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=MissingEventIdClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "implementation",
                "updated_at": "2026-04-05T10:02:00Z",
            }
        ),
    )
    c = TestClient(app)

    response = c.get(
        "/api/v1/watchdog/sessions/repo-a/event-snapshot",
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["reply_code"] == "session_event_snapshot"
    assert len(data["events"]) == 2
    assert data["events"][0]["event_code"] == "session_resumed"
    assert data["events"][1]["event_code"] == "session_resumed"
    assert data["events"][0]["event_id"].startswith("synthetic:")
    assert data["events"][1]["event_id"].startswith("synthetic:")
    assert data["events"][0]["event_id"] != data["events"][1]["event_id"]


def test_session_event_snapshot_route_prefers_explicit_native_thread_id(tmp_path) -> None:
    class EventsClient(FakeAClient):
        def get_events_snapshot(
            self,
            project_id: str,
            *,
            poll_interval: float = 0.5,
        ) -> tuple[str, str]:
            assert project_id == "repo-a"
            _ = poll_interval
            return (
                'id: evt_001\n'
                "event: resume\n"
                'data: {"event_id":"evt_001","project_id":"repo-a","thread_id":"session:repo-a","native_thread_id":"thr_native_1","event_type":"resume","event_source":"a_control_agent","payload_json":{"mode":"resume_or_new_thread"},"created_at":"2026-04-05T10:00:00Z"}\n\n',
                "text/event-stream",
            )

    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=EventsClient(
            task={
                "project_id": "repo-a",
                "thread_id": "session:repo-a",
                "native_thread_id": "thr_native_1",
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

    response = c.get(
        "/api/v1/watchdog/sessions/repo-a/event-snapshot",
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["reply_code"] == "session_event_snapshot"
    assert len(data["events"]) == 1
    assert data["events"][0]["event_code"] == "session_resumed"
    assert data["events"][0]["thread_id"] == "session:repo-a"
    assert data["events"][0]["native_thread_id"] == "thr_native_1"


def test_session_event_snapshot_route_merges_raw_and_session_service_child_adoption_events(
    tmp_path,
) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeAClient(
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
    goal_contracts = GoalContractService(app.state.session_service)
    created = goal_contracts.bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="继续 recovery",
        task_prompt="把 child adoption 合并到 event snapshot",
        last_user_instruction="继续补 event snapshot merge",
        phase="implementation",
        last_summary="正在补 event snapshot merge",
        explicit_deliverables=["event snapshot 合并 raw 与 canonical"],
        completion_signals=["相关 pytest 通过"],
    )
    goal_contracts.adopt_contract_for_child_session(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        child_session_id="session:repo-a:thr_child_1",
        child_native_thread_id="thr_child_1",
        expected_version=created.version,
        recovery_transaction_id="recovery-tx:1",
        source_packet_id="packet:handoff-1",
    )
    c = TestClient(app)

    response = c.get(
        "/api/v1/watchdog/sessions/repo-a/event-snapshot",
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["reply_code"] == "session_event_snapshot"
    assert len(data["events"]) == 3
    assert [event["event_code"] for event in data["events"]].count("session_updated") == 2
    resumed_events = [
        event for event in data["events"] if event["event_code"] == "session_resumed"
    ]
    assert len(resumed_events) == 1
    assert resumed_events[0]["thread_id"] == "session:repo-a:thr_child_1"
    assert resumed_events[0]["native_thread_id"] == "thr_child_1"
    assert resumed_events[0]["related_ids"]["child_session_id"] == "session:repo-a:thr_child_1"


def test_session_event_snapshot_route_falls_back_to_session_service_when_control_link_fails(
    tmp_path,
) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    class BrokenEventsClient(FakeAClient):
        def get_events_snapshot(
            self,
            project_id: str,
            *,
            poll_interval: float = 0.5,
        ) -> tuple[str, str]:
            _ = (project_id, poll_interval)
            raise RuntimeError("a-side temporarily unavailable")

    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=BrokenEventsClient(
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
    goal_contracts = GoalContractService(app.state.session_service)
    created = goal_contracts.bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="继续 recovery",
        task_prompt="control link 失败时也要能读 canonical events",
        last_user_instruction="继续补 event snapshot fallback",
        phase="implementation",
        last_summary="正在补 event snapshot fallback",
        explicit_deliverables=["event snapshot fallback 到 session service"],
        completion_signals=["相关 pytest 通过"],
    )
    goal_contracts.adopt_contract_for_child_session(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        child_session_id="session:repo-a:thr_child_1",
        child_native_thread_id="thr_child_1",
        expected_version=created.version,
        recovery_transaction_id="recovery-tx:1",
        source_packet_id="packet:handoff-1",
    )
    c = TestClient(app)

    response = c.get(
        "/api/v1/watchdog/sessions/repo-a/event-snapshot",
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["reply_code"] == "session_event_snapshot"
    assert len(data["events"]) == 2
    assert data["events"][-1]["event_code"] == "session_resumed"
    assert data["events"][-1]["related_ids"]["recovery_transaction_id"] == "recovery-tx:1"


def test_approval_inbox_route_returns_stable_reply_and_optional_project_filter(tmp_path) -> None:
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeAClient(
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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeAClient(
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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=a_client,
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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=PartialFailureAClient(
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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=a_client,
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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=LegacyFilterAClient(
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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeAClient(
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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeAClient(
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


def test_session_spine_stuck_explanation_route_surfaces_goal_contract_context(tmp_path) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeAClient(
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
    GoalContractService(app.state.session_service).bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="收口 recovery 自动重入",
        task_prompt="收口 recovery 自动重入",
        last_user_instruction="继续把 recovery 自动重入收口到 child continuation",
        phase="editing_source",
        last_summary="repeated failures",
        current_phase_goal="继续把 recovery 自动重入收口到 child continuation",
        explicit_deliverables=["避免重复 handoff"],
        completion_signals=["child continuation 稳定"],
    )
    c = TestClient(app)

    response = c.get(
        "/api/v1/watchdog/sessions/repo-a/stuck-explanation",
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["reply_code"] == "stuck_explanation"
    assert (
        data["message"]
        == "session appears stuck; repeated failures detected; context pressure is critical"
        " | 当前目标=继续把 recovery 自动重入收口到 child continuation"
    )


def test_session_spine_blocker_explanation_route_returns_stable_reply_model(tmp_path) -> None:
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=_client(),
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


def test_session_spine_blocker_explanation_route_surfaces_goal_contract_context(tmp_path) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=_client(),
    )
    GoalContractService(app.state.session_service).bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="收口 recovery 自动重入",
        task_prompt="收口 recovery 自动重入",
        last_user_instruction="继续把 recovery 自动重入收口到 child continuation",
        phase="approval",
        last_summary="waiting for approval",
        current_phase_goal="继续把 recovery 自动重入收口到 child continuation",
        explicit_deliverables=["避免重复 handoff"],
        completion_signals=["child continuation 稳定"],
    )
    c = TestClient(app)

    response = c.get(
        "/api/v1/watchdog/sessions/repo-a/blocker-explanation",
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["reply_code"] == "blocker_explanation"
    assert (
        data["message"]
        == "approval required; awaiting operator direction"
        " | 当前目标=继续把 recovery 自动重入收口到 child continuation"
    )


def test_stuck_and_blocker_routes_fall_back_to_session_events_without_persisted_spine(
    tmp_path,
) -> None:
    a_client = BrokenAClient()
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=a_client,
    )
    materialize_canonical_approval(
        _decision_record(project_id="repo-a").model_copy(update={"native_thread_id": "thr_native_1"}),
        approval_store=app.state.canonical_approval_store,
        session_service=app.state.session_service,
    )
    c = TestClient(app)

    stuck_response = c.get(
        "/api/v1/watchdog/sessions/repo-a/stuck-explanation",
        headers={"Authorization": "Bearer wt"},
    )
    blocker_response = c.get(
        "/api/v1/watchdog/sessions/repo-a/blocker-explanation",
        headers={"Authorization": "Bearer wt"},
    )

    assert stuck_response.status_code == 200
    assert blocker_response.status_code == 200
    stuck_data = stuck_response.json()["data"]
    blocker_data = blocker_response.json()["data"]

    assert stuck_data["reply_code"] == "stuck_explanation"
    assert blocker_data["reply_code"] == "blocker_explanation"
    assert stuck_data["session"]["thread_id"] == "session:repo-a"
    assert blocker_data["session"]["thread_id"] == "session:repo-a"
    assert stuck_data["session"]["native_thread_id"] == "thr_native_1"
    assert blocker_data["session"]["native_thread_id"] == "thr_native_1"
    assert stuck_data["progress"]["native_thread_id"] == "thr_native_1"
    assert blocker_data["progress"]["native_thread_id"] == "thr_native_1"
    assert [fact["fact_code"] for fact in blocker_data["facts"]] == [
        "approval_pending",
        "awaiting_human_direction",
    ]
    assert a_client.get_envelope_calls == []
    assert a_client.list_approvals_calls == []


def test_continue_action_blocks_from_session_events_without_persisted_spine(tmp_path) -> None:
    a_client = BrokenAClient()
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=a_client,
    )
    materialize_canonical_approval(
        _decision_record(project_id="repo-a").model_copy(update={"native_thread_id": "thr_native_1"}),
        approval_store=app.state.canonical_approval_store,
        session_service=app.state.session_service,
    )
    c = TestClient(app)

    response = c.post(
        "/api/v1/watchdog/actions",
        json={
            "action_code": "continue_session",
            "project_id": "repo-a",
            "operator": "watchdog",
            "idempotency_key": "idem-event-only-continue-blocked",
            "arguments": {},
        },
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    data = response.json()["data"]
    assert data["action_status"] == "blocked"
    assert data["reply_code"] == "action_not_available"
    assert data["message"] == "session is awaiting human approval"
    assert [fact["fact_code"] for fact in data["facts"]] == [
        "approval_pending",
        "awaiting_human_direction",
    ]
    assert a_client.get_envelope_calls == []
    assert a_client.list_approvals_calls == []


def test_approval_alias_resolves_project_id_from_canonical_store_when_a_side_is_unavailable(
    tmp_path,
) -> None:
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=BrokenAClient(),
    )
    approval = materialize_canonical_approval(
        _decision_record(project_id="repo-a").model_copy(update={"native_thread_id": "thr_native_1"}),
        approval_store=app.state.canonical_approval_store,
        session_service=app.state.session_service,
    )
    c = TestClient(app)

    response = c.post(
        f"/api/v1/watchdog/approvals/{approval.approval_id}/reject",
        json={"operator": "watchdog", "idempotency_key": "idem-approval-alias-native-fallback"},
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["error"]["code"] == "CONTROL_LINK_ERROR"


def test_session_spine_canonical_and_alias_actions_share_the_same_result(tmp_path) -> None:
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeAClient(
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
                "operator": "watchdog",
                "idempotency_key": "idem-continue-1",
                "arguments": {},
            },
            headers={"Authorization": "Bearer wt"},
        )
        alias = c.post(
            "/api/v1/watchdog/sessions/repo-a/actions/continue",
            json={"operator": "watchdog", "idempotency_key": "idem-continue-1"},
            headers={"Authorization": "Bearer wt"},
        )

    assert canonical.status_code == 200
    assert alias.status_code == 200
    assert steer_mock.call_count == 1
    assert canonical.json()["data"] == alias.json()["data"]
    assert canonical.json()["data"]["effect"] == "steer_posted"


def test_session_spine_action_routes_reject_empty_idempotency_key(tmp_path) -> None:
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=_client(),
    )
    c = TestClient(app)

    canonical = c.post(
        "/api/v1/watchdog/actions",
        json={
            "action_code": "continue_session",
            "project_id": "repo-a",
            "operator": "watchdog",
            "idempotency_key": "",
            "arguments": {},
        },
        headers={"Authorization": "Bearer wt"},
    )
    alias = c.post(
        "/api/v1/watchdog/sessions/repo-a/actions/continue",
        json={"operator": "watchdog", "idempotency_key": ""},
        headers={"Authorization": "Bearer wt"},
    )

    assert canonical.status_code == 200
    assert canonical.json()["success"] is False
    assert canonical.json()["error"]["code"] == "INVALID_ARGUMENT"
    assert alias.status_code == 200
    assert alias.json()["success"] is False
    assert alias.json()["error"]["code"] == "INVALID_ARGUMENT"


def test_session_spine_continue_session_uses_structured_steer_arguments(tmp_path) -> None:
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
            http_timeout_s=30.0,
        ),
        runtime_client=FakeAClient(
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
        response = c.post(
            "/api/v1/watchdog/actions",
            json={
                "action_code": "continue_session",
                "project_id": "repo-a",
                "operator": "watchdog",
                "idempotency_key": "idem-continue-structured-1",
                "arguments": {
                    "message": "下一步建议：补齐飞书控制链路；回写验证结果。",
                    "reason_code": "brain_auto_continue",
                    "stuck_level": 1,
                },
            },
            headers={"Authorization": "Bearer wt"},
        )

    assert response.status_code == 200
    steer_mock.assert_called_once_with(
        "http://a.test",
        "at",
        "repo-a",
        message="下一步建议：补齐飞书控制链路；回写验证结果。",
        reason="brain_auto_continue",
        stuck_level=1,
        timeout=30.0,
    )


def test_session_spine_continue_retries_after_rejected_steer_without_caching_receipt(tmp_path) -> None:
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeAClient(
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
                "operator": "watchdog",
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
                "operator": "watchdog",
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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeAClient(
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
                "operator": "watchdog",
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
                "operator": "watchdog",
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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeAClient(
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
                "operator": "watchdog",
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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=_client(),
    )
    c = TestClient(app)

    canonical = c.post(
        "/api/v1/watchdog/actions",
        json={
            "action_code": "post_operator_guidance",
            "project_id": "repo-a",
            "operator": "watchdog",
            "idempotency_key": "idem-guidance-api-2",
            "arguments": {},
        },
        headers={"Authorization": "Bearer wt"},
    )
    alias = c.post(
        "/api/v1/watchdog/sessions/repo-a/actions/post-guidance",
        json={"operator": "watchdog", "idempotency_key": "idem-guidance-api-3"},
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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=_client(),
    )
    c = TestClient(app)

    response = c.post(
        "/api/v1/watchdog/sessions/repo-a/actions/continue",
        json={
            "operator": "watchdog",
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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeAClient(
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
                "operator": "watchdog",
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
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    first_app = create_app(settings, runtime_client=BrokenAClient())
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

    restarted = create_app(settings, runtime_client=BrokenAClient())
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


def test_watchdog_read_surfaces_suppress_stale_canonical_approval_behind_newer_progress(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings, runtime_client=BrokenAClient())
    task = {
        "project_id": "repo-a",
        "thread_id": "thr_native_1",
        "status": "running",
        "phase": "editing_source",
        "pending_approval": False,
        "last_summary": "runtime has moved past the old approval",
        "files_touched": ["src/example.py"],
        "context_pressure": "medium",
        "stuck_level": 2,
        "failure_count": 0,
        "last_progress_at": "2026-04-07T00:10:00Z",
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
        last_refreshed_at="2026-04-07T00:10:05Z",
    )
    approval = materialize_canonical_approval(
        _decision_record(project_id="repo-a", fact_snapshot_version="fact-v10"),
        approval_store=app.state.canonical_approval_store,
    )
    app.state.canonical_approval_store.update(
        approval.model_copy(
            update={
                "created_at": "2026-04-07T00:00:00Z",
            }
        )
    )

    c = TestClient(app)
    session_resp = c.get("/api/v1/watchdog/sessions/repo-a", headers={"Authorization": "Bearer wt"})
    approvals_resp = c.get(
        "/api/v1/watchdog/sessions/repo-a/pending-approvals",
        headers={"Authorization": "Bearer wt"},
    )

    assert session_resp.status_code == 200
    assert approvals_resp.status_code == 200
    session_data = session_resp.json()["data"]
    approvals_data = approvals_resp.json()["data"]
    assert session_data["session"]["session_state"] == "blocked"
    assert session_data["session"]["pending_approval_count"] == 0
    assert [fact["fact_code"] for fact in session_data["facts"]] == [
        "stuck_no_progress",
        "recovery_available",
    ]
    assert approvals_data["approvals"] == []


def test_watchdog_read_surfaces_keep_newer_persisted_progress_over_older_session_events(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings, runtime_client=BrokenAClient())
    task = {
        "project_id": "repo-a",
        "thread_id": "thr_native_1",
        "status": "running",
        "phase": "editing_source",
        "pending_approval": False,
        "last_summary": "persisted progress is newer than session events",
        "files_touched": ["src/example.py"],
        "context_pressure": "medium",
        "stuck_level": 2,
        "failure_count": 0,
        "last_progress_at": "2026-04-07T00:10:00Z",
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
        last_refreshed_at="2026-04-07T00:10:05Z",
    )
    approval = materialize_canonical_approval(
        _decision_record(project_id="repo-a", fact_snapshot_version="fact-v10"),
        approval_store=app.state.canonical_approval_store,
    )
    app.state.canonical_approval_store.update(
        approval.model_copy(
            update={
                "created_at": "2026-04-07T00:00:00Z",
            }
        )
    )
    app.state.session_service.record_event(
        event_type="notification_announced",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:notification:repo-a:stale-approval",
        related_ids={
            "native_thread_id": "thr_native_1",
            "notification_event_id": "event:notification:repo-a",
        },
        payload={
            "notification_kind": "decision_result",
            "delivery_status": "pending",
        },
        occurred_at="2026-04-07T00:05:00Z",
    )

    c = TestClient(app)
    session_resp = c.get("/api/v1/watchdog/sessions/repo-a", headers={"Authorization": "Bearer wt"})
    approvals_resp = c.get(
        "/api/v1/watchdog/sessions/repo-a/pending-approvals",
        headers={"Authorization": "Bearer wt"},
    )

    assert session_resp.status_code == 200
    assert approvals_resp.status_code == 200
    session_data = session_resp.json()["data"]
    approvals_data = approvals_resp.json()["data"]
    assert session_data["session"]["session_state"] == "blocked"
    assert session_data["session"]["pending_approval_count"] == 0
    assert session_data["progress"]["last_progress_at"] == "2026-04-07T00:10:00Z"
    assert approvals_data["approvals"] == []


def test_watchdog_read_keeps_pending_approval_after_later_notification_event(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings, runtime_client=BrokenAClient())
    approval = materialize_canonical_approval(
        _decision_record(project_id="repo-a", fact_snapshot_version="fact-v10"),
        approval_store=app.state.canonical_approval_store,
    )
    app.state.canonical_approval_store.update(
        approval.model_copy(update={"created_at": "2026-04-07T00:00:00Z"})
    )
    app.state.session_service.record_event(
        event_type="notification_delivery_succeeded",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:notification:repo-a:after-approval",
        related_ids={
            "native_thread_id": "native:repo-a",
            "notification_event_id": "event:notification:repo-a",
        },
        payload={
            "notification_kind": "decision_result",
            "delivery_status": "delivered",
        },
        occurred_at="2026-04-07T00:10:00Z",
    )

    c = TestClient(app)
    session_resp = c.get("/api/v1/watchdog/sessions/repo-a", headers={"Authorization": "Bearer wt"})
    approvals_resp = c.get(
        "/api/v1/watchdog/sessions/repo-a/pending-approvals",
        headers={"Authorization": "Bearer wt"},
    )

    assert session_resp.status_code == 200
    assert approvals_resp.status_code == 200
    session_data = session_resp.json()["data"]
    approvals_data = approvals_resp.json()["data"]
    assert session_data["session"]["session_state"] == "awaiting_approval"
    assert session_data["session"]["pending_approval_count"] == 1
    assert [item["approval_id"] for item in approvals_data["approvals"]] == [
        approval.approval_id
    ]


def test_watchdog_read_filters_approvals_against_persisted_thread_identity(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings, runtime_client=BrokenAClient())
    task = {
        "project_id": "repo-a",
        "thread_id": "thr_current",
        "status": "running",
        "phase": "editing_source",
        "pending_approval": False,
        "last_summary": "current thread is active",
        "files_touched": ["src/example.py"],
        "context_pressure": "low",
        "stuck_level": 0,
        "failure_count": 0,
        "last_progress_at": "2026-04-07T00:10:00Z",
    }
    facts = build_fact_records(project_id="repo-a", task=task, approvals=[])
    app.state.session_spine_store.put(
        project_id="repo-a",
        session=build_session_projection(
            project_id="repo-a",
            task=task,
            approvals=[],
            facts=facts,
        ),
        progress=build_task_progress_view(
            project_id="repo-a",
            task=task,
            facts=facts,
        ),
        facts=facts,
        approval_queue=[],
        last_refreshed_at="2026-04-07T00:10:05Z",
    )
    stale_approval = materialize_canonical_approval(
        _decision_record(project_id="repo-a", fact_snapshot_version="fact-v1").model_copy(
            update={"native_thread_id": "thr_stale"}
        ),
        approval_store=app.state.canonical_approval_store,
    )
    current_approval = materialize_canonical_approval(
        _decision_record(project_id="repo-a", fact_snapshot_version="fact-v2").model_copy(
            update={"native_thread_id": "thr_current"}
        ),
        approval_store=app.state.canonical_approval_store,
    )
    app.state.canonical_approval_store.update(
        stale_approval.model_copy(update={"created_at": "2026-04-07T00:00:00Z"})
    )
    app.state.canonical_approval_store.update(
        current_approval.model_copy(update={"created_at": "2026-04-07T00:11:00Z"})
    )
    app.state.session_service.record_event(
        event_type="notification_delivery_succeeded",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:notification:repo-a:mixed-approval-threads",
        related_ids={
            "notification_event_id": "event:notification:repo-a",
        },
        payload={
            "notification_kind": "decision_result",
            "delivery_status": "delivered",
        },
        occurred_at="2026-04-07T00:12:00Z",
    )

    c = TestClient(app)
    session_resp = c.get("/api/v1/watchdog/sessions/repo-a", headers={"Authorization": "Bearer wt"})
    approvals_resp = c.get(
        "/api/v1/watchdog/sessions/repo-a/pending-approvals",
        headers={"Authorization": "Bearer wt"},
    )

    assert session_resp.status_code == 200
    assert approvals_resp.status_code == 200
    session_data = session_resp.json()["data"]
    approvals_data = approvals_resp.json()["data"]
    assert session_data["session"]["native_thread_id"] == "thr_current"
    assert session_data["session"]["pending_approval_count"] == 1
    assert [item["approval_id"] for item in approvals_data["approvals"]] == [
        current_approval.approval_id
    ]


def test_watchdog_restart_preserves_action_receipt_lookup_without_reexecution(tmp_path: Path) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    first_app = create_app(
        settings,
        runtime_client=FakeAClient(
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
                "operator": "watchdog",
                "idempotency_key": "idem-restart-receipt-1",
                "arguments": {},
            },
            headers={"Authorization": "Bearer wt"},
        )

    assert create_receipt.status_code == 200
    assert create_receipt.json()["success"] is True

    restarted = create_app(settings, runtime_client=BrokenAClient())
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
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    first_app = create_app(settings, runtime_client=BrokenAClient())
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

    restarted = create_app(settings, runtime_client=BrokenAClient())
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
        "stuck_no_progress",
        "context_critical",
        "recovery_available",
        "human_override_recorded",
        "notification_receipt_recorded",
    ]


def test_session_spine_receipt_query_route_returns_stable_not_found_reply(tmp_path) -> None:
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=_client(),
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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=client,
    )
    c = TestClient(app)

    canonical = c.post(
        "/api/v1/watchdog/actions",
        json={
            "action_code": "execute_recovery",
            "project_id": "repo-a",
            "operator": "watchdog",
            "idempotency_key": "idem-execute-recovery-1",
            "arguments": {},
        },
        headers={"Authorization": "Bearer wt"},
    )
    alias = c.post(
        "/api/v1/watchdog/sessions/repo-a/actions/execute-recovery",
        json={"operator": "watchdog", "idempotency_key": "idem-execute-recovery-1"},
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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=client,
    )
    c = TestClient(app)

    canonical = c.post(
        "/api/v1/watchdog/actions",
        json={
            "action_code": "pause_session",
            "project_id": "repo-a",
            "operator": "watchdog",
            "idempotency_key": "idem-pause-1",
            "arguments": {},
        },
        headers={"Authorization": "Bearer wt"},
    )
    alias = c.post(
        "/api/v1/watchdog/sessions/repo-a/actions/pause",
        json={"operator": "watchdog", "idempotency_key": "idem-pause-1"},
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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=client,
    )
    c = TestClient(app)

    canonical = c.post(
        "/api/v1/watchdog/actions",
        json={
            "action_code": "resume_session",
            "project_id": "repo-a",
            "operator": "watchdog",
            "idempotency_key": "idem-resume-1",
            "arguments": {"handoff_summary": "resume from saved handoff"},
        },
        headers={"Authorization": "Bearer wt"},
    )
    alias = c.post(
        "/api/v1/watchdog/sessions/repo-a/actions/resume",
        json={
            "operator": "watchdog",
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


@pytest.mark.parametrize("raw_packet", ["broken-packet", ["broken-packet"]])
def test_session_spine_resume_rejects_non_object_continuation_packet_for_canonical_and_alias(
    tmp_path,
    raw_packet,
) -> None:
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "handoff_in_progress",
            "phase": "handoff",
            "pending_approval": False,
            "last_summary": "handoff drafted",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=client,
    )
    c = TestClient(app)

    canonical = c.post(
        "/api/v1/watchdog/actions",
        json={
            "action_code": "resume_session",
            "project_id": "repo-a",
            "operator": "watchdog",
            "idempotency_key": f"idem-resume-invalid-{type(raw_packet).__name__}",
            "arguments": {"continuation_packet": raw_packet},
        },
        headers={"Authorization": "Bearer wt"},
    )
    alias = c.post(
        "/api/v1/watchdog/sessions/repo-a/actions/resume",
        json={
            "operator": "watchdog",
            "idempotency_key": f"idem-resume-invalid-alias-{type(raw_packet).__name__}",
            "continuation_packet": raw_packet,
        },
        headers={"Authorization": "Bearer wt"},
    )

    assert canonical.status_code == 200
    assert canonical.json()["success"] is False
    assert canonical.json()["error"]["code"] == "INVALID_ARGUMENT"
    assert canonical.json()["error"]["message"] == "continuation_packet must be an object"
    assert alias.status_code == 200
    assert alias.json()["success"] is False
    assert alias.json()["error"]["code"] == "INVALID_ARGUMENT"
    assert alias.json()["error"]["message"] == "continuation_packet must be an object"
    assert client.resume_calls == []


def test_session_spine_summarize_canonical_and_alias_share_the_same_result(tmp_path) -> None:
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeAClient(
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
            "operator": "watchdog",
            "idempotency_key": "idem-summarize-1",
            "arguments": {},
        },
        headers={"Authorization": "Bearer wt"},
    )
    alias = c.post(
        "/api/v1/watchdog/sessions/repo-a/actions/summarize",
        json={"operator": "watchdog", "idempotency_key": "idem-summarize-1"},
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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=client,
    )
    c = TestClient(app)

    canonical = c.post(
        "/api/v1/watchdog/actions",
        json={
            "action_code": "force_handoff",
            "project_id": "repo-a",
            "operator": "watchdog",
            "idempotency_key": "idem-force-handoff-1",
            "arguments": {},
        },
        headers={"Authorization": "Bearer wt"},
    )
    alias = c.post(
        "/api/v1/watchdog/sessions/repo-a/actions/force-handoff",
        json={"operator": "watchdog", "idempotency_key": "idem-force-handoff-1"},
        headers={"Authorization": "Bearer wt"},
    )

    assert canonical.status_code == 200
    assert alias.status_code == 200
    assert client.handoff_calls == [("repo-a", "force_handoff")]
    assert canonical.json()["data"] == alias.json()["data"]
    assert canonical.json()["data"]["effect"] == "handoff_triggered"


def test_session_spine_retry_conservative_canonical_and_alias_share_the_same_result(tmp_path) -> None:
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeAClient(
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
                "operator": "watchdog",
                "idempotency_key": "idem-retry-conservative-1",
                "arguments": {},
            },
            headers={"Authorization": "Bearer wt"},
        )
        alias = c.post(
            "/api/v1/watchdog/sessions/repo-a/actions/retry-with-conservative-path",
            json={"operator": "watchdog", "idempotency_key": "idem-retry-conservative-1"},
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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeAClient(
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
                "operator": "watchdog",
                "idempotency_key": "idem-supervision-1",
                "arguments": {},
            },
            headers={"Authorization": "Bearer wt"},
        )
        alias = c.post(
            "/api/v1/watchdog/sessions/repo-a/actions/evaluate-supervision",
            json={"operator": "watchdog", "idempotency_key": "idem-supervision-1"},
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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeAClient(
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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=_client(),
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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=_client(),
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
