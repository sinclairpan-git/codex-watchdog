from __future__ import annotations

import json
from pathlib import Path

import httpx

from watchdog.main import create_app
from watchdog.contracts.session_spine.models import FactRecord
from watchdog.contracts.session_spine.models import SessionProjection, TaskProgressView
from watchdog.services.brain.models import DecisionIntent
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
                provider_request_id="chatcmpl-trace-1",
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
