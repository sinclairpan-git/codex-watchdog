from __future__ import annotations

from typing import Any

import httpx

from watchdog.settings import Settings


class AControlAgentClient:
    """通过 HTTP 调用 A-Control-Agent，返回完整 envelope JSON。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def get_envelope(self, project_id: str) -> dict[str, Any]:
        url = f"{self._settings.a_agent_base_url.rstrip('/')}/api/v1/tasks/{project_id}"
        headers = {"Authorization": f"Bearer {self._settings.a_agent_token}"}
        with httpx.Client(timeout=self._settings.http_timeout_s) as client:
            try:
                resp = client.get(url, headers=headers)
            except httpx.RequestError as exc:
                raise exc
            try:
                body = resp.json()
            except ValueError as exc:
                raise RuntimeError("invalid_json_from_a_agent") from exc
            if isinstance(body, dict):
                return body
            raise RuntimeError("invalid_envelope_shape")
