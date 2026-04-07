from __future__ import annotations

from datetime import datetime, timezone

import httpx
from pydantic import BaseModel

from watchdog.services.delivery.envelopes import ApprovalEnvelope, DecisionEnvelope, NotificationEnvelope
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
    def __init__(self, *, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        self._settings = settings
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
        ):
            return DeliveryAttemptResult(
                envelope_id=envelope_id,
                delivery_status="delivered",
                accepted=True,
                receipt_id=str(body["receipt_id"]),
                received_at=str(body.get("received_at") or ""),
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

    def deliver_envelope(
        self,
        envelope: DecisionEnvelope | NotificationEnvelope | ApprovalEnvelope,
    ) -> DeliveryAttemptResult:
        url = f"{self._settings.openclaw_webhook_base_url.rstrip('/')}/openclaw/v1/watchdog/envelopes"
        with httpx.Client(timeout=self._settings.http_timeout_s, transport=self._transport) as client:
            try:
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
        if 200 <= response.status_code < 300:
            return self._classify_success(envelope_id=envelope.envelope_id, response=response)
        return self._classify_status_failure(envelope.envelope_id, response)

    def deliver_record(self, record: DeliveryOutboxRecord) -> DeliveryAttemptResult:
        envelope_type = str(record.envelope_payload.get("envelope_type"))
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
        envelope = model.model_validate(record.envelope_payload)
        return self.deliver_envelope(envelope)
