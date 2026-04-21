from __future__ import annotations

from unittest.mock import patch

from watchdog.services.session_service.models import SessionEventRecord
from watchdog.services.session_spine.facts import build_fact_records
from watchdog.services.session_spine.projection import (
    build_approval_projections,
    build_session_service_fact_records,
    build_session_projection,
    build_task_progress_view,
    stable_thread_id_for_project,
)


def test_projection_builds_awaiting_approval_session_and_pending_approval_fact() -> None:
    raw_task = {
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
    approvals = [
        {
            "approval_id": "appr_001",
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "risk_level": "L2",
            "command": "uv run pytest",
            "reason": "need test verification",
            "alternative": "skip tests",
            "status": "pending",
            "requested_at": "2026-04-05T05:21:00Z",
        }
    ]

    facts = build_fact_records(project_id="repo-a", task=raw_task, approvals=approvals)
    session = build_session_projection(project_id="repo-a", task=raw_task, approvals=approvals, facts=facts)
    progress = build_task_progress_view(project_id="repo-a", task=raw_task, facts=facts)
    projected_approvals = build_approval_projections(
        project_id="repo-a",
        native_thread_id="thr_native_1",
        approvals=approvals,
    )

    assert session.thread_id == stable_thread_id_for_project("repo-a")
    assert session.native_thread_id == "thr_native_1"
    assert session.session_state == "awaiting_approval"
    assert session.attention_state == "needs_human"
    assert progress.blocker_fact_codes == ["approval_pending", "awaiting_human_direction"]
    assert [fact.fact_code for fact in facts] == ["approval_pending", "awaiting_human_direction"]
    assert projected_approvals[0].thread_id == stable_thread_id_for_project("repo-a")
    assert projected_approvals[0].native_thread_id == "thr_native_1"


def test_projection_ignores_stale_pending_approval_flag_without_actionable_approvals() -> None:
    raw_task = {
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

    facts = build_fact_records(project_id="repo-a", task=raw_task, approvals=[])
    session = build_session_projection(project_id="repo-a", task=raw_task, approvals=[], facts=facts)
    progress = build_task_progress_view(project_id="repo-a", task=raw_task, facts=facts)

    assert facts == []
    assert session.session_state == "active"
    assert session.attention_state == "normal"
    assert session.pending_approval_count == 0
    assert progress.blocker_fact_codes == []


def test_projection_marks_done_session_complete_and_omits_continue_intent() -> None:
    raw_task = {
        "project_id": "repo-a",
        "thread_id": "thr_native_done",
        "status": "waiting_human",
        "phase": "done",
        "pending_approval": False,
        "last_summary": "task complete",
        "files_touched": ["src/example.py"],
        "context_pressure": "low",
        "stuck_level": 2,
        "failure_count": 3,
        "last_progress_at": "2026-04-05T05:20:00Z",
    }

    facts = build_fact_records(project_id="repo-a", task=raw_task, approvals=[])
    session = build_session_projection(project_id="repo-a", task=raw_task, approvals=[], facts=facts)
    progress = build_task_progress_view(project_id="repo-a", task=raw_task, facts=facts)

    assert [fact.fact_code for fact in facts] == ["task_completed"]
    assert session.session_state == "active"
    assert session.attention_state == "normal"
    assert "continue_session" not in session.available_intents
    assert progress.primary_fact_codes == ["task_completed"]
    assert progress.blocker_fact_codes == []


def test_projection_builds_goal_context_into_task_progress_view() -> None:
    raw_task = {
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

    facts = build_fact_records(project_id="repo-a", task=raw_task, approvals=[])
    progress = build_task_progress_view(
        project_id="repo-a",
        task=raw_task,
        facts=facts,
        goal_context={
            "goal_contract_version": "goal-v2",
            "current_phase_goal": "继续把 recovery 自动重入收口到 child continuation",
            "last_user_instruction": "继续把 recovery 自动重入收口到 child continuation",
        },
    )

    assert progress.goal_contract_version == "goal-v2"
    assert progress.current_phase_goal == "继续把 recovery 自动重入收口到 child continuation"
    assert progress.last_user_instruction == "继续把 recovery 自动重入收口到 child continuation"


def test_projection_builds_recovery_related_facts_from_stuck_and_critical_pressure() -> None:
    raw_task = {
        "project_id": "repo-a",
        "thread_id": "thr_native_2",
        "status": "running",
        "phase": "editing_source",
        "pending_approval": False,
        "last_summary": "stalled on repeated failures",
        "files_touched": ["src/example.py", "tests/test_example.py"],
        "context_pressure": "critical",
        "stuck_level": 2,
        "failure_count": 3,
        "last_progress_at": "2026-04-05T04:00:00Z",
    }

    facts = build_fact_records(project_id="repo-a", task=raw_task, approvals=[])
    session = build_session_projection(project_id="repo-a", task=raw_task, approvals=[], facts=facts)
    progress = build_task_progress_view(project_id="repo-a", task=raw_task, facts=facts)

    assert [fact.fact_code for fact in facts] == [
        "stuck_no_progress",
        "repeat_failure",
        "context_critical",
        "recovery_available",
    ]
    assert session.session_state == "blocked"
    assert session.attention_state == "critical"
    assert progress.primary_fact_codes == [
        "stuck_no_progress",
        "repeat_failure",
        "context_critical",
        "recovery_available",
    ]


def test_projection_suppresses_recovery_facts_while_handoff_is_in_progress() -> None:
    raw_task = {
        "project_id": "repo-a",
        "thread_id": "thr_native_2",
        "status": "handoff_in_progress",
        "phase": "handoff",
        "pending_approval": False,
        "last_summary": "handoff drafted",
        "files_touched": ["src/watchdog/services/session_spine/facts.py"],
        "context_pressure": "critical",
        "stuck_level": 4,
        "failure_count": 3,
        "last_progress_at": "2026-04-05T04:00:00Z",
    }

    facts = build_fact_records(project_id="repo-a", task=raw_task, approvals=[])
    session = build_session_projection(project_id="repo-a", task=raw_task, approvals=[], facts=facts)

    fact_codes = {fact.fact_code for fact in facts}
    assert fact_codes.isdisjoint(
        {"stuck_no_progress", "repeat_failure", "context_critical", "recovery_available"}
    )
    assert "execute_recovery" not in session.available_intents


def test_projection_suppresses_recovery_facts_while_session_is_resuming() -> None:
    raw_task = {
        "project_id": "repo-a",
        "thread_id": "thr_native_2",
        "status": "resuming",
        "phase": "editing_source",
        "pending_approval": False,
        "last_summary": "resuming after overflow",
        "files_touched": ["src/watchdog/services/session_spine/recovery.py"],
        "context_pressure": "critical",
        "stuck_level": 2,
        "failure_count": 3,
        "last_progress_at": "2026-04-05T04:00:00Z",
    }

    facts = build_fact_records(project_id="repo-a", task=raw_task, approvals=[])
    session = build_session_projection(project_id="repo-a", task=raw_task, approvals=[], facts=facts)

    fact_codes = {fact.fact_code for fact in facts}
    assert fact_codes.isdisjoint(
        {"stuck_no_progress", "repeat_failure", "context_critical", "recovery_available"}
    )
    assert "execute_recovery" not in session.available_intents


def test_projection_suppresses_recovery_facts_while_session_is_paused() -> None:
    raw_task = {
        "project_id": "repo-a",
        "thread_id": "thr_native_2",
        "status": "paused",
        "phase": "editing_source",
        "pending_approval": False,
        "last_summary": "paused by operator",
        "files_touched": ["src/watchdog/services/session_spine/facts.py"],
        "context_pressure": "critical",
        "stuck_level": 2,
        "failure_count": 3,
        "last_progress_at": "2026-04-05T04:00:00Z",
    }

    facts = build_fact_records(project_id="repo-a", task=raw_task, approvals=[])
    session = build_session_projection(project_id="repo-a", task=raw_task, approvals=[], facts=facts)

    fact_codes = {fact.fact_code for fact in facts}
    assert fact_codes.isdisjoint(
        {"stuck_no_progress", "repeat_failure", "context_critical", "recovery_available"}
    )
    assert "execute_recovery" not in session.available_intents


def test_projection_blocks_autonomous_continuation_when_project_is_not_active() -> None:
    raw_task = {
        "project_id": "repo-a",
        "thread_id": "thr_native_2",
        "status": "running",
        "phase": "editing_source",
        "project_execution_state": "completed",
        "pending_approval": False,
        "last_summary": "branch work already done",
        "files_touched": ["src/watchdog/services/session_spine/facts.py"],
        "context_pressure": "critical",
        "stuck_level": 2,
        "failure_count": 3,
        "last_progress_at": "2026-04-05T04:00:00Z",
    }

    facts = build_fact_records(project_id="repo-a", task=raw_task, approvals=[])
    session = build_session_projection(project_id="repo-a", task=raw_task, approvals=[], facts=facts)

    assert [fact.fact_code for fact in facts] == ["project_not_active"]
    assert "continue_session" not in session.available_intents
    assert "execute_recovery" not in session.available_intents


def test_projection_surfaces_control_link_error_without_raw_task() -> None:
    facts = build_fact_records(
        project_id="repo-a",
        task=None,
        approvals=[],
        link_error="A-Control-Agent unavailable",
    )
    session = build_session_projection(project_id="repo-a", task=None, approvals=[], facts=facts)

    assert session.thread_id == stable_thread_id_for_project("repo-a")
    assert session.native_thread_id is None
    assert session.session_state == "unavailable"
    assert session.attention_state == "unreachable"
    assert [fact.fact_code for fact in facts] == ["control_link_error"]


def test_projection_facts_fallback_observed_at_when_approval_timestamps_are_missing() -> None:
    approvals = [
        {
            "approval_id": "appr_001",
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "pending",
        }
    ]

    with patch("watchdog.services.session_spine.facts._now_iso", return_value="2026-04-06T00:00:00Z"):
        facts = build_fact_records(
            project_id="repo-a",
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "pending_approval": True,
                "last_progress_at": None,
            },
            approvals=approvals,
        )

    assert [fact.fact_code for fact in facts] == ["approval_pending", "awaiting_human_direction"]
    assert [fact.observed_at for fact in facts] == [
        "2026-04-06T00:00:00Z",
        "2026-04-06T00:00:00Z",
    ]


def test_projection_falls_back_to_canonical_approval_fields() -> None:
    approvals = [
        {
            "approval_id": "appr_001",
            "project_id": "repo-a",
            "thread_id": "session:repo-a",
            "native_thread_id": "thr_native_1",
            "risk_class": "human_gate",
            "requested_action": "execute_recovery",
            "summary": "manual approval required",
            "status": "pending",
            "created_at": "2026-04-05T05:21:00Z",
        }
    ]

    projected = build_approval_projections(
        project_id="repo-a",
        native_thread_id="thr_native_1",
        approvals=approvals,
    )

    assert projected[0].risk_level == "human_gate"
    assert projected[0].command == "execute_recovery"
    assert projected[0].reason == "manual approval required"
    assert projected[0].requested_at == "2026-04-05T05:21:00Z"


def test_projection_builds_current_memory_anomaly_facts_from_session_service_events() -> None:
    events = [
        SessionEventRecord(
            event_id="evt-memory-1",
            project_id="repo-a",
            session_id="session:repo-a",
            event_type="memory_unavailable_degraded",
            occurred_at="2026-04-12T01:00:00Z",
            causation_id="memory-hub:offline",
            correlation_id="corr:memory-unavailable:1",
            idempotency_key="idem:memory-unavailable:1",
            related_ids={"memory_scope": "project"},
            payload={
                "fallback_mode": "reference_only",
                "degradation_reason": "memory_hub_unreachable",
            },
            log_seq=1,
        ),
        SessionEventRecord(
            event_id="evt-memory-2",
            project_id="repo-a",
            session_id="session:repo-a",
            event_type="memory_conflict_detected",
            occurred_at="2026-04-12T01:01:00Z",
            causation_id="memory-sync:conflict",
            correlation_id="corr:memory-conflict:1",
            idempotency_key="idem:memory-conflict:1",
            related_ids={
                "memory_scope": "project",
                "goal_contract_version": "goal-v9",
            },
            payload={
                "conflict_reason": "goal_contract_version_mismatch",
                "resolution": "reference_only",
            },
            log_seq=2,
        ),
    ]

    facts = build_session_service_fact_records(project_id="repo-a", events=events)

    assert [fact.fact_code for fact in facts] == [
        "memory_unavailable_degraded",
        "memory_conflict_detected",
    ]
    assert facts[0].related_ids == {"memory_scope": "project"}
    assert facts[1].related_ids == {
        "memory_scope": "project",
        "goal_contract_version": "goal-v9",
    }


def test_projection_builds_human_override_and_notification_facts_from_session_service_events() -> None:
    events = [
        SessionEventRecord(
            event_id="evt-override-1",
            project_id="repo-a",
            session_id="session:repo-a",
            event_type="human_override_recorded",
            occurred_at="2026-04-12T01:02:00Z",
            causation_id="approval-response:test",
            correlation_id="corr:override:approval-response:test",
            idempotency_key="idem:override:1",
            related_ids={
                "approval_id": "approval:test",
                "decision_id": "decision:test",
                "response_id": "approval-response:test",
                "envelope_id": "approval-envelope:test",
            },
            payload={
                "response_action": "approve",
                "approval_status": "approved",
                "operator": "operator-1",
                "note": "looks safe",
                "requested_action": "execute_recovery",
                "execution_status": "completed",
                "execution_effect": "handoff_triggered",
            },
            log_seq=1,
        ),
        SessionEventRecord(
            event_id="evt-notification-1",
            project_id="repo-a",
            session_id="session:repo-a",
            event_type="notification_receipt_recorded",
            occurred_at="2026-04-12T01:03:00Z",
            causation_id="notification-envelope:test",
            correlation_id="corr:notification:notification-envelope:test:receipt:receipt:test",
            idempotency_key="idem:notification-receipt:1",
            related_ids={
                "envelope_id": "notification-envelope:test",
                "notification_kind": "approval_result",
                "receipt_id": "receipt:test",
            },
            payload={
                "delivery_status": "delivered",
                "delivery_attempt": 1,
                "receipt_id": "receipt:test",
                "received_at": "2026-04-12T01:03:30Z",
            },
            log_seq=2,
        ),
    ]

    facts = build_session_service_fact_records(project_id="repo-a", events=events)

    assert [fact.fact_code for fact in facts] == [
        "human_override_recorded",
        "notification_receipt_recorded",
    ]
    assert facts[0].related_ids == {
        "approval_id": "approval:test",
        "decision_id": "decision:test",
        "response_id": "approval-response:test",
        "envelope_id": "approval-envelope:test",
    }
    assert facts[1].related_ids == {
        "envelope_id": "notification-envelope:test",
        "notification_kind": "approval_result",
        "receipt_id": "receipt:test",
    }


def test_projection_humanizes_recovery_suppression_fact_detail_from_session_service_events() -> None:
    expectations = {
        "reentry_without_newer_progress": "等待新进展",
        "recovery_in_flight": "恢复进行中",
        "cooldown_window_active": "恢复冷却中",
    }

    for index, (reason, label) in enumerate(expectations.items(), start=1):
        events = [
            SessionEventRecord(
                event_id=f"evt-recovery-suppressed-{index}",
                project_id="repo-a",
                session_id="session:repo-a",
                event_type="recovery_execution_suppressed",
                occurred_at=f"2026-04-12T01:0{index}:00Z",
                causation_id=f"recovery:tx:{index}",
                correlation_id=f"corr:recovery-suppressed:{index}",
                idempotency_key=f"idem:recovery-suppressed:{index}",
                related_ids={"recovery_transaction_id": f"recovery-tx:{index}"},
                payload={
                    "suppression_reason": reason,
                    "suppression_source": "resident_orchestrator",
                },
                log_seq=index,
            )
        ]

        facts = build_session_service_fact_records(project_id="repo-a", events=events)

        assert len(facts) == 1
        assert facts[0].fact_code == "recovery_execution_suppressed"
        assert facts[0].detail == (
            f"suppression_reason={label} suppression_source=resident_orchestrator"
        )
