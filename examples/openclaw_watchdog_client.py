#!/usr/bin/env python3
"""
OpenClaw 侧调用 Watchdog 的最小模板（仅 HTTP，无飞书/OpenClaw runtime）。

部署时设置环境变量：
  WATCHDOG_BASE_URL  例如 https://watchdog.internal:8720
  WATCHDOG_API_TOKEN  与 Watchdog 配置的 token 一致
  WATCHDOG_DEFAULT_PROJECT_ID  默认 project_id；显式传参优先
  WATCHDOG_OPERATOR  默认操作人；缺省为 openclaw
"""

from __future__ import annotations

import os
import sys

import httpx


class WatchdogTemplateClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_token: str | None = None,
        default_project_id: str | None = None,
        operator: str | None = None,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = (base_url or os.environ.get("WATCHDOG_BASE_URL", "http://127.0.0.1:8720")).rstrip("/")
        self._api_token = api_token if api_token is not None else os.environ.get("WATCHDOG_API_TOKEN", "")
        self._default_project_id = (
            default_project_id
            if default_project_id is not None
            else os.environ.get("WATCHDOG_DEFAULT_PROJECT_ID")
        )
        self._operator = operator if operator is not None else os.environ.get("WATCHDOG_OPERATOR", "openclaw")
        self._timeout = timeout
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_token}"} if self._api_token else {}

    def _resolve_project_id(self, project_id: str | None) -> str:
        resolved = project_id or self._default_project_id
        if resolved:
            return resolved
        raise ValueError("project_id is required; pass project_id or set WATCHDOG_DEFAULT_PROJECT_ID")

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, str] | None = None,
    ) -> dict:
        with httpx.Client(
            base_url=self._base_url,
            headers=self._headers(),
            timeout=self._timeout,
            transport=self._transport,
        ) as client:
            response = client.request(method, path, params=params, json=body)
            response.raise_for_status()
            return response.json()

    def _require_idempotency_key(self, idempotency_key: str) -> str:
        resolved = idempotency_key.strip()
        if resolved:
            return resolved
        raise ValueError("idempotency_key is required for write actions")

    def query_progress(self, project_id: str | None = None) -> dict:
        pid = self._resolve_project_id(project_id)
        return self._request_json("GET", f"/api/v1/watchdog/sessions/{pid}/progress")

    def query_stuck(self, project_id: str | None = None) -> dict:
        pid = self._resolve_project_id(project_id)
        return self._request_json("GET", f"/api/v1/watchdog/sessions/{pid}/stuck-explanation")

    def continue_session(
        self,
        project_id: str | None = None,
        *,
        operator: str | None = None,
        idempotency_key: str,
    ) -> dict:
        pid = self._resolve_project_id(project_id)
        payload = {
            "operator": operator or self._operator,
            "idempotency_key": self._require_idempotency_key(idempotency_key),
        }
        return self._request_json(
            "POST",
            f"/api/v1/watchdog/sessions/{pid}/actions/continue",
            body=payload,
        )

    def list_approval_inbox(self, *, project_id: str | None = None) -> dict:
        resolved = project_id or self._default_project_id
        params = {"project_id": resolved} if resolved else None
        return self._request_json("GET", "/api/v1/watchdog/approval-inbox", params=params)

    def approve_approval(
        self,
        approval_id: str,
        *,
        operator: str | None = None,
        idempotency_key: str,
        note: str = "",
    ) -> dict:
        return self._request_json(
            "POST",
            f"/api/v1/watchdog/approvals/{approval_id}/approve",
            body={
                "operator": operator or self._operator,
                "idempotency_key": self._require_idempotency_key(idempotency_key),
                "note": note,
            },
        )

    def reject_approval(
        self,
        approval_id: str,
        *,
        operator: str | None = None,
        idempotency_key: str,
        note: str = "",
    ) -> dict:
        return self._request_json(
            "POST",
            f"/api/v1/watchdog/approvals/{approval_id}/reject",
            body={
                "operator": operator or self._operator,
                "idempotency_key": self._require_idempotency_key(idempotency_key),
                "note": note,
            },
        )

    def post_openclaw_response(
        self,
        *,
        envelope_id: str,
        envelope_type: str,
        approval_id: str,
        decision_id: str,
        response_action: str,
        response_token: str,
        user_ref: str,
        channel_ref: str,
        client_request_id: str,
        operator: str | None = None,
        note: str = "",
    ) -> dict:
        return self._request_json(
            "POST",
            "/api/v1/watchdog/openclaw/responses",
            body={
                "envelope_id": envelope_id,
                "envelope_type": envelope_type,
                "approval_id": approval_id,
                "decision_id": decision_id,
                "response_action": response_action,
                "response_token": response_token,
                "user_ref": user_ref,
                "channel_ref": channel_ref,
                "client_request_id": client_request_id,
                "operator": operator or self._operator,
                "note": note,
            },
        )


def fetch_progress(project_id: str | None = None) -> dict:
    return WatchdogTemplateClient().query_progress(project_id)


def main() -> None:
    pid = sys.argv[1] if len(sys.argv) > 1 else None
    body = fetch_progress(pid)
    print(body)


if __name__ == "__main__":
    main()
