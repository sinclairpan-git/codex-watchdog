from __future__ import annotations

from pydantic import BaseModel


class DeliveryAttemptResult(BaseModel):
    envelope_id: str
    delivery_status: str
    accepted: bool
    receipt_id: str | None = None
    received_at: str | None = None
    failure_code: str | None = None
    status_code: int | None = None
