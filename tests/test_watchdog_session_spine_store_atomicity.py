from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from watchdog.contracts.session_spine.models import SessionProjection, TaskProgressView
from watchdog.services.session_spine.store import SessionSpineStore


def _put_record(store: SessionSpineStore, *, project_id: str, summary: str) -> None:
    store.put(
        project_id=project_id,
        session=SessionProjection(
            project_id=project_id,
            thread_id=f"session:{project_id}",
            native_thread_id=f"thr:{project_id}",
            session_state="active",
            activity_phase="editing_source",
            attention_state="normal",
            headline=summary,
            pending_approval_count=0,
            available_intents=["continue"],
        ),
        progress=TaskProgressView(
            project_id=project_id,
            thread_id=f"session:{project_id}",
            native_thread_id=f"thr:{project_id}",
            activity_phase="editing_source",
            summary=summary,
            files_touched=[f"src/{project_id}.py"],
            context_pressure="low",
            stuck_level=0,
            primary_fact_codes=[],
            blocker_fact_codes=[],
            last_progress_at="2026-04-17T00:00:00Z",
        ),
        facts=[],
        approval_queue=[],
        last_refreshed_at="2026-04-17T00:00:00Z",
    )


def test_session_spine_store_serializes_concurrent_puts_across_instances(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store_path = tmp_path / "session_spine.json"
    _put_record(SessionSpineStore(store_path), project_id="seed", summary="seed")

    original_write_text = Path.write_text

    def slow_write_text(self: Path, data: str, *args, **kwargs) -> int:
        if self.parent == store_path.parent and self.name.startswith(f"{store_path.name}."):
            encoding = kwargs.get("encoding", "utf-8")
            midpoint = len(data) // 2
            with self.open("w", encoding=encoding) as handle:
                handle.write(data[:midpoint])
                handle.flush()
                time.sleep(0.01)
                handle.write(data[midpoint:])
                handle.flush()
            return len(data)
        return original_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", slow_write_text)

    errors: list[str] = []

    def writer(label: str) -> None:
        store = SessionSpineStore(store_path)
        for attempt in range(5):
            try:
                _put_record(
                    store,
                    project_id=f"{label}-{attempt}",
                    summary=f"{label}-{attempt}",
                )
            except Exception as exc:  # pragma: no cover - captured for assertion
                errors.append(f"{type(exc).__name__}: {exc}")
                return

    left = threading.Thread(target=writer, args=("left",))
    right = threading.Thread(target=writer, args=("right",))
    left.start()
    right.start()
    left.join()
    right.join()

    assert errors == []
    records = SessionSpineStore(store_path).list_records()
    assert len(records) == 11
    assert sorted(record.project_id for record in records) == [
        "left-0",
        "left-1",
        "left-2",
        "left-3",
        "left-4",
        "right-0",
        "right-1",
        "right-2",
        "right-3",
        "right-4",
        "seed",
    ]


def test_session_spine_store_fails_closed_when_lock_acquisition_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store_path = tmp_path / "session_spine.json"
    store = SessionSpineStore(store_path)

    def fail_flock(_fd: int, _operation: int) -> None:
        raise OSError("lock unavailable")

    monkeypatch.setattr("watchdog.services.session_spine.store.fcntl.flock", fail_flock)

    with pytest.raises(OSError, match="lock unavailable"):
        _put_record(store, project_id="repo-a", summary="repo-a")

    raw = json.loads(store_path.read_text(encoding="utf-8"))
    assert raw["sessions"] == {}


def test_session_spine_store_keeps_previous_snapshot_when_atomic_replace_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store_path = tmp_path / "session_spine.json"
    store = SessionSpineStore(store_path)
    _put_record(store, project_id="seed", summary="seed")

    original_replace = Path.replace

    def fail_replace(self: Path, target: Path) -> Path:
        if self.parent == store_path.parent and self.name.startswith(f"{store_path.name}."):
            raise OSError("atomic replace failed")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(OSError, match="atomic replace failed"):
        _put_record(store, project_id="repo-a", summary="repo-a")

    reparsed = SessionSpineStore(store_path).list_records()
    assert [record.project_id for record in reparsed] == ["seed"]
    assert list(tmp_path.glob("*.tmp")) == []
