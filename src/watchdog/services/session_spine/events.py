from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any

import httpx

from watchdog.contracts.session_spine.enums import EventCode, EventKind
from watchdog.contracts.session_spine.models import SessionEvent
from watchdog.services.a_client.client import AControlAgentClient
from watchdog.services.session_spine.projection import stable_thread_id_for_project
from watchdog.services.session_spine.service import CONTROL_LINK_ERROR, SessionSpineUpstreamError

_RAW_EVENT_MAPPING: dict[str, tuple[EventCode, EventKind]] = {
    "task_created": (EventCode.SESSION_CREATED, EventKind.LIFECYCLE),
    "native_thread_registered": (EventCode.NATIVE_THREAD_BOUND, EventKind.LIFECYCLE),
    "steer": (EventCode.GUIDANCE_POSTED, EventKind.GUIDANCE),
    "handoff": (EventCode.HANDOFF_REQUESTED, EventKind.RECOVERY),
    "resume": (EventCode.SESSION_RESUMED, EventKind.RECOVERY),
    "approval_decided": (EventCode.APPROVAL_RESOLVED, EventKind.APPROVAL),
}


def _event_mapping(raw_event_type: str) -> tuple[EventCode, EventKind]:
    return _RAW_EVENT_MAPPING.get(
        raw_event_type,
        (EventCode.SESSION_UPDATED, EventKind.OBSERVATION),
    )


def _event_attributes(raw_event: dict[str, Any]) -> dict[str, Any]:
    payload = raw_event.get("payload_json")
    if isinstance(payload, dict):
        return dict(payload)
    return {}


def _event_related_ids(event_code: EventCode, attributes: dict[str, Any]) -> dict[str, Any]:
    if event_code == EventCode.APPROVAL_RESOLVED:
        approval_id = str(attributes.get("approval_id") or "")
        if approval_id:
            return {"approval_id": approval_id}
    return {}


def _event_summary(
    event_code: EventCode,
    *,
    project_id: str,
    attributes: dict[str, Any],
) -> str:
    if event_code == EventCode.SESSION_CREATED:
        phase = str(attributes.get("phase") or "")
        return f"session created in {phase}" if phase else f"session created for {project_id}"
    if event_code == EventCode.NATIVE_THREAD_BOUND:
        return "native thread registered"
    if event_code == EventCode.GUIDANCE_POSTED:
        message = str(attributes.get("message") or "")
        return message or "guidance posted"
    if event_code == EventCode.HANDOFF_REQUESTED:
        return "handoff requested"
    if event_code == EventCode.SESSION_RESUMED:
        mode = str(attributes.get("mode") or "")
        return f"session resumed via {mode}" if mode else "session resumed"
    if event_code == EventCode.APPROVAL_RESOLVED:
        decision = str(attributes.get("decision") or "")
        return f"approval {decision}" if decision else "approval resolved"
    return "session updated"


def project_raw_event(raw_event: dict[str, Any]) -> SessionEvent:
    project_id = str(raw_event.get("project_id") or "")
    native_thread_id = str(raw_event.get("thread_id") or "") or None
    raw_event_type = str(raw_event.get("event_type") or "")
    event_code, event_kind = _event_mapping(raw_event_type)
    attributes = _event_attributes(raw_event)
    return SessionEvent(
        event_id=str(raw_event.get("event_id") or ""),
        event_code=event_code,
        event_kind=event_kind,
        project_id=project_id,
        thread_id=stable_thread_id_for_project(project_id),
        native_thread_id=native_thread_id,
        source=str(raw_event.get("event_source") or "unknown"),
        observed_at=str(raw_event.get("created_at") or raw_event.get("ts") or ""),
        summary=_event_summary(
            event_code,
            project_id=project_id,
            attributes=attributes,
        ),
        related_ids=_event_related_ids(event_code, attributes),
        attributes=attributes,
    )


def render_stable_sse_event(event: SessionEvent) -> str:
    body = json.dumps(event.model_dump(mode="json"), separators=(",", ":"))
    return f"id: {event.event_id}\nevent: {event.event_code}\ndata: {body}\n\n"


def _iter_sse_messages(text: str) -> Iterator[str]:
    for message in text.split("\n\n"):
        if message.strip():
            yield message


def _parse_raw_event_message(message: str) -> dict[str, Any] | None:
    event_id = ""
    event_name = ""
    data_lines: list[str] = []
    for line in message.splitlines():
        if line.startswith("id:"):
            event_id = line.partition(":")[2].strip()
            continue
        if line.startswith("event:"):
            event_name = line.partition(":")[2].strip()
            continue
        if line.startswith("data:"):
            data_lines.append(line.partition(":")[2].lstrip())
    data = "\n".join(data_lines)
    if not data:
        return None
    try:
        payload = json.loads(data)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    raw_event = dict(payload)
    if event_id and not raw_event.get("event_id"):
        raw_event["event_id"] = event_id
    if event_name and not raw_event.get("event_type"):
        raw_event["event_type"] = event_name
    return raw_event


def _iter_projected_events_from_snapshot(raw_snapshot: str) -> Iterator[SessionEvent]:
    for message in _iter_sse_messages(raw_snapshot):
        raw_event = _parse_raw_event_message(message)
        if raw_event is None:
            continue
        yield project_raw_event(raw_event)


def _iter_projected_events_from_chunks(raw_chunks: Iterable[str]) -> Iterator[SessionEvent]:
    buffer = ""
    for chunk in raw_chunks:
        if not chunk:
            continue
        buffer += chunk
        while "\n\n" in buffer:
            message, buffer = buffer.split("\n\n", 1)
            if not message.strip():
                continue
            raw_event = _parse_raw_event_message(message)
            if raw_event is None:
                continue
            yield project_raw_event(raw_event)
    if buffer.strip():
        raw_event = _parse_raw_event_message(buffer)
        if raw_event is not None:
            yield project_raw_event(raw_event)


def render_stable_sse_snapshot(raw_snapshot: str) -> str:
    return "".join(
        render_stable_sse_event(event)
        for event in _iter_projected_events_from_snapshot(raw_snapshot)
    )


def iter_stable_sse_stream(raw_chunks: Iterable[str]) -> Iterator[str]:
    for event in _iter_projected_events_from_chunks(raw_chunks):
        yield render_stable_sse_event(event)


def _load_raw_events_snapshot_or_raise(
    client: AControlAgentClient,
    project_id: str,
    *,
    poll_interval: float = 0.5,
) -> str:
    try:
        snapshot = client.get_events_snapshot(project_id, poll_interval=poll_interval)
    except (httpx.RequestError, RuntimeError, OSError) as exc:
        raise SessionSpineUpstreamError(dict(CONTROL_LINK_ERROR)) from exc
    if isinstance(snapshot, dict):
        error = snapshot.get("error")
        if isinstance(error, dict):
            raise SessionSpineUpstreamError(dict(error))
        raise SessionSpineUpstreamError(
            {"code": "CONTROL_LINK_ERROR", "message": "A 侧事件流返回格式异常"}
        )
    body, _content_type = snapshot
    return body


def list_session_events(
    client: AControlAgentClient,
    project_id: str,
    *,
    poll_interval: float = 0.5,
) -> list[SessionEvent]:
    raw_snapshot = _load_raw_events_snapshot_or_raise(
        client,
        project_id,
        poll_interval=poll_interval,
    )
    return list(_iter_projected_events_from_snapshot(raw_snapshot))


def iter_session_events(
    client: AControlAgentClient,
    project_id: str,
    *,
    poll_interval: float = 0.5,
) -> Iterator[SessionEvent]:
    try:
        raw_chunks = client.iter_events(project_id, poll_interval=poll_interval)
    except (httpx.RequestError, RuntimeError, OSError) as exc:
        raise SessionSpineUpstreamError(dict(CONTROL_LINK_ERROR)) from exc

    def _iter_events() -> Iterator[SessionEvent]:
        try:
            yield from _iter_projected_events_from_chunks(raw_chunks)
        except (httpx.RequestError, RuntimeError, OSError) as exc:
            raise SessionSpineUpstreamError(dict(CONTROL_LINK_ERROR)) from exc

    return _iter_events()
