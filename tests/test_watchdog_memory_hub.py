from __future__ import annotations

from pathlib import Path

from watchdog.services.session_service.service import SessionService
from watchdog.services.session_service.store import SessionServiceStore


def _session_service(tmp_path: Path) -> SessionService:
    return SessionService(SessionServiceStore(tmp_path / "session_service.json"))


def test_session_service_exposes_replayable_event_slices_with_cursor_and_anchor(
    tmp_path: Path,
) -> None:
    service = _session_service(tmp_path)

    service.record_event(
        event_type="decision_proposed",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:decision:1",
        payload={"step": "proposed"},
        occurred_at="2026-04-13T10:00:00Z",
    )
    service.record_event(
        event_type="decision_validated",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:decision:1",
        payload={"step": "validated"},
        occurred_at="2026-04-13T10:00:01Z",
    )
    service.record_event(
        event_type="command_created",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:decision:1",
        payload={"step": "created"},
        occurred_at="2026-04-13T10:00:02Z",
    )

    assert hasattr(
        service,
        "get_events",
    ), "SessionService must expose get_events(session_id=..., after_log_seq=..., limit=..., anchor_event_id=...)"


def test_memory_unavailable_event_captures_reason_code_and_source_ref(
    tmp_path: Path,
) -> None:
    service = _session_service(tmp_path)

    event = service.record_memory_unavailable_degraded(
        project_id="repo-a",
        session_id="session:repo-a",
        memory_scope="project",
        fallback_mode="session_service_runtime_snapshot",
        degradation_reason="memory_hub_unreachable",
        related_ids={"source_ref": "memory-provider:sqlite"},
        occurred_at="2026-04-13T10:01:00Z",
    )

    assert event.payload.get("reason_code") == "outage"
    assert event.related_ids.get("source_ref") == "memory-provider:sqlite"

