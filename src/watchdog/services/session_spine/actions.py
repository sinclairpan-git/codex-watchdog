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
from watchdog.services.session_spine.recovery import perform_recovery_execution
from watchdog.services.session_spine.service import (
    SessionSpineUpstreamError,
    build_session_read_bundle,
)
from watchdog.services.session_spine.supervision import execute_supervision_evaluation
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


def _invalid_action_arguments(action: WatchdogAction, message: str) -> WatchdogActionResult:
    return _result(
        action,
        action_status=ActionStatus.ERROR,
        effect=Effect.NOOP,
        reply_code=ReplyCode.ACTION_NOT_AVAILABLE,
        message=message,
    )


def _validate_steer_response_or_raise(steer_body: Any) -> None:
    if isinstance(steer_body, dict) and steer_body.get("success"):
        return
    if isinstance(steer_body, dict):
        error = steer_body.get("error")
        if isinstance(error, dict):
            raise SessionSpineUpstreamError(dict(error))
    raise SessionSpineUpstreamError(
        {"code": "CONTROL_LINK_ERROR", "message": "A 侧拒绝 steer"}
    )


def _normalize_operator_guidance_arguments(
    action: WatchdogAction,
) -> tuple[str, str, int | None] | WatchdogActionResult:
    message = str(action.arguments.get("message") or "").strip()
    if not message:
        return _invalid_action_arguments(action, "arguments.message is required")
    reason_code = str(action.arguments.get("reason_code") or "operator_guidance").strip()
    if not reason_code:
        reason_code = "operator_guidance"
    stuck_level_raw = action.arguments.get("stuck_level")
    if stuck_level_raw in (None, ""):
        return message, reason_code, None
    try:
        stuck_level = int(stuck_level_raw)
    except (TypeError, ValueError):
        return _invalid_action_arguments(action, "arguments.stuck_level must be an integer in 0..4")
    if stuck_level < 0 or stuck_level > 4:
        return _invalid_action_arguments(action, "arguments.stuck_level must be an integer in 0..4")
    return message, reason_code, stuck_level


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
        steer_body = post_steer(
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
    _validate_steer_response_or_raise(steer_body)
    return _result(
        action,
        action_status=ActionStatus.COMPLETED,
        effect=Effect.STEER_POSTED,
        reply_code=ReplyCode.ACTION_RESULT,
        message="continue request accepted",
        facts=bundle.facts,
    )


def _execute_operator_guidance(
    action: WatchdogAction,
    *,
    settings: Settings,
    client: AControlAgentClient,
) -> WatchdogActionResult:
    normalized = _normalize_operator_guidance_arguments(action)
    if isinstance(normalized, WatchdogActionResult):
        return normalized
    message, reason_code, stuck_level = normalized
    bundle = build_session_read_bundle(client, action.project_id)
    try:
        steer_body = post_steer(
            settings.a_agent_base_url,
            settings.a_agent_token,
            action.project_id,
            message=message,
            reason=reason_code,
            stuck_level=stuck_level,
            timeout=settings.http_timeout_s,
        )
    except (httpx.HTTPError, RuntimeError) as exc:
        raise SessionSpineUpstreamError(
            {"code": "CONTROL_LINK_ERROR", "message": "steer 调用失败：无法连接 A-Control-Agent"}
        ) from exc
    _validate_steer_response_or_raise(steer_body)
    return _result(
        action,
        action_status=ActionStatus.COMPLETED,
        effect=Effect.STEER_POSTED,
        reply_code=ReplyCode.ACTION_RESULT,
        message="operator guidance posted",
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


def _execute_recovery(
    action: WatchdogAction,
    *,
    settings: Settings,
    client: AControlAgentClient,
) -> WatchdogActionResult:
    outcome = perform_recovery_execution(
        action.project_id,
        settings=settings,
        client=client,
    )
    facts = list(outcome.facts)
    if outcome.action == "noop":
        return _result(
            action,
            action_status=ActionStatus.NOOP,
            effect=Effect.NOOP,
            reply_code=ReplyCode.RECOVERY_EXECUTION_RESULT,
            message="recovery not executed because context is not critical",
            facts=facts,
        )
    if outcome.action == "handoff_and_resume":
        return _result(
            action,
            action_status=ActionStatus.COMPLETED,
            effect=Effect.HANDOFF_AND_RESUME,
            reply_code=ReplyCode.RECOVERY_EXECUTION_RESULT,
            message="recovery handoff triggered and resume requested",
            facts=facts,
        )
    message = "recovery handoff triggered"
    if outcome.resume_error:
        message = "recovery handoff triggered; resume failed"
    return _result(
        action,
        action_status=ActionStatus.COMPLETED,
        effect=Effect.HANDOFF_TRIGGERED,
        reply_code=ReplyCode.RECOVERY_EXECUTION_RESULT,
        message=message,
        facts=facts,
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
    elif action.action_code == ActionCode.POST_OPERATOR_GUIDANCE:
        result = _execute_operator_guidance(action, settings=settings, client=client)
    elif action.action_code == ActionCode.REQUEST_RECOVERY:
        result = _execute_request_recovery(action, client=client)
    elif action.action_code == ActionCode.EXECUTE_RECOVERY:
        result = _execute_recovery(action, settings=settings, client=client)
    elif action.action_code == ActionCode.EVALUATE_SUPERVISION:
        result = execute_supervision_evaluation(action, settings=settings, client=client)
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
