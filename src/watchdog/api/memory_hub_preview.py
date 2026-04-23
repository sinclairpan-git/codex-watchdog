from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, ValidationError

from watchdog.api.deps import require_token
from watchdog.envelope import err, ok
from watchdog.services.memory_hub.models import (
    AIAutoSDLCCursorRequest,
    ContextQualitySnapshot,
)
from watchdog.services.memory_hub.service import MemoryHubService

router = APIRouter(prefix="/watchdog", tags=["memory-hub"])


class AIAutoSDLCCursorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request: AIAutoSDLCCursorRequest
    quality: ContextQualitySnapshot


def get_memory_hub_service(request: Request) -> MemoryHubService:
    return request.app.state.memory_hub_service


def _validation_message(exc: ValidationError) -> str:
    fields = [
        ".".join(str(part) for part in item["loc"])
        for item in exc.errors()
        if item.get("loc")
    ]
    if not fields:
        return "invalid ai_autosdlc_cursor request"
    return f"missing or invalid fields: {', '.join(fields)}"


@router.post(
    "/memory/preview/ai-autosdlc-cursor",
    summary="Query Memory Hub AI_AutoSDLC preview cursor",
    description=(
        "Token-protected preview route for the Memory Hub stage-aware cursor. "
        "The route remains callable when the preview contract is disabled, but "
        "returns an `enabled=false` preview payload until app-level opt-in is configured."
    ),
)
def post_ai_autosdlc_cursor_preview(
    request: Request,
    body: dict[str, Any],
    memory_hub_service: MemoryHubService = Depends(get_memory_hub_service),
    _: None = Depends(require_token),
) -> dict[str, object]:
    rid = request.headers.get("x-request-id")
    try:
        envelope = AIAutoSDLCCursorEnvelope.model_validate(body)
    except ValidationError as exc:
        return err(
            rid,
            {
                "code": "INVALID_ARGUMENT",
                "message": _validation_message(exc),
            },
        )
    response = memory_hub_service.ai_autosdlc_cursor(
        request=envelope.request,
        quality=envelope.quality,
    )
    return ok(rid, response.model_dump(mode="json"))
