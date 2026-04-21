from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from watchdog.main import create_app
from watchdog.services.approvals.service import materialize_canonical_approval
from watchdog.services.goal_contract.service import GoalContractService
from watchdog.services.policy.decisions import CanonicalDecisionRecord
from watchdog.services.session_service import SessionService
from watchdog.services.session_spine.facts import build_fact_records
from watchdog.services.session_spine.projection import (
    build_session_projection,
    build_task_progress_view,
)
from watchdog.settings import Settings


class _IngressAClient:
    def __init__(
        self,
        *,
        tasks: list[dict[str, object]],
        approvals: list[dict[str, object]] | None = None,
    ) -> None:
        self._tasks = tasks
        self._approvals = [dict(approval) for approval in approvals or []]
        self.pause_calls: list[str] = []

    def list_tasks(self) -> list[dict[str, object]]:
        return [dict(task) for task in self._tasks]

    def trigger_pause(self, project_id: str) -> dict[str, object]:
        self.pause_calls.append(project_id)
        return {
            "success": True,
            "data": {"project_id": project_id, "status": "paused"},
        }

    def get_envelope(self, project_id: str) -> dict[str, object]:
        task = next(task for task in self._tasks if task["project_id"] == project_id)
        return {"success": True, "data": dict(task)}

    def get_envelope_by_thread(self, thread_id: str) -> dict[str, object]:
        task = next(
            task
            for task in self._tasks
            if task["thread_id"] == thread_id or task.get("native_thread_id") == thread_id
        )
        return {"success": True, "data": dict(task)}

    def list_approvals(
        self,
        *,
        status: str | None = None,
        project_id: str | None = None,
        decided_by: str | None = None,
        callback_status: str | None = None,
    ) -> list[dict[str, object]]:
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


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        api_token="watchdog-token",
        a_agent_token="a-agent-token",
        a_agent_base_url="http://a-control.test",
        data_dir=str(tmp_path),
        feishu_verification_token="verify-token",
    )


def _task(
    project_id: str,
    *,
    thread_id: str | None = None,
    native_thread_id: str | None = None,
    status: str = "running",
) -> dict[str, object]:
    return {
        "project_id": project_id,
        "thread_id": thread_id or f"session:{project_id}",
        "native_thread_id": native_thread_id or f"thr:{project_id}",
        "status": status,
        "phase": "planning",
        "pending_approval": False,
        "last_summary": "waiting",
        "files_touched": [],
        "context_pressure": "low",
        "stuck_level": 0,
        "failure_count": 0,
        "last_progress_at": "2026-04-16T13:00:00Z",
    }


def _message_event(
    text: str,
    *,
    token: str = "verify-token",
    event_id: str = "evt-feishu-1",
    message_id: str = "om_message_1",
    chat_id: str = "oc_dm_chat_1",
) -> dict[str, object]:
    return {
        "schema": "2.0",
        "header": {
            "event_id": event_id,
            "event_type": "im.message.receive_v1",
            "create_time": "1713274200000",
            "token": token,
            "app_id": "cli_app",
            "tenant_key": "tenant-1",
        },
        "event": {
            "message": {
                "message_id": message_id,
                "chat_id": chat_id,
                "chat_type": "p2p",
                "message_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
            "sender": {"sender_id": {"open_id": "ou_actor_1"}},
        },
    }


def _approval_decision(
    *,
    approval_id: str = "appr_bootstrap",
    goal_contract_version: str | None = None,
) -> CanonicalDecisionRecord:
    evidence = {
        "facts": [],
        "matched_policy_rules": ["human_gate"],
        "decision": {
            "decision_result": "require_user_decision",
            "action_ref": "continue_session",
            "approval_id": approval_id,
        },
    }
    if goal_contract_version is not None:
        evidence["goal_contract_version"] = goal_contract_version
    return CanonicalDecisionRecord(
        decision_id=f"decision:repo-a:fact-v7:require_user_decision:{approval_id}",
        decision_key=(
            "session:repo-a|fact-v7|policy-v1|require_user_decision|continue_session|"
            f"{approval_id}"
        ),
        session_id="session:repo-a",
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="thr:repo-a",
        approval_id=approval_id,
        action_ref="continue_session",
        trigger="resident_supervision",
        decision_result="require_user_decision",
        risk_class="human_gate",
        decision_reason="explicit human confirmation required before continuing",
        matched_policy_rules=["human_gate"],
        why_not_escalated=None,
        why_escalated="manual decision required",
        uncertainty_reasons=[],
        policy_version="policy-v1",
        fact_snapshot_version="fact-v7",
        idempotency_key=(
            "session:repo-a|fact-v7|policy-v1|require_user_decision|continue_session|"
            f"{approval_id}"
        ),
        created_at="2026-04-15T04:45:04Z",
        operator_notes=[],
        evidence=evidence,
    )


def _provider_invalid_decision(
    *,
    project_id: str = "repo-a",
    session_id: str = "session:repo-a",
    native_thread_id: str = "thr:repo-a",
) -> CanonicalDecisionRecord:
    return CanonicalDecisionRecord(
        decision_id=f"decision:{project_id}:provider-invalid",
        decision_key=f"{session_id}|fact-v7|policy-v1|require_user_decision|execute_recovery|",
        session_id=session_id,
        project_id=project_id,
        thread_id=session_id,
        native_thread_id=native_thread_id,
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
        fact_snapshot_version="fact-v7",
        idempotency_key=f"{session_id}|fact-v7|policy-v1|require_user_decision|execute_recovery|",
        created_at="2026-04-15T04:45:05Z",
        operator_notes=[],
        evidence={
            "facts": [
                {
                    "fact_id": "fact-1",
                    "fact_code": "approval_pending",
                    "fact_kind": "blocker",
                    "severity": "warning",
                    "summary": "approval pending",
                    "detail": "approval pending",
                    "source": "watchdog",
                    "observed_at": "2026-04-15T04:45:05Z",
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
                "trace_id": f"trace:{project_id}-provider-invalid",
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
    )


def test_feishu_ingress_answers_url_verification_challenge(tmp_path: Path) -> None:
    app = create_app(settings=_settings(tmp_path), a_client=_IngressAClient(tasks=[]))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json={
                "type": "url_verification",
                "token": "verify-token",
                "challenge": "challenge-123",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"challenge": "challenge-123"}


def test_feishu_ingress_routes_text_message_with_explicit_repo_prefix(tmp_path: Path) -> None:
    a_client = _IngressAClient(tasks=[_task("repo-a")])
    app = create_app(settings=_settings(tmp_path), a_client=a_client)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("repo:repo-a pause"),
        )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert a_client.pause_calls == ["repo-a"]


def test_feishu_ingress_explicit_repo_goal_uses_local_session_spine_without_upstream_lookup(
    tmp_path: Path,
) -> None:
    a_client = _IngressAClient(tasks=[_task("repo-a", thread_id="session:repo-a")])
    app = create_app(settings=_settings(tmp_path), a_client=a_client)
    app.state.session_spine_runtime.refresh_all()

    def _unexpected_call(*_: object, **__: object) -> object:
        raise AssertionError("unexpected upstream lookup")

    a_client.list_tasks = _unexpected_call  # type: ignore[method-assign]
    a_client.get_envelope = _unexpected_call  # type: ignore[method-assign]

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("repo:repo-a /goal 继续把本地 Feishu 链路打通"),
        )

    assert response.status_code == 200
    contracts = GoalContractService(app.state.session_service)
    assert contracts.get_current_contract(
        project_id="repo-a",
        session_id="session:repo-a",
    ) is not None


def test_feishu_ingress_can_auto_bind_single_active_task_for_goal_bootstrap(
    tmp_path: Path,
) -> None:
    a_client = _IngressAClient(tasks=[_task("repo-a", thread_id="session:repo-a")])
    app = create_app(settings=_settings(tmp_path), a_client=a_client)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("/goal 继续把主链路打通到 release gate"),
        )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    events = app.state.session_service.list_events(session_id="session:repo-a")
    assert events[0].event_type == "goal_contract_created"
    assert events[0].related_ids["native_thread_id"] == "thr:repo-a"
    assert events[0].related_ids["interaction_family_id"] == "om_message_1"
    assert events[0].related_ids["feishu_chat_id"] == "oc_dm_chat_1"
    assert events[0].related_ids["feishu_receive_id_type"] == "chat_id"


def test_feishu_ingress_auto_bind_prefers_native_thread_lookup_for_single_active_task(
    tmp_path: Path,
) -> None:
    class NativeLookupClient(_IngressAClient):
        def get_envelope_by_thread(self, thread_id: str) -> dict[str, object]:
            assert thread_id == "thr:repo-a"
            return {
                "success": True,
                "data": dict(
                    _task(
                        "repo-a",
                        thread_id="session:repo-a",
                        native_thread_id="thr:repo-a",
                    )
                ),
            }

    app = create_app(
        settings=_settings(tmp_path),
        a_client=NativeLookupClient(
            tasks=[_task("repo-a", thread_id="session:repo-a", native_thread_id="thr:repo-a")]
        ),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("/goal 继续把主链路打通到 release gate"),
        )

    assert response.status_code == 200
    assert response.json()["accepted"] is True


def test_feishu_ingress_goal_bootstrap_falls_back_to_stable_session_id_when_envelope_omits_thread_id(
    tmp_path: Path,
) -> None:
    class MissingSessionThreadClient(_IngressAClient):
        def get_envelope_by_thread(self, thread_id: str) -> dict[str, object]:
            assert thread_id == "thr:repo-a"
            return {
                "success": True,
                "data": {
                    "project_id": "repo-a",
                    "native_thread_id": "thr:repo-a",
                    "status": "running",
                    "phase": "planning",
                    "pending_approval": False,
                    "last_summary": "waiting",
                    "files_touched": [],
                    "context_pressure": "low",
                    "stuck_level": 0,
                    "failure_count": 0,
                    "last_progress_at": "2026-04-16T13:00:00Z",
                },
            }

    app = create_app(
        settings=_settings(tmp_path),
        a_client=MissingSessionThreadClient(
            tasks=[_task("repo-a", thread_id="session:repo-a", native_thread_id="thr:repo-a")]
        ),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("/goal 继续把主链路打通到 release gate"),
        )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    contracts = GoalContractService(app.state.session_service)
    assert contracts.get_current_contract(
        project_id="repo-a",
        session_id="session:repo-a",
    ) is not None
    assert contracts.get_current_contract(
        project_id="repo-a",
        session_id="thr:repo-a",
    ) is None


def test_feishu_ingress_default_bound_plain_text_bootstraps_goal_without_command_syntax(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path).model_copy(update={"default_project_id": "repo-a"})
    a_client = _IngressAClient(tasks=[_task("repo-a"), _task("repo-b")])
    app = create_app(settings=settings, a_client=a_client)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("飞书联调"),
        )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["event_type"] == "goal_contract_bootstrap"
    contract = GoalContractService(app.state.session_service).get_current_contract(
        project_id="repo-a",
        session_id="session:repo-a",
    )
    assert contract is not None
    assert contract.current_phase_goal == "飞书联调"


def test_feishu_ingress_default_bound_goal_bootstrap_uses_effective_native_thread_from_legacy_persisted_store(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path).model_copy(update={"default_project_id": "repo-a"})
    a_client = _IngressAClient(tasks=[])
    app = create_app(settings=settings, a_client=a_client)
    task = _task("repo-a", thread_id="session:repo-a", native_thread_id="thr:repo-a")
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
        last_refreshed_at="2026-04-16T13:01:00Z",
    )
    path = tmp_path / "session_spine.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["sessions"]["repo-a"]["native_thread_id"] = None
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("飞书联调"),
        )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["event_type"] == "goal_contract_bootstrap"
    events = app.state.session_service.list_events(session_id="session:repo-a")
    assert events[0].event_type == "goal_contract_created"
    assert events[0].related_ids["native_thread_id"] == "thr:repo-a"


def test_feishu_ingress_default_bound_status_stays_command_request(tmp_path: Path) -> None:
    settings = _settings(tmp_path).model_copy(update={"default_project_id": "repo-a"})
    a_client = _IngressAClient(tasks=[_task("repo-a"), _task("repo-b")])
    app = create_app(settings=settings, a_client=a_client)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("状态"),
        )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["event_type"] == "command_request"
    assert response.json()["data"]["intent_code"] == "get_session"


def test_feishu_ingress_default_bound_project_directory_stays_command_request(tmp_path: Path) -> None:
    settings = _settings(tmp_path).model_copy(update={"default_project_id": "repo-a"})
    a_client = _IngressAClient(tasks=[_task("repo-a"), _task("repo-b")])
    app = create_app(settings=settings, a_client=a_client)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("项目列表"),
        )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["event_type"] == "command_request"
    assert response.json()["data"]["intent_code"] == "list_sessions"
    assert response.json()["data"]["reply_code"] == "session_directory"
    assert {session["project_id"] for session in response.json()["data"]["sessions"]} == {
        "repo-a",
        "repo-b",
    }


def test_feishu_ingress_default_bound_discovery_alias_stays_command_request(tmp_path: Path) -> None:
    settings = _settings(tmp_path).model_copy(update={"default_project_id": "repo-a"})
    a_client = _IngressAClient(tasks=[_task("repo-a"), _task("repo-b")])
    app = create_app(settings=settings, a_client=a_client)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("所有项目进展"),
        )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["event_type"] == "command_request"
    assert response.json()["data"]["intent_code"] == "list_sessions"
    assert response.json()["data"]["reply_code"] == "session_directory"
    assert {session["project_id"] for session in response.json()["data"]["sessions"]} == {
        "repo-a",
        "repo-b",
    }


def test_feishu_ingress_progress_surfaces_decision_degradation_annotations(tmp_path: Path) -> None:
    settings = _settings(tmp_path).model_copy(update={"default_project_id": "repo-a"})
    a_client = _IngressAClient(tasks=[_task("repo-a"), _task("repo-b")])
    app = create_app(settings=settings, a_client=a_client)
    app.state.policy_decision_store.put(_provider_invalid_decision())

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("进展"),
        )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["event_type"] == "command_request"
    assert response.json()["data"]["intent_code"] == "get_progress"
    assert response.json()["data"]["message"] == (
        "waiting | 决策=provider降级(schema:provider-decision-v2)"
    )
    assert response.json()["data"]["progress"]["decision_trace_ref"] == (
        "trace:repo-a-provider-invalid"
    )


def test_feishu_ingress_progress_surfaces_goal_contract_context(tmp_path: Path) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    settings = _settings(tmp_path).model_copy(update={"default_project_id": "repo-a"})
    a_client = _IngressAClient(tasks=[_task("repo-a"), _task("repo-b")])
    app = create_app(settings=settings, a_client=a_client)
    GoalContractService(app.state.session_service).bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="收口 recovery 自动重入",
        task_prompt="收口 recovery 自动重入",
        last_user_instruction="继续把 recovery 自动重入收口到 child continuation",
        phase="planning",
        last_summary="waiting",
        current_phase_goal="继续把 recovery 自动重入收口到 child continuation",
        explicit_deliverables=["避免重复 handoff"],
        completion_signals=["child continuation 稳定"],
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("进展"),
        )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["event_type"] == "command_request"
    assert response.json()["data"]["intent_code"] == "get_progress"
    assert response.json()["data"]["message"] == (
        "waiting | 当前目标=继续把 recovery 自动重入收口到 child continuation"
    )
    assert response.json()["data"]["progress"]["goal_contract_version"] == "goal-v1"
    assert response.json()["data"]["progress"]["current_phase_goal"] == (
        "继续把 recovery 自动重入收口到 child continuation"
    )


def test_feishu_ingress_session_directory_surfaces_goal_contract_context(tmp_path: Path) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    settings = _settings(tmp_path)
    a_client = _IngressAClient(
        tasks=[
            {
                **_task("repo-a"),
                "phase": "editing_source",
                "last_summary": "editing files",
                "last_progress_at": "2026-04-16T13:00:00Z",
            }
        ]
    )
    app = create_app(settings=settings, a_client=a_client)
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

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("项目列表"),
        )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["data"]["intent_code"] == "list_sessions"
    assert response.json()["data"]["reply_code"] == "session_directory"
    assert response.json()["data"]["message"] == (
        "多项目进展（1） | 状态=进行中1\n"
        "- repo-a | editing_source | editing files | 上下文=low"
        " | 当前目标=继续把 recovery 自动重入收口到 child continuation"
    )


def test_feishu_ingress_session_directory_surfaces_current_child_session_id_resume_shape(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    a_client = _IngressAClient(
        tasks=[
            {
                **_task("repo-a"),
                "phase": "editing_source",
                "last_summary": "editing files",
                "last_progress_at": "2026-04-16T13:00:00Z",
            }
        ]
    )
    app = create_app(settings=settings, a_client=a_client)
    app.state.session_service.record_recovery_execution(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        parent_native_thread_id="thr:repo-a",
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
            "resume_outcome": "new_child_session",
            "child_session_id": "session:repo-a:thr_child_v1",
            "thread_id": "thr_child_v1",
            "native_thread_id": "thr_child_v1",
        },
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("项目列表"),
        )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["data"]["intent_code"] == "list_sessions"
    assert response.json()["data"]["reply_code"] == "session_directory"
    assert response.json()["data"]["progresses"][0]["recovery_outcome"] == "new_child_session"
    assert response.json()["data"]["progresses"][0]["recovery_child_session_id"] == (
        "session:repo-a:thr_child_v1"
    )
    assert response.json()["data"]["message"] == (
        "多项目进展（1） | 状态=进行中1\n"
        "- repo-a | editing_source | editing files | 上下文=low | 恢复=新子会话 repo-a:thr_child_v1"
    )


def test_feishu_ingress_blocker_explanation_surfaces_goal_contract_context(tmp_path: Path) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    settings = _settings(tmp_path).model_copy(update={"default_project_id": "repo-a"})
    a_client = _IngressAClient(
        tasks=[
            {
                **_task("repo-a"),
                "status": "waiting_human",
                "phase": "approval",
                "pending_approval": True,
                "last_summary": "waiting for approval",
            }
        ],
        approvals=[
            {
                "approval_id": "appr_001",
                "project_id": "repo-a",
                "thread_id": "thr:repo-a",
                "risk_level": "L2",
                "command": "uv run pytest",
                "reason": "verify tests",
                "alternative": "",
                "status": "pending",
                "requested_at": "2026-04-16T13:00:00Z",
            }
        ],
    )
    app = create_app(settings=settings, a_client=a_client)
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

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("卡在哪里"),
        )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["event_type"] == "command_request"
    assert response.json()["data"]["intent_code"] == "explain_blocker"
    assert response.json()["data"]["message"] == (
        "approval required; awaiting operator direction"
        " | 当前目标=继续把 recovery 自动重入收口到 child continuation"
        " | 下一步=审批列表、回复同意/拒绝、为什么卡住"
    )


def test_feishu_ingress_session_surfaces_operator_next_steps_for_pending_approval(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path).model_copy(update={"default_project_id": "repo-a"})
    a_client = _IngressAClient(
        tasks=[
            {
                **_task("repo-a"),
                "status": "waiting_human",
                "phase": "approval",
                "pending_approval": True,
                "last_summary": "waiting for approval",
            }
        ],
        approvals=[
            {
                "approval_id": "appr_001",
                "project_id": "repo-a",
                "thread_id": "thr:repo-a",
                "risk_level": "L2",
                "command": "uv run pytest",
                "reason": "verify tests",
                "alternative": "",
                "status": "pending",
                "requested_at": "2026-04-16T13:01:00Z",
            }
        ],
    )
    app = create_app(settings=settings, a_client=a_client)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("状态"),
        )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["event_type"] == "command_request"
    assert response.json()["data"]["intent_code"] == "get_session"
    assert response.json()["data"]["message"] == (
        "waiting for approval | 下一步=审批列表、回复同意/拒绝、卡在哪里"
    )
    assert response.json()["data"]["session"]["native_thread_id"] == "thr:repo-a"
    assert response.json()["data"]["progress"]["project_id"] == "repo-a"
    assert response.json()["data"]["progress"]["native_thread_id"] == "thr:repo-a"
    assert response.json()["data"]["progress"]["summary"] == "waiting for approval"


def test_feishu_ingress_session_surfaces_active_recovery_suppression(tmp_path: Path) -> None:
    settings = _settings(tmp_path).model_copy(update={"default_project_id": "repo-a"})
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="recovery_execution_suppressed",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:recovery-suppressed:repo-a:feishu-ingress",
        related_ids={"recovery_transaction_id": "recovery-tx:repo-a"},
        payload={
            "suppression_reason": "reentry_without_newer_progress",
            "suppression_source": "resident_orchestrator",
            "context_pressure": "critical",
            "last_progress_at": "2026-04-16T13:00:00Z",
        },
        occurred_at="2026-04-16T13:01:00Z",
    )
    a_client = _IngressAClient(
        tasks=[
            {
                **_task("repo-a"),
                "phase": "editing_source",
                "last_summary": "editing recovery path",
                "files_touched": ["src/recovery.py"],
                "context_pressure": "critical",
                "stuck_level": 2,
                "failure_count": 3,
            }
        ]
    )
    app = create_app(settings=settings, a_client=a_client)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("状态"),
        )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["event_type"] == "command_request"
    assert response.json()["data"]["intent_code"] == "get_session"
    assert response.json()["data"]["message"] == (
        "editing recovery path | 恢复抑制=等待新进展 | 下一步=卡在哪里"
    )
    assert response.json()["data"]["session"]["native_thread_id"] == "thr:repo-a"
    assert (
        response.json()["data"]["progress"]["recovery_suppression_reason"]
        == "reentry_without_newer_progress"
    )
    assert response.json()["data"]["progress"]["recovery_suppression_source"] == (
        "resident_orchestrator"
    )
    assert response.json()["data"]["progress"]["recovery_suppression_observed_at"] == (
        "2026-04-16T13:01:00Z"
    )


def test_feishu_ingress_session_surfaces_recovery_cooldown_suppression(tmp_path: Path) -> None:
    settings = _settings(tmp_path).model_copy(update={"default_project_id": "repo-a"})
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="recovery_execution_suppressed",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:recovery-suppressed:repo-a:feishu-ingress:cooldown",
        related_ids={"recovery_transaction_id": "recovery-tx:repo-a"},
        payload={
            "suppression_reason": "cooldown_window_active",
            "suppression_source": "resident_orchestrator",
            "context_pressure": "critical",
            "last_progress_at": "2026-04-16T13:00:00Z",
            "cooldown_seconds": "300",
        },
        occurred_at="2026-04-16T13:01:00Z",
    )
    a_client = _IngressAClient(
        tasks=[
            {
                **_task("repo-a"),
                "phase": "editing_source",
                "last_summary": "editing recovery path",
                "files_touched": ["src/recovery.py"],
                "context_pressure": "critical",
                "stuck_level": 2,
                "failure_count": 3,
            }
        ]
    )
    app = create_app(settings=settings, a_client=a_client)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("状态"),
        )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["event_type"] == "command_request"
    assert response.json()["data"]["intent_code"] == "get_session"
    assert response.json()["data"]["message"] == (
        "editing recovery path | 恢复抑制=恢复冷却中 | 下一步=卡在哪里"
    )
    assert response.json()["data"]["session"]["native_thread_id"] == "thr:repo-a"
    assert (
        response.json()["data"]["progress"]["recovery_suppression_reason"]
        == "cooldown_window_active"
    )
    assert response.json()["data"]["progress"]["recovery_suppression_source"] == (
        "resident_orchestrator"
    )
    assert response.json()["data"]["progress"]["recovery_suppression_observed_at"] == (
        "2026-04-16T13:01:00Z"
    )


def test_feishu_ingress_session_surfaces_recovery_in_flight_suppression(tmp_path: Path) -> None:
    settings = _settings(tmp_path).model_copy(update={"default_project_id": "repo-a"})
    SessionService.from_data_dir(tmp_path).record_event(
        event_type="recovery_execution_suppressed",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:recovery-suppressed:repo-a:feishu-ingress:in-flight",
        related_ids={"recovery_transaction_id": "recovery-tx:repo-a"},
        payload={
            "suppression_reason": "recovery_in_flight",
            "suppression_source": "resident_orchestrator",
            "task_status": "handoff_in_progress",
            "context_pressure": "critical",
            "last_progress_at": "2026-04-16T13:00:00Z",
        },
        occurred_at="2026-04-16T13:01:00Z",
    )
    a_client = _IngressAClient(
        tasks=[
            {
                **_task("repo-a"),
                "status": "handoff_in_progress",
                "phase": "handoff",
                "last_summary": "handoff drafted",
                "files_touched": ["src/recovery.py"],
                "context_pressure": "critical",
                "stuck_level": 2,
                "failure_count": 3,
            }
        ]
    )
    app = create_app(settings=settings, a_client=a_client)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("状态"),
        )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["event_type"] == "command_request"
    assert response.json()["data"]["intent_code"] == "get_session"
    assert response.json()["data"]["message"] == (
        "handoff drafted | 恢复抑制=恢复进行中"
    )
    assert response.json()["data"]["session"]["native_thread_id"] == "thr:repo-a"
    assert (
        response.json()["data"]["progress"]["recovery_suppression_reason"]
        == "recovery_in_flight"
    )
    assert response.json()["data"]["progress"]["recovery_suppression_source"] == (
        "resident_orchestrator"
    )
    assert response.json()["data"]["progress"]["recovery_suppression_observed_at"] == (
        "2026-04-16T13:01:00Z"
    )


def test_feishu_ingress_global_project_directory_command_skips_project_binding(tmp_path: Path) -> None:
    a_client = _IngressAClient(tasks=[_task("repo-a"), _task("repo-b")])
    app = create_app(settings=_settings(tmp_path), a_client=a_client)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("项目列表"),
        )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["event_type"] == "command_request"
    assert response.json()["data"]["intent_code"] == "list_sessions"
    assert response.json()["data"]["reply_code"] == "session_directory"
    assert {session["project_id"] for session in response.json()["data"]["sessions"]} == {
        "repo-a",
        "repo-b",
    }
    assert response.json()["data"]["message"] == (
        "多项目进展（2） | 状态=进行中2\n"
        "- repo-a | planning | waiting | 上下文=low\n"
        "- repo-b | planning | waiting | 上下文=low"
    )


def test_feishu_ingress_discovery_alias_routes_to_session_directory(tmp_path: Path) -> None:
    a_client = _IngressAClient(tasks=[_task("repo-a"), _task("repo-b")])
    app = create_app(settings=_settings(tmp_path), a_client=a_client)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("所有项目进展"),
        )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["event_type"] == "command_request"
    assert response.json()["data"]["intent_code"] == "list_sessions"
    assert response.json()["data"]["reply_code"] == "session_directory"
    assert {session["project_id"] for session in response.json()["data"]["sessions"]} == {
        "repo-a",
        "repo-b",
    }


def test_feishu_ingress_project_directory_surfaces_next_steps_for_pending_approval(
    tmp_path: Path,
) -> None:
    a_client = _IngressAClient(
        tasks=[
            _task("repo-a", status="running"),
            {
                **_task("repo-b", status="waiting_human"),
                "phase": "approval",
                "pending_approval": True,
                "last_summary": "waiting for approval",
            },
        ],
        approvals=[
            {
                "approval_id": "appr_001",
                "project_id": "repo-b",
                "thread_id": "thr:repo-b",
                "risk_level": "L2",
                "command": "uv run pytest",
                "reason": "verify tests",
                "alternative": "",
                "status": "pending",
                "requested_at": "2026-04-16T13:01:00Z",
            }
        ],
    )
    app = create_app(settings=_settings(tmp_path), a_client=a_client)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("项目列表"),
        )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["data"]["message"] == (
        "多项目进展（2） | 状态=进行中1、待审批1 | 先处理=repo-b:待审批\n"
        "- repo-b | approval | waiting for approval | 上下文=low"
        " | 关注=待审批 | 下一步=审批列表、回复同意/拒绝、卡在哪里\n"
        "- repo-a | planning | waiting | 上下文=low"
    )


def test_feishu_ingress_lists_projects_with_relative_freshness(tmp_path: Path) -> None:
    tasks = [
        {
            **_task("repo-a"),
            "phase": "editing_source",
            "last_summary": "editing files",
            "last_progress_at": "2026-04-16T13:00:00Z",
        },
        {
            **_task("repo-b"),
            "last_progress_at": "2026-04-16T12:20:00Z",
        },
        {
            **_task("repo-c"),
            "last_progress_at": "",
        },
    ]
    app = create_app(settings=_settings(tmp_path), a_client=_IngressAClient(tasks=tasks))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("项目列表"),
        )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["data"]["message"] == (
        "多项目进展（3） | 状态=进行中3\n"
        "- repo-a | editing_source | editing files | 上下文=low\n"
        "- repo-b | planning | waiting | 上下文=low | 更新=较早\n"
        "- repo-c | planning | waiting | 上下文=low | 更新=未知"
    )


def test_feishu_ingress_rejects_ambiguous_project_binding(tmp_path: Path) -> None:
    a_client = _IngressAClient(tasks=[_task("repo-a"), _task("repo-b")])
    app = create_app(settings=_settings(tmp_path), a_client=a_client)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("/goal 继续推进"),
        )

    assert response.status_code == 400
    assert "project" in response.json()["detail"].lower()


def test_feishu_ingress_does_not_auto_bind_only_completed_task(tmp_path: Path) -> None:
    a_client = _IngressAClient(tasks=[_task("repo-a", status="completed")])
    app = create_app(settings=_settings(tmp_path), a_client=a_client)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("/goal 继续推进"),
        )

    assert response.status_code == 400
    assert "project" in response.json()["detail"].lower()


def test_feishu_ingress_rejects_malformed_create_time(tmp_path: Path) -> None:
    a_client = _IngressAClient(tasks=[_task("repo-a")])
    app = create_app(settings=_settings(tmp_path), a_client=a_client)
    body = _message_event("repo:repo-a pause")
    body["header"]["create_time"] = "not-a-timestamp"

    with TestClient(app) as client:
        response = client.post("/api/v1/watchdog/feishu/events", json=body)

    assert response.status_code == 400
    assert "timestamp" in response.json()["detail"].lower()


def test_feishu_ingress_auto_bind_uses_active_thread_envelope(tmp_path: Path) -> None:
    a_client = _IngressAClient(
        tasks=[
            _task(
                "repo-a",
                thread_id="session:completed",
                native_thread_id="thr:completed",
                status="completed",
            ),
            _task(
                "repo-a",
                thread_id="session:active",
                native_thread_id="thr:active",
                status="running",
            ),
        ]
    )
    app = create_app(settings=_settings(tmp_path), a_client=a_client)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("/goal 只绑定活跃 session"),
        )

    assert response.status_code == 200
    contracts = GoalContractService(app.state.session_service)
    assert contracts.get_current_contract(
        project_id="repo-a",
        session_id="session:active",
    ) is not None
    assert contracts.get_current_contract(
        project_id="repo-a",
        session_id="session:completed",
    ) is None


def test_feishu_ingress_replay_does_not_overwrite_newer_goal_contract(tmp_path: Path) -> None:
    a_client = _IngressAClient(tasks=[_task("repo-a", thread_id="session:repo-a")])
    app = create_app(settings=_settings(tmp_path), a_client=a_client)

    with TestClient(app) as client:
        first = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event(
                "/goal 先把 Feishu 主链路打通",
                event_id="evt-feishu-1",
                message_id="om_message_1",
            ),
        )
        second = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event(
                "/goal 再把 release gate 收口",
                event_id="evt-feishu-2",
                message_id="om_message_2",
            ),
        )
        replay = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event(
                "/goal 先把 Feishu 主链路打通",
                event_id="evt-feishu-1",
                message_id="om_message_1",
            ),
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert replay.status_code == 200
    assert replay.json()["data"]["replayed"] is True

    contract = GoalContractService(app.state.session_service).get_current_contract(
        project_id="repo-a",
        session_id="session:repo-a",
    )
    assert contract is not None
    assert contract.current_phase_goal == "再把 release gate 收口"
    events = [
        event
        for event in app.state.session_service.list_events(session_id="session:repo-a")
        if event.event_type in {"goal_contract_created", "goal_contract_revised"}
    ]
    assert [event.related_ids["feishu_event_id"] for event in events] == [
        "evt-feishu-1",
        "evt-feishu-2",
    ]


def test_feishu_ingress_replay_rejects_drifted_goal_payload(tmp_path: Path) -> None:
    a_client = _IngressAClient(tasks=[_task("repo-a", thread_id="session:repo-a")])
    app = create_app(settings=_settings(tmp_path), a_client=a_client)

    with TestClient(app) as client:
        first = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event(
                "/goal 先把 Feishu 主链路打通",
                event_id="evt-feishu-1",
                message_id="om_message_1",
            ),
        )
        replay = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event(
                "/goal 同一个事件号但目标已经变了",
                event_id="evt-feishu-1",
                message_id="om_message_1",
            ),
        )

    assert first.status_code == 200
    assert replay.status_code == 400
    assert replay.json()["detail"] == "goal bootstrap replay payload drifted from existing contract"


def test_feishu_goal_bootstrap_supersedes_pending_approval_and_outbox(tmp_path: Path) -> None:
    a_client = _IngressAClient(tasks=[_task("repo-a", thread_id="session:repo-a")])
    app = create_app(settings=_settings(tmp_path), a_client=a_client)
    approval = materialize_canonical_approval(
        _approval_decision(),
        approval_store=app.state.canonical_approval_store,
        delivery_outbox_store=app.state.delivery_outbox_store,
        session_service=app.state.session_service,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("repo:repo-a /goal 飞书联调"),
        )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["data"]["superseded_approval_count"] == 1

    refreshed = app.state.canonical_approval_store.get(approval.envelope_id)
    assert refreshed is not None
    assert refreshed.status == "superseded"
    assert refreshed.decided_by == "feishu-goal-bootstrap"

    outbox = app.state.delivery_outbox_store.get_delivery_record(approval.envelope_id)
    assert outbox is not None
    assert outbox.delivery_status == "superseded"

    events = app.state.session_service.list_events(
        session_id="session:repo-a",
        event_type="approval_superseded_by_goal_contract_bootstrap",
    )
    assert len(events) == 1
    assert events[0].related_ids["native_thread_id"] == approval.native_thread_id
    assert approval.approval_id in events[0].payload["approval_ids"]


def test_feishu_goal_bootstrap_supersede_event_uses_effective_native_thread_from_deep_legacy_approval_record(
    tmp_path: Path,
) -> None:
    a_client = _IngressAClient(tasks=[_task("repo-a", thread_id="session:repo-a")])
    app = create_app(settings=_settings(tmp_path), a_client=a_client)
    approval = materialize_canonical_approval(
        _approval_decision(),
        approval_store=app.state.canonical_approval_store,
        delivery_outbox_store=app.state.delivery_outbox_store,
        session_service=app.state.session_service,
    )
    path = tmp_path / "canonical_approvals.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload[approval.envelope_id]["native_thread_id"] = None
    payload[approval.envelope_id]["decision"]["native_thread_id"] = None
    payload[approval.envelope_id]["decision"].setdefault("evidence", {})
    payload[approval.envelope_id]["decision"]["evidence"]["target"] = {
        "session_id": "session:repo-a",
        "project_id": "repo-a",
        "thread_id": "session:repo-a",
        "native_thread_id": "thr_native_1",
        "approval_id": approval.approval_id,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("repo:repo-a /goal 飞书联调"),
        )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    events = app.state.session_service.list_events(
        session_id="session:repo-a",
        event_type="approval_superseded_by_goal_contract_bootstrap",
    )
    assert len(events) == 1
    assert events[0].related_ids["native_thread_id"] == "thr_native_1"


def test_feishu_goal_bootstrap_only_supersedes_stale_goal_contract_approvals(
    tmp_path: Path,
) -> None:
    a_client = _IngressAClient(tasks=[_task("repo-a", thread_id="session:repo-a")])
    app = create_app(settings=_settings(tmp_path), a_client=a_client)
    contracts = GoalContractService(app.state.session_service)
    current = contracts.bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="旧目标",
        task_prompt="旧目标",
        last_user_instruction="旧目标",
        phase="bootstrap",
        last_summary="seed contract",
        explicit_deliverables=["旧目标"],
        completion_signals=["autonomy golden path release blocker passes"],
        causation_id="seed-goal-contract",
        related_ids={"feishu_actor_id": "ou_actor_1"},
    )
    stale = materialize_canonical_approval(
        _approval_decision(
            approval_id="appr_old_contract",
            goal_contract_version=current.version,
        ),
        approval_store=app.state.canonical_approval_store,
        delivery_outbox_store=app.state.delivery_outbox_store,
        session_service=app.state.session_service,
    )
    active_line = materialize_canonical_approval(
        _approval_decision(
            approval_id="appr_keep_current_line",
            goal_contract_version="goal-v2",
        ),
        approval_store=app.state.canonical_approval_store,
        delivery_outbox_store=app.state.delivery_outbox_store,
        session_service=app.state.session_service,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/watchdog/feishu/events",
            json=_message_event("repo:repo-a /goal 新目标"),
        )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert response.json()["data"]["goal_contract_version"] == "goal-v2"
    assert response.json()["data"]["superseded_approval_count"] == 1

    refreshed_stale = app.state.canonical_approval_store.get(stale.envelope_id)
    refreshed_active = app.state.canonical_approval_store.get(active_line.envelope_id)
    assert refreshed_stale is not None
    assert refreshed_active is not None
    assert refreshed_stale.status == "superseded"
    assert refreshed_active.status == "pending"

    stale_outbox = app.state.delivery_outbox_store.get_delivery_record(stale.envelope_id)
    active_outbox = app.state.delivery_outbox_store.get_delivery_record(active_line.envelope_id)
    assert stale_outbox is not None
    assert active_outbox is not None
    assert stale_outbox.delivery_status == "superseded"
    assert active_outbox.delivery_status == "pending"
