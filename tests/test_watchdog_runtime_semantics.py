from __future__ import annotations

from watchdog.services.session_spine import task_state


def test_normalize_task_status_maps_legacy_values_to_prd_canonical_states() -> None:
    assert task_state.normalize_task_status(
        {
            "status": "waiting_human",
            "phase": "approval",
            "pending_approval": True,
        }
    ) == "waiting_for_approval"
    assert task_state.normalize_task_status(
        {
            "status": "waiting_human",
            "phase": "coding",
            "pending_approval": False,
        }
    ) == "waiting_for_direction"
    assert task_state.normalize_task_status(
        {
            "status": "running",
            "phase": "editing_source",
            "pending_approval": True,
        }
    ) == "waiting_for_approval"
    assert task_state.normalize_task_status({"status": "done", "phase": "done"}) == "completed"
    assert task_state.normalize_task_status({"status": "resume_failed", "phase": "recovery"}) == "failed"
    assert task_state.normalize_task_status({"status": "failed"}) == "failed"


def test_normalize_task_phase_maps_legacy_values_to_prd_canonical_phases() -> None:
    assert task_state.normalize_task_phase({"phase": "coding"}) == "editing_source"
    assert task_state.normalize_task_phase({"phase": "approval"}) == "planning"
    assert task_state.normalize_task_phase({"phase": "recovery"}) == "handoff"
    assert task_state.normalize_task_phase({"phase": "done"}) == "summarizing"


def test_validate_action_transition_rejects_missing_guards_and_preserves_source_state() -> None:
    verdict = task_state.validate_action_transition(
        "continue",
        task={
            "status": "waiting_human",
            "phase": "approval",
            "pending_approval": True,
        },
        has_approval=False,
    )

    assert verdict["allowed"] is False
    assert verdict["target_status"] == "waiting_for_approval"
    assert verdict["reason_code"] == "rejected_invalid_state"


def test_validate_action_transition_allows_continue_from_stuck_status() -> None:
    verdict = task_state.validate_action_transition(
        "continue",
        task={
            "status": "stuck",
            "phase": "debugging",
            "pending_approval": False,
        },
    )

    assert verdict["allowed"] is True
    assert verdict["target_status"] == "running"
    assert verdict["reason_code"] == "continue"


def test_failed_task_is_terminal_under_canonical_runtime_semantics() -> None:
    assert task_state.is_terminal_task({"status": "failed", "phase": "debugging"}) is True
