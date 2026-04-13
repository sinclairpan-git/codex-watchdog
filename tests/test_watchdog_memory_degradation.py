from __future__ import annotations

from pathlib import Path

from watchdog.services.session_service.service import SessionService
from watchdog.services.session_service.store import SessionServiceStore


def _session_service(tmp_path: Path) -> SessionService:
    return SessionService(SessionServiceStore(tmp_path / "session_service.json"))


def test_memory_conflict_event_captures_reason_code_and_source_ref(
    tmp_path: Path,
) -> None:
    service = _session_service(tmp_path)

    event = service.record_memory_conflict_detected(
        project_id="repo-a",
        session_id="session:repo-a",
        memory_scope="project",
        conflict_reason="resident_goal_contract_mismatch",
        resolution="reference_only",
        related_ids={"source_ref": "skill:shared:python"},
        occurred_at="2026-04-13T10:02:00Z",
    )

    assert event.payload.get("reason_code") == "conflict"
    assert event.related_ids.get("source_ref") == "skill:shared:python"


def test_memory_security_block_event_records_dangerous_verdict_without_hot_path_override(
    tmp_path: Path,
) -> None:
    service = _session_service(tmp_path)

    event = service.record_memory_unavailable_degraded(
        project_id="repo-a",
        session_id="session:repo-a",
        memory_scope="project",
        fallback_mode="session_service_runtime_snapshot",
        degradation_reason="security_verdict_failed",
        related_ids={"source_ref": "archive:repo-a:artifact-17"},
        occurred_at="2026-04-13T10:03:00Z",
    )

    assert event.payload.get("reason_code") == "security_blocked"
    assert event.payload.get("security_verdict") == "dangerous"
    assert event.payload.get("override_mode") is None
