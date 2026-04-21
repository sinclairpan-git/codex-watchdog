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
from watchdog.services.delivery.store import DeliveryOutboxRecord, DeliveryOutboxStore
from watchdog.services.session_service import SessionService

router = APIRouter(prefix="/watchdog", tags=["openclaw-compatibility"])


def get_openclaw_webhook_store(request: Request) -> OpenClawWebhookEndpointStore:
    return request.app.state.openclaw_webhook_endpoint_store


def get_delivery_outbox_store(request: Request) -> DeliveryOutboxStore:
    return request.app.state.delivery_outbox_store


def get_session_service(request: Request) -> SessionService:
    return request.app.state.session_service


def _validation_message(exc: ValidationError) -> str:
    fields = [
        ".".join(str(part) for part in item["loc"])
        for item in exc.errors()
        if item.get("loc")
    ]
    if not fields:
        return "invalid openclaw bootstrap contract"
    return f"missing or invalid fields: {', '.join(fields)}"


def _record_notification_requeued(
    service: SessionService,
    record: DeliveryOutboxRecord,
    *,
    reason: str,
    previous_failure_code: str | None,
) -> None:
    payload = dict(record.envelope_payload)
    if payload.get("envelope_type") != "notification":
        return
    mirrored: dict[str, Any] = {
        "outbox_seq": record.outbox_seq,
        "delivery_status": record.delivery_status,
        "delivery_attempt": record.delivery_attempt,
        "reason": reason,
    }
    if previous_failure_code:
        mirrored["failure_code"] = previous_failure_code
    next_retry_at = record.next_retry_at
    if next_retry_at is not None:
        mirrored["next_retry_at"] = next_retry_at
    for field in (
        "event_id",
        "notification_kind",
        "severity",
        "title",
        "summary",
        "occurred_at",
        "decision_result",
        "action_name",
        "interaction_context_id",
        "interaction_family_id",
        "actor_id",
        "channel_kind",
        "action_window_expires_at",
    ):
        value = payload.get(field)
        if value is not None:
            mirrored[field] = value
    service.record_event(
        event_type="notification_requeued",
        project_id=record.project_id,
        session_id=record.session_id,
        occurred_at=record.updated_at,
        correlation_id=f"corr:notification:{record.envelope_id}:requeue:{reason}",
        causation_id=str(payload.get("event_id") or record.envelope_id),
        related_ids={
            "envelope_id": record.envelope_id,
            **(
                {"native_thread_id": record.effective_native_thread_id}
                if isinstance(record.effective_native_thread_id, str)
                and record.effective_native_thread_id
                else {}
            ),
            **(
                {"notification_event_id": payload["event_id"]}
                if isinstance(payload.get("event_id"), str) and payload.get("event_id")
                else {}
            ),
            **(
                {"notification_kind": payload["notification_kind"]}
                if isinstance(payload.get("notification_kind"), str)
                and payload.get("notification_kind")
                else {}
            ),
            **(
                {"interaction_context_id": payload["interaction_context_id"]}
                if isinstance(payload.get("interaction_context_id"), str)
                and payload.get("interaction_context_id")
                else {}
            ),
            **(
                {"interaction_family_id": payload["interaction_family_id"]}
                if isinstance(payload.get("interaction_family_id"), str)
                and payload.get("interaction_family_id")
                else {}
            ),
            **(
                {"actor_id": payload["actor_id"]}
                if isinstance(payload.get("actor_id"), str) and payload.get("actor_id")
                else {}
            ),
        },
        payload=mirrored,
    )


@router.post(
    "/bootstrap/openclaw-webhook",
    summary="Persist latest compatibility OpenClaw webhook endpoint",
    description=(
        "Compatibility-only bootstrap surface for migration-period OpenClaw endpoint changes. "
        "Persists the latest OpenClaw public webhook root so legacy delivery can resolve it "
        "without reclaiming the primary control-plane role."
    ),
)
def post_openclaw_webhook_bootstrap(
    request: Request,
    body: dict[str, Any],
    store: OpenClawWebhookEndpointStore = Depends(get_openclaw_webhook_store),
    delivery_store: DeliveryOutboxStore = Depends(get_delivery_outbox_store),
    session_service: SessionService = Depends(get_session_service),
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
    requeued = delivery_store.requeue_transport_failures(
        reason="openclaw_webhook_base_url_changed",
        updated_at=state.updated_at,
    )
    for record in requeued:
        previous_failure_code = None
        for note in reversed(record.operator_notes):
            prefix = "delivery_requeued reason=openclaw_webhook_base_url_changed previous_failure_code="
            if note.startswith(prefix):
                previous_failure_code = note.removeprefix(prefix) or None
                break
        _record_notification_requeued(
            session_service,
            record,
            reason="openclaw_webhook_base_url_changed",
            previous_failure_code=previous_failure_code,
        )
    return ok(
        rid,
        OpenClawWebhookBootstrapReceipt(
            openclaw_webhook_base_url=state.openclaw_webhook_base_url,
            updated_at=state.updated_at,
        ).model_dump(mode="json"),
    )
