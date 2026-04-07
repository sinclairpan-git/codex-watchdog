from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError

from watchdog.api.deps import require_token
from watchdog.api.openclaw_callbacks import (
    OpenClawWebhookBootstrapReceipt,
    OpenClawWebhookBootstrapRequest,
)
from watchdog.envelope import err, ok
from watchdog.services.delivery.openclaw_webhook_store import OpenClawWebhookEndpointStore

router = APIRouter(prefix="/watchdog", tags=["openclaw-bootstrap"])


def get_openclaw_webhook_store(request: Request) -> OpenClawWebhookEndpointStore:
    return request.app.state.openclaw_webhook_endpoint_store


def _validation_message(exc: ValidationError) -> str:
    fields = [
        ".".join(str(part) for part in item["loc"])
        for item in exc.errors()
        if item.get("loc")
    ]
    if not fields:
        return "invalid openclaw bootstrap contract"
    return f"missing or invalid fields: {', '.join(fields)}"


@router.post(
    "/bootstrap/openclaw-webhook",
    summary="Persist latest public OpenClaw webhook endpoint",
    description=(
        "Bootstrap surface for B-host endpoint changes. Persists the latest "
        "OpenClaw public webhook root so envelope delivery can resolve it dynamically."
    ),
)
def post_openclaw_webhook_bootstrap(
    request: Request,
    body: dict[str, Any],
    store: OpenClawWebhookEndpointStore = Depends(get_openclaw_webhook_store),
    _: None = Depends(require_token),
) -> dict[str, object]:
    rid = request.headers.get("x-request-id")
    try:
        contract = OpenClawWebhookBootstrapRequest.model_validate(body)
    except ValidationError as exc:
        return err(
            rid,
            {
                "code": "INVALID_ARGUMENT",
                "message": _validation_message(exc),
            },
        )
    if contract.event_type != "openclaw_webhook_base_url_changed":
        return err(
            rid,
            {
                "code": "INVALID_ARGUMENT",
                "message": "event_type must be openclaw_webhook_base_url_changed",
            },
        )
    state = store.put(
        openclaw_webhook_base_url=contract.openclaw_webhook_base_url,
        changed_at=contract.changed_at,
        source=contract.source,
    )
    return ok(
        rid,
        OpenClawWebhookBootstrapReceipt(
            openclaw_webhook_base_url=state.openclaw_webhook_base_url,
            updated_at=state.updated_at,
        ).model_dump(mode="json"),
    )
