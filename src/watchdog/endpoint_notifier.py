from __future__ import annotations
import logging
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import httpx
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

TRYCLOUDFLARE_URL_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.IGNORECASE)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _isoformat(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def extract_latest_trycloudflare_url(log_text: str) -> str | None:
    matches = TRYCLOUDFLARE_URL_PATTERN.findall(log_text)
    if not matches:
        return None
    return matches[-1]


class EndpointNotifierSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WATCHDOG_")

    bootstrap_webhook_base_url: str = "http://127.0.0.1:8740"
    bootstrap_webhook_token: str = "dev-token-change-me"
    public_tunnel_log_path: str = str(Path.home() / "Library/Logs/openclaw-watchdog.public-tunnel.err.log")
    public_url_state_file: str = ".data/watchdog/public_endpoint_state.json"
    public_url_notify_interval_seconds: float = 10.0
    public_url_source: str = "a-host-watchdog"
    http_timeout_s: float = 3.0


class EndpointBootstrapState(BaseModel):
    watchdog_base_url: str
    changed_at: str
    notified_at: str
    source: str


class EndpointNotifierClient(Protocol):
    def notify_watchdog_base_url_changed(
        self,
        *,
        watchdog_base_url: str,
        changed_at: datetime,
        source: str,
    ) -> None: ...


class OpenClawBootstrapClient:
    def __init__(
        self,
        *,
        settings: EndpointNotifierSettings,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport

    def notify_watchdog_base_url_changed(
        self,
        *,
        watchdog_base_url: str,
        changed_at: datetime,
        source: str,
    ) -> None:
        url = (
            f"{self._settings.bootstrap_webhook_base_url.rstrip('/')}"
            "/openclaw/v1/watchdog/bootstrap"
        )
        payload = {
            "event_type": "watchdog_base_url_changed",
            "watchdog_base_url": watchdog_base_url,
            "changed_at": changed_at.isoformat(),
            "source": source,
        }
        headers = {
            "Authorization": f"Bearer {self._settings.bootstrap_webhook_token}",
            "Content-Type": "application/json",
        }
        with httpx.Client(
            timeout=self._settings.http_timeout_s,
            transport=self._transport,
            trust_env=False,
        ) as client:
            response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or body.get("accepted") is not True:
            raise RuntimeError("bootstrap webhook rejected watchdog_base_url update")


class EndpointNotifier:
    def __init__(
        self,
        *,
        settings: EndpointNotifierSettings,
        client: EndpointNotifierClient,
    ) -> None:
        self._settings = settings
        self._client = client
        self._log_path = Path(settings.public_tunnel_log_path)
        self._state_path = Path(settings.public_url_state_file)

    def _read_latest_watchdog_base_url(self) -> str | None:
        if not self._log_path.exists():
            return None
        return extract_latest_trycloudflare_url(self._log_path.read_text(encoding="utf-8"))

    def _load_state(self) -> EndpointBootstrapState | None:
        if not self._state_path.exists():
            return None
        return EndpointBootstrapState.model_validate_json(self._state_path.read_text(encoding="utf-8"))

    def _save_state(self, state: EndpointBootstrapState) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(
            state.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def run_once(self, *, now: datetime | None = None) -> str:
        watchdog_base_url = self._read_latest_watchdog_base_url()
        if not watchdog_base_url:
            return "missing_url"
        existing_state = self._load_state()
        if existing_state is not None and existing_state.watchdog_base_url == watchdog_base_url:
            return "unchanged"
        changed_at = now or _utc_now()
        self._client.notify_watchdog_base_url_changed(
            watchdog_base_url=watchdog_base_url,
            changed_at=changed_at,
            source=self._settings.public_url_source,
        )
        self._save_state(
            EndpointBootstrapState(
                watchdog_base_url=watchdog_base_url,
                changed_at=_isoformat(changed_at),
                notified_at=_isoformat(_utc_now()),
                source=self._settings.public_url_source,
            )
        )
        return "notified"

    def run_forever(self) -> None:
        interval_seconds = max(self._settings.public_url_notify_interval_seconds, 0.1)
        while True:
            try:
                result = self.run_once()
                if result == "notified":
                    logger.info("watchdog public url updated and notified")
            except Exception:
                logger.exception("watchdog endpoint notifier iteration failed")
            time.sleep(interval_seconds)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = EndpointNotifierSettings()
    notifier = EndpointNotifier(
        settings=settings,
        client=OpenClawBootstrapClient(settings=settings),
    )
    notifier.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
