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


def _continuation_packet() -> dict[str, object]:
    return {
        "packet_id": "packet:continuation:repo-a:1",
        "packet_version": "continuation-packet/v1",
        "packet_state": "issued",
        "decision_class": "recover_current_branch",
        "continuation_identity": "repo-a:session:repo-a:thr_native_1:recover_current_branch",
        "project_id": "repo-a",
        "session_id": "session:repo-a",
        "native_thread_id": "thr_native_1",
        "route_key": "repo-a:session:repo-a:thr_native_1:recover_current_branch:fact-v9",
        "target_route": {
            "route_kind": "same_thread",
            "target_project_id": "repo-a",
            "target_session_id": "session:repo-a",
            "target_thread_id": "thr_native_1",
            "target_work_item_id": "WI-085",
        },
        "project_total_goal": "把 watchdog 自动推进收口为 model-first continuation governance",
        "branch_goal": "实现 ContinuationPacket 真值对象",
        "current_progress_summary": "已经锁定 markdown 回流口",
        "completed_work": ["T856 control-plane projection complete"],
        "remaining_tasks": ["切换 handoff/resume 到 packet truth"],
        "first_action": "先读取 structured continuation packet。",
        "execution_mode": "resume_or_new_thread",
        "action_ref": "continue_current_branch",
        "action_args": {"resume_target_phase": "editing_source"},
        "expected_next_state": "running",
        "continue_boundary": "只继续当前分支",
        "stop_conditions": ["需要新的人工批准"],
        "operator_boundary": "不要把 markdown 当作 truth。",
        "source_refs": {
            "decision_source": "recovery_guard",
            "goal_contract_version": "goal-v9",
            "authoritative_snapshot_version": "fact-v9",
            "snapshot_epoch": "session-seq:9",
            "decision_trace_ref": "trace:packet:1",
            "lineage_refs": ["recovery-tx:1"],
        },
        "freshness": {
            "generated_at": "2026-04-21T01:20:00Z",
            "expires_at": "2026-04-21T02:20:00Z",
        },
        "dedupe": {
            "dedupe_key": "dedupe:repo-a:packet:1",
            "supersedes_packet_id": None,
        },
        "render_contract_ref": "continuation-packet-markdown/v1",
    }


def test_session_service_models_freeze_canonical_truth_primitives() -> None:
    assert "memory_unavailable_degraded" in CONTROLLED_SESSION_EVENT_TYPES
    assert "memory_conflict_detected" in CONTROLLED_SESSION_EVENT_TYPES
    assert "stage_goal_conflict_detected" in CONTROLLED_SESSION_EVENT_TYPES
    assert "recovery_dispatch_started" in CONTROLLED_SESSION_EVENT_TYPES
    assert "recovery_execution_suppressed" in CONTROLLED_SESSION_EVENT_TYPES
    assert "continuation_gate_evaluated" in CONTROLLED_SESSION_EVENT_TYPES
    assert "continuation_identity_issued" in CONTROLLED_SESSION_EVENT_TYPES
    assert "continuation_identity_consumed" in CONTROLLED_SESSION_EVENT_TYPES
    assert "continuation_identity_invalidated" in CONTROLLED_SESSION_EVENT_TYPES
    assert "branch_switch_token_issued" in CONTROLLED_SESSION_EVENT_TYPES
    assert "branch_switch_token_consumed" in CONTROLLED_SESSION_EVENT_TYPES
    assert "branch_switch_token_invalidated" in CONTROLLED_SESSION_EVENT_TYPES
    assert "continuation_replay_invalidated" in CONTROLLED_SESSION_EVENT_TYPES
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


def test_session_service_store_reuses_cached_snapshot_until_file_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store_path = tmp_path / "session_service.json"
    store = SessionServiceStore(store_path)
    event = store.append_event(
        SessionEventRecord(
            event_id="event:cached-read",
            project_id="repo-a",
            session_id="session:repo-a",
            event_type="decision_proposed",
            occurred_at="2026-04-16T01:00:00Z",
            correlation_id="corr:cache",
            idempotency_key="idem:cached-read",
            payload={"step": "cached"},
        )
    )

    original_read_text = Path.read_text
    read_calls = 0

    def counting_read_text(self: Path, *args, **kwargs):
        nonlocal read_calls
        if self == store_path:
            read_calls += 1
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)

    assert store.list_events(session_id="session:repo-a")[0].event_id == event.event_id
    assert store.list_events(event_type="decision_proposed")[0].event_id == event.event_id
    assert read_calls == 0

    store_path.write_text(original_read_text(store_path, encoding="utf-8") + "\n", encoding="utf-8")

    assert store.list_events(session_id="session:repo-a")[0].event_id == event.event_id
    assert read_calls == 1


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
            "resume_outcome": "new_child_session",
            "session_id": "session:repo-a:child-v9",
        },
    )

    events = service.list_events(correlation_id=recorded.correlation_id)
    assert [event.event_type for event in events] == [
        "recovery_tx_started",
        "handoff_packet_frozen",
        "continuation_identity_issued",
        "child_session_created",
        "lineage_committed",
        "parent_session_closed_or_cooled",
        "recovery_tx_completed",
        "continuation_identity_consumed",
    ]
    assert events[0].related_ids["native_thread_id"] == "thr_native_1"
    assert events[1].related_ids["native_thread_id"] == "thr_native_1"
    assert events[5].related_ids["native_thread_id"] == "thr_native_1"
    assert events[7].related_ids["continuation_identity"].startswith(
        "repo-a:session:repo-a:thr_native_1"
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

    lineage_records = service.list_lineage(
        recovery_transaction_id=recorded.recovery_transaction_id
    )
    assert len(lineage_records) == 1
    assert lineage_records[0].lineage_id == recorded.lineage_id
    assert lineage_records[0].parent_session_id == "session:repo-a"
    assert lineage_records[0].child_session_id == recorded.child_session_id
    assert lineage_records[0].relation == "resumes_after_interruption"


def test_session_service_records_recovery_packet_lineage_and_identity_transitions(
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
            "thread_id": "thr_native_1",
        },
        resume_outcome="same_thread_resume",
        goal_contract_version="goal-v9",
        source_packet_id="packet:handoff-v9",
        continuation_identity="repo-a:session:repo-a:thr_native_1:recover_current_branch",
        route_key="repo-a:session:repo-a:thr_native_1:recover_current_branch:fact-v9",
        authoritative_snapshot_version="fact-v9",
        snapshot_epoch="session-seq:9",
    )

    events = service.list_events(correlation_id=recorded.correlation_id)

    assert [event.event_type for event in events] == [
        "recovery_tx_started",
        "handoff_packet_frozen",
        "continuation_identity_issued",
        "continuation_identity_consumed",
        "recovery_tx_completed",
    ]
    assert events[1].payload["decision_source"] == "recovery_guard"
    assert events[1].payload["decision_class"] == "recover_current_branch"
    assert events[1].payload["authoritative_snapshot_version"] == "fact-v9"
    assert events[1].payload["snapshot_epoch"] == "session-seq:9"
    assert events[1].payload["goal_contract_version"] == "goal-v9"
    assert events[1].related_ids["continuation_identity"] == (
        "repo-a:session:repo-a:thr_native_1:recover_current_branch"
    )
    assert events[1].related_ids["route_key"] == (
        "repo-a:session:repo-a:thr_native_1:recover_current_branch:fact-v9"
    )
    assert events[2].related_ids["source_packet_id"] == "packet:handoff-v9"
    assert events[3].payload["state"] == "consumed"


def test_record_recovery_execution_freezes_structured_continuation_packet_and_hashes(
    tmp_path: Path,
) -> None:
    service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    packet = _continuation_packet()

    recorded = service.record_recovery_execution(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        parent_native_thread_id="thr_native_1",
        recovery_reason="context_critical",
        failure_family="context_pressure",
        failure_signature="critical",
        handoff={
            "handoff_file": "/tmp/repo-a.handoff.md",
            "summary": "# Continuation packet\npacket_id=packet:continuation:repo-a:1\n",
            "continuation_packet": packet,
        },
        resume={
            "project_id": "repo-a",
            "status": "running",
            "mode": "resume_or_new_thread",
            "thread_id": "thr_native_1",
            "source_packet_id": packet["packet_id"],
        },
        resume_outcome="same_thread_resume",
        goal_contract_version="goal-v9",
        source_packet_id="packet:handoff-v9",
        continuation_identity="repo-a:session:repo-a:thr_native_1:recover_current_branch",
        route_key="repo-a:session:repo-a:thr_native_1:recover_current_branch:fact-v9",
        authoritative_snapshot_version="fact-v9",
        snapshot_epoch="session-seq:9",
    )

    events = service.list_events(correlation_id=recorded.correlation_id)
    frozen = next(event for event in events if event.event_type == "handoff_packet_frozen")

    assert frozen.related_ids["source_packet_id"] == packet["packet_id"]
    assert frozen.payload["continuation_packet"]["packet_id"] == packet["packet_id"]
    assert frozen.payload["packet_hash"]
    assert frozen.payload["rendered_markdown_hash"]
    assert frozen.payload["rendered_from_packet_id"] == packet["packet_id"]


def test_record_recovery_execution_persists_normalized_goal_contract_version_to_lineage(
    tmp_path: Path,
) -> None:
    service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    packet = _continuation_packet()

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
            "continuation_packet": packet,
        },
        resume={
            "project_id": "repo-a",
            "status": "running",
            "mode": "resume_or_new_thread",
            "resume_outcome": "new_child_session",
            "session_id": "session:repo-a:child-v9",
            "source_packet_id": packet["packet_id"],
        },
        goal_contract_version="goal-contract:unknown",
        source_packet_id="packet:handoff-v9",
    )

    lineage_records = service.list_lineage(
        recovery_transaction_id=recorded.recovery_transaction_id
    )
    assert len(lineage_records) == 1
    assert lineage_records[0].goal_contract_version == "goal-v9"

    recovery_records = service.list_recovery_transactions(
        recovery_transaction_id=recorded.recovery_transaction_id
    )
    lineage_pending = next(record for record in recovery_records if record.status == "lineage_pending")
    lineage_committed = next(
        record for record in recovery_records if record.status == "lineage_committed"
    )
    assert lineage_pending.metadata["goal_contract_version"] == "goal-v9"
    assert lineage_committed.metadata["goal_contract_version"] == "goal-v9"

    lineage_events = service.list_events(correlation_id=recorded.correlation_id)
    committed = next(event for event in lineage_events if event.event_type == "lineage_committed")
    assert committed.payload["goal_contract_version"] == "goal-v9"


@pytest.mark.parametrize(
    ("resume_payload", "expected_child_session_id"),
    [
        (
            {
                "project_id": "repo-a",
                "status": "running",
                "mode": "resume_or_new_thread",
                "resume_outcome": "new_child_session",
                "session_id": "session:repo-a:child-v9",
            },
            "session:repo-a:child-v9",
        ),
        (
            {
                "project_id": "repo-a",
                "status": "running",
                "mode": "resume_or_new_thread",
                "resume_outcome": "new_child_session",
                "child_session_id": "session:repo-a:thr_child_v9",
                "thread_id": "thr_child_v9",
                "native_thread_id": "thr_child_v9",
            },
            "session:repo-a:thr_child_v9",
        ),
    ],
)
def test_session_service_resolves_legacy_and_current_new_child_resume_shapes_equally(
    tmp_path: Path,
    resume_payload: dict[str, str],
    expected_child_session_id: str,
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
        resume=resume_payload,
    )

    assert recorded.child_session_id == expected_child_session_id
    recovery_records = service.list_recovery_transactions(
        recovery_transaction_id=recorded.recovery_transaction_id
    )
    assert recovery_records[-1].status == "completed"
    assert recovery_records[-1].child_session_id == expected_child_session_id
    assert recovery_records[-1].metadata["resume_outcome"] == "new_child_session"
    lineage_records = service.list_lineage(
        recovery_transaction_id=recorded.recovery_transaction_id
    )
    assert len(lineage_records) == 1
    assert lineage_records[0].child_session_id == expected_child_session_id


def test_session_service_same_thread_resume_does_not_create_lineage(
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
            "thread_id": "thr_native_1",
        },
        resume_outcome="same_thread_resume",
    )

    events = service.list_events(correlation_id=recorded.correlation_id)
    assert [event.event_type for event in events] == [
        "recovery_tx_started",
        "handoff_packet_frozen",
        "continuation_identity_issued",
        "continuation_identity_consumed",
        "recovery_tx_completed",
    ]
    assert events[0].related_ids["native_thread_id"] == "thr_native_1"
    assert events[1].related_ids["native_thread_id"] == "thr_native_1"
    assert events[2].related_ids["continuation_identity"].startswith(
        "repo-a:session:repo-a:thr_native_1"
    )

    recovery_records = service.list_recovery_transactions(
        recovery_transaction_id=recorded.recovery_transaction_id
    )
    assert [record.status for record in recovery_records] == [
        "started",
        "packet_frozen",
        "completed",
    ]
    assert recovery_records[-1].metadata == {
        "resume_error": None,
        "resume_outcome": "same_thread_resume",
    }
    assert service.list_lineage(
        recovery_transaction_id=recorded.recovery_transaction_id
    ) == []
    assert recorded.child_session_id is None
    assert recorded.lineage_id is None


def test_session_service_recovery_transaction_identity_ignores_handoff_summary_text(
    tmp_path: Path,
) -> None:
    first = SessionService(SessionServiceStore(tmp_path / "session_service_a.json"))
    second = SessionService(SessionServiceStore(tmp_path / "session_service_b.json"))

    recorded_first = first.record_recovery_execution(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        parent_native_thread_id="thr_native_1",
        recovery_reason="context_critical",
        failure_family="context_pressure",
        failure_signature="critical",
        handoff={
            "handoff_file": "/tmp/repo-a.handoff.md",
            "summary": "first rendered handoff summary",
        },
    )
    recorded_second = second.record_recovery_execution(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        parent_native_thread_id="thr_native_1",
        recovery_reason="context_critical",
        failure_family="context_pressure",
        failure_signature="critical",
        handoff={
            "handoff_file": "/tmp/repo-a.handoff.md",
            "summary": "second rendered handoff summary",
        },
    )

    assert recorded_first.recovery_transaction_id == recorded_second.recovery_transaction_id
    assert recorded_first.correlation_id == recorded_second.correlation_id
    assert recorded_first.source_packet_id == recorded_second.source_packet_id


def test_session_service_same_thread_resume_prefers_explicit_native_thread_id(
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
            "thread_id": "session:repo-a",
            "native_thread_id": "thr_native_1",
        },
    )

    recovery_records = service.list_recovery_transactions(
        recovery_transaction_id=recorded.recovery_transaction_id
    )
    assert recovery_records[-1].metadata == {
        "resume_error": None,
        "resume_outcome": "same_thread_resume",
    }
    assert service.list_lineage(
        recovery_transaction_id=recorded.recovery_transaction_id
    ) == []
    assert recorded.child_session_id is None
    assert recorded.lineage_id is None


def test_session_service_same_thread_resume_does_not_treat_stable_session_thread_as_child(
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
            "thread_id": "session:repo-a",
        },
    )

    recovery_records = service.list_recovery_transactions(
        recovery_transaction_id=recorded.recovery_transaction_id
    )
    assert recovery_records[-1].metadata == {
        "resume_error": None,
        "resume_outcome": "same_thread_resume",
    }
    assert service.list_lineage(
        recovery_transaction_id=recorded.recovery_transaction_id
    ) == []
    assert recorded.child_session_id is None
    assert recorded.lineage_id is None


def test_session_service_child_session_fallback_id_prefers_explicit_native_thread_id(
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
            "thread_id": "session:repo-a",
            "native_thread_id": "thr_child_2",
        },
        resume_outcome="new_child_session",
    )

    assert recorded.child_session_id == "session:repo-a:thr_child_2"
    child_events = service.list_events(correlation_id=recorded.correlation_id)
    assert child_events[3].event_type == "child_session_created"
    assert child_events[3].related_ids["native_thread_id"] == "thr_child_2"
    assert child_events[4].event_type == "lineage_committed"
    assert child_events[4].related_ids["native_thread_id"] == "thr_child_2"


def test_session_service_failed_retryable_recovery_invalidates_continuation_identity(
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
        resume_error="resume_call_failed",
        continuation_identity="repo-a:session:repo-a:thr_native_1:recover_current_branch",
        route_key="repo-a:session:repo-a:thr_native_1:recover_current_branch:fact-v9",
        authoritative_snapshot_version="fact-v9",
        snapshot_epoch="session-seq:9",
        goal_contract_version="goal-v9",
    )

    events = service.list_events(correlation_id=recorded.correlation_id)
    assert [event.event_type for event in events] == [
        "recovery_tx_started",
        "handoff_packet_frozen",
        "continuation_identity_issued",
        "continuation_identity_invalidated",
        "continuation_replay_invalidated",
        "recovery_tx_completed",
    ]
    assert events[3].payload["state"] == "invalidated"
    assert events[3].payload["suppression_reason"] == "resume_call_failed"
    assert events[3].related_ids["source_packet_id"] == recorded.source_packet_id
    assert events[4].payload["invalidation_reason"] == "resume_call_failed"
    assert events[4].related_ids == {
        "continuation_identity": "repo-a:session:repo-a:thr_native_1:recover_current_branch",
        "route_key": "repo-a:session:repo-a:thr_native_1:recover_current_branch:fact-v9",
        "source_packet_id": recorded.source_packet_id,
    }

    recovery_records = service.list_recovery_transactions(
        recovery_transaction_id=recorded.recovery_transaction_id
    )
    assert [record.status for record in recovery_records] == [
        "started",
        "packet_frozen",
        "failed_retryable",
    ]


def test_session_service_child_session_fallback_id_accepts_stable_session_thread_when_native_missing(
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
            "thread_id": "session:repo-a:child-v9",
        },
    )

    assert recorded.child_session_id == "session:repo-a:child-v9"


def test_session_service_record_event_once_accepts_legacy_subset_payload_during_schema_expansion(
    tmp_path: Path,
) -> None:
    service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))

    original = service.record_event(
        event_type="approval_requested",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:approval:legacy",
        causation_id="decision:legacy",
        related_ids={"approval_id": "appr_001", "decision_id": "decision:legacy"},
        payload={
            "requested_action": "execute_recovery",
            "decision_options": ["approve", "reject", "execute_action"],
            "fact_snapshot_version": "fact-v7",
            "policy_version": "policy-v1",
        },
    )

    replayed = service.record_event_once(
        event_type="approval_requested",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:approval:legacy",
        causation_id="decision:legacy",
        related_ids={"approval_id": "appr_001", "decision_id": "decision:legacy"},
        payload={
            "requested_action": "execute_recovery",
            "requested_action_args": {"mode": "safe"},
            "decision_options": ["approve", "reject", "execute_action"],
            "fact_snapshot_version": "fact-v7",
            "goal_contract_version": "goal-v1",
            "policy_version": "policy-v1",
        },
    )

    assert replayed.event_id == original.event_id
    assert len(
        service.list_events(
            session_id="session:repo-a",
            event_type="approval_requested",
        )
    ) == 1


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
        "reason_code": "outage",
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
        "reason_code": "conflict",
    }
    assert [event.event_type for event in events] == [
        "memory_unavailable_degraded",
        "memory_conflict_detected",
    ]


def test_session_service_records_approval_expired_with_stable_writer(
    tmp_path: Path,
) -> None:
    service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))

    first = service.record_approval_expired(
        project_id="repo-a",
        session_id="session:repo-a",
        approval_id="approval:123",
        decision_id="decision:456",
        envelope_id="approval-envelope:789",
        native_thread_id="thr_native_1",
        requested_action="system.shell.exec",
        expiration_reason="timeout_elapsed",
        causation_id="approval-timeout:tick-1",
        occurred_at="2026-04-12T01:05:00Z",
    )
    replay = service.record_approval_expired(
        project_id="repo-a",
        session_id="session:repo-a",
        approval_id="approval:123",
        decision_id="decision:456",
        envelope_id="approval-envelope:789",
        native_thread_id="thr_native_1",
        requested_action="system.shell.exec",
        expiration_reason="timeout_elapsed",
        causation_id="approval-timeout:tick-1",
        occurred_at="2026-04-12T01:05:00Z",
    )

    events = service.list_events(session_id="session:repo-a")

    assert first.event_id == replay.event_id
    assert first.log_seq == replay.log_seq == 1
    assert first.event_type == "approval_expired"
    assert first.correlation_id == "corr:approval:approval:123"
    assert first.related_ids == {
        "approval_id": "approval:123",
        "decision_id": "decision:456",
        "envelope_id": "approval-envelope:789",
        "native_thread_id": "thr_native_1",
    }
    assert first.payload == {
        "approval_status": "expired",
        "requested_action": "system.shell.exec",
        "expiration_reason": "timeout_elapsed",
    }
    assert [event.event_type for event in events] == ["approval_expired"]


def test_session_service_records_continuation_governance_events_with_stable_writers(
    tmp_path: Path,
) -> None:
    service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))

    gate = service.record_continuation_gate_verdict(
        project_id="repo-a",
        session_id="session:repo-a",
        gate_kind="eligibility",
        gate_status="suppressed",
        decision_source="rules_fallback",
        decision_class="recover_current_branch",
        action_ref="execute_recovery",
        authoritative_snapshot_version="fact-v9",
        snapshot_epoch="session-seq:9",
        goal_contract_version="goal-v9",
        suppression_reason="pending_approval",
        continuation_identity="repo-a:session:repo-a:thr_native_1:recover_current_branch",
        route_key="repo-a:session:repo-a:thr_native_1:recover_current_branch:fact-v9",
        branch_switch_token="branch-switch:repo-a:86:fact-v9",
        lineage_refs=["trace:continuation-1", "goal-contract:goal-v9"],
    )
    replayed_gate = service.record_continuation_gate_verdict(
        project_id="repo-a",
        session_id="session:repo-a",
        gate_kind="eligibility",
        gate_status="suppressed",
        decision_source="rules_fallback",
        decision_class="recover_current_branch",
        action_ref="execute_recovery",
        authoritative_snapshot_version="fact-v9",
        snapshot_epoch="session-seq:9",
        goal_contract_version="goal-v9",
        suppression_reason="pending_approval",
        continuation_identity="repo-a:session:repo-a:thr_native_1:recover_current_branch",
        route_key="repo-a:session:repo-a:thr_native_1:recover_current_branch:fact-v9",
        branch_switch_token="branch-switch:repo-a:86:fact-v9",
        lineage_refs=["trace:continuation-1", "goal-contract:goal-v9"],
    )
    issued = service.record_continuation_identity_state(
        project_id="repo-a",
        session_id="session:repo-a",
        continuation_identity="repo-a:session:repo-a:thr_native_1:recover_current_branch",
        state="issued",
        decision_source="recovery_guard",
        decision_class="recover_current_branch",
        action_ref="execute_recovery",
        authoritative_snapshot_version="fact-v9",
        snapshot_epoch="session-seq:9",
        goal_contract_version="goal-v9",
        route_key="repo-a:session:repo-a:thr_native_1:recover_current_branch:fact-v9",
        source_packet_id="packet:handoff-v9",
        lineage_refs=["trace:continuation-1"],
    )
    consumed = service.record_continuation_identity_state(
        project_id="repo-a",
        session_id="session:repo-a",
        continuation_identity="repo-a:session:repo-a:thr_native_1:recover_current_branch",
        state="consumed",
        decision_source="recovery_guard",
        decision_class="recover_current_branch",
        action_ref="execute_recovery",
        authoritative_snapshot_version="fact-v9",
        snapshot_epoch="session-seq:9",
        goal_contract_version="goal-v9",
        route_key="repo-a:session:repo-a:thr_native_1:recover_current_branch:fact-v9",
        source_packet_id="packet:handoff-v9",
        lineage_refs=["trace:continuation-1"],
        consumed_at="2026-04-20T08:00:03Z",
    )
    token_invalidated = service.record_branch_switch_token_state(
        project_id="repo-a",
        session_id="session:repo-a",
        branch_switch_token="branch-switch:repo-a:86:fact-v9",
        state="invalidated",
        decision_source="rules_fallback",
        decision_class="branch_complete_switch",
        authoritative_snapshot_version="fact-v9",
        snapshot_epoch="session-seq:9",
        goal_contract_version="goal-v9",
        suppression_reason="project_not_active",
        lineage_refs=["trace:continuation-1"],
    )
    replay_invalidated = service.record_continuation_replay_invalidated(
        project_id="repo-a",
        session_id="session:repo-a",
        decision_source="recovery_guard",
        decision_class="recover_current_branch",
        authoritative_snapshot_version="fact-v9",
        snapshot_epoch="session-seq:9",
        goal_contract_version="goal-v9",
        continuation_identity="repo-a:session:repo-a:thr_native_1:recover_current_branch",
        route_key="repo-a:session:repo-a:thr_native_1:recover_current_branch:fact-v9",
        source_packet_id="packet:handoff-v9",
        invalidation_reason="project_not_active",
        lineage_refs=["trace:continuation-1", "packet:handoff-v9"],
    )

    events = service.list_events(session_id="session:repo-a")

    assert replayed_gate.event_id == gate.event_id
    assert gate.log_seq == replayed_gate.log_seq == 1
    assert [event.event_type for event in events] == [
        "continuation_gate_evaluated",
        "continuation_identity_issued",
        "continuation_identity_consumed",
        "branch_switch_token_invalidated",
        "continuation_replay_invalidated",
    ]
    assert gate.payload == {
        "gate_kind": "eligibility",
        "gate_status": "suppressed",
        "decision_source": "rules_fallback",
        "decision_class": "recover_current_branch",
        "action_ref": "execute_recovery",
        "authoritative_snapshot_version": "fact-v9",
        "snapshot_epoch": "session-seq:9",
        "goal_contract_version": "goal-v9",
        "suppression_reason": "pending_approval",
        "lineage_refs": ["trace:continuation-1", "goal-contract:goal-v9"],
    }
    assert gate.related_ids == {
        "continuation_identity": "repo-a:session:repo-a:thr_native_1:recover_current_branch",
        "route_key": "repo-a:session:repo-a:thr_native_1:recover_current_branch:fact-v9",
        "branch_switch_token": "branch-switch:repo-a:86:fact-v9",
    }
    assert issued.payload["state"] == "issued"
    assert issued.related_ids["source_packet_id"] == "packet:handoff-v9"
    assert consumed.payload["state"] == "consumed"
    assert consumed.payload["consumed_at"] == "2026-04-20T08:00:03Z"
    assert token_invalidated.payload["suppression_reason"] == "project_not_active"
    assert replay_invalidated.payload == {
        "decision_source": "recovery_guard",
        "decision_class": "recover_current_branch",
        "authoritative_snapshot_version": "fact-v9",
        "snapshot_epoch": "session-seq:9",
        "goal_contract_version": "goal-v9",
        "invalidation_reason": "project_not_active",
        "lineage_refs": ["trace:continuation-1", "packet:handoff-v9"],
    }
    assert replay_invalidated.related_ids == {
        "continuation_identity": "repo-a:session:repo-a:thr_native_1:recover_current_branch",
        "route_key": "repo-a:session:repo-a:thr_native_1:recover_current_branch:fact-v9",
        "source_packet_id": "packet:handoff-v9",
    }
