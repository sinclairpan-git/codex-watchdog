from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError

from watchdog.api.deps import require_token
from watchdog.envelope import err, ok
from watchdog.services.runtime_client.client import CodexRuntimeClient
from watchdog.services.approvals.service import ApprovalResponseStore, CanonicalApprovalStore
from watchdog.services.delivery.store import DeliveryOutboxStore
from watchdog.services.feishu_control import (
    FeishuControlError,
    FeishuControlRequest,
    FeishuControlService,
)
from watchdog.services.session_service import SessionService
from watchdog.settings import Settings
from watchdog.storage.action_receipts import ActionReceiptStore

router = APIRouter(prefix="/watchdog", tags=["feishu-control"])


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_client(request: Request) -> CodexRuntimeClient:
    return request.app.state.runtime_client


def get_receipt_store(request: Request) -> ActionReceiptStore:
    return request.app.state.action_receipt_store


def get_approval_store(request: Request) -> CanonicalApprovalStore:
    return request.app.state.canonical_approval_store


def get_response_store(request: Request) -> ApprovalResponseStore:
    return request.app.state.approval_response_store


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
        return "invalid feishu control contract"
    return f"missing or invalid fields: {', '.join(fields)}"


@router.post(
    "/feishu/control",
    summary="Handle primary Feishu control-plane responses",
    description=(
        "Primary control-plane surface for Feishu DM approval responses and other "
        "interaction-bound control actions. This route validates interaction context, "
        "records receipt/audit events, and then delegates to canonical approval handling."
    ),
)
def post_feishu_control(
    request: Request,
    body: dict[str, Any],
    settings: Settings = Depends(get_settings),
    client: CodexRuntimeClient = Depends(get_client),
    receipt_store: ActionReceiptStore = Depends(get_receipt_store),
    approval_store: CanonicalApprovalStore = Depends(get_approval_store),
    response_store: ApprovalResponseStore = Depends(get_response_store),
    delivery_outbox_store: DeliveryOutboxStore = Depends(get_delivery_outbox_store),
    session_service: SessionService = Depends(get_session_service),
    _: None = Depends(require_token),
) -> dict[str, object]:
    rid = request.headers.get("x-request-id")
    try:
        contract = FeishuControlRequest.model_validate(body)
    except ValidationError as exc:
        return err(rid, {"code": "INVALID_ARGUMENT", "message": _validation_message(exc)})

    service = FeishuControlService(
        settings=settings,
        client=client,
        receipt_store=receipt_store,
        approval_store=approval_store,
        response_store=response_store,
        delivery_outbox_store=delivery_outbox_store,
        session_service=session_service,
    )
    try:
        result = service.handle_request(contract)
    except KeyError as exc:
        return err(rid, {"code": "NOT_FOUND", "message": str(exc)})
    except FeishuControlError as exc:
        return err(rid, {"code": "INVALID_ARGUMENT", "message": exc.message})
    except ValueError as exc:
        return err(rid, {"code": "INVALID_ARGUMENT", "message": str(exc)})
    if hasattr(result, "model_dump"):
        return ok(rid, result.model_dump(mode="json"))
    return ok(rid, result)
