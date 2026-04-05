from __future__ import annotations

from typing import Any

import httpx

from watchdog.contracts.session_spine.enums import (
    ActionCode,
    ActionStatus,
    Effect,
    ReplyCode,
)
from watchdog.contracts.session_spine.models import WatchdogAction, WatchdogActionResult
from watchdog.services.action_executor.steer import SOFT_STEER_MESSAGE, post_steer
from watchdog.services.a_client.client import AControlAgentClient
from watchdog.services.session_spine.service import (
    SessionSpineUpstreamError,
    build_session_read_bundle,
)
from watchdog.settings import Settings
from watchdog.storage.action_receipts import ActionReceiptStore, receipt_key_for_action


def _result(
    action: WatchdogAction,
    *,
    action_status: ActionStatus,
    effect: Effect,
    reply_code: ReplyCode,
    message: str,
    approval_id: str | None = None,
    facts: list[Any] | None = None,
) -> WatchdogActionResult:
    return WatchdogActionResult(
        action_code=action.action_code,
        project_id=action.project_id,
        approval_id=approval_id,
        idempotency_key=action.idempotency_key,
        action_status=action_status,
        effect=effect,
        reply_code=reply_code,
        message=message,
        facts=list(facts or []),
    )


def _execute_continue(
    action: WatchdogAction,
    *,
    settings: Settings,
    client: AControlAgentClient,
) -> WatchdogActionResult:
    bundle = build_session_read_bundle(client, action.project_id)
    fact_codes = {fact.fact_code for fact in bundle.facts}
    if fact_codes.intersection({"approval_pending", "awaiting_human_direction"}):
        return _result(
            action,
            action_status=ActionStatus.BLOCKED,
            effect=Effect.NOOP,
            reply_code=ReplyCode.ACTION_NOT_AVAILABLE,
            message="session is awaiting human approval",
            facts=bundle.facts,
        )
    try:
        post_steer(
            settings.a_agent_base_url,
            settings.a_agent_token,
            action.project_id,
            message=SOFT_STEER_MESSAGE,
            reason="openclaw_continue_session",
            stuck_level=int(bundle.task.get("stuck_level", 0) or 0),
            timeout=settings.http_timeout_s,
        )
    except (httpx.HTTPError, RuntimeError) as exc:
        raise SessionSpineUpstreamError(
            {"code": "CONTROL_LINK_ERROR", "message": "steer 调用失败：无法连接 A-Control-Agent"}
        ) from exc
    return _result(
        action,
        action_status=ActionStatus.COMPLETED,
        effect=Effect.STEER_POSTED,
        reply_code=ReplyCode.ACTION_RESULT,
        message="continue request accepted",
        facts=bundle.facts,
    )


def _execute_request_recovery(
    action: WatchdogAction,
    *,
    client: AControlAgentClient,
) -> WatchdogActionResult:
    bundle = build_session_read_bundle(client, action.project_id)
    fact_codes = {fact.fact_code for fact in bundle.facts}
    message = "recovery is not currently advised"
    if "recovery_available" in fact_codes:
        message = "recovery is available"
    return _result(
        action,
        action_status=ActionStatus.COMPLETED,
        effect=Effect.ADVISORY_ONLY,
        reply_code=ReplyCode.RECOVERY_AVAILABILITY,
        message=message,
        facts=bundle.facts,
    )


def _execute_approval_action(
    action: WatchdogAction,
    *,
    client: AControlAgentClient,
    decision: str,
) -> WatchdogActionResult:
    approval_id = str(action.arguments.get("approval_id") or "")
    if not approval_id:
        return _result(
            action,
            action_status=ActionStatus.ERROR,
            effect=Effect.NOOP,
            reply_code=ReplyCode.ACTION_NOT_AVAILABLE,
            message="approval_id is required",
        )
    try:
        body = client.decide_approval(
            approval_id,
            decision=decision,
            operator=action.operator,
            note=action.note,
        )
    except (httpx.RequestError, RuntimeError, OSError) as exc:
        raise SessionSpineUpstreamError(
            {"code": "CONTROL_LINK_ERROR", "message": "无法连接 A-Control-Agent"}
        ) from exc
    if not body.get("success"):
        error = body.get("error")
        if isinstance(error, dict):
            raise SessionSpineUpstreamError(dict(error))
        raise SessionSpineUpstreamError(
            {"code": "CONTROL_LINK_ERROR", "message": "审批决定执行失败"}
        )
    return _result(
        action,
        action_status=ActionStatus.COMPLETED,
        effect=Effect.APPROVAL_DECIDED,
        reply_code=ReplyCode.APPROVAL_RESULT,
        message=f"approval {decision}d",
        approval_id=approval_id,
    )


def execute_watchdog_action(
    action: WatchdogAction,
    *,
    settings: Settings,
    client: AControlAgentClient,
    receipt_store: ActionReceiptStore,
) -> WatchdogActionResult:
    approval_id = str(action.arguments.get("approval_id") or "") or None
    receipt_key = receipt_key_for_action(action, approval_id)
    existing = receipt_store.get(receipt_key)
    if existing is not None:
        return existing

    if action.action_code == ActionCode.CONTINUE_SESSION:
        result = _execute_continue(action, settings=settings, client=client)
    elif action.action_code == ActionCode.REQUEST_RECOVERY:
        result = _execute_request_recovery(action, client=client)
    elif action.action_code == ActionCode.APPROVE_APPROVAL:
        result = _execute_approval_action(action, client=client, decision="approve")
    elif action.action_code == ActionCode.REJECT_APPROVAL:
        result = _execute_approval_action(action, client=client, decision="reject")
    else:
        result = _result(
            action,
            action_status=ActionStatus.NOT_AVAILABLE,
            effect=Effect.NOOP,
            reply_code=ReplyCode.ACTION_NOT_AVAILABLE,
            message=f"unsupported action: {action.action_code}",
        )
    return receipt_store.put(receipt_key, result)
