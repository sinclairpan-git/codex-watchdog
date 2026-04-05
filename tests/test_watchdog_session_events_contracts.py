from __future__ import annotations

from watchdog.contracts.session_spine.enums import EventCode, EventKind
from watchdog.contracts.session_spine.models import SessionEvent
from watchdog.contracts.session_spine.versioning import (
    SESSION_EVENTS_CONTRACT_VERSION,
    SESSION_EVENTS_SCHEMA_VERSION,
)


def test_session_event_version_constants_are_frozen() -> None:
    assert SESSION_EVENTS_CONTRACT_VERSION == "watchdog-session-events/v1alpha1"
    assert SESSION_EVENTS_SCHEMA_VERSION == "2026-04-05.011"


def test_session_event_uses_stable_and_native_thread_ids_separately() -> None:
    event = SessionEvent(
        event_id="evt_001",
        event_code=EventCode.SESSION_CREATED,
        event_kind=EventKind.LIFECYCLE,
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="thr_native_1",
        source="a_control_agent",
        observed_at="2026-04-05T10:00:00Z",
        summary="session created in planning",
        related_ids={},
        attributes={"status": "running", "phase": "planning"},
    )

    payload = event.model_dump(mode="json")

    assert payload["contract_version"] == SESSION_EVENTS_CONTRACT_VERSION
    assert payload["schema_version"] == SESSION_EVENTS_SCHEMA_VERSION
    assert payload["event_code"] == "session_created"
    assert payload["thread_id"] == "session:repo-a"
    assert payload["native_thread_id"] == "thr_native_1"
    assert payload["attributes"]["phase"] == "planning"
