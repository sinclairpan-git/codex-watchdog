from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from watchdog.services.delivery.envelopes import (
    ApprovalEnvelope,
    DecisionEnvelope,
    NotificationEnvelope,
)
from watchdog.services.delivery.http_client import DeliveryAttemptResult
from watchdog.services.delivery.store import DeliveryOutboxRecord
from watchdog.settings import Settings


def _iso_z(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(slots=True)
class _TenantToken:
    value: str
    expires_at: datetime


class FeishuAppDeliveryClient:
    def __init__(
        self,
        *,
        settings: Settings,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._tenant_token: _TenantToken | None = None

    def configured(self) -> bool:
        return all(
            [
                str(self._settings.feishu_base_url or "").strip(),
                str(self._settings.feishu_app_id or "").strip(),
                str(self._settings.feishu_app_secret or "").strip(),
                str(self._settings.feishu_receive_id or "").strip(),
                str(self._settings.feishu_receive_id_type or "").strip(),
            ]
        )

    def deliver_record(self, record: DeliveryOutboxRecord) -> DeliveryAttemptResult:
        payload = dict(record.envelope_payload)
        model_map = {
            "decision": DecisionEnvelope,
            "notification": NotificationEnvelope,
            "approval": ApprovalEnvelope,
        }
        model = model_map.get(str(payload.get("envelope_type")))
        if model is None:
            return DeliveryAttemptResult(
                envelope_id=record.envelope_id,
                delivery_status="delivery_failed",
                accepted=False,
                failure_code="unsupported_envelope_type",
            )
        envelope = model.model_validate(payload)
        return self.deliver_envelope(envelope)

    def deliver_envelope(
        self,
        envelope: DecisionEnvelope | NotificationEnvelope | ApprovalEnvelope,
    ) -> DeliveryAttemptResult:
        if not self.configured():
            return DeliveryAttemptResult(
                envelope_id=envelope.envelope_id,
                delivery_status="delivery_failed",
                accepted=False,
                failure_code="feishu_not_configured",
            )
        try:
            tenant_token = self._tenant_access_token()
        except httpx.TimeoutException:
            return DeliveryAttemptResult(
                envelope_id=envelope.envelope_id,
                delivery_status="retryable_failure",
                accepted=False,
                failure_code="transport_timeout",
            )
        except httpx.HTTPStatusError as exc:
            return self._classify_http_status_failure(
                envelope_id=envelope.envelope_id,
                status_code=exc.response.status_code,
            )
        except httpx.RequestError:
            return DeliveryAttemptResult(
                envelope_id=envelope.envelope_id,
                delivery_status="retryable_failure",
                accepted=False,
                failure_code="transport_error",
            )
        except ValueError:
            return DeliveryAttemptResult(
                envelope_id=envelope.envelope_id,
                delivery_status="retryable_failure",
                accepted=False,
                failure_code="protocol_incomplete",
            )

        url = (
            f"{str(self._settings.feishu_base_url).rstrip('/')}"
            "/open-apis/im/v1/messages"
        )
        body = {
            "receive_id": str(self._settings.feishu_receive_id),
            "msg_type": "text",
            "content": json.dumps(
                {"text": self._render_text(envelope)},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        }
        try:
            with httpx.Client(
                timeout=self._settings.http_timeout_s,
                transport=self._transport,
                trust_env=False,
            ) as client:
                response = client.post(
                    url,
                    params={"receive_id_type": str(self._settings.feishu_receive_id_type)},
                    headers={
                        "Authorization": f"Bearer {tenant_token}",
                        "Content-Type": "application/json; charset=utf-8",
                    },
                    json=body,
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
        return self._classify_http_status_failure(
            envelope_id=envelope.envelope_id,
            status_code=response.status_code,
        )

    def _tenant_access_token(self) -> str:
        current = self._tenant_token
        now = datetime.now(UTC)
        if current is not None and current.expires_at > now + timedelta(seconds=30):
            return current.value
        url = (
            f"{str(self._settings.feishu_base_url).rstrip('/')}"
            "/open-apis/auth/v3/tenant_access_token/internal"
        )
        with httpx.Client(
            timeout=self._settings.http_timeout_s,
            transport=self._transport,
            trust_env=False,
        ) as client:
            response = client.post(
                url,
                json={
                    "app_id": str(self._settings.feishu_app_id),
                    "app_secret": str(self._settings.feishu_app_secret),
                },
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
            response.raise_for_status()
        body = response.json()
        if int(body.get("code", 1)) != 0:
            raise ValueError("feishu tenant token rejected")
        token = str(body.get("tenant_access_token") or "").strip()
        if not token:
            raise ValueError("feishu tenant token missing")
        expire_seconds = int(body.get("expire") or 7200)
        self._tenant_token = _TenantToken(
            value=token,
            expires_at=now + timedelta(seconds=max(expire_seconds, 60)),
        )
        return token

    @staticmethod
    def _classify_http_status_failure(
        *,
        envelope_id: str,
        status_code: int,
    ) -> DeliveryAttemptResult:
        return DeliveryAttemptResult(
            envelope_id=envelope_id,
            delivery_status=(
                "retryable_failure" if status_code in {408, 429} or status_code >= 500 else "delivery_failed"
            ),
            accepted=False,
            failure_code=f"http_{status_code}",
            status_code=status_code,
        )

    @staticmethod
    def _classify_success(
        *,
        envelope_id: str,
        response: httpx.Response,
    ) -> DeliveryAttemptResult:
        try:
            body = response.json()
        except ValueError:
            return DeliveryAttemptResult(
                envelope_id=envelope_id,
                delivery_status="retryable_failure",
                accepted=False,
                failure_code="protocol_incomplete",
                status_code=response.status_code,
            )
        if int(body.get("code", 1)) != 0:
            return DeliveryAttemptResult(
                envelope_id=envelope_id,
                delivery_status="retryable_failure",
                accepted=False,
                failure_code="protocol_incomplete",
                status_code=response.status_code,
            )
        data = body.get("data")
        if not isinstance(data, dict):
            return DeliveryAttemptResult(
                envelope_id=envelope_id,
                delivery_status="retryable_failure",
                accepted=False,
                failure_code="protocol_incomplete",
                status_code=response.status_code,
            )
        message_id = str(data.get("message_id") or "").strip()
        if not message_id:
            return DeliveryAttemptResult(
                envelope_id=envelope_id,
                delivery_status="retryable_failure",
                accepted=False,
                failure_code="protocol_incomplete",
                status_code=response.status_code,
            )
        return DeliveryAttemptResult(
            envelope_id=envelope_id,
            delivery_status="delivered",
            accepted=True,
            receipt_id=message_id,
            received_at=_iso_z(datetime.now(UTC)),
            status_code=response.status_code,
        )

    @staticmethod
    def _render_text(
        envelope: DecisionEnvelope | NotificationEnvelope | ApprovalEnvelope,
    ) -> str:
        lines: list[str] = [
            f"[watchdog] {envelope.envelope_type}",
            f"project={envelope.project_id}",
            f"session={envelope.session_id}",
        ]
        title = str(getattr(envelope, "title", "") or "").strip()
        summary = str(getattr(envelope, "summary", "") or "").strip()
        reason = str(getattr(envelope, "reason", "") or "").strip()
        if title:
            lines.append(f"title={title}")
        if summary:
            lines.append(f"summary={summary}")
        if reason:
            lines.append(f"reason={reason}")
        if isinstance(envelope, DecisionEnvelope):
            lines.append(f"decision={envelope.decision_result}")
            lines.append(f"action={envelope.action_name}")
        if isinstance(envelope, ApprovalEnvelope):
            lines.append(f"approval_id={envelope.approval_id}")
            lines.append(f"requested_action={envelope.requested_action}")
            lines.append(f"options={','.join(envelope.decision_options)}")
        if isinstance(envelope, NotificationEnvelope):
            lines.append(f"notification_kind={envelope.notification_kind}")
            lines.append(f"severity={envelope.severity}")
        lines.append(f"envelope_id={envelope.envelope_id}")
        return "\n".join(lines)
