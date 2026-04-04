from __future__ import annotations

from datetime import datetime, timedelta, timezone

from a_control_agent.storage.tasks_store import TaskStore
from watchdog.services.status_analyzer.stuck import (
    StuckThresholds,
    bump_failure_if_same_signature,
    evaluate_stuck,
)


def test_evaluate_stuck_triggers_after_8min() -> None:
    old = (datetime.now(timezone.utc) - timedelta(minutes=9)).isoformat()
    task = {"stuck_level": 0, "last_progress_at": old}
    ev = evaluate_stuck(task, thresholds=StuckThresholds(soft_steer_after_minutes=8.0))
    assert ev["should_steer"] is True
    assert ev["next_stuck_level"] == 2


def test_evaluate_stuck_no_trigger_recent() -> None:
    recent = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    task = {"stuck_level": 0, "last_progress_at": recent}
    ev = evaluate_stuck(task)
    assert ev["should_steer"] is False


def test_bump_failure_same_sig(tmp_path) -> None:
    store = TaskStore(tmp_path / "tasks.json")
    store.upsert_from_create("p", {"project_id": "p", "cwd": "/"})
    store.record_error_repeat("p", "E1")
    store.record_error_repeat("p", "E1")
    r = store.get("p")
    assert r is not None
    assert r["failure_count"] == 2


def test_bump_failure_new_sig(tmp_path) -> None:
    c, repeat = bump_failure_if_same_signature("a", "b", 3)
    assert c == 1
    assert repeat is False
    c2, r2 = bump_failure_if_same_signature("x", "x", 2)
    assert c2 == 3
    assert r2 is True
