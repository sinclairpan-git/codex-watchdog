from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx

from watchdog.settings import Settings


class AControlAgentClient:
    """通过 HTTP 调用 A-Control-Agent，返回完整 envelope JSON。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._settings.a_agent_token}"}

    def get_envelope(self, project_id: str) -> dict[str, Any]:
        url = f"{self._settings.a_agent_base_url.rstrip('/')}/api/v1/tasks/{project_id}"
        with httpx.Client(timeout=self._settings.http_timeout_s) as client:
            try:
                resp = client.get(url, headers=self._auth_headers())
            except httpx.RequestError as exc:
                raise exc
            try:
                body = resp.json()
            except ValueError as exc:
                raise RuntimeError("invalid_json_from_a_agent") from exc
            if isinstance(body, dict):
                return body
            raise RuntimeError("invalid_envelope_shape")

    def get_envelope_by_thread(self, thread_id: str) -> dict[str, Any]:
        url = f"{self._settings.a_agent_base_url.rstrip('/')}/api/v1/tasks/by-thread/{thread_id}"
        with httpx.Client(timeout=self._settings.http_timeout_s) as client:
            try:
                resp = client.get(url, headers=self._auth_headers())
            except httpx.RequestError as exc:
                raise exc
            try:
                body = resp.json()
            except ValueError as exc:
                raise RuntimeError("invalid_json_from_a_agent") from exc
            if isinstance(body, dict):
                return body
            raise RuntimeError("invalid_envelope_shape")

    def list_tasks(self) -> list[dict[str, Any]]:
        url = f"{self._settings.a_agent_base_url.rstrip('/')}/api/v1/tasks"
        with httpx.Client(timeout=self._settings.http_timeout_s) as client:
            try:
                resp = client.get(url, headers=self._auth_headers())
            except httpx.RequestError as exc:
                raise exc
            try:
                body = resp.json()
            except ValueError as exc:
                raise RuntimeError("invalid_json_from_a_agent") from exc
            if not isinstance(body, dict):
                raise RuntimeError("invalid_envelope_shape")
            if not body.get("success"):
                return []
            data = body.get("data")
            if not isinstance(data, dict):
                raise RuntimeError("invalid_envelope_shape")
            tasks = data.get("tasks")
            if not isinstance(tasks, list):
                raise RuntimeError("invalid_envelope_shape")
            return [dict(task) for task in tasks if isinstance(task, dict)]

    def list_approvals(self, *, status: str | None = None) -> list[dict[str, Any]]:
        url = f"{self._settings.a_agent_base_url.rstrip('/')}/api/v1/approvals"
        params: dict[str, str] = {}
        if status:
            params["status"] = status
        with httpx.Client(timeout=self._settings.http_timeout_s) as client:
            try:
                resp = client.get(url, headers=self._auth_headers(), params=params)
            except httpx.RequestError as exc:
                raise exc
            try:
                body = resp.json()
            except ValueError as exc:
                raise RuntimeError("invalid_json_from_a_agent") from exc
            if not isinstance(body, dict):
                raise RuntimeError("invalid_envelope_shape")
            if not body.get("success"):
                return []
            data = body.get("data")
            if not isinstance(data, dict):
                raise RuntimeError("invalid_envelope_shape")
            items = data.get("items")
            if not isinstance(items, list):
                raise RuntimeError("invalid_envelope_shape")
            return [dict(item) for item in items if isinstance(item, dict)]

    def decide_approval(
        self,
        approval_id: str,
        *,
        decision: str,
        operator: str,
        note: str = "",
    ) -> dict[str, Any]:
        url = f"{self._settings.a_agent_base_url.rstrip('/')}/api/v1/approvals/{approval_id}/decision"
        payload: dict[str, Any] = {
            "decision": decision,
            "operator": operator,
        }
        if note:
            payload["note"] = note
        with httpx.Client(timeout=self._settings.http_timeout_s) as client:
            try:
                resp = client.post(url, headers=self._auth_headers(), json=payload)
            except httpx.RequestError as exc:
                raise exc
            try:
                body = resp.json()
            except ValueError as exc:
                raise RuntimeError("invalid_json_from_a_agent") from exc
            if isinstance(body, dict):
                return body
            raise RuntimeError("invalid_envelope_shape")

    def trigger_handoff(
        self,
        project_id: str,
        *,
        reason: str,
    ) -> dict[str, Any]:
        url = f"{self._settings.a_agent_base_url.rstrip('/')}/api/v1/tasks/{project_id}/handoff"
        with httpx.Client(timeout=self._settings.http_timeout_s) as client:
            try:
                resp = client.post(
                    url,
                    headers=self._auth_headers(),
                    json={"reason": reason},
                )
                resp.raise_for_status()
            except httpx.RequestError as exc:
                raise exc
            except httpx.HTTPError as exc:
                raise RuntimeError("handoff_http_error") from exc
            try:
                body = resp.json()
            except ValueError as exc:
                raise RuntimeError("invalid_json_from_a_agent") from exc
            if isinstance(body, dict):
                return body
            raise RuntimeError("invalid_envelope_shape")

    def trigger_resume(
        self,
        project_id: str,
        *,
        mode: str,
        handoff_summary: str,
    ) -> dict[str, Any]:
        url = f"{self._settings.a_agent_base_url.rstrip('/')}/api/v1/tasks/{project_id}/resume"
        payload = {
            "mode": mode,
            "handoff_summary": handoff_summary,
        }
        with httpx.Client(timeout=self._settings.http_timeout_s) as client:
            try:
                resp = client.post(url, headers=self._auth_headers(), json=payload)
                resp.raise_for_status()
            except httpx.RequestError as exc:
                raise exc
            except httpx.HTTPError as exc:
                raise RuntimeError("resume_http_error") from exc
            try:
                body = resp.json()
            except ValueError as exc:
                raise RuntimeError("invalid_json_from_a_agent") from exc
            if isinstance(body, dict):
                return body
            raise RuntimeError("invalid_envelope_shape")

    def get_events_snapshot(
        self,
        project_id: str,
        *,
        poll_interval: float = 0.5,
    ) -> tuple[str, str] | dict[str, Any]:
        url = f"{self._settings.a_agent_base_url.rstrip('/')}/api/v1/tasks/{project_id}/events"
        params = {"follow": "false", "poll_interval": str(poll_interval)}
        with httpx.Client(timeout=self._settings.http_timeout_s) as client:
            try:
                resp = client.get(url, headers=self._auth_headers(), params=params)
            except httpx.RequestError as exc:
                raise exc
        content_type = str(resp.headers.get("content-type", ""))
        if content_type.startswith("text/event-stream"):
            return resp.text, content_type
        try:
            body = resp.json()
        except ValueError as exc:
            raise RuntimeError("invalid_json_from_a_agent") from exc
        if isinstance(body, dict):
            return body
        raise RuntimeError("invalid_envelope_shape")

    def iter_events(
        self,
        project_id: str,
        *,
        poll_interval: float = 0.5,
    ) -> Iterator[str]:
        url = f"{self._settings.a_agent_base_url.rstrip('/')}/api/v1/tasks/{project_id}/events"
        params = {"follow": "true", "poll_interval": str(poll_interval)}
        timeout = httpx.Timeout(self._settings.http_timeout_s, read=None)
        with httpx.Client(timeout=timeout) as client:
            with client.stream("GET", url, headers=self._auth_headers(), params=params) as resp:
                content_type = str(resp.headers.get("content-type", ""))
                if not content_type.startswith("text/event-stream"):
                    raise RuntimeError("invalid_event_stream_from_a_agent")
                for chunk in resp.iter_text():
                    if chunk:
                        yield chunk
