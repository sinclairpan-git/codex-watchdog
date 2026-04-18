from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from watchdog.main import create_app
from watchdog.contracts.session_spine.models import FactRecord
from watchdog.contracts.session_spine.models import SessionProjection, TaskProgressView
from watchdog.services.brain.models import DecisionIntent
from watchdog.services.brain.provider_runtime import OpenAICompatibleBrainProvider
from watchdog.services.policy.rules import MANAGED_AGENT_ACTION_ARGUMENT_CONTRACTS
from watchdog.services.brain.service import BrainDecisionService
from watchdog.services.session_service.service import SessionService
from watchdog.services.session_service.store import SessionServiceStore
from watchdog.services.session_spine.store import PersistedSessionRecord
from watchdog.settings import Settings


def _session_service(tmp_path: Path) -> SessionService:
    return SessionService(SessionServiceStore(tmp_path / "session_service.json"))


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
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test-1",
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
                                    "remaining_work_hypothesis": ["continue implementation"],
                                    "confidence": 0.91,
                                    "reason_short": "current work can continue",
                                    "evidence_codes": ["active_goal_present"],
                                }
                            )
                        }
                    }
                ],
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
        session_service=_session_service(tmp_path),
        provider_transport=httpx.MockTransport(handler),
    )

    intent = service.evaluate_session(record=_record())

    assert intent.intent == "propose_execute"
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
                                    "session_decision": "active",
                                    "execution_advice": "auto_execute",
                                    "approval_advice": "none",
                                    "risk_band": "low",
                                    "goal_coverage": "partial",
                                    "remaining_work_hypothesis": ["continue implementation"],
                                    "confidence": 0.91,
                                    "reason_short": "current work can continue",
                                    "evidence_codes": ["active_goal_present"],
                                }
                            )
                        }
                    }
                ],
            },
        )

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
        session_service=_session_service(tmp_path),
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
                                    "session_decision": "active",
                                    "execution_advice": "auto_execute",
                                    "approval_advice": "none",
                                    "risk_band": "low",
                                    "goal_coverage": "partial",
                                    "remaining_work_hypothesis": ["continue implementation"],
                                    "confidence": 0.91,
                                    "reason_short": "current work can continue",
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
    )

    assert intent.prompt_schema_ref == "prompt:brain-decision-v2"
    assert intent.output_schema_ref == "schema:provider-decision-v2"


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
                                    "session_decision": "active",
                                    "execution_advice": "auto_execute",
                                    "approval_advice": "none",
                                    "risk_band": "low",
                                    "goal_coverage": "partial",
                                    "remaining_work_hypothesis": ["continue implementation"],
                                    "confidence": 0.77,
                                    "reason_short": "current work can continue",
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
        )


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

    service = BrainDecisionService(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        session_service=_session_service(tmp_path),
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

    service = BrainDecisionService(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        session_service=_session_service(tmp_path),
        provider_transport=httpx.MockTransport(handler),
    )

    intent = service.evaluate_session(record=record)

    assert intent.intent == "candidate_closure"
    assert intent.provider == "resident_orchestrator"
    assert intent.model == "rule-based-brain"


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

    service = BrainDecisionService(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        session_service=_session_service(tmp_path),
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

    service = BrainDecisionService(
        settings=Settings(
            data_dir=str(tmp_path),
            brain_provider_name="openai-compatible",
            brain_provider_base_url="https://provider.example/v1",
            brain_provider_api_key="sk-provider",
            brain_provider_model="minimax-m2.7",
        ),
        session_service=_session_service(tmp_path),
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
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        a_client=FakeAClient(),
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
