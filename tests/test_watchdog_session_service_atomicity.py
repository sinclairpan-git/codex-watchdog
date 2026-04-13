from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from watchdog.services.session_service.models import SessionEventRecord
from watchdog.services.session_service.store import SessionServiceStore


def _event(event_id: str, *, idempotency_key: str | None = None) -> SessionEventRecord:
    return SessionEventRecord(
        event_id=event_id,
        project_id="repo-a",
        session_id="session:repo-a",
        event_type="decision_proposed",
        occurred_at="2026-04-12T00:00:00Z",
        causation_id="policy:tick",
        correlation_id="corr:policy-1",
        idempotency_key=idempotency_key or f"idem:{event_id}",
        payload={"decision": "continue"},
    )


def test_session_service_store_serializes_concurrent_appends_across_instances(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store_path = tmp_path / "session_service.json"
    SessionServiceStore(store_path).append_event(_event("event:seed"))

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
        store = SessionServiceStore(store_path)
        for attempt in range(5):
            try:
                store.append_event(_event(f"event:{label}:{attempt}"))
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
    events = SessionServiceStore(store_path).list_events(session_id="session:repo-a")
    assert len(events) == 11
    assert [event.log_seq for event in events] == list(range(1, 12))


def test_session_service_store_fails_closed_when_lock_acquisition_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store_path = tmp_path / "session_service.json"
    store = SessionServiceStore(store_path)

    def fail_flock(_fd: int, _operation: int) -> None:
        raise OSError("lock unavailable")

    monkeypatch.setattr("watchdog.services.session_service.store.fcntl.flock", fail_flock)

    with pytest.raises(OSError, match="lock unavailable"):
        store.append_event(_event("event:lock-failure"))

    raw = json.loads(store_path.read_text(encoding="utf-8"))
    assert raw["events"] == []


def test_session_service_store_keeps_previous_snapshot_when_atomic_replace_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store_path = tmp_path / "session_service.json"
    store = SessionServiceStore(store_path)
    store.append_event(_event("event:seed"))

    original_replace = Path.replace

    def fail_replace(self: Path, target: Path) -> Path:
        if self.parent == store_path.parent and self.name.startswith(f"{store_path.name}."):
            raise OSError("atomic replace failed")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(OSError, match="atomic replace failed"):
        store.append_event(_event("event:replace-failure"))

    reparsed = SessionServiceStore(store_path).list_events(session_id="session:repo-a")
    assert [event.event_id for event in reparsed] == ["event:seed"]
    assert list(tmp_path.glob("*.tmp")) == []
