from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError

from watchdog.api.openclaw_callbacks import OpenClawResponseRequest
from watchdog.api.deps import require_token
from watchdog.envelope import err, ok
from watchdog.services.a_client.client import AControlAgentClient
from watchdog.services.approvals.service import (
    ApprovalResponseStore,
    CanonicalApprovalStore,
    respond_to_canonical_approval,
)
from watchdog.services.delivery.store import DeliveryOutboxStore
from watchdog.settings import Settings
from watchdog.storage.action_receipts import ActionReceiptStore

router = APIRouter(prefix="/watchdog", tags=["openclaw-responses"])


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_client(request: Request) -> AControlAgentClient:
    return request.app.state.a_client


def get_receipt_store(request: Request) -> ActionReceiptStore:
    return request.app.state.action_receipt_store


def get_approval_store(request: Request) -> CanonicalApprovalStore:
    return request.app.state.canonical_approval_store


def get_response_store(request: Request) -> ApprovalResponseStore:
    return request.app.state.approval_response_store


def get_delivery_outbox_store(request: Request) -> DeliveryOutboxStore:
    return request.app.state.delivery_outbox_store


def _validation_message(exc: ValidationError) -> str:
    fields = [
        ".".join(str(part) for part in item["loc"])
        for item in exc.errors()
        if item.get("loc")
    ]
    if not fields:
        return "invalid openclaw response contract"
    return f"missing or invalid fields: {', '.join(fields)}"


@router.post(
    "/openclaw/responses",
    summary="Record canonical openclaw approval responses",
    description=(
        "Canonical response surface keyed by (envelope_id, response_action, client_request_id). "
        "This route records a stable approval response and executes the requested action at most once."
    ),
)
def post_openclaw_response(
    request: Request,
    body: dict[str, Any],
    settings: Settings = Depends(get_settings),
    client: AControlAgentClient = Depends(get_client),
    receipt_store: ActionReceiptStore = Depends(get_receipt_store),
    approval_store: CanonicalApprovalStore = Depends(get_approval_store),
    response_store: ApprovalResponseStore = Depends(get_response_store),
    delivery_outbox_store: DeliveryOutboxStore = Depends(get_delivery_outbox_store),
    _: None = Depends(require_token),
) -> dict[str, object]:
    rid = request.headers.get("x-request-id")
    try:
        contract = OpenClawResponseRequest.model_validate(body)
    except ValidationError as exc:
        return err(
            rid,
            {
                "code": "INVALID_ARGUMENT",
                "message": _validation_message(exc),
            },
        )
    if contract.envelope_type != "approval":
        return err(
            rid,
            {
                "code": "INVALID_ARGUMENT",
                "message": "envelope_type must be approval",
            },
        )
    approval = approval_store.get(contract.envelope_id)
    if approval is None:
        return err(
            rid,
            {
                "code": "NOT_FOUND",
                "message": f"unknown approval envelope: {contract.envelope_id}",
            },
        )
    if contract.approval_id != approval.approval_id:
        return err(
            rid,
            {
                "code": "INVALID_ARGUMENT",
                "message": "approval_id does not match envelope_id",
            },
        )
    if contract.decision_id != approval.decision.decision_id:
        return err(
            rid,
            {
                "code": "INVALID_ARGUMENT",
                "message": "decision_id does not match envelope_id",
            },
        )
    if contract.response_token != approval.approval_token:
        return err(
            rid,
            {
                "code": "INVALID_ARGUMENT",
                "message": "response_token does not match envelope_id",
            },
        )
    operator = contract.operator.strip() or "openclaw"
    try:
        result = respond_to_canonical_approval(
            envelope_id=contract.envelope_id,
            response_action=contract.response_action,
            client_request_id=contract.client_request_id,
            operator=operator,
            note=contract.note,
            approval_store=approval_store,
            response_store=response_store,
            settings=settings,
            client=client,
            receipt_store=receipt_store,
            delivery_outbox_store=delivery_outbox_store,
        )
    except KeyError as exc:
        return err(rid, {"code": "NOT_FOUND", "message": str(exc)})
    except ValueError as exc:
        return err(rid, {"code": "INVALID_ARGUMENT", "message": str(exc)})
    return ok(rid, result.model_dump(mode="json"))
