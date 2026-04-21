from __future__ import annotations

from contextlib import ExitStack
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

    def _client_kwargs(self, *, timeout: float | httpx.Timeout | None = None) -> dict[str, Any]:
        return {
            "timeout": self._settings.http_timeout_s if timeout is None else timeout,
            "trust_env": False,
        }

    def get_envelope(self, project_id: str) -> dict[str, Any]:
        url = f"{self._settings.a_agent_base_url.rstrip('/')}/api/v1/tasks/{project_id}"
        with httpx.Client(**self._client_kwargs()) as client:
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
        with httpx.Client(**self._client_kwargs()) as client:
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
        with httpx.Client(**self._client_kwargs()) as client:
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
                raise RuntimeError("task_list_failed")
            data = body.get("data")
            if not isinstance(data, dict):
                raise RuntimeError("invalid_envelope_shape")
            tasks = data.get("tasks")
            if not isinstance(tasks, list):
                raise RuntimeError("invalid_envelope_shape")
            return [dict(task) for task in tasks if isinstance(task, dict)]

    def register_native_thread(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._settings.a_agent_base_url.rstrip('/')}/api/v1/tasks/native-threads"
        with httpx.Client(**self._client_kwargs()) as client:
            try:
                resp = client.post(url, headers=self._auth_headers(), json=payload)
                resp.raise_for_status()
            except httpx.RequestError as exc:
                raise exc
            except httpx.HTTPError as exc:
                raise RuntimeError("register_native_thread_http_error") from exc
            try:
                body = resp.json()
            except ValueError as exc:
                raise RuntimeError("invalid_json_from_a_agent") from exc
            if isinstance(body, dict):
                return body
            raise RuntimeError("invalid_envelope_shape")

    def list_approvals(
        self,
        *,
        status: str | None = None,
        project_id: str | None = None,
        decided_by: str | None = None,
        callback_status: str | None = None,
    ) -> list[dict[str, Any]]:
        url = f"{self._settings.a_agent_base_url.rstrip('/')}/api/v1/approvals"
        params: dict[str, str] = {}
        if status:
            params["status"] = status
        if project_id:
            params["project_id"] = project_id
        if decided_by:
            params["decided_by"] = decided_by
        if callback_status:
            params["callback_status"] = callback_status
        with httpx.Client(**self._client_kwargs()) as client:
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
                raise RuntimeError("approval_list_failed")
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
        with httpx.Client(**self._client_kwargs()) as client:
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
        continuation_packet: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._settings.a_agent_base_url.rstrip('/')}/api/v1/tasks/{project_id}/handoff"
        payload: dict[str, Any] = {"reason": reason}
        if continuation_packet is not None:
            payload["continuation_packet"] = continuation_packet
        with httpx.Client(**self._client_kwargs()) as client:
            try:
                resp = client.post(
                    url,
                    headers=self._auth_headers(),
                    json=payload,
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

    def trigger_pause(self, project_id: str) -> dict[str, Any]:
        url = f"{self._settings.a_agent_base_url.rstrip('/')}/api/v1/tasks/{project_id}/pause"
        with httpx.Client(**self._client_kwargs()) as client:
            try:
                resp = client.post(
                    url,
                    headers=self._auth_headers(),
                    json={},
                )
                resp.raise_for_status()
            except httpx.RequestError as exc:
                raise exc
            except httpx.HTTPError as exc:
                raise RuntimeError("pause_http_error") from exc
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
        continuation_packet: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._settings.a_agent_base_url.rstrip('/')}/api/v1/tasks/{project_id}/resume"
        payload: dict[str, Any] = {
            "mode": mode,
            "handoff_summary": handoff_summary,
        }
        if continuation_packet is not None:
            payload["continuation_packet"] = continuation_packet
        with httpx.Client(**self._client_kwargs()) as client:
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
        with httpx.Client(**self._client_kwargs()) as client:
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

    def get_workspace_activity_envelope(
        self,
        project_id: str,
        *,
        recent_minutes: int = 15,
    ) -> dict[str, Any]:
        url = f"{self._settings.a_agent_base_url.rstrip('/')}/api/v1/tasks/{project_id}/workspace-activity"
        params = {"recent_minutes": str(recent_minutes)}
        with httpx.Client(**self._client_kwargs()) as client:
            try:
                resp = client.get(url, headers=self._auth_headers(), params=params)
            except httpx.RequestError as exc:
                raise exc
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
        stack = ExitStack()
        try:
            client = stack.enter_context(httpx.Client(**self._client_kwargs(timeout=timeout)))
            resp = stack.enter_context(
                client.stream("GET", url, headers=self._auth_headers(), params=params)
            )
            content_type = str(resp.headers.get("content-type", ""))
            if not content_type.startswith("text/event-stream"):
                raise RuntimeError("invalid_event_stream_from_a_agent")
        except Exception:
            stack.close()
            raise

        def _iter_chunks() -> Iterator[str]:
            try:
                for chunk in resp.iter_text():
                    if chunk:
                        yield chunk
            finally:
                stack.close()

        return _iter_chunks()
