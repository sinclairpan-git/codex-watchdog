from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from watchdog.services.session_service.models import (
    CONTROLLED_SESSION_EVENT_TYPES,
    RECOVERY_TRANSACTION_STATUSES,
    SESSION_LINEAGE_RELATIONS,
    RecoveryTransactionRecord,
    SessionEventRecord,
    SessionLineageRecord,
)
from watchdog.services.session_service.service import SessionService
from watchdog.services.session_service.store import SessionServiceStore


def test_session_service_models_freeze_canonical_truth_primitives() -> None:
    assert "memory_unavailable_degraded" in CONTROLLED_SESSION_EVENT_TYPES
    assert "memory_conflict_detected" in CONTROLLED_SESSION_EVENT_TYPES
    assert "stage_goal_conflict_detected" in CONTROLLED_SESSION_EVENT_TYPES
    assert "resumes_after_interruption" in SESSION_LINEAGE_RELATIONS
    assert "lineage_pending" in RECOVERY_TRANSACTION_STATUSES

    event = SessionEventRecord(
        event_id="event:stage-goal-conflict",
        project_id="repo-a",
        session_id="session:parent",
        event_type="stage_goal_conflict_detected",
        occurred_at="2026-04-12T00:00:00Z",
        causation_id="fact:goal-mismatch",
        correlation_id="corr:goal-mismatch",
        idempotency_key="idem:event:stage-goal-conflict",
        related_ids={"goal_id": "goal:active"},
        payload={"resolution": "human_handled"},
    )
    lineage = SessionLineageRecord(
        lineage_id="lineage:recovery-1",
        project_id="repo-a",
        parent_session_id="session:parent",
        child_session_id="session:child",
        relation="resumes_after_interruption",
        source_packet_id="packet:handoff-1",
        recovery_reason="remote_compact",
        goal_contract_version="goal-v3",
        recovery_transaction_id="recovery-tx:1",
        committed_at="2026-04-12T00:00:03Z",
        correlation_id="corr:recovery-1",
        idempotency_key="idem:lineage:recovery-1",
    )
    recovery = RecoveryTransactionRecord(
        recovery_transaction_id="recovery-tx:1",
        recovery_key="session:parent|remote_compact|thread-disappeared",
        project_id="repo-a",
        parent_session_id="session:parent",
        child_session_id="session:child",
        source_packet_id="packet:handoff-1",
        recovery_reason="remote_compact",
        failure_family="continuity_failure",
        failure_signature="thread-disappeared",
        status="lineage_pending",
        started_at="2026-04-12T00:00:01Z",
        updated_at="2026-04-12T00:00:03Z",
        correlation_id="corr:recovery-1",
        idempotency_key="idem:recovery:lineage-pending",
    )

    assert event.event_type == "stage_goal_conflict_detected"
    assert lineage.relation == "resumes_after_interruption"
    assert recovery.status == "lineage_pending"

    with pytest.raises(ValidationError, match="unsupported session event type"):
        SessionEventRecord(
            event_id="event:bad",
            project_id="repo-a",
            session_id="session:parent",
            event_type="totally_unsupported_event",
            occurred_at="2026-04-12T00:00:00Z",
            causation_id=None,
            correlation_id="corr:bad",
            idempotency_key="idem:bad",
            payload={},
        )


def test_session_service_store_appends_and_queries_canonical_truth_records(
    tmp_path: Path,
) -> None:
    store = SessionServiceStore(tmp_path / "session_service.json")

    first_event = store.append_event(
        SessionEventRecord(
            event_id="event:memory-unavailable",
            project_id="repo-a",
            session_id="session:parent",
            event_type="memory_unavailable_degraded",
            occurred_at="2026-04-12T00:00:00Z",
            causation_id="memory-hub:offline",
            correlation_id="corr:memory-degraded",
            idempotency_key="idem:event:memory-unavailable",
            related_ids={"memory_scope": "project"},
            payload={"fallback_mode": "reference_only"},
        )
    )
    replayed_event = store.append_event(
        SessionEventRecord(
            event_id="event:memory-unavailable",
            project_id="repo-a",
            session_id="session:parent",
            event_type="memory_unavailable_degraded",
            occurred_at="2026-04-12T00:00:00Z",
            causation_id="memory-hub:offline",
            correlation_id="corr:memory-degraded",
            idempotency_key="idem:event:memory-unavailable",
            related_ids={"memory_scope": "project"},
            payload={"fallback_mode": "reference_only"},
        )
    )
    lineage = store.append_lineage(
        SessionLineageRecord(
            lineage_id="lineage:recovery-1",
            project_id="repo-a",
            parent_session_id="session:parent",
            child_session_id="session:child",
            relation="resumes_after_interruption",
            source_packet_id="packet:handoff-1",
            recovery_reason="remote_compact",
            goal_contract_version="goal-v3",
            recovery_transaction_id="recovery-tx:1",
            committed_at="2026-04-12T00:00:03Z",
            correlation_id="corr:recovery-1",
            idempotency_key="idem:lineage:recovery-1",
        )
    )
    recovery_started = store.append_recovery_transaction(
        RecoveryTransactionRecord(
            recovery_transaction_id="recovery-tx:1",
            recovery_key="session:parent|remote_compact|thread-disappeared",
            project_id="repo-a",
            parent_session_id="session:parent",
            child_session_id=None,
            source_packet_id="packet:handoff-1",
            recovery_reason="remote_compact",
            failure_family="continuity_failure",
            failure_signature="thread-disappeared",
            status="started",
            started_at="2026-04-12T00:00:01Z",
            updated_at="2026-04-12T00:00:01Z",
            correlation_id="corr:recovery-1",
            idempotency_key="idem:recovery:started",
        )
    )
    recovery_lineage_pending = store.append_recovery_transaction(
        RecoveryTransactionRecord(
            recovery_transaction_id="recovery-tx:1",
            recovery_key="session:parent|remote_compact|thread-disappeared",
            project_id="repo-a",
            parent_session_id="session:parent",
            child_session_id="session:child",
            source_packet_id="packet:handoff-1",
            recovery_reason="remote_compact",
            failure_family="continuity_failure",
            failure_signature="thread-disappeared",
            status="lineage_pending",
            started_at="2026-04-12T00:00:01Z",
            updated_at="2026-04-12T00:00:03Z",
            lineage_id="lineage:recovery-1",
            correlation_id="corr:recovery-1",
            idempotency_key="idem:recovery:lineage-pending",
        )
    )

    assert first_event.log_seq == replayed_event.log_seq == 1
    assert lineage.log_seq == 2
    assert recovery_started.log_seq == 3
    assert recovery_lineage_pending.log_seq == 4

    events = store.list_events(
        session_id="session:parent",
        event_type="memory_unavailable_degraded",
        related_id_key="memory_scope",
        related_id_value="project",
    )
    assert [event.event_id for event in events] == ["event:memory-unavailable"]

    lineage_records = store.list_lineage(child_session_id="session:child")
    assert [record.lineage_id for record in lineage_records] == ["lineage:recovery-1"]

    recovery_records = store.list_recovery_transactions(parent_session_id="session:parent")
    assert [record.status for record in recovery_records] == ["started", "lineage_pending"]

    latest = store.get_latest_recovery_transaction("recovery-tx:1")
    assert latest is not None
    assert latest.status == "lineage_pending"
    assert latest.lineage_id == "lineage:recovery-1"


def test_session_service_records_recovery_truth_in_canonical_order(
    tmp_path: Path,
) -> None:
    service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))

    recorded = service.record_recovery_execution(
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
        },
    )

    events = service.list_events(correlation_id=recorded.correlation_id)
    assert [event.event_type for event in events] == [
        "recovery_tx_started",
        "handoff_packet_frozen",
        "child_session_created",
        "lineage_committed",
        "parent_session_closed_or_cooled",
        "recovery_tx_completed",
    ]

    recovery_records = service.list_recovery_transactions(
        recovery_transaction_id=recorded.recovery_transaction_id
    )
    assert [record.status for record in recovery_records] == [
        "started",
        "packet_frozen",
        "child_created",
        "lineage_committed",
        "completed",
    ]

    lineage_records = service.list_lineage(
        recovery_transaction_id=recorded.recovery_transaction_id
    )
    assert len(lineage_records) == 1
    assert lineage_records[0].lineage_id == recorded.lineage_id
    assert lineage_records[0].parent_session_id == "session:repo-a"
    assert lineage_records[0].child_session_id == recorded.child_session_id
    assert lineage_records[0].relation == "resumes_after_interruption"


def test_session_service_records_memory_anomaly_events_with_stable_writers(
    tmp_path: Path,
) -> None:
    service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))

    first = service.record_memory_unavailable_degraded(
        project_id="repo-a",
        session_id="session:repo-a",
        memory_scope="project",
        fallback_mode="reference_only",
        degradation_reason="memory_hub_unreachable",
        causation_id="memory-hub:offline",
        occurred_at="2026-04-12T01:00:00Z",
    )
    replay = service.record_memory_unavailable_degraded(
        project_id="repo-a",
        session_id="session:repo-a",
        memory_scope="project",
        fallback_mode="reference_only",
        degradation_reason="memory_hub_unreachable",
        causation_id="memory-hub:offline",
        occurred_at="2026-04-12T01:00:00Z",
    )
    conflict = service.record_memory_conflict_detected(
        project_id="repo-a",
        session_id="session:repo-a",
        memory_scope="project",
        conflict_reason="goal_contract_version_mismatch",
        resolution="reference_only",
        causation_id="memory-sync:conflict",
        occurred_at="2026-04-12T01:01:00Z",
        related_ids={"goal_contract_version": "goal-v9"},
    )

    events = service.list_events(session_id="session:repo-a")

    assert first.event_id == replay.event_id
    assert first.log_seq == replay.log_seq == 1
    assert first.event_type == "memory_unavailable_degraded"
    assert first.correlation_id.startswith("corr:memory-unavailable:")
    assert first.related_ids == {"memory_scope": "project"}
    assert first.payload == {
        "fallback_mode": "reference_only",
        "degradation_reason": "memory_hub_unreachable",
    }

    assert conflict.event_type == "memory_conflict_detected"
    assert conflict.correlation_id.startswith("corr:memory-conflict:")
    assert conflict.related_ids == {
        "memory_scope": "project",
        "goal_contract_version": "goal-v9",
    }
    assert conflict.payload == {
        "conflict_reason": "goal_contract_version_mismatch",
        "resolution": "reference_only",
    }
    assert [event.event_type for event in events] == [
        "memory_unavailable_degraded",
        "memory_conflict_detected",
    ]
