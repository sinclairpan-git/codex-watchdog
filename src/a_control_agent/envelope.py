from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any


def iso_ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def ok(request_id: str | None, data: Any) -> dict[str, Any]:
    return {
        "success": True,
        "request_id": request_id or f"req_{uuid.uuid4().hex[:12]}",
        "data": data,
        "error": None,
        "ts": iso_ts(),
    }


def err(request_id: str | None, error: dict[str, Any], data: Any | None = None) -> dict[str, Any]:
    return {
        "success": False,
        "request_id": request_id or f"req_{uuid.uuid4().hex[:12]}",
        "data": data,
        "error": error,
        "ts": iso_ts(),
    }
