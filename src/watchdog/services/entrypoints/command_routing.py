from __future__ import annotations

from typing import Any

import httpx

from watchdog.services.a_client.client import AControlAgentClient
from watchdog.services.adapters.openclaw.intents import resolve_message_to_intent
from watchdog.services.session_spine.service import SessionSpineUpstreamError

_CONTROL_LINK_ERROR = {
    "code": "CONTROL_LINK_ERROR",
    "message": "A 侧返回数据格式异常",
}


def resolve_entry_message(message: str) -> str | None:
    return resolve_message_to_intent(message)


def resolve_entry_route(
    *,
    client: AControlAgentClient,
    intent_code: str,
    project_id: str | None = None,
    native_thread_id: str | None = None,
    arguments: dict[str, Any] | None = None,
) -> tuple[str, str | None, dict[str, Any]]:
    routed_arguments = dict(arguments or {})
    normalized_project_id = str(project_id or "").strip() or None
    normalized_native_thread_id = str(
        native_thread_id or routed_arguments.get("native_thread_id") or ""
    ).strip() or None
    if normalized_native_thread_id:
        routed_arguments.setdefault("native_thread_id", normalized_native_thread_id)
    if normalized_project_id:
        return intent_code, normalized_project_id, routed_arguments
    if not normalized_native_thread_id:
        return intent_code, None, routed_arguments
    if intent_code == "get_session":
        return "get_session_by_native_thread", None, routed_arguments
    task = _load_task_by_native_thread_or_raise(client, normalized_native_thread_id)
    routed_project_id = str(task.get("project_id") or "").strip()
    if not routed_project_id:
        raise SessionSpineUpstreamError(dict(_CONTROL_LINK_ERROR))
    return intent_code, routed_project_id, routed_arguments


def _load_task_by_native_thread_or_raise(
    client: AControlAgentClient,
    native_thread_id: str,
) -> dict[str, Any]:
    try:
        body = client.get_envelope_by_thread(native_thread_id)
    except (httpx.RequestError, RuntimeError, OSError) as exc:
        raise SessionSpineUpstreamError(dict(_CONTROL_LINK_ERROR)) from exc
    if not body.get("success"):
        error = body.get("error")
        if isinstance(error, dict):
            raise SessionSpineUpstreamError(dict(error))
        raise SessionSpineUpstreamError(dict(_CONTROL_LINK_ERROR))
    data = body.get("data")
    if not isinstance(data, dict):
        raise SessionSpineUpstreamError(dict(_CONTROL_LINK_ERROR))
    return data
