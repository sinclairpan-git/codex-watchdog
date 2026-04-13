#!/usr/bin/env python3
"""
最小 OpenClaw reference runtime。

它只消费 Watchdog 发来的 envelope，返回 receipt，并把用户结构化响应回传给
`POST /api/v1/watchdog/openclaw/responses`。它不承担策略、执行或第二套状态机。
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import httpx

from watchdog.api.openclaw_callbacks import OpenClawResponseRequest, OpenClawWebhookReceipt, utc_now_iso
from watchdog.services.delivery.envelopes import ApprovalEnvelope, DecisionEnvelope, NotificationEnvelope


class OpenClawWebhookRuntime:
    def __init__(
        self,
        *,
        watchdog_base_url: str | None = None,
        watchdog_api_token: str | None = None,
        operator: str | None = None,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._watchdog_base_url = (
            watchdog_base_url
            or os.environ.get("WATCHDOG_BASE_URL", "http://127.0.0.1:8720")
        ).rstrip("/")
        self._watchdog_api_token = (
            watchdog_api_token
            if watchdog_api_token is not None
            else os.environ.get("WATCHDOG_API_TOKEN", "")
        )
        self._operator = operator or os.environ.get("WATCHDOG_OPERATOR", "openclaw")
        self._timeout = timeout
        self._transport = transport
        self._received: dict[str, dict[str, Any]] = {}

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._watchdog_api_token}"} if self._watchdog_api_token else {}

    def receive_envelope(
        self,
        envelope: dict[str, Any],
        *,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        required_headers = [
            "Authorization",
            "X-Watchdog-Delivery-Id",
            "X-Watchdog-Timestamp",
            "X-Watchdog-Signature",
        ]
        missing = [name for name in required_headers if not headers.get(name)]
        if missing:
            raise ValueError(f"missing required headers: {', '.join(missing)}")
        envelope_id = str(envelope.get("envelope_id") or "").strip()
        if headers["X-Watchdog-Delivery-Id"] != envelope_id:
            raise ValueError("X-Watchdog-Delivery-Id does not match envelope_id")
        self._received[envelope_id] = dict(envelope)
        receipt = OpenClawWebhookReceipt(
            envelope_id=envelope_id,
            receipt_id=f"receipt:{uuid.uuid4().hex[:16]}",
            received_at=utc_now_iso(),
        )
        return receipt.model_dump(mode="json")

    def render_envelope(self, envelope: dict[str, Any]) -> dict[str, Any]:
        envelope_type = str(envelope.get("envelope_type") or "")
        if envelope_type == "notification":
            payload = NotificationEnvelope.model_validate(envelope)
            return {
                "host_behavior": "post_notification",
                "title": payload.title,
                "summary": payload.summary,
                "severity": payload.severity,
            }
        if envelope_type == "decision":
            payload = DecisionEnvelope.model_validate(envelope)
            return {
                "host_behavior": "post_decision",
                "title": payload.title or payload.action_name,
                "summary": payload.summary or payload.decision_reason,
                "decision_result": payload.decision_result,
            }
        if envelope_type == "approval":
            payload = ApprovalEnvelope.model_validate(envelope)
            return {
                "host_behavior": "request_approval",
                "title": payload.title,
                "summary": payload.summary,
                "decision_options": payload.decision_options,
                "response_contract": {
                    "envelope_id": payload.envelope_id,
                    "envelope_type": payload.envelope_type,
                    "approval_id": payload.approval_id,
                    "decision_id": payload.correlation_id,
                    "response_token": payload.approval_token,
                },
            }
        raise ValueError(f"unsupported envelope_type: {envelope_type}")

    def respond_to_envelope(
        self,
        envelope: dict[str, Any],
        *,
        response_action: str,
        client_request_id: str,
        user_ref: str,
        channel_ref: str,
        note: str = "",
        operator: str | None = None,
    ) -> dict[str, Any]:
        payload = ApprovalEnvelope.model_validate(envelope)
        contract = OpenClawResponseRequest(
            envelope_id=payload.envelope_id,
            envelope_type=payload.envelope_type,
            approval_id=payload.approval_id,
            decision_id=payload.correlation_id,
            response_action=response_action,
            response_token=payload.approval_token,
            user_ref=user_ref,
            channel_ref=channel_ref,
            client_request_id=client_request_id,
            operator=operator or self._operator,
            note=note,
        )
        with httpx.Client(
            base_url=self._watchdog_base_url,
            headers=self._headers(),
            timeout=self._timeout,
            transport=self._transport,
        ) as client:
            response = client.post(
                "/api/v1/watchdog/openclaw/responses",
                json=contract.model_dump(mode="json"),
            )
            response.raise_for_status()
            return response.json()
