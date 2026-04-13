from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class OpenClawWebhookReceipt(BaseModel):
    """Compatibility receipt contract for legacy OpenClaw delivery hosts."""

    accepted: bool = True
    envelope_id: str
    receipt_id: str
    received_at: str


class OpenClawResponseRequest(BaseModel):
    """Compatibility-only response contract preserved during Feishu control-plane migration."""

    envelope_id: str
    envelope_type: str
    approval_id: str
    decision_id: str
    response_action: str
    response_token: str
    user_ref: str
    channel_ref: str
    client_request_id: str
    operator: str = "openclaw"
    note: str = ""


class OpenClawWebhookBootstrapRequest(BaseModel):
    """Compatibility-only webhook bootstrap contract for legacy OpenClaw hosts."""

    event_type: str
    openclaw_webhook_base_url: str
    changed_at: str
    source: str


class OpenClawWebhookBootstrapReceipt(BaseModel):
    """Compatibility receipt for persisted legacy OpenClaw webhook state."""

    accepted: bool = True
    openclaw_webhook_base_url: str
    updated_at: str
