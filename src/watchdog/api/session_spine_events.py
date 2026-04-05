from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response, StreamingResponse

from watchdog.api.deps import require_token
from watchdog.envelope import err
from watchdog.services.a_client.client import AControlAgentClient
from watchdog.services.session_spine.events import (
    _load_raw_events_snapshot_or_raise,
    iter_stable_sse_stream,
    render_stable_sse_snapshot,
)
from watchdog.services.session_spine.service import SessionSpineUpstreamError

router = APIRouter(prefix="/watchdog", tags=["session-spine-events"])


def get_client(request: Request) -> AControlAgentClient:
    return request.app.state.a_client


@router.get(
    "/sessions/{project_id}/events",
    summary="Get stable session events stream",
    description=(
        "Stable read-only event surface. This route projects raw task events "
        "into versioned SessionEvent records and keeps the legacy raw proxy unchanged."
    ),
)
def get_session_events(
    project_id: str,
    request: Request,
    follow: bool = Query(default=True),
    poll_interval: float = Query(default=0.5, ge=0.1, le=10.0),
    client: AControlAgentClient = Depends(get_client),
    _: None = Depends(require_token),
) -> Any:
    rid = request.headers.get("x-request-id")
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
    }
    if not follow:
        try:
            raw_snapshot = _load_raw_events_snapshot_or_raise(
                client,
                project_id,
                poll_interval=poll_interval,
            )
        except SessionSpineUpstreamError as exc:
            return err(rid, exc.error)
        return Response(
            content=render_stable_sse_snapshot(raw_snapshot),
            media_type="text/event-stream",
            headers=headers,
        )

    def stream() -> Any:
        yield from iter_stable_sse_stream(
            client.iter_events(project_id, poll_interval=poll_interval)
        )

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers=headers,
    )
