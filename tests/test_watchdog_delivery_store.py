from __future__ import annotations

import threading
import time
from pathlib import Path

from watchdog.services.delivery.store import DeliveryOutboxRecord, DeliveryOutboxStore


def _record(*, note: str, attempt: int) -> DeliveryOutboxRecord:
    return DeliveryOutboxRecord(
        envelope_id="decision-envelope:test",
        envelope_type="decision",
        correlation_id="corr:test",
        session_id="session:test",
        project_id="project:test",
        policy_version="policy-v1",
        fact_snapshot_version="fact-v1",
        idempotency_key="idemp:test",
        audit_ref="audit:test",
        created_at="2026-04-10T00:00:00Z",
        updated_at="2026-04-10T00:00:00Z",
        outbox_seq=1,
        delivery_attempt=attempt,
        operator_notes=[note],
        envelope_payload={"envelope_type": "decision"},
    )


def test_delivery_outbox_store_serializes_concurrent_updates_across_instances(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store_path = tmp_path / "delivery_outbox.json"
    DeliveryOutboxStore(store_path).update_delivery_record(_record(note="seed", attempt=0))

    original_write_text = Path.write_text
    shared_tmp_path = store_path.with_suffix(".tmp")

    def slow_write_text(self: Path, data: str, *args, **kwargs) -> int:
        if self == shared_tmp_path:
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
        store = DeliveryOutboxStore(store_path)
        for attempt in range(5):
            try:
                store.update_delivery_record(_record(note=f"{label}-{attempt}", attempt=attempt))
            except Exception as exc:  # pragma: no cover - captured for assertion below
                errors.append(f"{type(exc).__name__}: {exc}")
                return

    left = threading.Thread(target=writer, args=("left",))
    right = threading.Thread(target=writer, args=("right",))
    left.start()
    right.start()
    left.join()
    right.join()

    assert errors == []
    reparsed = DeliveryOutboxStore(store_path).list_records()
    assert [record.envelope_id for record in reparsed] == ["decision-envelope:test"]
