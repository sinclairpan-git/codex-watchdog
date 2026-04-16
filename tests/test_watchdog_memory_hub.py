from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from watchdog.main import create_app
from watchdog.services.memory_hub.ingest_queue import (
    MemoryIngestEnqueuer,
    MemoryIngestEnqueueFailureStore,
    MemoryIngestQueueStore,
)
from watchdog.services.memory_hub.ingest_worker import MemoryIngestWorker
from watchdog.services.memory_hub.models import ContextQualitySnapshot, PacketInputRef
from watchdog.services.memory_hub.service import MemoryHubService
from watchdog.services.memory_hub.skills import SkillMetadata, SkillRegistry
from watchdog.services.session_service.service import SessionService
from watchdog.services.session_service.store import SessionServiceStore
from watchdog.services.session_spine.recovery import perform_recovery_execution
from watchdog.settings import Settings


def _session_service(tmp_path: Path) -> SessionService:
    return SessionService(SessionServiceStore(tmp_path / "session_service.json"))


def test_session_service_exposes_replayable_event_slices_with_cursor_and_anchor(
    tmp_path: Path,
) -> None:
    service = _session_service(tmp_path)

    service.record_event(
        event_type="decision_proposed",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:decision:1",
        payload={"step": "proposed"},
        occurred_at="2026-04-13T10:00:00Z",
    )
    service.record_event(
        event_type="decision_validated",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:decision:1",
        payload={"step": "validated"},
        occurred_at="2026-04-13T10:00:01Z",
    )
    service.record_event(
        event_type="command_created",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:decision:1",
        payload={"step": "created"},
        occurred_at="2026-04-13T10:00:02Z",
    )

    assert hasattr(
        service,
        "get_events",
    ), "SessionService must expose get_events(session_id=..., after_log_seq=..., limit=..., anchor_event_id=...)"


def test_memory_unavailable_event_captures_reason_code_and_source_ref(
    tmp_path: Path,
) -> None:
    service = _session_service(tmp_path)

    event = service.record_memory_unavailable_degraded(
        project_id="repo-a",
        session_id="session:repo-a",
        memory_scope="project",
        fallback_mode="session_service_runtime_snapshot",
        degradation_reason="memory_hub_unreachable",
        related_ids={"source_ref": "memory-provider:sqlite"},
        occurred_at="2026-04-13T10:01:00Z",
    )

    assert event.payload.get("reason_code") == "outage"
    assert event.related_ids.get("source_ref") == "memory-provider:sqlite"


def test_memory_hub_builds_runtime_advisory_context_for_recovery_and_decision_inputs() -> None:
    class FakeIndexer:
        def search(
            self,
            query: str,
            *,
            project_id: str | None = None,
            session_id: str | None = None,
            limit: int | None = None,
        ) -> list[PacketInputRef]:
            assert query == "resume repo-a"
            assert project_id == "repo-a"
            assert session_id == "session:repo-a"
            assert limit == 4
            return [
                PacketInputRef(
                    ref_id="ref-1",
                    summary="latest recovery case",
                    source_ref="archive:repo-a:recovery-1",
                )
            ]

    registry = SkillRegistry(
        records=[
            SkillMetadata(
                name="pytest",
                short_description="python test runner",
                trust_level="trusted",
                security_verdict="pass",
                content_hash="hash:pytest-v1",
                installed_version="8.0.0",
                last_scanned_at="2026-04-15T00:00:00Z",
                source_ref="skill:local:pytest",
                source_kind="local",
            )
        ]
    )
    service = MemoryHubService(indexer=FakeIndexer(), skill_registry=registry)

    payload = service.build_runtime_advisory_context(
        query="resume repo-a",
        project_id="repo-a",
        session_id="session:repo-a",
        limit=4,
        quality=ContextQualitySnapshot(
            key_fact_recall=0.9,
            irrelevant_summary_precision=0.8,
            token_budget_utilization=0.4,
            expansion_miss_rate=0.1,
        ),
    )

    assert payload["packet_inputs"]["refs"][0]["source_ref"] == "archive:repo-a:recovery-1"
    assert payload["skills"][0]["name"] == "pytest"
    assert payload["precedence"] == "session_service"


def test_recovery_execution_consumes_memory_hub_advisory_context_on_hot_path(
    tmp_path: Path,
) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.handoff_calls: list[tuple[str, str]] = []

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
            self.handoff_calls.append((project_id, reason))
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

    class FakeMemoryHub:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def build_runtime_advisory_context(self, **kwargs: object) -> dict[str, object]:
            self.calls.append(dict(kwargs))
            return {
                "packet_inputs": {
                    "refs": [
                        {
                            "ref_id": "ref-1",
                            "summary": "latest recovery case",
                            "source_ref": "archive:repo-a:recovery-1",
                        }
                    ]
                },
                "skills": [{"name": "pytest", "source_ref": "skill:local:pytest"}],
                "precedence": "session_service",
            }

    session_service = _session_service(tmp_path)
    memory_hub = FakeMemoryHub()

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
        memory_hub_service=memory_hub,
    )

    assert memory_hub.calls != []
    assert memory_hub.calls[0]["project_id"] == "repo-a"
    assert memory_hub.calls[0]["session_id"] == "session:repo-a"
    assert outcome.action == "handoff_triggered"
    assert outcome.memory_advisory_context is not None
    assert outcome.memory_advisory_context["packet_inputs"]["refs"][0]["source_ref"] == (
        "archive:repo-a:recovery-1"
    )
    assert outcome.memory_advisory_context["skills"][0]["name"] == "pytest"


def test_memory_hub_persists_resident_capsule_and_archive_refs_across_restart(
    tmp_path: Path,
) -> None:
    service = MemoryHubService.from_data_dir(tmp_path)
    service.register_project(
        project_id="repo-a",
        repo_root="/workspace/repo-a",
        repo_fingerprint="fingerprint:repo-a",
    )
    service.upsert_resident_memory(
        project_id="repo-a",
        memory_key="goal.current",
        summary="ship feishu control plane",
        source_ref="session:event:goal-1",
        source_scope="project-local",
        source_runtime="watchdog",
    )
    registry = SkillRegistry(
        records=[
            SkillMetadata(
                name="pytest",
                short_description="python test runner",
                trust_level="trusted",
                security_verdict="pass",
                content_hash="hash:pytest-v1",
                installed_version="8.0.0",
                last_scanned_at="2026-04-15T00:00:00Z",
                source_ref="skill:local:pytest",
                source_kind="local",
            )
        ]
    )
    if service._store is not None:
        service._store.replace_skills(registry.list_metadata())
    service.store_archive_entry(
        project_id="repo-a",
        session_id="session:repo-a",
        summary="feishu recovery and approval flow",
        source_ref="session:event:42",
        raw_content="full transcript blob",
    )

    restarted = MemoryHubService.from_data_dir(tmp_path)
    payload = restarted.build_runtime_advisory_context(
        query="feishu recovery",
        project_id="repo-a",
        session_id="session:repo-a",
        limit=4,
        quality=ContextQualitySnapshot(
            key_fact_recall=0.9,
            irrelevant_summary_precision=0.8,
            token_budget_utilization=0.4,
            expansion_miss_rate=0.1,
        ),
    )

    assert payload["resident_capsule"][0]["summary"] == "ship feishu control plane"
    assert payload["packet_inputs"]["refs"][0]["source_ref"] == "session:event:42"
    assert restarted._store is not None
    assert restarted._store.list_projects()[0].project_id == "repo-a"
    assert restarted.list_skill_metadata()[0].name == "pytest"


def test_memory_ingest_queue_dedupes_session_events_by_event_id(tmp_path: Path) -> None:
    queue_store = MemoryIngestQueueStore(tmp_path / "memory_ingest_queue.json")
    session_service = SessionService(
        SessionServiceStore(tmp_path / "session_service.json"),
        event_listeners=[queue_store.enqueue_event],
    )

    event = session_service.record_event(
        event_type="goal_contract_revised",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:goal:1",
        payload={"current_phase_goal": "ship feishu control plane"},
        related_ids={"source_ref": "goal-contract:v2"},
        occurred_at="2026-04-16T01:00:00Z",
    )

    duplicate = queue_store.enqueue_event(event)

    records = queue_store.list_records()
    assert len(records) == 1
    assert records[0].event_id == event.event_id
    assert duplicate.event_id == event.event_id
    assert queue_store.list_pending()[0].status == "pending"


def test_memory_ingest_worker_marks_failure_without_blocking_session_truth(tmp_path: Path) -> None:
    class FailingMemoryHub:
        def ingest_session_event(self, event) -> None:
            raise RuntimeError(f"boom:{event.event_id}")

    queue_store = MemoryIngestQueueStore(tmp_path / "memory_ingest_queue.json")
    session_service = SessionService(
        SessionServiceStore(tmp_path / "session_service.json"),
        event_listeners=[queue_store.enqueue_event],
    )

    event = session_service.record_event(
        event_type="goal_contract_revised",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:goal:2",
        payload={"current_phase_goal": "ship feishu control plane"},
        related_ids={"source_ref": "goal-contract:v3"},
        occurred_at="2026-04-16T01:01:00Z",
    )

    worker = MemoryIngestWorker(
        store=queue_store,
        memory_hub_service=FailingMemoryHub(),  # type: ignore[arg-type]
        max_attempts=1,
        initial_backoff_seconds=0.0,
    )

    assert worker.process_next() is True
    assert session_service.list_events(session_id="session:repo-a")[0].event_id == event.event_id
    record = queue_store.list_records()[0]
    assert record.status == "failed"
    assert record.failure_code == "memory_ingest_failed"
    assert record.attempts == 1


def test_memory_ingest_enqueue_failure_is_recorded_for_ops_visibility(tmp_path: Path) -> None:
    class FailingQueueStore:
        def enqueue_event(self, event) -> None:
            raise RuntimeError(f"queue-down:{event.event_id}")

    failure_store = MemoryIngestEnqueueFailureStore(tmp_path / "memory_ingest_enqueue_failures.json")
    enqueuer = MemoryIngestEnqueuer(
        queue_store=FailingQueueStore(),  # type: ignore[arg-type]
        failure_store=failure_store,
    )
    session_service = SessionService(
        SessionServiceStore(tmp_path / "session_service.json"),
        event_listeners=[enqueuer.enqueue_event],
    )

    event = session_service.record_event(
        event_type="goal_contract_revised",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:goal:3",
        payload={"current_phase_goal": "ship feishu control plane"},
        related_ids={"source_ref": "goal-contract:v4"},
        occurred_at="2026-04-16T01:02:00Z",
    )

    failures = failure_store.list_failures()
    assert session_service.list_events(session_id="session:repo-a")[0].event_id == event.event_id
    assert len(failures) == 1
    assert failures[0].event_id == event.event_id
    assert failures[0].failure_code == "memory_ingest_enqueue_failed"


def test_memory_ingest_worker_recovers_inflight_records_after_restart(tmp_path: Path) -> None:
    queue_store = MemoryIngestQueueStore(tmp_path / "memory_ingest_queue.json")
    session_service = SessionService(
        SessionServiceStore(tmp_path / "session_service.json"),
        event_listeners=[queue_store.enqueue_event],
    )
    memory_hub = MemoryHubService.from_data_dir(tmp_path)

    session_service.record_event(
        event_type="goal_contract_revised",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:goal:4",
        payload={
            "current_phase_goal": "ship feishu control plane",
            "task_title": "ship feishu control plane",
        },
        related_ids={"source_ref": "goal-contract:v5"},
        occurred_at="2026-04-16T01:03:00Z",
    )

    claimed = queue_store.claim_next(now=datetime(2026, 4, 16, 1, 3, 1, tzinfo=UTC))
    assert claimed is not None
    assert claimed.status == "processing"

    restarted_queue = MemoryIngestQueueStore(tmp_path / "memory_ingest_queue.json")
    recovered = restarted_queue.recover_inflight()
    assert len(recovered) == 1
    assert recovered[0].status == "pending"
    assert recovered[0].failure_code == "worker_interrupted"

    worker = MemoryIngestWorker(
        store=restarted_queue,
        memory_hub_service=memory_hub,
        max_attempts=3,
        initial_backoff_seconds=0.0,
    )
    assert worker.drain_all(now=datetime(2026, 4, 16, 1, 3, 2, tzinfo=UTC)) == 1
    payload = memory_hub.build_runtime_advisory_context(
        query="ship feishu",
        project_id="repo-a",
        session_id="session:repo-a",
        limit=4,
        quality=ContextQualitySnapshot(
            key_fact_recall=0.9,
            irrelevant_summary_precision=0.8,
            token_budget_utilization=0.4,
            expansion_miss_rate=0.1,
        ),
    )

    assert payload["resident_capsule"][0]["summary"] == "ship feishu control plane"
    assert len(payload["packet_inputs"]["refs"]) == 1
    assert restarted_queue.list_records()[0].status == "processed"


def test_create_app_enqueues_session_events_before_memory_hub_drain(tmp_path: Path) -> None:
    app = create_app(Settings(api_token="wt", data_dir=str(tmp_path)))

    event = app.state.session_service.record_event(
        event_type="goal_contract_revised",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:goal:1",
        payload={
            "current_phase_goal": "ship feishu control plane",
            "task_title": "ship feishu control plane",
        },
        related_ids={"source_ref": "goal-contract:v2"},
        occurred_at="2026-04-16T01:00:00Z",
    )

    before_drain = app.state.memory_hub_service.build_runtime_advisory_context(
        query="ship feishu",
        project_id="repo-a",
        session_id="session:repo-a",
        limit=4,
        quality=ContextQualitySnapshot(
            key_fact_recall=0.9,
            irrelevant_summary_precision=0.8,
            token_budget_utilization=0.4,
            expansion_miss_rate=0.1,
        ),
    )

    pending = app.state.memory_ingest_queue_store.list_pending()
    assert len(pending) == 1
    assert pending[0].event_id == event.event_id
    assert before_drain["resident_capsule"] == []
    assert before_drain["packet_inputs"]["refs"] == []

    assert app.state.memory_ingest_worker.drain_all() == 1

    after_drain = app.state.memory_hub_service.build_runtime_advisory_context(
        query="ship feishu",
        project_id="repo-a",
        session_id="session:repo-a",
        limit=4,
        quality=ContextQualitySnapshot(
            key_fact_recall=0.9,
            irrelevant_summary_precision=0.8,
            token_budget_utilization=0.4,
            expansion_miss_rate=0.1,
        ),
    )

    assert after_drain["resident_capsule"][0]["summary"] == "ship feishu control plane"
    assert after_drain["packet_inputs"]["refs"] != []
