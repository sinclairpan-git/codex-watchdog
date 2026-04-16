from __future__ import annotations

from pathlib import Path

from watchdog.contracts.session_spine.models import SessionProjection, TaskProgressView
from watchdog.services.brain.service import BrainDecisionService
from watchdog.services.memory_hub.models import ContextQualitySnapshot
from watchdog.services.memory_hub.service import MemoryHubService
from watchdog.services.session_service.service import SessionService
from watchdog.services.session_service.store import SessionServiceStore
from watchdog.services.session_spine.recovery import perform_recovery_execution
from watchdog.services.session_spine.store import PersistedSessionRecord
from watchdog.settings import Settings


def _session_service(tmp_path: Path) -> SessionService:
    return SessionService(SessionServiceStore(tmp_path / "session_service.json"))


def test_memory_conflict_event_captures_reason_code_and_source_ref(
    tmp_path: Path,
) -> None:
    service = _session_service(tmp_path)

    event = service.record_memory_conflict_detected(
        project_id="repo-a",
        session_id="session:repo-a",
        memory_scope="project",
        conflict_reason="resident_goal_contract_mismatch",
        resolution="reference_only",
        related_ids={"source_ref": "skill:shared:python"},
        occurred_at="2026-04-13T10:02:00Z",
    )

    assert event.payload.get("reason_code") == "conflict"
    assert event.related_ids.get("source_ref") == "skill:shared:python"


def test_memory_security_block_event_records_dangerous_verdict_without_hot_path_override(
    tmp_path: Path,
) -> None:
    service = _session_service(tmp_path)

    event = service.record_memory_unavailable_degraded(
        project_id="repo-a",
        session_id="session:repo-a",
        memory_scope="project",
        fallback_mode="session_service_runtime_snapshot",
        degradation_reason="security_verdict_failed",
        related_ids={"source_ref": "archive:repo-a:artifact-17"},
        occurred_at="2026-04-13T10:03:00Z",
    )

    assert event.payload.get("reason_code") == "security_blocked"
    assert event.payload.get("security_verdict") == "dangerous"
    assert event.payload.get("override_mode") is None


def test_memory_hub_conflict_runtime_context_never_overrides_goal_contract_truth() -> None:
    service = MemoryHubService()

    payload = service.build_runtime_advisory_context(
        query="continue repo-a",
        project_id="repo-a",
        session_id="session:repo-a",
        limit=2,
        quality=ContextQualitySnapshot(
            key_fact_recall=0.6,
            irrelevant_summary_precision=0.8,
            token_budget_utilization=0.7,
            expansion_miss_rate=0.2,
        ),
        session_truth={
            "current_phase_goal": "ship canonical runtime semantics",
            "status": "running",
        },
        memory_goal_candidate="rewrite the release gate",
    )

    assert payload["goal_context"]["source"] == "session_service"
    assert payload["goal_context"]["current_phase_goal"] == "ship canonical runtime semantics"
    assert payload["degradation"]["reason_code"] == "memory_conflict_detected"


def test_brain_service_records_memory_conflict_without_overriding_decision_intent(
    tmp_path: Path,
) -> None:
    class FakeConflictMemoryHub:
        def build_runtime_advisory_context(self, **_: object) -> dict[str, object]:
            return {
                "packet_inputs": {
                    "refs": [
                        {
                            "ref_id": "ref-1",
                            "summary": "rewrite the release gate",
                            "source_ref": "archive:repo-a:goal-1",
                        }
                    ]
                },
                "skills": [],
                "precedence": "session_service",
                "degradation": {
                    "reason_code": "memory_conflict_detected",
                    "resolution": "session_service_truth",
                },
            }

    session_service = _session_service(tmp_path)
    service = BrainDecisionService(
        memory_hub_service=FakeConflictMemoryHub(),
        session_service=session_service,
    )
    record = PersistedSessionRecord(
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
            summary="editing files",
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

    intent = service.evaluate_session(record=record)

    conflicts = session_service.list_events(
        session_id="session:repo-a",
        event_type="memory_conflict_detected",
    )
    assert intent.intent == "observe_only"
    assert len(conflicts) == 1
    assert conflicts[0].related_ids["source_ref"] == "archive:repo-a:goal-1"
    assert conflicts[0].payload["reason_code"] == "conflict"


def test_recovery_execution_records_memory_unavailable_degraded_and_continues(
    tmp_path: Path,
) -> None:
    class FakeClient:
        def get_envelope(self, project_id: str) -> dict[str, object]:
            return {
                "success": True,
                "data": {
                    "project_id": project_id,
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
            }

        def trigger_handoff(self, project_id: str, *, reason: str) -> dict[str, object]:
            return {
                "success": True,
                "data": {
                    "handoff_file": f"/tmp/{project_id}.handoff.md",
                    "summary": "handoff",
                },
            }

        def trigger_resume(
            self,
            project_id: str,
            *,
            mode: str,
            handoff_summary: str,
        ) -> dict[str, object]:
            return {
                "success": True,
                "data": {"project_id": project_id, "status": "running", "mode": mode},
            }

    class UnavailableMemoryHub:
        def build_runtime_advisory_context(self, **_: object) -> dict[str, object]:
            raise RuntimeError("memory hub unavailable")

    session_service = _session_service(tmp_path)

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=False,
        ),
        client=FakeClient(),
        session_service=session_service,
        memory_hub_service=UnavailableMemoryHub(),
    )

    degraded = session_service.list_events(
        session_id="session:repo-a",
        event_type="memory_unavailable_degraded",
    )
    assert outcome.action == "handoff_triggered"
    assert outcome.memory_advisory_context is None
    assert len(degraded) == 1
    assert degraded[0].payload["reason_code"] == "outage"
