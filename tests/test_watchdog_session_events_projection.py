from __future__ import annotations

from watchdog.services.session_spine.events import (
    iter_stable_sse_stream,
    project_raw_event,
    render_stable_sse_snapshot,
)


def test_project_raw_event_maps_known_raw_event_to_stable_contract() -> None:
    event = project_raw_event(
        {
            "event_id": "evt_001",
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "event_type": "approval_decided",
            "event_source": "a_control_agent",
            "payload_json": {
                "approval_id": "appr_001",
                "decision": "approve",
                "operator": "alice",
                "note": "",
            },
            "created_at": "2026-04-05T10:00:00Z",
        }
    )

    payload = event.model_dump(mode="json")

    assert payload["event_code"] == "approval_resolved"
    assert payload["event_kind"] == "approval"
    assert payload["thread_id"] == "session:repo-a"
    assert payload["native_thread_id"] == "thr_native_1"
    assert payload["related_ids"] == {"approval_id": "appr_001"}
    assert payload["attributes"]["decision"] == "approve"


def test_project_raw_event_downgrades_unknown_type_to_session_updated() -> None:
    event = project_raw_event(
        {
            "event_id": "evt_002",
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "event_type": "mystery_event",
            "event_source": "a_control_agent",
            "payload_json": {"foo": "bar"},
            "created_at": "2026-04-05T10:01:00Z",
        }
    )

    payload = event.model_dump(mode="json")

    assert payload["event_code"] == "session_updated"
    assert payload["event_kind"] == "observation"
    assert payload["attributes"] == {"foo": "bar"}


def test_project_raw_event_prefers_explicit_native_thread_id() -> None:
    event = project_raw_event(
        {
            "event_id": "evt_003",
            "project_id": "repo-a",
            "thread_id": "session:repo-a",
            "native_thread_id": "thr_native_1",
            "event_type": "resume",
            "event_source": "a_control_agent",
            "payload_json": {"mode": "resume_or_new_thread"},
            "created_at": "2026-04-05T10:02:00Z",
        }
    )

    payload = event.model_dump(mode="json")

    assert payload["event_code"] == "session_resumed"
    assert payload["thread_id"] == "session:repo-a"
    assert payload["native_thread_id"] == "thr_native_1"


def test_project_raw_event_synthesizes_stable_event_id_when_missing() -> None:
    event = project_raw_event(
        {
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "event_type": "resume",
            "event_source": "a_control_agent",
            "payload_json": {"mode": "resume_or_new_thread"},
            "created_at": "2026-04-05T10:02:00Z",
        }
    )

    payload = event.model_dump(mode="json")

    assert payload["event_code"] == "session_resumed"
    assert payload["event_id"].startswith("synthetic:")
    assert payload["event_id"] != "synthetic:"


def test_project_raw_event_uses_raw_event_ordinal_to_disambiguate_legacy_duplicates() -> None:
    first = project_raw_event(
        {
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "event_type": "resume",
            "event_source": "a_control_agent",
            "payload_json": {"mode": "resume_or_new_thread"},
            "created_at": "2026-04-05T10:02:00Z",
            "_raw_event_ordinal": 1,
        }
    )
    second = project_raw_event(
        {
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "event_type": "resume",
            "event_source": "a_control_agent",
            "payload_json": {"mode": "resume_or_new_thread"},
            "created_at": "2026-04-05T10:02:00Z",
            "_raw_event_ordinal": 2,
        }
    )

    assert first.event_id.startswith("synthetic:")
    assert second.event_id.startswith("synthetic:")
    assert first.event_id != second.event_id


def test_render_stable_sse_snapshot_transforms_raw_events_without_leaking_payload_json() -> None:
    raw_snapshot = (
        'id: evt_001\n'
        "event: task_created\n"
        'data: {"event_id":"evt_001","project_id":"repo-a","thread_id":"thr_native_1","event_type":"task_created","event_source":"a_control_agent","payload_json":{"status":"running","phase":"planning"},"created_at":"2026-04-05T10:00:00Z"}\n\n'
        'id: evt_002\n'
        "event: approval_decided\n"
        'data: {"event_id":"evt_002","project_id":"repo-a","thread_id":"thr_native_1","event_type":"approval_decided","event_source":"a_control_agent","payload_json":{"approval_id":"appr_001","decision":"approve","operator":"alice"},"created_at":"2026-04-05T10:01:00Z"}\n\n'
    )

    stable_snapshot = render_stable_sse_snapshot(raw_snapshot)

    assert "event: session_created" in stable_snapshot
    assert "event: approval_resolved" in stable_snapshot
    assert '"schema_version":"2026-04-05.011"' in stable_snapshot
    assert "payload_json" not in stable_snapshot
    assert '"event_type":"approval_decided"' not in stable_snapshot


def test_render_stable_sse_snapshot_dedupes_duplicate_event_ids() -> None:
    raw_snapshot = (
        'id: evt_001\n'
        "event: task_created\n"
        'data: {"event_id":"evt_001","project_id":"repo-a","thread_id":"thr_native_1","event_type":"task_created","event_source":"a_control_agent","payload_json":{"status":"running","phase":"planning"},"created_at":"2026-04-05T10:00:00Z"}\n\n'
        'id: evt_001\n'
        "event: task_created\n"
        'data: {"event_id":"evt_001","project_id":"repo-a","thread_id":"thr_native_1","event_type":"task_created","event_source":"a_control_agent","payload_json":{"status":"running","phase":"planning"},"created_at":"2026-04-05T10:00:00Z"}\n\n'
    )

    stable_snapshot = render_stable_sse_snapshot(raw_snapshot)

    assert stable_snapshot.count("event: session_created") == 1


def test_render_stable_sse_snapshot_keeps_distinct_legacy_events_when_raw_event_id_is_missing() -> None:
    raw_snapshot = (
        "event: resume\n"
        'data: {"project_id":"repo-a","thread_id":"thr_native_1","event_type":"resume","event_source":"a_control_agent","payload_json":{"mode":"resume_or_new_thread"},"created_at":"2026-04-05T10:02:00Z"}\n\n'
        "event: resume\n"
        'data: {"project_id":"repo-a","thread_id":"thr_native_1","event_type":"resume","event_source":"a_control_agent","payload_json":{"mode":"resume_or_new_thread"},"created_at":"2026-04-05T10:02:00Z"}\n\n'
    )

    stable_snapshot = render_stable_sse_snapshot(raw_snapshot)

    assert stable_snapshot.count("event: session_resumed") == 2


def test_iter_stable_sse_stream_reassembles_split_chunks() -> None:
    chunks = [
        'id: evt_003\nevent: resume\ndata: {"event_id":"evt_003","project_id":"repo-a",',
        '"thread_id":"thr_native_1","event_type":"resume","event_source":"a_control_agent","payload_json":{"mode":"resume_or_new_thread","status":"running","phase":"editing_source"},"created_at":"2026-04-05T10:02:00Z"}\n\n',
    ]

    stable_chunks = list(iter_stable_sse_stream(chunks))

    assert len(stable_chunks) == 1
    assert "event: session_resumed" in stable_chunks[0]
    assert '"mode":"resume_or_new_thread"' in stable_chunks[0]
    assert "payload_json" not in stable_chunks[0]


def test_iter_stable_sse_stream_dedupes_duplicate_event_ids() -> None:
    chunks = [
        'id: evt_003\nevent: resume\ndata: {"event_id":"evt_003","project_id":"repo-a","thread_id":"thr_native_1","event_type":"resume","event_source":"a_control_agent","payload_json":{"mode":"resume_or_new_thread"},"created_at":"2026-04-05T10:02:00Z"}\n\n',
        'id: evt_003\nevent: resume\ndata: {"event_id":"evt_003","project_id":"repo-a","thread_id":"thr_native_1","event_type":"resume","event_source":"a_control_agent","payload_json":{"mode":"resume_or_new_thread"},"created_at":"2026-04-05T10:02:00Z"}\n\n',
    ]

    stable_chunks = list(iter_stable_sse_stream(chunks))

    assert len(stable_chunks) == 1
    assert "event: session_resumed" in stable_chunks[0]
