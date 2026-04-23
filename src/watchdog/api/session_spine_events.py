from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response, StreamingResponse

from watchdog.api.deps import require_token
from watchdog.envelope import err
from watchdog.services.runtime_client.client import CodexRuntimeClient
from watchdog.services.session_service.service import SessionService
from watchdog.services.session_spine.events import (
    iter_session_events,
    render_stable_sse_event,
    render_stable_sse_events,
    list_session_events,
)
from watchdog.services.session_spine.service import SessionSpineUpstreamError

router = APIRouter(prefix="/watchdog", tags=["session-spine-events"])


def get_client(request: Request) -> CodexRuntimeClient:
    return request.app.state.runtime_client


def get_session_service(request: Request) -> SessionService:
    return request.app.state.session_service


@router.get(
    "/sessions/{project_id}/events",
    summary="Get stable session events stream",
    description=(
        "Stable read-only event surface. `follow=true` first emits a stable bootstrap "
        "snapshot made from projected raw snapshot events plus continuity-related "
        "canonical Session Service events, then follows the projected raw task event "
        "stream with duplicate event_ids suppressed. When raw events omit `event_id`, "
        "the projection synthesizes deterministic ids before dedupe. If stream startup "
        "fails it falls back to the bootstrap events already available. `follow=false` "
        "returns a versioned SessionEvent snapshot with a broader selected canonical "
        "Session Service merge."
    ),
)
def get_session_events(
    project_id: str,
    request: Request,
    follow: bool = Query(default=True),
    poll_interval: float = Query(default=0.5, ge=0.1, le=10.0),
    client: CodexRuntimeClient = Depends(get_client),
    session_service: SessionService = Depends(get_session_service),
    _: None = Depends(require_token),
) -> Any:
    rid = request.headers.get("x-request-id")
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
    }
    if not follow:
        try:
            events = list_session_events(
                client,
                project_id,
                poll_interval=poll_interval,
                session_service=session_service,
            )
        except SessionSpineUpstreamError as exc:
            return err(rid, exc.error)
        return Response(
            content=render_stable_sse_events(events),
            media_type="text/event-stream",
            headers=headers,
        )

    try:
        stable_events = iter_session_events(
            client,
            project_id,
            poll_interval=poll_interval,
            session_service=session_service,
        )
    except SessionSpineUpstreamError as exc:
        return err(rid, exc.error)

    def stream() -> Any:
        for event in stable_events:
            yield render_stable_sse_event(event)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers=headers,
    )
