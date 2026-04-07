from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from watchdog.settings import Settings


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class OpenClawWebhookEndpointState(BaseModel):
    openclaw_webhook_base_url: str
    updated_at: str
    changed_at: str
    source: str


class OpenClawWebhookEndpointStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def get(self) -> OpenClawWebhookEndpointState | None:
        with self._lock:
            if not self._path.exists():
                return None
            raw = self._path.read_text(encoding="utf-8")
            if not raw.strip():
                return None
            return OpenClawWebhookEndpointState.model_validate_json(raw)

    def put(
        self,
        *,
        openclaw_webhook_base_url: str,
        changed_at: str,
        source: str,
        updated_at: str | None = None,
    ) -> OpenClawWebhookEndpointState:
        state = OpenClawWebhookEndpointState(
            openclaw_webhook_base_url=openclaw_webhook_base_url,
            updated_at=updated_at or _utc_now_iso(),
            changed_at=changed_at,
            source=source,
        )
        with self._lock:
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(state.model_dump_json(indent=2), encoding="utf-8")
            tmp.replace(self._path)
        return state


def openclaw_webhook_endpoint_state_path(settings: Settings) -> Path:
    if settings.openclaw_webhook_endpoint_state_file:
        return Path(settings.openclaw_webhook_endpoint_state_file)
    return Path(settings.data_dir) / "openclaw_webhook_endpoint.json"
