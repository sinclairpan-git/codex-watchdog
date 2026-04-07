from __future__ import annotations

from datetime import datetime, timedelta, timezone

from a_control_agent.services.codex.client import fingerprint_input_text
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


def test_task_store_updates_last_local_manual_activity_only_for_non_service_echo(tmp_path) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    echoed_at = (now + timedelta(seconds=30)).isoformat().replace("+00:00", "Z")
    manual_at = (now + timedelta(seconds=45)).isoformat().replace("+00:00", "Z")

    store = TaskStore(tmp_path / "tasks.json", service_input_match_window_seconds=120.0)
    store.upsert_native_thread(
        {
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "cwd": str(tmp_path),
            "status": "running",
            "phase": "coding",
        }
    )

    store.apply_steer(
        "repo-a",
        message="continue coding",
        source="watchdog",
        reason="openclaw_continue_session",
    )
    echoed = store.upsert_native_thread(
        {
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "cwd": str(tmp_path),
            "status": "running",
            "phase": "coding",
            "last_substantive_user_input_at": echoed_at,
            "last_substantive_user_input_fingerprint": fingerprint_input_text("continue coding"),
        }
    )
    manual = store.upsert_native_thread(
        {
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "cwd": str(tmp_path),
            "status": "running",
            "phase": "coding",
            "last_substantive_user_input_at": manual_at,
            "last_substantive_user_input_fingerprint": fingerprint_input_text(
                "不要把我正在本地看的动态再往飞书发。"
            ),
        }
    )

    assert echoed.get("last_local_manual_activity_at") is None
    assert manual["last_local_manual_activity_at"] == manual_at
