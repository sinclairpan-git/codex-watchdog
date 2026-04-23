from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from watchdog.main import create_app
from watchdog.contracts.session_spine.models import ApprovalProjection, FactRecord
from watchdog.contracts.session_spine.models import SessionProjection, TaskProgressView
from watchdog.services.brain.models import DecisionIntent
from watchdog.services.brain.provider_runtime import OpenAICompatibleBrainProvider
from watchdog.services.goal_contract.service import GoalContractService
from watchdog.services.policy.rules import MANAGED_AGENT_ACTION_ARGUMENT_CONTRACTS
from watchdog.services.brain.service import BrainDecisionService
from watchdog.services.session_service.service import SessionService
from watchdog.services.session_service.store import SessionServiceStore
from watchdog.services.session_spine.store import PersistedSessionRecord
from watchdog.settings import Settings


def _session_service(tmp_path: Path) -> SessionService:
    return SessionService(SessionServiceStore(tmp_path / "session_service.json"))


def _bootstrap_goal_contract(session_service: SessionService) -> None:
    GoalContractService(session_service).bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="invoice assistant",
        task_prompt="Build the invoice assistant end to end",
        last_user_instruction="Continue the export audit refresh work",
        phase="editing_source",
        last_summary="Implemented the export audit surfaces",
        current_phase_goal="Refresh the export audit surface",
        explicit_deliverables=["export audit surface", "verification evidence"],
        completion_signals=["export audit refresh merged", "targeted tests green"],
        active_goal="Refresh the export audit surface",
    )


def _seed_active_state(repo_root: Path) -> None:
    project_state_dir = repo_root / ".ai-sdlc" / "project" / "config"
    project_state_dir.mkdir(parents=True, exist_ok=True)
    (project_state_dir / "project-state.yaml").write_text(
        "status: initialized\nproject_execution_state: active\nnext_work_item_seq: 86\n",
        encoding="utf-8",
    )
    checkpoint_dir = repo_root / ".ai-sdlc" / "state"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    (checkpoint_dir / "checkpoint.yml").write_text(
        "current_stage: execute\nfeature:\n  id: 085-model-first-continuation-governance\n  current_branch: codex/085-model-first-continuation-governance\n",
        encoding="utf-8",
    )


def _decision_context_payload() -> dict[str, object]:
    return {
        "packet_version": "pcdi:v1",
        "project_ref": {
            "project_id": "repo-a",
            "project_execution_state": "active",
            "project_total_goal": "Build the invoice assistant end to end",
        },
        "branch_ref": {
            "branch_goal": "Refresh the export audit surface",
            "next_work_item_seq": 86,
            "target_work_item_seq": 86,
        },
        "progress_ref": {
            "current_phase": "editing_source",
            "current_progress_summary": "ship feishu and memory hub integration",
        },
        "session_ref": {
            "session_id": "session:repo-a",
            "native_thread_id": "thr_native_1",
            "task_status": "active",
        },
        "governance_ref": {
            "goal_contract_version": "goal-v1",
        },
        "approval_ref": {
            "pending_approval_count": 0,
            "actionable_commands": [],
            "latest_approval_reason": None,
        },
        "completion_ref": {
            "task_completion_candidate": False,
            "branch_completion_candidate": False,
            "next_branch_available": True,
            "target_work_item_seq": 86,
        },
        "error_ref": {
            "primary_fact_codes": [],
            "blocker_fact_codes": [],
            "latest_error_summary": None,
            "recovery_candidate": False,
        },
        "decision_scope_ref": {
            "can_request_approval": True,
            "can_continue_current_branch": True,
            "can_recover_current_branch": True,
            "can_switch_branch": True,
            "can_close_session": True,
        },
        "freshness_ref": {
            "snapshot_epoch": "session-seq:1",
            "snapshot_version": "fact-v1",
            "snapshot_observed_at": "2026-04-16T00:00:00Z",
        },
        "continuation_identity": "repo-a:session:repo-a:thr_native_1",
        "route_key": "repo-a:session:repo-a:thr_native_1:fact-v1",
        "branch_switch_token": "branch-switch:repo-a:86:fact-v1",
    }


def _record() -> PersistedSessionRecord:
    return PersistedSessionRecord(
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="thr_native_1",
        session_seq=1,
        fact_snapshot_version="fact-v1",
        last_refreshed_at="2026-04-16T00:00:00Z",
        session=SessionProjection(
            project_id="repo-a",
            thread_id="session:repo-a",
            native_thread_id="thr_native_1",
            session_state="active",
            activity_phase="editing_source",
            attention_state="normal",
            headline="editing files",
            pending_approval_count=0,
            available_intents=["continue"],
        ),
        progress=TaskProgressView(
            project_id="repo-a",
            thread_id="session:repo-a",
            native_thread_id="thr_native_1",
            activity_phase="editing_source",
            summary="ship feishu and memory hub integration",
            files_touched=["src/example.py"],
            context_pressure="low",
            stuck_level=0,
            primary_fact_codes=[],
            blocker_fact_codes=[],
            last_progress_at="2026-04-16T00:00:00Z",
        ),
        facts=[],
        approval_queue=[],
    )


def test_brain_service_uses_openai_compatible_provider_when_configured(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://provider.example/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer sk-provider"
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "minimax-m2.7"
        decision_context = json.loads(payload["messages"][1]["content"])["decision_context"]
        assert decision_context["project_ref"]["project_total_goal"] == "Build the invoice assistant end to end"
        assert decision_context["branch_ref"]["branch_goal"] == "Refresh the export audit surface"
        assert decision_context["branch_ref"]["next_branch_candidate"] == "work-item-seq:86"
        assert decision_context["progress_ref"]["current_progress_summary"] == "ship feishu and memory hub integration"
        assert decision_context["governance_ref"]["goal_contract_version"] == "goal-v1"
        assert decision_context["approval_ref"]["pending_approval_count"] == 0
        assert decision_context["completion_ref"]["next_branch_available"] is True
        assert decision_context["error_ref"]["recovery_candidate"] is False
        assert decision_context["decision_scope_ref"]["can_continue_current_branch"] is True
        assert decision_context["continuation_identity"] == "repo-a:session:repo-a:thr_native_1"
        assert decision_context["route_key"] == "repo-a:session:repo-a:thr_native_1:fact-v1"
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test-1",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "continuation_decision": "continue_current_branch",
                                    "routing_preference": "same_thread",
                                    "goal_coverage": "partial",
                                    "remaining_work_hypothesis": ["continue implementation"],
                                    "completion_confidence": 0.91,
                                    "next_branch_hypothesis": "",
                                    "decision_reason": "current work can continue",
                                    "evidence_codes": ["active_goal_present"],
                                }
                            )
                        }
                    }
                ],
            },
        )

    session_service = _session_service(tmp_path)
    _bootstrap_goal_contract(session_service)
    _seed_active_state(tmp_path)

    service = BrainDecisionService(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        session_service=session_service,
        repo_root=tmp_path,
        provider_transport=httpx.MockTransport(handler),
    )

    intent = service.evaluate_session(record=_record())

    assert intent.intent == "propose_execute"
    assert intent.continuation_decision == "continue_current_branch"
    assert intent.provider == "openai-compatible"
    assert intent.model == "minimax-m2.7"


def test_brain_service_precondition_blocks_include_structured_diagnostics(tmp_path: Path) -> None:
    inactive_service = BrainDecisionService(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        session_service=_session_service(tmp_path),
        repo_root=tmp_path,
    )
    inactive_intent = inactive_service.evaluate_session(record=_record())
    assert inactive_intent.intent == "observe_only"
    assert "project_execution_state_not_active" in inactive_intent.evidence_codes
    assert inactive_intent.remaining_work_hypothesis == [
        "wait until project execution state returns to active"
    ]

    session_service = _session_service(tmp_path)
    _bootstrap_goal_contract(session_service)
    _seed_active_state(tmp_path)
    approval_record = _record().model_copy(
        update={
            "session": _record().session.model_copy(update={"pending_approval_count": 1}),
        }
    )
    approval_service = BrainDecisionService(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        session_service=session_service,
        repo_root=tmp_path,
    )
    approval_intent = approval_service.evaluate_session(record=approval_record)
    assert approval_intent.intent == "require_approval"
    assert "approval_pending" in approval_intent.evidence_codes
    assert approval_intent.remaining_work_hypothesis == [
        "review the pending approval and decide approve or reject"
    ]

    no_goal_root = tmp_path / "no-goal"
    _seed_active_state(no_goal_root)
    no_goal_service = BrainDecisionService(
        settings=Settings(
            data_dir=str(no_goal_root),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        session_service=_session_service(no_goal_root),
        repo_root=no_goal_root,
    )
    no_goal_intent = no_goal_service.evaluate_session(record=_record())
    assert "goal_contract_not_ready" in no_goal_intent.evidence_codes


def test_brain_service_ignores_stale_approval_queue_when_session_has_no_pending_approval(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        decision_context = json.loads(payload["messages"][1]["content"])["decision_context"]
        assert decision_context["governance_ref"]["pending_approval"] is False
        assert decision_context["approval_ref"]["pending_approval_count"] == 0
        assert decision_context["approval_ref"]["latest_approval_reason"] is None
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-stale-approval-queue-1",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "continuation_decision": "continue_current_branch",
                                    "routing_preference": "same_thread",
                                    "goal_coverage": "partial",
                                    "remaining_work_hypothesis": ["continue implementation"],
                                    "completion_confidence": 0.8,
                                    "next_branch_hypothesis": "",
                                    "decision_reason": "no approval is currently pending",
                                    "evidence_codes": ["active_goal_present"],
                                }
                            )
                        }
                    }
                ],
            },
        )

    session_service = _session_service(tmp_path)
    _bootstrap_goal_contract(session_service)
    _seed_active_state(tmp_path)
    record = _record().model_copy(
        update={
            "approval_queue": [
                ApprovalProjection(
                    approval_id="appr_stale",
                    project_id="repo-a",
                    thread_id="session:repo-a",
                    native_thread_id="thr_native_1",
                    risk_level="L1",
                    command="pytest -q",
                    reason="stale approval shadow",
                    alternative="",
                    status="pending",
                    requested_at="2026-04-16T00:01:00Z",
                )
            ],
        }
    )
    service = BrainDecisionService(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        session_service=session_service,
        repo_root=tmp_path,
        provider_transport=httpx.MockTransport(handler),
    )

    intent = service.evaluate_session(record=record)

    assert intent.intent == "propose_execute"
    assert "approval_pending" not in intent.evidence_codes


def test_brain_service_sanitizes_dirty_progress_summary_before_provider_request(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        decision_context = json.loads(payload["messages"][1]["content"])["decision_context"]
        assert decision_context["progress_ref"]["current_progress_summary"] == (
            "codex开发进度，并优先验证最近改动。"
        )
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-sanitized-summary-1",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "continuation_decision": "continue_current_branch",
                                    "routing_preference": "same_thread",
                                    "goal_coverage": "partial",
                                    "remaining_work_hypothesis": ["continue implementation"],
                                    "completion_confidence": 0.91,
                                    "decision_reason": "current work can continue",
                                    "evidence_codes": ["active_goal_present"],
                                }
                            )
                        }
                    }
                ],
            },
        )

    session_service = _session_service(tmp_path)
    _bootstrap_goal_contract(session_service)
    _seed_active_state(tmp_path)
    dirty_record = _record().model_copy(
        update={
            "progress": _record().progress.model_copy(
                update={
                    "summary": (
                        "[steer:rule_based_continue] 下一步建议：继续推进 "
                        "[steer:rule_based_continue] 下一步建议：继续推进 "
                        "codex开发进度，并优先验证最近改动。，并优先验证最近改动。"
                    )
                }
            )
        }
    )

    service = BrainDecisionService(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        session_service=session_service,
        repo_root=tmp_path,
        provider_transport=httpx.MockTransport(handler),
    )

    intent = service.evaluate_session(record=dirty_record)

    assert intent.intent == "propose_execute"


def test_brain_service_ignores_stale_approval_commands_without_visible_pending_approval(
    tmp_path: Path,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-stale-approval-commands-1",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "continuation_decision": "continue_current_branch",
                                    "routing_preference": "same_thread",
                                    "goal_coverage": "partial",
                                    "remaining_work_hypothesis": ["continue implementation"],
                                    "completion_confidence": 0.61,
                                    "decision_reason": "no visible pending approval remains",
                                    "evidence_codes": ["stuck_no_progress"],
                                }
                            )
                        }
                    }
                ],
            },
        )

    session_service = _session_service(tmp_path)
    _bootstrap_goal_contract(session_service)
    _seed_active_state(tmp_path)
    base_record = _record()
    record = base_record.model_copy(
        update={
            "session": base_record.session.model_copy(
                update={
                    "pending_approval_count": 0,
                    "available_intents": [
                        "get_session",
                        "continue_session",
                        "list_pending_approvals",
                        "approve_approval",
                        "reject_approval",
                    ],
                }
            ),
            "approval_queue": [],
        }
    )

    service = BrainDecisionService(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        session_service=session_service,
        repo_root=tmp_path,
        provider_transport=httpx.MockTransport(handler),
    )

    intent = service.evaluate_session(record=record)

    assert intent.intent == "propose_execute"
    assert "approval_pending" not in intent.evidence_codes


def test_brain_service_synthesizes_placeholder_progress_summary_for_provider(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        decision_context = json.loads(payload["messages"][1]["content"])["decision_context"]
        summary = decision_context["progress_ref"]["current_progress_summary"]
        assert "当前进展待汇总" not in summary
        assert "当前分支目标：Refresh the export audit surface" in summary
        assert "当前阶段：handoff" in summary
        assert "阻塞信号：stuck_no_progress" in summary
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-synthesized-summary-1",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "continuation_decision": "continue_current_branch",
                                    "routing_preference": "same_thread",
                                    "goal_coverage": "partial",
                                    "remaining_work_hypothesis": ["resume implementation"],
                                    "completion_confidence": 0.75,
                                    "decision_reason": "derived context is sufficient to continue",
                                    "evidence_codes": ["derived_progress_summary"],
                                }
                            )
                        }
                    }
                ],
            },
        )

    session_service = _session_service(tmp_path)
    _bootstrap_goal_contract(session_service)
    _seed_active_state(tmp_path)
    placeholder_record = _record().model_copy(
        update={
            "session": _record().session.model_copy(update={"activity_phase": "handoff"}),
            "progress": _record().progress.model_copy(
                update={
                    "activity_phase": "handoff",
                    "summary": "当前进展待汇总；需要先返回已完成内容、阻塞点和下一步动作。",
                    "blocker_fact_codes": ["stuck_no_progress"],
                }
            ),
        }
    )

    service = BrainDecisionService(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        session_service=session_service,
        repo_root=tmp_path,
        provider_transport=httpx.MockTransport(handler),
    )

    intent = service.evaluate_session(record=placeholder_record)

    assert intent.intent == "propose_execute"


def test_rule_based_continue_uses_synthesized_progress_summary(tmp_path: Path) -> None:
    session_service = _session_service(tmp_path)
    _bootstrap_goal_contract(session_service)
    _seed_active_state(tmp_path)
    placeholder_record = _record().model_copy(
        update={
            "progress": _record().progress.model_copy(
                update={
                    "activity_phase": "handoff",
                    "summary": "当前进展待汇总；需要先返回已完成内容、阻塞点和下一步动作。",
                    "blocker_fact_codes": ["stuck_no_progress"],
                }
            ),
            "facts": [
                FactRecord(
                    contract_version="watchdog-session-spine/v1alpha1",
                    schema_version="2026-04-05.022",
                    fact_id="repo-a:stuck_no_progress",
                    fact_code="stuck_no_progress",
                    fact_kind="blocker",
                    severity="warning",
                    summary="session appears stuck",
                    detail="no meaningful progress has been observed within the watchdog threshold",
                    source="status_analyzer",
                    observed_at="2026-04-16T00:00:00Z",
                    related_ids={},
                )
            ],
        }
    )
    service = BrainDecisionService(
        settings=Settings(data_dir=str(tmp_path)),
        session_service=session_service,
        repo_root=tmp_path,
    )

    intent = service.evaluate_session(record=placeholder_record)

    assert intent.intent == "propose_execute"
    assert "当前进展待汇总" not in str(intent.action_arguments.get("message") or "")
    assert "当前分支目标：Refresh the export audit surface" in str(
        intent.action_arguments.get("message") or ""
    )


def test_brain_service_surfaces_provider_unavailable_error_class(tmp_path: Path) -> None:
    session_service = _session_service(tmp_path)
    _bootstrap_goal_contract(session_service)
    _seed_active_state(tmp_path)

    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connect failed")

    service = BrainDecisionService(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        session_service=session_service,
        repo_root=tmp_path,
        provider_transport=httpx.MockTransport(handler),
    )

    failing_record = _record().model_copy(
        update={
            "facts": [
                FactRecord(
                    contract_version="watchdog-session-spine/v1alpha1",
                    schema_version="2026-04-05.022",
                    fact_id="repo-a:stuck_no_progress",
                    fact_code="stuck_no_progress",
                    fact_kind="blocker",
                    severity="warning",
                    summary="session appears stuck",
                    detail="no meaningful progress has been observed within the watchdog threshold",
                    source="status_analyzer",
                    observed_at="2026-04-16T00:00:00Z",
                    related_ids={},
                )
            ]
        }
    )

    intent = service.evaluate_session(record=failing_record)

    assert intent.intent == "propose_execute"
    assert intent.degrade_reason == "provider_unavailable"
    assert "provider_unavailable" in intent.evidence_codes
    assert "provider_error:ConnectError" in intent.evidence_codes
    assert intent.provider == "openai-compatible"
    assert intent.model == "minimax-m2.7"
    assert intent.provider == "openai-compatible"


def test_brain_service_surfaces_provider_rate_limited_error_class(tmp_path: Path) -> None:
    session_service = _session_service(tmp_path)
    _bootstrap_goal_contract(session_service)
    _seed_active_state(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            request=request,
            json={
                "type": "error",
                "error": {
                    "type": "rate_limit_error",
                    "message": "usage limit exceeded",
                    "http_code": "429",
                },
            },
        )

    service = BrainDecisionService(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        session_service=session_service,
        repo_root=tmp_path,
        provider_transport=httpx.MockTransport(handler),
    )

    failing_record = _record().model_copy(
        update={
            "facts": [
                FactRecord(
                    contract_version="watchdog-session-spine/v1alpha1",
                    schema_version="2026-04-05.022",
                    fact_id="repo-a:stuck_no_progress",
                    fact_code="stuck_no_progress",
                    fact_kind="blocker",
                    severity="warning",
                    summary="session appears stuck",
                    detail="no meaningful progress has been observed within the watchdog threshold",
                    source="status_analyzer",
                    observed_at="2026-04-16T00:00:00Z",
                    related_ids={},
                )
            ]
        }
    )

    intent = service.evaluate_session(record=failing_record)

    assert intent.intent == "propose_execute"
    assert intent.degrade_reason == "provider_rate_limited"
    assert "provider_http_status:429" in intent.evidence_codes
    assert "provider_rate_limited" in intent.evidence_codes
    assert "provider_unavailable" not in intent.evidence_codes
    assert intent.provider == "openai-compatible"
    assert intent.model == "minimax-m2.7"


def test_brain_service_uses_named_provider_profile_when_selected(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://deepseek.example/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer sk-deepseek"
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "deepseek-chat"
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-deepseek-1",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "continuation_decision": "continue_current_branch",
                                    "routing_preference": "same_thread",
                                    "goal_coverage": "partial",
                                    "remaining_work_hypothesis": ["continue implementation"],
                                    "completion_confidence": 0.91,
                                    "next_branch_hypothesis": "",
                                    "decision_reason": "current work can continue",
                                    "evidence_codes": ["active_goal_present"],
                                }
                            )
                        }
                    }
                ],
            },
        )

    session_service = _session_service(tmp_path)
    _bootstrap_goal_contract(session_service)
    _seed_active_state(tmp_path)

    service = BrainDecisionService(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="deepseek-prod",
            brain_provider_profiles_json=(
                '{"deepseek-prod": {"provider": "openai-compatible", '
                '"base_url": "https://deepseek.example/v1", '
                '"api_key": "sk-deepseek", '
                '"model": "deepseek-chat"}}'
            ),
        ),
        session_service=session_service,
        repo_root=tmp_path,
        provider_transport=httpx.MockTransport(handler),
    )

    intent = service.evaluate_session(record=_record())

    assert intent.intent == "propose_execute"
    assert intent.provider == "deepseek-prod"
    assert intent.model == "deepseek-chat"


def test_provider_runtime_sends_managed_action_contract_surface(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "minimax-m2.7"
        system_prompt = payload["messages"][0]["content"]
        user_payload = json.loads(payload["messages"][1]["content"])
        continue_session = user_payload["managed_agent_contract"]["actions"]["continue_session"]
        execute_recovery = user_payload["managed_agent_contract"]["actions"]["execute_recovery"]
        post_operator_guidance = user_payload["managed_agent_contract"]["actions"]["post_operator_guidance"]

        assert "Do not emit action_ref, action_arguments, approval_id, mode, or resume payloads." in system_prompt
        assert user_payload["decision_context"]["packet_version"] == "pcdi:v1"
        assert user_payload["decision_context"]["session_ref"]["native_thread_id"] == "thr_native_1"
        assert user_payload["decision_context"]["branch_switch_token"] == "branch-switch:repo-a:86:fact-v1"
        assert continue_session["allowed_keys"] == list(
            MANAGED_AGENT_ACTION_ARGUMENT_CONTRACTS["continue_session"]["allowed_keys"]
        )
        assert continue_session["required_keys"] == []
        assert execute_recovery["allowed_keys"] == []
        assert execute_recovery["required_keys"] == []
        assert post_operator_guidance["allowed_keys"] == list(
            MANAGED_AGENT_ACTION_ARGUMENT_CONTRACTS["post_operator_guidance"]["allowed_keys"]
        )
        assert post_operator_guidance["required_keys"] == ["message"]
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-contract-1",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "continuation_decision": "continue_current_branch",
                                    "routing_preference": "same_thread",
                                    "goal_coverage": "partial",
                                    "remaining_work_hypothesis": ["continue implementation"],
                                    "completion_confidence": 0.91,
                                    "next_branch_hypothesis": "",
                                    "decision_reason": "current work can continue",
                                    "evidence_codes": ["active_goal_present"],
                                }
                            )
                        }
                    }
                ],
            },
        )

    provider = OpenAICompatibleBrainProvider(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        transport=httpx.MockTransport(handler),
    )

    intent = provider.decide(
        record=_record(),
        session_truth={"status": "active", "activity_phase": "editing_source"},
        memory_advisory_context=None,
        decision_context=_decision_context_payload(),
    )

    assert intent.prompt_schema_ref == "prompt:brain-continuation-decision-v3"
    assert intent.output_schema_ref == "schema:provider-continuation-decision-v3"
    assert intent.continuation_decision == "continue_current_branch"


def test_provider_runtime_rejects_raw_action_arguments_from_provider(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-raw-action-args-1",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "continuation_decision": "continue_current_branch",
                                    "routing_preference": "same_thread",
                                    "goal_coverage": "partial",
                                    "remaining_work_hypothesis": ["continue implementation"],
                                    "completion_confidence": 0.77,
                                    "next_branch_hypothesis": "",
                                    "decision_reason": "current work can continue",
                                    "evidence_codes": ["active_goal_present"],
                                    "action_arguments": {
                                        "message": "override",
                                        "reason_code": "provider_override",
                                        "stuck_level": 4,
                                        "approval_id": "approval-bad",
                                    },
                                }
                            )
                        }
                    }
                ],
            },
        )

    provider = OpenAICompatibleBrainProvider(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ValueError, match="provider response violates schema"):
        provider.decide(
            record=_record(),
            session_truth={"status": "active", "activity_phase": "editing_source"},
            memory_advisory_context=None,
            decision_context=_decision_context_payload(),
        )


def test_provider_runtime_maps_branch_switch_decision_to_observe_only_metadata(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-branch-switch-1",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "continuation_decision": "branch_complete_switch",
                                    "routing_preference": "next_branch_session",
                                    "goal_coverage": "complete",
                                    "remaining_work_hypothesis": [],
                                    "completion_confidence": 0.96,
                                    "next_branch_hypothesis": "086-continuation-routing",
                                    "decision_reason": "current branch goal is complete",
                                    "evidence_codes": ["branch_goal_complete", "next_work_item_available"],
                                }
                            )
                        }
                    }
                ],
            },
        )

    provider = OpenAICompatibleBrainProvider(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        transport=httpx.MockTransport(handler),
    )

    intent = provider.decide(
        record=_record(),
        session_truth={"status": "active", "activity_phase": "editing_source"},
        memory_advisory_context=None,
        decision_context=_decision_context_payload(),
    )

    assert intent.intent == "branch_complete_switch"
    assert intent.continuation_decision == "branch_complete_switch"
    assert intent.routing_preference == "next_branch_session"
    assert intent.next_branch_hypothesis == "086-continuation-routing"
    assert intent.target_work_item_seq == 86
    assert intent.branch_switch_token == "branch-switch:repo-a:86:fact-v1"


def test_provider_runtime_does_not_emit_continue_args_for_recovery_intents(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-recovery-1",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "continuation_decision": "recover_current_branch",
                                    "routing_preference": "same_thread",
                                    "goal_coverage": "partial",
                                    "remaining_work_hypothesis": ["回滚最近的坏状态", "重试控制链路"],
                                    "completion_confidence": 0.72,
                                    "next_branch_hypothesis": "",
                                    "decision_reason": "需要执行恢复动作",
                                    "evidence_codes": ["recovery_required"],
                                }
                            )
                        }
                    }
                ],
            },
        )

    provider = OpenAICompatibleBrainProvider(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        transport=httpx.MockTransport(handler),
    )

    intent = provider.decide(
        record=_record(),
        session_truth={"status": "active", "activity_phase": "editing_source"},
        memory_advisory_context=None,
        decision_context=_decision_context_payload(),
    )

    assert intent.intent == "propose_recovery"
    assert intent.continuation_decision == "recover_current_branch"
    assert intent.action_arguments == {}
    assert intent.remaining_work_hypothesis == ["回滚最近的坏状态", "重试控制链路"]


def test_brain_service_falls_back_when_provider_output_violates_schema(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-invalid-schema-1",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "session_decision": "active",
                                    "execution_advice": "auto_execute",
                                    "reason_short": "current work can continue",
                                    "action_arguments": {
                                        "message": "override",
                                        "reason_code": "provider_override",
                                        "stuck_level": 4,
                                    },
                                }
                            )
                        }
                    }
                ],
            },
        )

    record = _record().model_copy(
        update={
            "facts": [
                FactRecord(
                    fact_id="fact:stuck",
                    fact_code="stuck_no_progress",
                    fact_kind="derived",
                    severity="warning",
                    summary="session stalled",
                    detail="no progress in the last interval",
                    source="projection",
                    observed_at="2026-04-16T00:00:00Z",
                )
            ]
        }
    )

    session_service = _session_service(tmp_path)
    _bootstrap_goal_contract(session_service)
    _seed_active_state(tmp_path)
    service = BrainDecisionService(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        session_service=session_service,
        repo_root=tmp_path,
        provider_transport=httpx.MockTransport(handler),
    )

    intent = service.evaluate_session(record=record)

    assert intent.intent == "propose_execute"
    assert intent.action_arguments == {
        "message": "下一步建议：继续推进 ship feishu and memory hub integration，并优先验证最近改动。",
        "reason_code": "rule_based_continue",
        "stuck_level": 0,
    }
    assert intent.provider == "resident_orchestrator"
    assert intent.model == "rule-based-brain"
    assert intent.output_schema_ref == "schema:decision-trace-v1"
    assert intent.provider_output_schema_ref == "schema:provider-decision-v2"
    assert intent.degrade_reason == "provider_output_invalid"


def test_brain_service_falls_back_to_rule_based_when_provider_unavailable(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("provider timeout")

    record = _record().model_copy(
        update={
            "facts": [
                FactRecord(
                    fact_id="fact:task-completed",
                    fact_code="task_completed",
                    fact_kind="derived",
                    severity="info",
                    summary="task completed",
                    detail="done",
                    source="projection",
                    observed_at="2026-04-16T00:00:00Z",
                )
            ]
        }
    )

    session_service = _session_service(tmp_path)
    _bootstrap_goal_contract(session_service)
    _seed_active_state(tmp_path)
    service = BrainDecisionService(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        session_service=session_service,
        repo_root=tmp_path,
        provider_transport=httpx.MockTransport(handler),
    )

    intent = service.evaluate_session(record=record)

    assert intent.intent == "candidate_closure"
    assert intent.provider == "openai-compatible"
    assert intent.model == "minimax-m2.7"
    assert intent.degrade_reason == "provider_unavailable"


def test_brain_service_blocks_provider_when_goal_contract_missing(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("provider should not be called without authoritative goal contract")

    _seed_active_state(tmp_path)
    service = BrainDecisionService(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        session_service=_session_service(tmp_path),
        repo_root=tmp_path,
        provider_transport=httpx.MockTransport(handler),
    )

    intent = service.evaluate_session(record=_record())

    assert intent.intent == "observe_only"
    assert intent.rationale == "goal contract is not ready for autonomous continuation"


def test_brain_service_falls_back_to_rule_based_when_goal_contract_missing_for_stuck_session(
    tmp_path: Path,
) -> None:
    provider_called = False

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal provider_called
        provider_called = True
        raise AssertionError("provider should not be called without authoritative goal contract")

    _seed_active_state(tmp_path)
    record = _record().model_copy(
        update={
            "facts": [
                FactRecord(
                    fact_id="fact:stuck",
                    fact_code="stuck_no_progress",
                    fact_kind="derived",
                    severity="warning",
                    summary="session stalled",
                    detail="no progress in the last interval",
                    source="projection",
                    observed_at="2026-04-16T00:00:00Z",
                )
            ]
        }
    )

    service = BrainDecisionService(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        session_service=_session_service(tmp_path),
        repo_root=tmp_path,
        provider_transport=httpx.MockTransport(handler),
    )

    intent = service.evaluate_session(record=record)

    assert provider_called is False
    assert intent.intent == "propose_execute"
    assert intent.action_arguments == {
        "message": "下一步建议：继续推进 ship feishu and memory hub integration，并优先验证最近改动。",
        "reason_code": "rule_based_continue",
        "stuck_level": 0,
    }
    assert intent.provider == "resident_orchestrator"
    assert intent.model == "rule-based-brain"
    assert intent.rationale == "goal contract is not ready for autonomous continuation"


def test_brain_service_blocks_provider_when_project_is_paused(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("provider should not be called for paused projects")

    session_service = _session_service(tmp_path)
    _bootstrap_goal_contract(session_service)
    _seed_active_state(tmp_path)
    resume_dir = tmp_path / ".ai-sdlc" / "state"
    resume_dir.mkdir(parents=True, exist_ok=True)
    (resume_dir / "resume-pack.yaml").write_text("current_stage: paused\n", encoding="utf-8")

    service = BrainDecisionService(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        session_service=session_service,
        repo_root=tmp_path,
        provider_transport=httpx.MockTransport(handler),
    )

    intent = service.evaluate_session(record=_record())

    assert intent.intent == "observe_only"
    assert intent.rationale == "project is not active for autonomous continuation"


def test_brain_service_prefers_authoritative_project_state_over_resume_pack_stage(
    tmp_path: Path,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("provider should not be called for completed projects")

    session_service = _session_service(tmp_path)
    _bootstrap_goal_contract(session_service)
    _seed_active_state(tmp_path)
    (tmp_path / ".ai-sdlc" / "project" / "config" / "project-state.yaml").write_text(
        "status: initialized\nproject_execution_state: completed\nnext_work_item_seq: 86\n",
        encoding="utf-8",
    )
    resume_dir = tmp_path / ".ai-sdlc" / "state"
    resume_dir.mkdir(parents=True, exist_ok=True)
    (resume_dir / "resume-pack.yaml").write_text("current_stage: design\n", encoding="utf-8")

    service = BrainDecisionService(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        session_service=session_service,
        repo_root=tmp_path,
        provider_transport=httpx.MockTransport(handler),
    )

    intent = service.evaluate_session(record=_record())

    assert intent.intent == "observe_only"
    assert intent.rationale == "project is not active for autonomous continuation"


def test_brain_service_treats_closed_project_execution_state_as_non_active(
    tmp_path: Path,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("provider should not be called for closed projects")

    session_service = _session_service(tmp_path)
    _bootstrap_goal_contract(session_service)
    _seed_active_state(tmp_path)
    (tmp_path / ".ai-sdlc" / "project" / "config" / "project-state.yaml").write_text(
        "status: initialized\nproject_execution_state: closed\nnext_work_item_seq: 86\n",
        encoding="utf-8",
    )
    resume_dir = tmp_path / ".ai-sdlc" / "state"
    resume_dir.mkdir(parents=True, exist_ok=True)
    (resume_dir / "resume-pack.yaml").write_text("current_stage: execute\n", encoding="utf-8")

    service = BrainDecisionService(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        session_service=session_service,
        repo_root=tmp_path,
        provider_transport=httpx.MockTransport(handler),
    )

    intent = service.evaluate_session(record=_record())

    assert intent.intent == "observe_only"
    assert intent.rationale == "project is not active for autonomous continuation"


def test_brain_service_treats_running_project_execution_state_as_active(
    tmp_path: Path,
) -> None:
    provider_called = False

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal provider_called
        provider_called = True
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-running-1",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "continuation_decision": "continue_current_branch",
                                    "routing_preference": "same_thread",
                                    "goal_coverage": "partial",
                                    "remaining_work_hypothesis": ["continue implementation"],
                                    "completion_confidence": 0.74,
                                    "next_branch_hypothesis": "",
                                    "decision_reason": "running projects should remain active",
                                    "evidence_codes": ["active_goal_present"],
                                }
                            )
                        }
                    }
                ],
            },
        )

    session_service = _session_service(tmp_path)
    _bootstrap_goal_contract(session_service)
    _seed_active_state(tmp_path)
    (tmp_path / ".ai-sdlc" / "project" / "config" / "project-state.yaml").write_text(
        "status: initialized\nproject_execution_state: running\nnext_work_item_seq: 86\n",
        encoding="utf-8",
    )
    resume_dir = tmp_path / ".ai-sdlc" / "state"
    resume_dir.mkdir(parents=True, exist_ok=True)
    (resume_dir / "resume-pack.yaml").write_text("current_stage: execute\n", encoding="utf-8")

    service = BrainDecisionService(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        session_service=session_service,
        repo_root=tmp_path,
        provider_transport=httpx.MockTransport(handler),
    )

    intent = service.evaluate_session(record=_record())

    assert provider_called is True
    assert intent.intent == "propose_execute"
    assert intent.continuation_decision == "continue_current_branch"
    assert intent.rationale == "running projects should remain active"


def test_brain_service_blocks_provider_when_pending_approval_exists(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("provider should not be called while approval is pending")

    session_service = _session_service(tmp_path)
    _bootstrap_goal_contract(session_service)
    _seed_active_state(tmp_path)
    record = _record().model_copy(
        update={
            "session": _record().session.model_copy(update={"pending_approval_count": 1}),
        }
    )

    service = BrainDecisionService(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        session_service=session_service,
        repo_root=tmp_path,
        provider_transport=httpx.MockTransport(handler),
    )

    intent = service.evaluate_session(record=record)

    assert intent.intent == "require_approval"
    assert intent.rationale == "pending approval blocks autonomous continuation"


def test_brain_service_rule_based_continue_keeps_next_step_when_provider_unavailable(
    tmp_path: Path,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("provider timeout")

    record = _record().model_copy(
        update={
            "facts": [
                FactRecord(
                    fact_id="fact:stuck",
                    fact_code="stuck_no_progress",
                    fact_kind="derived",
                    severity="warning",
                    summary="session stalled",
                    detail="no progress in the last interval",
                    source="projection",
                    observed_at="2026-04-16T00:00:00Z",
                )
            ]
        }
    )

    session_service = _session_service(tmp_path)
    _bootstrap_goal_contract(session_service)
    _seed_active_state(tmp_path)
    service = BrainDecisionService(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        session_service=session_service,
        repo_root=tmp_path,
        provider_transport=httpx.MockTransport(handler),
    )

    intent = service.evaluate_session(record=record)

    assert intent.intent == "propose_execute"
    assert intent.action_arguments == {
        "message": "下一步建议：继续推进 ship feishu and memory hub integration，并优先验证最近改动。",
        "reason_code": "rule_based_continue",
        "stuck_level": 0,
    }
    assert intent.provider == "resident_orchestrator"
    assert intent.model == "rule-based-brain"


def test_provider_runtime_uses_provider_specific_timeout(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, *, timeout, transport, trust_env: bool) -> None:
            captured["timeout"] = timeout
            captured["transport"] = transport
            captured["trust_env"] = trust_env

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def post(self, url: str, *, json: dict[str, object], headers: dict[str, str]) -> httpx.Response:
            captured["url"] = url
            captured["headers"] = headers
            captured["payload"] = json
            request = httpx.Request("POST", url, json=json, headers=headers)
            return httpx.Response(
                200,
                request=request,
                json={
                    "id": "chatcmpl-timeout-1",
                    "choices": [
                        {
                            "message": {
                                "content": __import__("json").dumps(
                                    {
                                        "session_decision": "active",
                                        "execution_advice": "auto_execute",
                                        "reason_short": "continue",
                                    }
                                )
                            }
                        }
                    ],
                },
            )

    monkeypatch.setattr("watchdog.services.brain.provider_runtime.httpx.Client", FakeClient)

    provider = OpenAICompatibleBrainProvider(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
            brain_provider_http_timeout_s=27.5,
        )
    )

    intent = provider.decide(
        record=_record(),
        session_truth={"status": "active", "activity_phase": "editing_source"},
        memory_advisory_context=None,
    )

    assert captured["timeout"] == 27.5
    assert captured["trust_env"] is False
    assert captured["url"] == "https://provider.example/v1/chat/completions"
    assert intent.provider_request_id == "chatcmpl-timeout-1"
    assert intent.provider == "openai-compatible"


def test_provider_runtime_parses_think_and_fenced_json(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-think-1",
                "choices": [
                    {
                        "message": {
                            "content": (
                                "<think>\ninternal reasoning\n</think>\n\n"
                                "```json\n"
                                "{\n"
                                '  "session_decision": "active",\n'
                                '  "execution_advice": "auto_execute",\n'
                                '  "reason_short": "continue"\n'
                                "}\n"
                                "```"
                            )
                        }
                    }
                ],
            },
        )

    provider = OpenAICompatibleBrainProvider(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        transport=httpx.MockTransport(handler),
    )

    intent = provider.decide(
        record=_record(),
        session_truth={"status": "active", "activity_phase": "editing_source"},
        memory_advisory_context=None,
    )

    assert intent.intent == "propose_execute"
    assert intent.provider == "openai-compatible"
    assert intent.provider_request_id == "chatcmpl-think-1"


def test_provider_runtime_accepts_minimax_style_continuation_payload(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-minimax-1",
                "choices": [
                    {
                        "message": {
                            "content": (
                                "<think>internal reasoning</think>\n\n"
                                "```json\n"
                                "{\n"
                                '  "continuation_decision": "execute_recovery",\n'
                                '  "routing_preference": "recovery_path",\n'
                                '  "goal_coverage": 0.85,\n'
                                '  "remaining_work_hypothesis": "autonomy golden path release blocker verification pending",\n'
                                '  "completion_confidence": 0.65,\n'
                                '  "next_branch_hypothesis": "work-item-seq:86",\n'
                                '  "decision_reason": "session is blocked and should recover",\n'
                                '  "evidence_codes": ["blocked", "recovery_available"]\n'
                                "}\n"
                                "```"
                            )
                        }
                    }
                ],
            },
        )

    provider = OpenAICompatibleBrainProvider(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        transport=httpx.MockTransport(handler),
    )

    intent = provider.decide(
        record=_record(),
        session_truth={"status": "blocked", "activity_phase": "editing_source"},
        memory_advisory_context=None,
    )

    assert intent.intent == "propose_recovery"
    assert intent.continuation_decision == "recover_current_branch"
    assert intent.routing_preference == "recovery_path"
    assert intent.goal_coverage == "0.85"
    assert intent.remaining_work_hypothesis == [
        "autonomy golden path release blocker verification pending"
    ]
    assert intent.completion_confidence == 0.65
    assert intent.provider == "openai-compatible"
    assert intent.provider_request_id == "chatcmpl-minimax-1"


def test_provider_runtime_accepts_live_recovery_aliases_and_ignores_extra_keys(
    tmp_path: Path,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-minimax-live-1",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "continuation_decision": "route_to_recovery",
                                    "routing_preference": "explain_blocker_and_recover",
                                    "goal_coverage": "unknown",
                                    "remaining_work_hypothesis": "golden path blocker unresolved",
                                    "completion_confidence": 0.2,
                                    "next_branch_hypothesis": "stay_on_current_branch_resolve_blocker",
                                    "decision_reason": "session is blocked",
                                    "evidence_codes": ["stuck_no_progress"],
                                    "session_recovery_hint": "diagnose_golden_path_blocker",
                                    "blocker_candidates": ["test_execution_timeout"],
                                    "message": "extra operator-facing text",
                                    "reason_code": "autonomy_golden_path_unverified",
                                    "stuck_level": 3,
                                }
                            )
                        }
                    }
                ],
            },
        )

    provider = OpenAICompatibleBrainProvider(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        transport=httpx.MockTransport(handler),
    )

    intent = provider.decide(
        record=_record(),
        session_truth={"status": "blocked", "activity_phase": "editing_source"},
        memory_advisory_context=None,
    )

    assert intent.intent == "propose_recovery"
    assert intent.continuation_decision == "recover_current_branch"
    assert intent.routing_preference == "explain_blocker_and_recover"
    assert intent.remaining_work_hypothesis == ["golden path blocker unresolved"]
    assert intent.provider == "openai-compatible"
    assert intent.provider_request_id == "chatcmpl-minimax-live-1"


def test_provider_runtime_accepts_content_parts_and_object_shaped_fields(
    tmp_path: Path,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-minimax-parts-1",
                "choices": [
                    {
                        "message": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": "<think>analyze</think>\n```json\n"
                                    + json.dumps(
                                        {
                                            "continuation_decision": {"value": "recover"},
                                            "routing_preference": {"label": "debug_handoff"},
                                            "goal_coverage": {
                                                "status": "blocked",
                                                "remaining_percentage_estimate": 85,
                                            },
                                            "remaining_work_hypothesis": {
                                                "summary": "autonomy golden path release blocker requires diagnosis before task can progress"
                                            },
                                            "completion_confidence": 0.1,
                                            "next_branch_hypothesis": {
                                                "text": "continue current branch after recovery clears blocker"
                                            },
                                            "decision_reason": {
                                                "summary": "session is blocked and needs recovery"
                                            },
                                            "evidence_codes": [
                                                {"code": "stuck_no_progress"},
                                                {"label": "handoff_phase"},
                                            ],
                                        },
                                        ensure_ascii=False,
                                    )
                                    + "\n```",
                                }
                            ]
                        }
                    }
                ],
            },
        )

    provider = OpenAICompatibleBrainProvider(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        transport=httpx.MockTransport(handler),
    )

    intent = provider.decide(
        record=_record(),
        session_truth={"status": "blocked", "activity_phase": "handoff"},
        memory_advisory_context=None,
    )

    assert intent.intent == "propose_recovery"
    assert intent.continuation_decision == "recover_current_branch"
    assert intent.routing_preference == "debug_handoff"
    assert intent.goal_coverage == "blocked"
    assert intent.remaining_work_hypothesis == [
        "autonomy golden path release blocker requires diagnosis before task can progress"
    ]
    assert intent.next_branch_hypothesis == "continue current branch after recovery clears blocker"
    assert intent.evidence_codes == ["stuck_no_progress", "handoff_phase"]
    assert intent.provider_request_id == "chatcmpl-minimax-parts-1"


def test_provider_runtime_accepts_textual_confidence_and_switch_branch_alias(
    tmp_path: Path,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-minimax-switch-1",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "continuation_decision": "switch_branch",
                                    "routing_preference": "switch_to_next_work_item",
                                    "goal_coverage": "partial_blocked",
                                    "remaining_work_hypothesis": "current branch is blocked; move to seq 86",
                                    "completion_confidence": "medium",
                                    "next_branch_hypothesis": "work-item-seq:86",
                                    "decision_reason": "switch to the next branch after blocker triage",
                                    "evidence_codes": ["next_branch_available", "blocked_current_branch"],
                                }
                            )
                        }
                    }
                ],
            },
        )

    provider = OpenAICompatibleBrainProvider(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        transport=httpx.MockTransport(handler),
    )

    intent = provider.decide(
        record=_record(),
        session_truth={"status": "blocked", "activity_phase": "editing_source"},
        memory_advisory_context=None,
    )

    assert intent.intent == "branch_complete_switch"
    assert intent.continuation_decision == "branch_complete_switch"
    assert intent.completion_confidence == 0.5
    assert intent.next_branch_hypothesis == "work-item-seq:86"


def test_provider_runtime_accepts_switch_branch_with_recovery_attempt_alias(
    tmp_path: Path,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-minimax-switch-recovery-1",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "continuation_decision": "switch_branch_with_recovery_attempt",
                                    "routing_preference": "recover_then_switch",
                                    "goal_coverage": "partial_blocked",
                                    "remaining_work_hypothesis": ["recover current blocker before switching"],
                                    "completion_confidence": 0.35,
                                    "next_branch_hypothesis": "work-item-seq:86",
                                    "decision_reason": "recover first, then switch if needed",
                                    "evidence_codes": ["stuck_no_progress", "next_branch_available"],
                                }
                            )
                        }
                    }
                ],
            },
        )

    provider = OpenAICompatibleBrainProvider(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        transport=httpx.MockTransport(handler),
    )

    intent = provider.decide(
        record=_record(),
        session_truth={"status": "blocked", "activity_phase": "editing_source"},
        memory_advisory_context=None,
    )

    assert intent.intent == "branch_complete_switch"
    assert intent.continuation_decision == "branch_complete_switch"


def test_provider_runtime_accepts_short_recover_alias(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-minimax-recover-1",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "continuation_decision": "recover",
                                    "routing_preference": "operator_guidance",
                                    "goal_coverage": "blocked",
                                    "remaining_work_hypothesis": "needs unblock",
                                    "completion_confidence": 0.2,
                                    "decision_reason": "session remains blocked",
                                    "evidence_codes": ["stuck_no_progress"],
                                }
                            )
                        }
                    }
                ],
            },
        )

    provider = OpenAICompatibleBrainProvider(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        transport=httpx.MockTransport(handler),
    )

    intent = provider.decide(
        record=_record(),
        session_truth={"status": "blocked", "activity_phase": "editing_source"},
        memory_advisory_context=None,
    )

    assert intent.intent == "propose_recovery"
    assert intent.continuation_decision == "recover_current_branch"
    assert intent.routing_preference == "operator_guidance"
    assert intent.provider == "openai-compatible"


def test_provider_runtime_accepts_recover_and_proceed_alias(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-minimax-recover-2",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "continuation_decision": "recover_and_proceed",
                                    "routing_preference": "execute_recovery",
                                    "goal_coverage": "blocked",
                                    "remaining_work_hypothesis": "recover workspace state",
                                    "completion_confidence": 0.3,
                                    "decision_reason": "session requires recovery before continuing",
                                    "evidence_codes": ["stuck_no_progress"],
                                }
                            )
                        }
                    }
                ],
            },
        )

    provider = OpenAICompatibleBrainProvider(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        transport=httpx.MockTransport(handler),
    )

    intent = provider.decide(
        record=_record(),
        session_truth={"status": "blocked", "activity_phase": "editing_source"},
        memory_advisory_context=None,
    )

    assert intent.intent == "propose_recovery"
    assert intent.continuation_decision == "recover_current_branch"
    assert intent.routing_preference == "execute_recovery"
    assert intent.provider == "openai-compatible"


def test_provider_runtime_accepts_request_recovery_alias(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-minimax-request-recovery-1",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "continuation_decision": "request_recovery",
                                    "routing_preference": "recover_from_loop",
                                    "goal_coverage": 0.3,
                                    "remaining_work_hypothesis": "looped progress summary without real work",
                                    "completion_confidence": 0.15,
                                    "decision_reason": "session is stuck and should recover",
                                    "evidence_codes": ["stuck_no_progress"],
                                }
                            )
                        }
                    }
                ],
            },
        )

    provider = OpenAICompatibleBrainProvider(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        transport=httpx.MockTransport(handler),
    )

    intent = provider.decide(
        record=_record(),
        session_truth={"status": "blocked", "activity_phase": "editing_source"},
        memory_advisory_context=None,
    )

    assert intent.intent == "propose_recovery"
    assert intent.continuation_decision == "recover_current_branch"
    assert intent.routing_preference == "recover_from_loop"
    assert intent.goal_coverage == "0.3"


def test_provider_runtime_treats_block_with_recovery_routing_as_recovery(
    tmp_path: Path,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-minimax-block-recovery-1",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "continuation_decision": "BLOCK",
                                    "routing_preference": "recovery",
                                    "goal_coverage": "blocked",
                                    "remaining_work_hypothesis": "needs recovery before continuing",
                                    "completion_confidence": 0.2,
                                    "decision_reason": "session is blocked and should recover",
                                    "evidence_codes": ["stuck_no_progress"],
                                }
                            )
                        }
                    }
                ],
            },
        )

    provider = OpenAICompatibleBrainProvider(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        transport=httpx.MockTransport(handler),
    )

    intent = provider.decide(
        record=_record(),
        session_truth={"status": "blocked", "activity_phase": "editing_source"},
        memory_advisory_context=None,
    )

    assert intent.intent == "propose_recovery"
    assert intent.continuation_decision == "recover_current_branch"
    assert intent.routing_preference == "recovery"


def test_provider_runtime_retries_transient_timeout_and_returns_provider_decision(
    tmp_path: Path,
) -> None:
    attempts = {"count": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise httpx.ReadTimeout("transient provider timeout")
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-minimax-retry-1",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "continuation_decision": "recover",
                                    "routing_preference": "operator_guidance",
                                    "goal_coverage": "blocked",
                                    "remaining_work_hypothesis": "needs unblock",
                                    "completion_confidence": 0.2,
                                    "decision_reason": "session remains blocked",
                                    "evidence_codes": ["stuck_no_progress"],
                                }
                            )
                        }
                    }
                ],
            },
        )

    provider = OpenAICompatibleBrainProvider(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        transport=httpx.MockTransport(handler),
    )

    intent = provider.decide(
        record=_record(),
        session_truth={"status": "blocked", "activity_phase": "editing_source"},
        memory_advisory_context=None,
    )

    assert attempts["count"] == 2
    assert intent.provider == "openai-compatible"
    assert intent.continuation_decision == "recover_current_branch"
    assert intent.intent == "propose_recovery"


def test_brain_service_keeps_structured_next_step_from_provider(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-next-step-1",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "session_decision": "active",
                                    "execution_advice": "auto_execute",
                                    "approval_advice": "none",
                                    "risk_band": "low",
                                    "goal_coverage": "partial",
                                    "remaining_work_hypothesis": [
                                        "补齐飞书控制链路",
                                        "回写验证结果",
                                    ],
                                    "confidence": 0.86,
                                    "reason_short": "当前任务可以继续自动推进",
                                    "evidence_codes": ["active_goal_present"],
                                }
                            )
                        }
                    }
                ],
            },
        )

    session_service = _session_service(tmp_path)
    _bootstrap_goal_contract(session_service)
    _seed_active_state(tmp_path)
    service = BrainDecisionService(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        session_service=session_service,
        repo_root=tmp_path,
        provider_transport=httpx.MockTransport(handler),
    )

    intent = service.evaluate_session(record=_record())

    assert intent.intent == "propose_execute"
    assert intent.action_arguments == {
        "message": "下一步建议：补齐飞书控制链路；回写验证结果。",
        "reason_code": "brain_auto_continue",
        "stuck_level": 0,
    }
    assert intent.confidence == pytest.approx(0.86)
    assert intent.goal_coverage == "partial"
    assert intent.remaining_work_hypothesis == [
        "补齐飞书控制链路",
        "回写验证结果",
    ]
    assert intent.evidence_codes == ["active_goal_present"]


def test_resident_orchestrator_decision_trace_uses_provider_metadata(tmp_path: Path) -> None:
    class FakeAClient:
        def list_tasks(self) -> list[dict[str, object]]:
            return [
                {
                    "project_id": "repo-a",
                    "thread_id": "thr_native_1",
                    "status": "running",
                    "phase": "editing_source",
                    "pending_approval": False,
                    "last_summary": "ship provider integration",
                    "files_touched": ["src/example.py"],
                    "context_pressure": "low",
                    "stuck_level": 0,
                    "failure_count": 0,
                    "last_progress_at": "2026-04-16T00:00:00Z",
                }
            ]

        def get_envelope(self, project_id: str) -> dict[str, object]:
            assert project_id == "repo-a"
            return {"success": True, "data": self.list_tasks()[0]}

        def list_approvals(self, **_: object) -> list[dict[str, object]]:
            return []

    class StaticBrainService:
        def evaluate_session(self, **_: object) -> DecisionIntent:
            return DecisionIntent(
                intent="propose_execute",
                rationale="provider decided continue",
                provider="openai-compatible",
                model="minimax-m2.7",
                prompt_schema_ref="prompt:brain-decision-v1",
                output_schema_ref="schema:provider-decision-v1",
                provider_output_schema_ref="schema:provider-decision-v1",
                provider_request_id="chatcmpl-trace-1",
                degrade_reason="provider_output_invalid",
            )

    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        runtime_client=FakeAClient(),
        start_background_workers=False,
    )
    app.state.resident_orchestrator._brain_service = StaticBrainService()
    app.state.session_spine_runtime.refresh_all()

    record = app.state.session_spine_store.list_records()[0]
    trace = app.state.resident_orchestrator._decision_trace_for_intent(
        record,
        brain_intent=app.state.resident_orchestrator._brain_service.evaluate_session(record=record),
        action_ref="continue_session",
        goal_contract_version="goal-contract:v1",
    )

    assert trace.provider == "openai-compatible"
    assert trace.model == "minimax-m2.7"
    assert trace.prompt_schema_ref == "prompt:brain-decision-v1"
    assert trace.output_schema_ref == "schema:provider-decision-v1"
    assert trace.provider_output_schema_ref == "schema:provider-decision-v1"
    assert trace.degrade_reason == "provider_output_invalid"
