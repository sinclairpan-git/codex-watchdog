from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, Query, Request

from a_control_agent.envelope import err
from watchdog.api.deps import require_token
from watchdog.settings import Settings

router = APIRouter(prefix="/watchdog", tags=["approvals"])


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def _a_headers(settings: Settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.codex_runtime_token}"}


def _a_client(settings: Settings) -> httpx.Client:
    return httpx.Client(timeout=settings.http_timeout_s, trust_env=False)


@router.get("/approvals")
def list_approvals_watchdog(
    request: Request,
    settings: Settings = Depends(get_settings),
    status: str | None = Query(default=None),
    _: None = Depends(require_token),
) -> dict[str, Any]:
    rid = request.headers.get("x-request-id")
    url = f"{settings.codex_runtime_base_url.rstrip('/')}/api/v1/approvals"
    params = {}
    if status:
        params["status"] = status
    try:
        with _a_client(settings) as client:
            r = client.get(url, headers=_a_headers(settings), params=params)
            body = r.json()
    except (httpx.RequestError, RuntimeError, OSError):
        return err(
            rid,
            {
                "code": "CONTROL_LINK_ERROR",
                "message": "无法连接 Codex runtime 控制链路",
            },
        )
    except ValueError:
        return err(rid, {"code": "CONTROL_LINK_ERROR", "message": "runtime 响应非 JSON"})
    if isinstance(body, dict):
        return body
    return err(rid, {"code": "CONTROL_LINK_ERROR", "message": "响应格式异常"})


@router.post("/approvals/{approval_id}/decision")
def decision_watchdog(
    approval_id: str,
    request: Request,
    body: dict[str, Any],
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_token),
) -> dict[str, Any]:
    rid = request.headers.get("x-request-id")
    url = f"{settings.codex_runtime_base_url.rstrip('/')}/api/v1/approvals/{approval_id}/decision"
    try:
        with _a_client(settings) as client:
            r = client.post(url, json=body, headers=_a_headers(settings))
            out = r.json()
    except (httpx.RequestError, RuntimeError, OSError):
        return err(
            rid,
            {
                "code": "CONTROL_LINK_ERROR",
                "message": "无法连接 Codex runtime 控制链路",
            },
        )
    except ValueError:
        return err(rid, {"code": "CONTROL_LINK_ERROR", "message": "runtime 响应非 JSON"})
    if isinstance(out, dict):
        return out
    return err(rid, {"code": "CONTROL_LINK_ERROR", "message": "响应格式异常"})
