from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator
from typing import Any

import httpx

from watchdog.contracts.session_spine.enums import EventCode, EventKind
from watchdog.contracts.session_spine.models import SessionEvent
from watchdog.services.a_client.client import AControlAgentClient
from watchdog.services.session_service.models import SessionEventRecord
from watchdog.services.session_service.service import SessionService
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

_SESSION_SERVICE_EVENT_MAPPING: dict[str, tuple[EventCode, EventKind]] = {
    "goal_contract_created": (EventCode.SESSION_UPDATED, EventKind.LIFECYCLE),
    "goal_contract_revised": (EventCode.SESSION_UPDATED, EventKind.LIFECYCLE),
    "goal_contract_adopted_by_child_session": (EventCode.SESSION_RESUMED, EventKind.RECOVERY),
    "recovery_execution_suppressed": (EventCode.SESSION_UPDATED, EventKind.RECOVERY),
    "interaction_context_superseded": (EventCode.SESSION_UPDATED, EventKind.OBSERVATION),
    "interaction_window_expired": (EventCode.SESSION_UPDATED, EventKind.OBSERVATION),
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


def _stable_event_id(raw_event: dict[str, Any], *, attributes: dict[str, Any]) -> str:
    explicit_event_id = str(raw_event.get("event_id") or "").strip()
    if explicit_event_id:
        return explicit_event_id
    fingerprint = json.dumps(
        {
            "project_id": str(raw_event.get("project_id") or ""),
            "thread_id": str(raw_event.get("thread_id") or ""),
            "native_thread_id": str(raw_event.get("native_thread_id") or ""),
            "event_type": str(raw_event.get("event_type") or ""),
            "event_source": str(raw_event.get("event_source") or ""),
            "created_at": str(raw_event.get("created_at") or raw_event.get("ts") or ""),
            "attributes": attributes,
            "raw_event_ordinal": _normalize_raw_event_ordinal(raw_event.get("_raw_event_ordinal")),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:16]
    return f"synthetic:{digest}"


def _normalize_raw_event_ordinal(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def project_raw_event(raw_event: dict[str, Any]) -> SessionEvent:
    project_id = str(raw_event.get("project_id") or "")
    native_thread_id = str(raw_event.get("native_thread_id") or "").strip()
    if not native_thread_id:
        fallback_thread_id = str(raw_event.get("thread_id") or "").strip()
        native_thread_id = (
            None if fallback_thread_id.startswith("session:") else fallback_thread_id or None
        )
    raw_event_type = str(raw_event.get("event_type") or "")
    event_code, event_kind = _event_mapping(raw_event_type)
    attributes = _event_attributes(raw_event)
    return SessionEvent(
        event_id=_stable_event_id(raw_event, attributes=attributes),
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


def _session_service_native_thread_id(event: SessionEventRecord) -> str | None:
    payload = event.payload if isinstance(event.payload, dict) else {}
    related_ids = event.related_ids if isinstance(event.related_ids, dict) else {}
    native_thread_id = str(
        payload.get("native_thread_id")
        or payload.get("parent_native_thread_id")
        or related_ids.get("native_thread_id")
        or related_ids.get("parent_native_thread_id")
        or ""
    ).strip()
    return native_thread_id or None


def _session_service_summary(event: SessionEventRecord) -> str:
    event_type = event.event_type
    payload = event.payload if isinstance(event.payload, dict) else {}
    if event_type == "goal_contract_created":
        return "goal contract created"
    if event_type == "goal_contract_revised":
        return "goal contract revised"
    if event_type == "goal_contract_adopted_by_child_session":
        child_session_id = str(
            payload.get("child_session_id")
            or (event.related_ids if isinstance(event.related_ids, dict) else {}).get("child_session_id")
            or ""
        ).strip()
        if child_session_id:
            return f"goal contract adopted by {child_session_id}"
        return "goal contract adopted by child session"
    if event_type == "recovery_execution_suppressed":
        reason = str(payload.get("suppression_reason") or "").strip()
        return f"recovery execution suppressed ({reason})" if reason else "recovery execution suppressed"
    if event_type == "interaction_context_superseded":
        return "interaction context superseded"
    if event_type == "interaction_window_expired":
        return "interaction window expired"
    return event_type


def project_session_service_event(event: SessionEventRecord) -> SessionEvent | None:
    mapping = _SESSION_SERVICE_EVENT_MAPPING.get(event.event_type)
    if mapping is None:
        return None
    event_code, event_kind = mapping
    attributes = dict(event.payload if isinstance(event.payload, dict) else {})
    attributes.setdefault("event_type", event.event_type)
    thread_id = str(event.session_id or "").strip() or stable_thread_id_for_project(event.project_id)
    return SessionEvent(
        event_id=event.event_id,
        event_code=event_code,
        event_kind=event_kind,
        project_id=event.project_id,
        thread_id=thread_id,
        native_thread_id=_session_service_native_thread_id(event),
        source="session_service",
        observed_at=event.occurred_at,
        summary=_session_service_summary(event),
        related_ids=dict(event.related_ids),
        attributes=attributes,
    )


def _sort_projected_events(events: Iterable[SessionEvent]) -> list[SessionEvent]:
    return sorted(
        events,
        key=lambda event: (
            str(event.observed_at or ""),
            str(event.event_id or ""),
            str(event.event_code or ""),
        ),
    )


def _sort_and_dedupe_projected_events(events: Iterable[SessionEvent]) -> list[SessionEvent]:
    deduped: list[SessionEvent] = []
    seen_event_ids: set[str] = set()
    for event in _sort_projected_events(events):
        event_id = str(event.event_id or "").strip()
        if event_id:
            if event_id in seen_event_ids:
                continue
            seen_event_ids.add(event_id)
        deduped.append(event)
    return deduped


def _list_session_service_events(
    *,
    project_id: str,
    session_service: SessionService | None,
) -> list[SessionEvent]:
    if session_service is None:
        return []
    projected: list[SessionEvent] = []
    for event in session_service.list_events():
        if event.project_id != project_id:
            continue
        projected_event = project_session_service_event(event)
        if projected_event is not None:
            projected.append(projected_event)
    return _sort_and_dedupe_projected_events(projected)


def _list_follow_session_service_events(
    *,
    project_id: str,
    session_service: SessionService | None,
) -> list[SessionEvent]:
    return [
        event
        for event in _list_session_service_events(
            project_id=project_id,
            session_service=session_service,
        )
        if event.attributes.get("event_type")
        not in {"goal_contract_created", "goal_contract_revised"}
    ]


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
    for ordinal, message in enumerate(_iter_sse_messages(raw_snapshot), start=1):
        raw_event = _parse_raw_event_message(message)
        if raw_event is None:
            continue
        raw_event.setdefault("_raw_event_ordinal", ordinal)
        yield project_raw_event(raw_event)


def _iter_projected_events_from_chunks(raw_chunks: Iterable[str]) -> Iterator[SessionEvent]:
    buffer = ""
    ordinal = 0
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
            ordinal += 1
            raw_event.setdefault("_raw_event_ordinal", ordinal)
            yield project_raw_event(raw_event)
    if buffer.strip():
        raw_event = _parse_raw_event_message(buffer)
        if raw_event is not None:
            ordinal += 1
            raw_event.setdefault("_raw_event_ordinal", ordinal)
            yield project_raw_event(raw_event)


def render_stable_sse_snapshot(raw_snapshot: str) -> str:
    return render_stable_sse_events(_iter_projected_events_from_snapshot(raw_snapshot))


def render_stable_sse_events(events: Iterable[SessionEvent]) -> str:
    return "".join(render_stable_sse_event(event) for event in _sort_and_dedupe_projected_events(events))


def _iter_deduped_projected_events(events: Iterable[SessionEvent]) -> Iterator[SessionEvent]:
    seen_event_ids: set[str] = set()
    for event in events:
        event_id = str(event.event_id or "").strip()
        if event_id:
            if event_id in seen_event_ids:
                continue
            seen_event_ids.add(event_id)
        yield event


def _load_initial_session_events(
    client: AControlAgentClient,
    project_id: str,
    *,
    poll_interval: float = 0.5,
    session_service_events: Iterable[SessionEvent] = (),
) -> list[SessionEvent]:
    raw_snapshot = _load_raw_events_snapshot_or_raise(
        client,
        project_id,
        poll_interval=poll_interval,
    )
    raw_events = list(_iter_projected_events_from_snapshot(raw_snapshot))
    return _sort_and_dedupe_projected_events([*raw_events, *session_service_events])


def iter_stable_sse_stream(raw_chunks: Iterable[str]) -> Iterator[str]:
    for event in _iter_deduped_projected_events(_iter_projected_events_from_chunks(raw_chunks)):
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
    session_service: SessionService | None = None,
) -> list[SessionEvent]:
    session_service_events = _list_session_service_events(
        project_id=project_id,
        session_service=session_service,
    )
    try:
        return _load_initial_session_events(
            client,
            project_id,
            poll_interval=poll_interval,
            session_service_events=session_service_events,
        )
    except SessionSpineUpstreamError:
        if session_service_events:
            return session_service_events
        raise


def iter_session_events(
    client: AControlAgentClient,
    project_id: str,
    *,
    poll_interval: float = 0.5,
    session_service: SessionService | None = None,
) -> Iterator[SessionEvent]:
    session_service_events = _list_follow_session_service_events(
        project_id=project_id,
        session_service=session_service,
    )
    try:
        initial_events = _load_initial_session_events(
            client,
            project_id,
            poll_interval=poll_interval,
            session_service_events=session_service_events,
        )
    except SessionSpineUpstreamError:
        initial_events = _sort_and_dedupe_projected_events(session_service_events)
    seen_event_ids = {
        str(event.event_id or "").strip()
        for event in initial_events
        if str(event.event_id or "").strip()
    }
    try:
        raw_chunks = client.iter_events(project_id, poll_interval=poll_interval)
    except (httpx.RequestError, RuntimeError, OSError) as exc:
        if initial_events:
            return iter(initial_events)
        raise SessionSpineUpstreamError(dict(CONTROL_LINK_ERROR)) from exc

    def _iter_events() -> Iterator[SessionEvent]:
        yield from initial_events
        raw_emitted = False
        try:
            for event in _iter_projected_events_from_chunks(raw_chunks):
                event_id = str(event.event_id or "").strip()
                if event_id and event_id in seen_event_ids:
                    continue
                if event_id:
                    seen_event_ids.add(event_id)
                raw_emitted = True
                yield event
        except (httpx.RequestError, RuntimeError, OSError) as exc:
            if initial_events and not raw_emitted:
                return
            raise SessionSpineUpstreamError(dict(CONTROL_LINK_ERROR)) from exc

    return _iter_events()
