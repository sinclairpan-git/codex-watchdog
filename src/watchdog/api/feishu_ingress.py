from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError

from watchdog.services.a_client.client import AControlAgentClient
from watchdog.services.approvals.service import ApprovalResponseStore, CanonicalApprovalStore
from watchdog.services.delivery.store import DeliveryOutboxStore
from watchdog.services.feishu_control import FeishuControlError, FeishuControlService
from watchdog.services.feishu_ingress.service import (
    FeishuIngressError,
    FeishuIngressNormalizationService,
    FeishuMessageCallback,
    FeishuURLVerificationRequest,
)
from watchdog.services.session_spine.store import SessionSpineStore
from watchdog.services.session_service import SessionService
from watchdog.settings import Settings
from watchdog.storage.action_receipts import ActionReceiptStore

router = APIRouter(prefix="/watchdog", tags=["feishu-ingress"])


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


def get_session_service(request: Request) -> SessionService:
    return request.app.state.session_service


def get_session_spine_store(request: Request) -> SessionSpineStore:
    return request.app.state.session_spine_store


def _bad_request(message: str, *, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail=message)


@router.post(
    "/feishu/events",
    summary="Handle official Feishu webhook ingress and normalize into canonical control requests",
)
def post_feishu_events(
    body: dict[str, Any],
    settings: Settings = Depends(get_settings),
    client: AControlAgentClient = Depends(get_client),
    receipt_store: ActionReceiptStore = Depends(get_receipt_store),
    approval_store: CanonicalApprovalStore = Depends(get_approval_store),
    response_store: ApprovalResponseStore = Depends(get_response_store),
    delivery_outbox_store: DeliveryOutboxStore = Depends(get_delivery_outbox_store),
    session_service: SessionService = Depends(get_session_service),
    session_spine_store: SessionSpineStore = Depends(get_session_spine_store),
) -> dict[str, object]:
    ingress = FeishuIngressNormalizationService(
        settings=settings,
        client=client,
        session_spine_store=session_spine_store,
    )
    if body.get("type") == "url_verification":
        try:
            contract = FeishuURLVerificationRequest.model_validate(body)
            return ingress.validate_url_verification(contract)
        except ValidationError as exc:
            raise _bad_request(str(exc)) from exc
        except FeishuIngressError as exc:
            raise _bad_request(exc.message, status_code=403) from exc

    try:
        event = FeishuMessageCallback.model_validate(body)
        normalized = ingress.normalize_message_event(event)
    except ValidationError as exc:
        raise _bad_request(str(exc)) from exc
    except FeishuIngressError as exc:
        raise _bad_request(exc.message) from exc

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
        result = service.handle_request(normalized)
    except (FeishuControlError, ValueError, KeyError) as exc:
        raise _bad_request(str(exc)) from exc
    return {
        "accepted": True,
        "event_type": normalized.event_type,
        "data": result.model_dump(mode="json") if hasattr(result, "model_dump") else result,
    }
