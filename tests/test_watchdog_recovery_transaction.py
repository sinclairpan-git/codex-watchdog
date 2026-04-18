from __future__ import annotations

from pathlib import Path

import pytest

from watchdog.services.session_service.models import RecoveryTransactionRecord
from watchdog.services.session_service.service import SessionService
from watchdog.services.session_service.store import SessionServiceStore


def test_recovery_transaction_persists_intermediate_lineage_and_parent_cooling_states(
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
            "resume_outcome": "new_child_session",
            "session_id": "session:repo-a:child-v9",
        },
        goal_contract_version="goal-v9",
        source_packet_id="packet:handoff-v9",
    )

    recovery_records = service.list_recovery_transactions(
        recovery_transaction_id=recorded.recovery_transaction_id
    )
    assert [record.status for record in recovery_records] == [
        "started",
        "packet_frozen",
        "child_created",
        "lineage_pending",
        "lineage_committed",
        "parent_cooling",
        "completed",
    ]

    lineage_pending = recovery_records[3]
    parent_cooling = recovery_records[5]

    assert lineage_pending.child_session_id == recorded.child_session_id
    assert lineage_pending.lineage_id == recorded.lineage_id
    assert parent_cooling.lineage_id == recorded.lineage_id
    assert parent_cooling.metadata == {"status": "cooled"}


def test_recovery_transaction_rejects_second_active_transaction_for_same_recovery_key(
    tmp_path: Path,
) -> None:
    store = SessionServiceStore(tmp_path / "session_service.json")
    service = SessionService(store)

    store.append_recovery_transaction(
        RecoveryTransactionRecord(
            recovery_transaction_id="recovery-tx:existing",
            recovery_key="session:repo-a|context_critical|critical",
            project_id="repo-a",
            parent_session_id="session:repo-a",
            child_session_id=None,
            source_packet_id="packet:handoff-existing",
            recovery_reason="context_critical",
            failure_family="context_pressure",
            failure_signature="critical",
            status="packet_frozen",
            started_at="2026-04-13T08:00:00Z",
            updated_at="2026-04-13T08:00:01Z",
            correlation_id="corr:recovery:existing",
            idempotency_key="idem:recovery:existing:packet_frozen",
            metadata={"handoff_file": "/tmp/repo-a-existing.handoff.md"},
        )
    )

    with pytest.raises(ValueError, match="active recovery transaction"):
        service.record_recovery_execution(
            project_id="repo-a",
            parent_session_id="session:repo-a",
            parent_native_thread_id="thr_native_1",
            recovery_reason="context_critical",
            failure_family="context_pressure",
            failure_signature="critical",
            handoff={
                "handoff_file": "/tmp/repo-a-next.handoff.md",
                "summary": "retry with same failure signature",
            },
            resume={
                "project_id": "repo-a",
                "status": "running",
                "mode": "resume_or_new_thread",
                "resume_outcome": "new_child_session",
                "session_id": "session:repo-a:child-v9",
            },
        )

    recovery_records = service.list_recovery_transactions(parent_session_id="session:repo-a")
    assert [record.recovery_transaction_id for record in recovery_records] == [
        "recovery-tx:existing"
    ]
    assert service.list_events(event_type="child_session_created") == []
