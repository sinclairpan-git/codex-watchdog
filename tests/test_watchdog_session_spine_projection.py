from __future__ import annotations

from watchdog.services.session_spine.facts import build_fact_records
from watchdog.services.session_spine.projection import (
    build_approval_projections,
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
