from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic import BaseModel

from watchdog.services.delivery.envelopes import (
    ApprovalEnvelope,
    DecisionEnvelope,
    NotificationEnvelope,
    _compatibility_command,
    _compatibility_risk_level,
)
from watchdog.services.delivery.openclaw_webhook_store import (
    OpenClawWebhookEndpointStore,
    openclaw_webhook_endpoint_state_path,
)
from watchdog.services.delivery.store import DeliveryOutboxRecord
from watchdog.settings import Settings


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class DeliveryAttemptResult(BaseModel):
    envelope_id: str
    delivery_status: str
    accepted: bool
    receipt_id: str | None = None
    received_at: str | None = None
    failure_code: str | None = None
    status_code: int | None = None


class OpenClawDeliveryClient:
    def __init__(
        self,
        *,
        settings: Settings,
        endpoint_store: OpenClawWebhookEndpointStore | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._endpoint_store = endpoint_store or OpenClawWebhookEndpointStore(
            openclaw_webhook_endpoint_state_path(settings)
        )
        self._transport = transport

    def _headers(self, envelope_id: str) -> dict[str, str]:
        timestamp = _utc_now_iso()
        return {
            "Authorization": f"Bearer {self._settings.openclaw_webhook_token}",
            "X-Watchdog-Delivery-Id": envelope_id,
            "X-Watchdog-Timestamp": timestamp,
            "X-Watchdog-Signature": f"unsigned:{envelope_id}:{timestamp}",
        }

    def _classify_success(
        self,
        *,
        envelope_id: str,
        response: httpx.Response,
    ) -> DeliveryAttemptResult:
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return DeliveryAttemptResult(
                envelope_id=envelope_id,
                delivery_status="retryable_failure",
                accepted=False,
                failure_code="protocol_incomplete",
                status_code=response.status_code,
            )
        if (
            body.get("accepted") is True
            and body.get("envelope_id") == envelope_id
            and isinstance(body.get("receipt_id"), str)
            and body.get("receipt_id")
            and isinstance(body.get("received_at"), str)
            and body.get("received_at")
        ):
            return DeliveryAttemptResult(
                envelope_id=envelope_id,
                delivery_status="delivered",
                accepted=True,
                receipt_id=str(body["receipt_id"]),
                received_at=str(body["received_at"]),
                status_code=response.status_code,
            )
        return DeliveryAttemptResult(
            envelope_id=envelope_id,
            delivery_status="retryable_failure",
            accepted=False,
            failure_code="protocol_incomplete",
            status_code=response.status_code,
        )

    def _classify_status_failure(self, envelope_id: str, response: httpx.Response) -> DeliveryAttemptResult:
        status_code = response.status_code
        if status_code in {408, 429} or status_code >= 500:
            return DeliveryAttemptResult(
                envelope_id=envelope_id,
                delivery_status="retryable_failure",
                accepted=False,
                failure_code=f"upstream_{status_code}",
                status_code=status_code,
            )
        return DeliveryAttemptResult(
            envelope_id=envelope_id,
            delivery_status="delivery_failed",
            accepted=False,
            failure_code=f"http_{status_code}",
            status_code=status_code,
        )

    def _resolve_base_url(self) -> str:
        state = self._endpoint_store.get()
        if state is not None and state.openclaw_webhook_base_url.strip():
            return state.openclaw_webhook_base_url
        return self._settings.openclaw_webhook_base_url

    @staticmethod
    def _normalize_legacy_approval_payload(
        record: DeliveryOutboxRecord,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = dict(payload)
        requested_action = str(normalized.get("requested_action") or "")
        requested_action_args = normalized.get("requested_action_args")
        if not isinstance(requested_action_args, dict):
            requested_action_args = {}
        risk_class = str(normalized.get("risk_class") or "")
        summary = str(normalized.get("summary") or "")
        why_escalated = normalized.get("why_escalated")
        reason = str(normalized.get("reason") or why_escalated or summary or requested_action)
        title = str(normalized.get("title") or "")
        if not title:
            title = (
                f"approval required for {requested_action}" if requested_action else "approval required"
            )
        normalized.update(
            {
                "requested_action_args": requested_action_args,
                "risk_level": normalized.get("risk_level")
                or (_compatibility_risk_level(risk_class) if risk_class else None),
                "command": normalized.get("command")
                or (_compatibility_command(requested_action, requested_action_args) if requested_action else ""),
                "reason": reason,
                "status": str(normalized.get("status") or "pending"),
                "requested_at": str(
                    normalized.get("requested_at")
                    or normalized.get("created_at")
                    or record.created_at
                ),
                "title": title,
                "summary": summary or reason or title,
            }
        )
        return normalized

    def _normalize_record_payload(self, record: DeliveryOutboxRecord) -> dict[str, Any]:
        payload = dict(record.envelope_payload)
        if str(payload.get("envelope_type")) == "approval":
            return self._normalize_legacy_approval_payload(record, payload)
        return payload

    def deliver_envelope(
        self,
        envelope: DecisionEnvelope | NotificationEnvelope | ApprovalEnvelope,
    ) -> DeliveryAttemptResult:
        url = f"{self._resolve_base_url().rstrip('/')}/openclaw/v1/watchdog/envelopes"
        try:
            with httpx.Client(
                timeout=self._settings.http_timeout_s,
                transport=self._transport,
                trust_env=False,
            ) as client:
                response = client.post(
                    url,
                    headers=self._headers(envelope.envelope_id),
                    json=envelope.model_dump(mode="json"),
                )
        except httpx.TimeoutException:
            return DeliveryAttemptResult(
                envelope_id=envelope.envelope_id,
                delivery_status="retryable_failure",
                accepted=False,
                failure_code="transport_timeout",
            )
        except httpx.RequestError:
            return DeliveryAttemptResult(
                envelope_id=envelope.envelope_id,
                delivery_status="retryable_failure",
                accepted=False,
                failure_code="transport_error",
            )
        except ImportError:
            return DeliveryAttemptResult(
                envelope_id=envelope.envelope_id,
                delivery_status="retryable_failure",
                accepted=False,
                failure_code="transport_configuration_error",
            )
        if 200 <= response.status_code < 300:
            return self._classify_success(envelope_id=envelope.envelope_id, response=response)
        return self._classify_status_failure(envelope.envelope_id, response)

    def deliver_record(self, record: DeliveryOutboxRecord) -> DeliveryAttemptResult:
        payload = self._normalize_record_payload(record)
        envelope_type = str(payload.get("envelope_type"))
        model_map = {
            "decision": DecisionEnvelope,
            "notification": NotificationEnvelope,
            "approval": ApprovalEnvelope,
        }
        model = model_map.get(envelope_type)
        if model is None:
            return DeliveryAttemptResult(
                envelope_id=record.envelope_id,
                delivery_status="delivery_failed",
                accepted=False,
                failure_code="unsupported_envelope_type",
            )
        envelope = model.model_validate(payload)
        return self.deliver_envelope(envelope)
