from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from watchdog.contracts.session_spine.enums import (
    ActionCode,
    ActionStatus,
    Effect,
    ReplyCode,
)
from watchdog.contracts.session_spine.models import WatchdogAction, WatchdogActionResult
from watchdog.services.action_executor.steer import (
    SOFT_STEER_MESSAGE,
    post_steer,
    steer_template_registry,
)
from watchdog.services.a_client.client import AControlAgentClient
from watchdog.services.session_service.service import SessionService
from watchdog.services.session_spine.recovery import perform_recovery_execution
from watchdog.services.session_spine.service import (
    SessionSpineUpstreamError,
    build_session_read_bundle,
)
from watchdog.services.session_spine.supervision import execute_supervision_evaluation
from watchdog.services.session_spine.task_state import (
    is_non_active_project_execution_state,
    is_terminal_task,
    normalize_project_execution_state,
    validate_action_transition,
)
from watchdog.settings import Settings
from watchdog.storage.action_receipts import ActionReceiptStore, receipt_key_for_action


def _build_action_read_bundle(
    action: WatchdogAction,
    *,
    client: AControlAgentClient,
    session_service: SessionService | None = None,
    store: Any | None = None,
    approval_store: Any | None = None,
    decision_store: Any | None = None,
):
    bundle = build_session_read_bundle(
        client,
        action.project_id,
        session_service=session_service,
        store=store,
        approval_store=approval_store,
        decision_store=decision_store,
    )
    if bundle.task is not None:
        return bundle
    fact_codes = {fact.fact_code for fact in bundle.facts}
    if fact_codes.intersection({"approval_pending", "awaiting_human_direction"}):
        return bundle
    return build_session_read_bundle(
        client,
        action.project_id,
        store=store,
        approval_store=approval_store,
        decision_store=decision_store,
    )


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


def _continuation_hard_block_result(
    action: WatchdogAction,
    *,
    bundle,
) -> WatchdogActionResult | None:
    fact_codes = {fact.fact_code for fact in bundle.facts}
    project_execution_state = normalize_project_execution_state(bundle.task)
    if is_non_active_project_execution_state(project_execution_state):
        return _result(
            action,
            action_status=ActionStatus.NOOP,
            effect=Effect.NOOP,
            reply_code=ReplyCode.ACTION_NOT_AVAILABLE,
            message="project is not active for continuation",
            facts=bundle.facts,
        )
    if "project_state_unavailable" in fact_codes:
        return _result(
            action,
            action_status=ActionStatus.BLOCKED,
            effect=Effect.NOOP,
            reply_code=ReplyCode.ACTION_NOT_AVAILABLE,
            message="authoritative project state is unavailable",
            facts=bundle.facts,
        )
    if fact_codes.intersection({"approval_pending", "awaiting_human_direction"}):
        return _result(
            action,
            action_status=ActionStatus.BLOCKED,
            effect=Effect.NOOP,
            reply_code=ReplyCode.ACTION_NOT_AVAILABLE,
            message="session is awaiting human approval",
            facts=bundle.facts,
        )
    if bool((bundle.task or {}).get("pending_approval")) or bool(
        getattr(bundle.session, "pending_approval_count", 0)
    ):
        return _result(
            action,
            action_status=ActionStatus.BLOCKED,
            effect=Effect.NOOP,
            reply_code=ReplyCode.ACTION_NOT_AVAILABLE,
            message="session is awaiting human approval",
            facts=bundle.facts,
        )
    return None


def _continuation_decision_class_for_action(action: WatchdogAction) -> str:
    if action.action_code == ActionCode.CONTINUE_SESSION:
        return "continue_current_branch"
    if action.action_code in {
        ActionCode.RESUME_SESSION,
        ActionCode.FORCE_HANDOFF,
        ActionCode.RETRY_WITH_CONSERVATIVE_PATH,
        ActionCode.EXECUTE_RECOVERY,
    }:
        return "recover_current_branch"
    return "blocked"


def _continuation_identity_for_bundle(bundle, *, decision_class: str) -> str | None:
    if decision_class in {"blocked", "await_human", "project_complete"}:
        return None
    native_thread_id = (
        str((bundle.task or {}).get("native_thread_id") or "").strip()
        or str(bundle.session.native_thread_id or "").strip()
        or "none"
    )
    return f"{bundle.project_id}:{bundle.session.thread_id}:{native_thread_id}:{decision_class}"


def _continuation_route_key_for_bundle(bundle, *, continuation_identity: str | None) -> str | None:
    if continuation_identity is None:
        return None
    snapshot_version = (
        str(getattr(bundle.snapshot, "fact_snapshot_version", "") or "").strip() or None
    )
    if snapshot_version is None:
        return None
    return f"{continuation_identity}:{snapshot_version}"


def _action_ref_for_code(action_code: ActionCode) -> str | None:
    return {
        ActionCode.CONTINUE_SESSION: "continue_session",
        ActionCode.RESUME_SESSION: "resume_session",
        ActionCode.FORCE_HANDOFF: "force_handoff",
        ActionCode.RETRY_WITH_CONSERVATIVE_PATH: "retry_with_conservative_path",
        ActionCode.EXECUTE_RECOVERY: "execute_recovery",
    }.get(action_code)


def _snapshot_epoch_for_bundle(bundle) -> str | None:
    session_seq = getattr(bundle.snapshot, "session_seq", None)
    if session_seq in (None, ""):
        return None
    return f"session-seq:{session_seq}"


def _continuation_governance_for_action(action: WatchdogAction, *, bundle) -> dict[str, str | None]:
    hidden = (
        action.arguments.get("_continuation_governance")
        if isinstance(action.arguments.get("_continuation_governance"), dict)
        else {}
    )
    decision_class = (
        str(hidden.get("decision_class") or "").strip()
        or _continuation_decision_class_for_action(action)
    )
    continuation_identity = (
        str(hidden.get("continuation_identity") or "").strip()
        or _continuation_identity_for_bundle(bundle, decision_class=decision_class)
    )
    route_key = (
        str(hidden.get("route_key") or "").strip()
        or _continuation_route_key_for_bundle(
            bundle,
            continuation_identity=continuation_identity or None,
        )
        or None
    )
    return {
        "decision_source": str(hidden.get("decision_source") or "manual_action") or "manual_action",
        "decision_class": decision_class,
        "action_ref": str(hidden.get("action_ref") or _action_ref_for_code(action.action_code) or "")
        or None,
        "authoritative_snapshot_version": (
            str(hidden.get("authoritative_snapshot_version") or "").strip()
            or str(getattr(bundle.snapshot, "fact_snapshot_version", "") or "").strip()
            or None
        ),
        "snapshot_epoch": str(hidden.get("snapshot_epoch") or "").strip() or _snapshot_epoch_for_bundle(bundle),
        "goal_contract_version": (
            str(hidden.get("goal_contract_version") or "").strip()
            or str(bundle.progress.goal_contract_version or "").strip()
            or None
        ),
        "continuation_identity": continuation_identity or None,
        "route_key": route_key,
        "branch_switch_token": str(hidden.get("branch_switch_token") or "").strip() or None,
    }


def _record_continuation_gate_for_action(
    action: WatchdogAction,
    *,
    settings: Settings,
    bundle,
    gate_status: str,
    suppression_reason: str | None = None,
    session_service: SessionService | None = None,
) -> None:
    governance = _continuation_governance_for_action(action, bundle=bundle)
    if bool(action.arguments.get("_continuation_gate_pre_recorded")) and gate_status == "eligible":
        return
    service = session_service or SessionService.from_data_dir(settings.data_dir)
    service.record_continuation_gate_verdict(
        project_id=action.project_id,
        session_id=bundle.session.thread_id,
        gate_kind="direct_action",
        gate_status=gate_status,
        decision_source=str(governance["decision_source"] or "manual_action"),
        decision_class=str(governance["decision_class"] or "blocked"),
        action_ref=governance["action_ref"],
        authoritative_snapshot_version=governance["authoritative_snapshot_version"],
        snapshot_epoch=governance["snapshot_epoch"],
        goal_contract_version=governance["goal_contract_version"],
        suppression_reason=suppression_reason,
        continuation_identity=governance["continuation_identity"],
        route_key=governance["route_key"],
    )


def _latest_continuation_identity_state(
    service: SessionService,
    *,
    session_id: str,
    continuation_identity: str | None,
) -> str | None:
    if continuation_identity is None:
        return None
    events = service.list_events(
        session_id=session_id,
        related_id_key="continuation_identity",
        related_id_value=continuation_identity,
    )
    relevant = [
        event
        for event in events
        if event.event_type
        in {
            "continuation_identity_issued",
            "continuation_identity_consumed",
            "continuation_identity_invalidated",
        }
    ]
    if not relevant:
        return None
    latest = max(relevant, key=lambda event: event.log_seq or 0)
    return str(latest.payload.get("state") or "").strip() or None


def _record_continuation_identity_for_action(
    action: WatchdogAction,
    *,
    settings: Settings,
    bundle,
    state: str,
    session_service: SessionService | None = None,
    suppression_reason: str | None = None,
    consumed_at: str | None = None,
) -> None:
    governance = _continuation_governance_for_action(action, bundle=bundle)
    continuation_identity = governance["continuation_identity"]
    if continuation_identity is None:
        return
    service = session_service or SessionService.from_data_dir(settings.data_dir)
    service.record_continuation_identity_state(
        project_id=action.project_id,
        session_id=bundle.session.thread_id,
        continuation_identity=continuation_identity,
        state=state,
        decision_source=str(governance["decision_source"] or "manual_action"),
        decision_class=str(governance["decision_class"] or "blocked"),
        action_ref=governance["action_ref"],
        authoritative_snapshot_version=governance["authoritative_snapshot_version"],
        snapshot_epoch=governance["snapshot_epoch"],
        goal_contract_version=governance["goal_contract_version"],
        route_key=governance["route_key"],
        suppression_reason=suppression_reason,
        consumed_at=consumed_at,
        causation_id=action.idempotency_key,
    )


def _preflight_continuation_identity_for_action(
    action: WatchdogAction,
    *,
    settings: Settings,
    bundle,
    session_service: SessionService | None = None,
) -> tuple[SessionService, WatchdogActionResult | None]:
    service = session_service or SessionService.from_data_dir(settings.data_dir)
    governance = _continuation_governance_for_action(action, bundle=bundle)
    if (
        _latest_continuation_identity_state(
            service,
            session_id=bundle.session.thread_id,
            continuation_identity=governance["continuation_identity"],
        )
        == "issued"
    ):
        return service, _continuation_identity_in_flight_result(
            action,
            settings=settings,
            bundle=bundle,
            session_service=service,
        )
    _record_continuation_identity_for_action(
        action,
        settings=settings,
        bundle=bundle,
        state="issued",
        session_service=service,
    )
    return service, None


def _invalidate_continuation_identity_for_action(
    action: WatchdogAction,
    *,
    settings: Settings,
    bundle,
    session_service: SessionService | None = None,
    suppression_reason: str,
) -> None:
    _record_continuation_identity_for_action(
        action,
        settings=settings,
        bundle=bundle,
        state="invalidated",
        session_service=session_service,
        suppression_reason=suppression_reason,
    )


def _consume_continuation_identity_for_action(
    action: WatchdogAction,
    *,
    settings: Settings,
    bundle,
    session_service: SessionService | None = None,
) -> None:
    _record_continuation_identity_for_action(
        action,
        settings=settings,
        bundle=bundle,
        state="consumed",
        session_service=session_service,
        consumed_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )


def _continuation_identity_in_flight_result(
    action: WatchdogAction,
    *,
    settings: Settings,
    bundle,
    session_service: SessionService | None = None,
) -> WatchdogActionResult:
    _record_continuation_gate_for_action(
        action,
        settings=settings,
        bundle=bundle,
        gate_status="suppressed",
        suppression_reason="continuation_identity_in_flight",
        session_service=session_service,
    )
    return _result(
        action,
        action_status=ActionStatus.NOOP,
        effect=Effect.NOOP,
        reply_code=ReplyCode.ACTION_NOT_AVAILABLE,
        message="continuation is already in flight",
        facts=bundle.facts,
    )


def _record_branch_switch_token_for_action(
    action: WatchdogAction,
    *,
    settings: Settings,
    bundle,
    state: str,
    session_service: SessionService | None = None,
    suppression_reason: str | None = None,
    consumed_at: str | None = None,
) -> None:
    governance = _continuation_governance_for_action(action, bundle=bundle)
    branch_switch_token = governance["branch_switch_token"]
    if (
        branch_switch_token is None
        or governance["decision_class"] != "branch_complete_switch"
    ):
        return
    service = session_service or SessionService.from_data_dir(settings.data_dir)
    service.record_branch_switch_token_state(
        project_id=action.project_id,
        session_id=bundle.session.thread_id,
        branch_switch_token=branch_switch_token,
        state=state,
        decision_source=str(governance["decision_source"] or "manual_action"),
        decision_class=str(governance["decision_class"] or "blocked"),
        authoritative_snapshot_version=governance["authoritative_snapshot_version"],
        snapshot_epoch=governance["snapshot_epoch"],
        goal_contract_version=governance["goal_contract_version"],
        continuation_identity=governance["continuation_identity"],
        route_key=governance["route_key"],
        suppression_reason=suppression_reason,
        consumed_at=consumed_at,
        causation_id=action.idempotency_key,
    )


def _invalidate_branch_switch_token_for_action(
    action: WatchdogAction,
    *,
    settings: Settings,
    bundle,
    session_service: SessionService | None = None,
    suppression_reason: str,
) -> None:
    _record_branch_switch_token_for_action(
        action,
        settings=settings,
        bundle=bundle,
        state="invalidated",
        session_service=session_service,
        suppression_reason=suppression_reason,
    )


def _consume_branch_switch_token_for_action(
    action: WatchdogAction,
    *,
    settings: Settings,
    bundle,
    session_service: SessionService | None = None,
) -> None:
    _record_branch_switch_token_for_action(
        action,
        settings=settings,
        bundle=bundle,
        state="consumed",
        session_service=session_service,
        consumed_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
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


def _normalize_continue_arguments(
    action: WatchdogAction,
    *,
    current_stuck_level: object,
) -> tuple[str, str, int] | WatchdogActionResult:
    soft = steer_template_registry()["soft"]
    message = str(action.arguments.get("message") or soft.message or SOFT_STEER_MESSAGE).strip()
    if not message:
        message = SOFT_STEER_MESSAGE
    reason_code = str(
        action.arguments.get("reason_code") or soft.reason_code or "openclaw_continue_session"
    ).strip()
    if not reason_code:
        reason_code = "openclaw_continue_session"
    stuck_level_raw = action.arguments.get("stuck_level", current_stuck_level)
    try:
        stuck_level = int(stuck_level_raw or 0)
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
    session_service: SessionService | None = None,
    store: Any | None = None,
    approval_store: Any | None = None,
    decision_store: Any | None = None,
) -> WatchdogActionResult:
    bundle = _build_action_read_bundle(
        action,
        client=client,
        session_service=session_service,
        store=store,
        approval_store=approval_store,
        decision_store=decision_store,
    )
    fact_codes = {fact.fact_code for fact in bundle.facts}
    hard_block = _continuation_hard_block_result(action, bundle=bundle)
    if hard_block is not None:
        _record_continuation_gate_for_action(
            action,
            settings=settings,
            bundle=bundle,
            gate_status="suppressed",
            suppression_reason=hard_block.message,
            session_service=session_service,
        )
        return hard_block
    if "task_completed" in fact_codes or is_terminal_task(bundle.task):
        _record_continuation_gate_for_action(
            action,
            settings=settings,
            bundle=bundle,
            gate_status="suppressed",
            suppression_reason="task_terminal",
            session_service=session_service,
        )
        return _result(
            action,
            action_status=ActionStatus.NOOP,
            effect=Effect.NOOP,
            reply_code=ReplyCode.ACTION_NOT_AVAILABLE,
            message="session is already complete",
            facts=bundle.facts,
        )
    continue_args = _normalize_continue_arguments(
        action,
        current_stuck_level=bundle.task.get("stuck_level", 0),
    )
    if isinstance(continue_args, WatchdogActionResult):
        return continue_args
    service, in_flight = _preflight_continuation_identity_for_action(
        action,
        settings=settings,
        bundle=bundle,
        session_service=session_service,
    )
    if in_flight is not None:
        return in_flight
    message, reason_code, stuck_level = continue_args
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
        _validate_steer_response_or_raise(steer_body)
    except (httpx.HTTPError, RuntimeError, SessionSpineUpstreamError) as exc:
        _invalidate_continuation_identity_for_action(
            action,
            settings=settings,
            bundle=bundle,
            session_service=service,
            suppression_reason=(
                str(getattr(exc, "error", {}).get("code") or "").strip().lower()
                if isinstance(exc, SessionSpineUpstreamError)
                else "control_link_error"
            )
            or "control_link_error",
        )
        if isinstance(exc, SessionSpineUpstreamError):
            raise
        raise SessionSpineUpstreamError(
            {"code": "CONTROL_LINK_ERROR", "message": "steer 调用失败：无法连接 A-Control-Agent"}
        ) from exc
    _record_continuation_gate_for_action(
        action,
        settings=settings,
        bundle=bundle,
        gate_status="eligible",
        session_service=service,
    )
    _consume_continuation_identity_for_action(
        action,
        settings=settings,
        bundle=bundle,
        session_service=service,
    )
    return _result(
        action,
        action_status=ActionStatus.COMPLETED,
        effect=Effect.STEER_POSTED,
        reply_code=ReplyCode.ACTION_RESULT,
        message="continue request accepted",
        facts=bundle.facts,
    )


def _rejected_transition(
    action: WatchdogAction,
    *,
    message: str,
    facts: list[Any] | None = None,
) -> WatchdogActionResult:
    return _result(
        action,
        action_status=ActionStatus.REJECTED,
        effect=Effect.NOOP,
        reply_code=ReplyCode.ACTION_NOT_AVAILABLE,
        message=message,
        facts=facts,
    )


def _execute_pause(
    action: WatchdogAction,
    *,
    client: AControlAgentClient,
    session_service: SessionService | None = None,
    store: Any | None = None,
    approval_store: Any | None = None,
    decision_store: Any | None = None,
) -> WatchdogActionResult:
    bundle = _build_action_read_bundle(
        action,
        client=client,
        session_service=session_service,
        store=store,
        approval_store=approval_store,
        decision_store=decision_store,
    )
    verdict = validate_action_transition("pause", task=bundle.task)
    if not verdict["allowed"]:
        return _rejected_transition(action, message="pause is not allowed from current state", facts=bundle.facts)
    try:
        body = client.trigger_pause(action.project_id)
    except (httpx.RequestError, RuntimeError, OSError) as exc:
        raise SessionSpineUpstreamError(
            {"code": "CONTROL_LINK_ERROR", "message": "pause 调用失败：无法连接 A-Control-Agent"}
        ) from exc
    if not body.get("success"):
        error = body.get("error")
        if isinstance(error, dict):
            raise SessionSpineUpstreamError(dict(error))
        raise SessionSpineUpstreamError(
            {"code": "CONTROL_LINK_ERROR", "message": "pause 调用失败"}
        )
    return _result(
        action,
        action_status=ActionStatus.COMPLETED,
        effect=Effect.SESSION_PAUSED,
        reply_code=ReplyCode.ACTION_RESULT,
        message="pause request accepted",
        facts=bundle.facts,
    )


def _execute_resume_session(
    action: WatchdogAction,
    *,
    settings: Settings,
    client: AControlAgentClient,
    session_service: SessionService | None = None,
    store: Any | None = None,
    approval_store: Any | None = None,
    decision_store: Any | None = None,
) -> WatchdogActionResult:
    bundle = _build_action_read_bundle(
        action,
        client=client,
        session_service=session_service,
        store=store,
        approval_store=approval_store,
        decision_store=decision_store,
    )
    handoff_summary = str(action.arguments.get("handoff_summary") or "")
    continuation_packet = action.arguments.get("continuation_packet")
    if continuation_packet is not None and not isinstance(continuation_packet, dict):
        raise SessionSpineUpstreamError(
            {"code": "INVALID_ARGUMENT", "message": "continuation_packet must be an object"}
        )
    hard_block = _continuation_hard_block_result(action, bundle=bundle)
    if hard_block is not None:
        _record_continuation_gate_for_action(
            action,
            settings=settings,
            bundle=bundle,
            gate_status="suppressed",
            suppression_reason=hard_block.message,
            session_service=session_service,
        )
        return hard_block
    verdict = validate_action_transition(
        "resume",
        task=bundle.task,
        has_continuation=bool(handoff_summary or continuation_packet),
    )
    if not verdict["allowed"]:
        _record_continuation_gate_for_action(
            action,
            settings=settings,
            bundle=bundle,
            gate_status="suppressed",
            suppression_reason="resume_not_allowed",
            session_service=session_service,
        )
        return _rejected_transition(action, message="resume is not allowed from current state", facts=bundle.facts)
    service, in_flight = _preflight_continuation_identity_for_action(
        action,
        settings=settings,
        bundle=bundle,
        session_service=session_service,
    )
    if in_flight is not None:
        return in_flight
    mode = str(action.arguments.get("mode") or "resume_or_new_thread")
    try:
        body = client.trigger_resume(
            action.project_id,
            mode=mode,
            handoff_summary=handoff_summary,
            continuation_packet=continuation_packet,
        )
    except (httpx.RequestError, RuntimeError, OSError) as exc:
        _invalidate_continuation_identity_for_action(
            action,
            settings=settings,
            bundle=bundle,
            session_service=service,
            suppression_reason="control_link_error",
        )
        raise SessionSpineUpstreamError(
            {"code": "CONTROL_LINK_ERROR", "message": "resume 调用失败：无法连接 A-Control-Agent"}
        ) from exc
    if not body.get("success"):
        _invalidate_continuation_identity_for_action(
            action,
            settings=settings,
            bundle=bundle,
            session_service=service,
            suppression_reason="control_link_error",
        )
        error = body.get("error")
        if isinstance(error, dict):
            raise SessionSpineUpstreamError(dict(error))
        raise SessionSpineUpstreamError(
            {"code": "CONTROL_LINK_ERROR", "message": "resume 调用失败"}
        )
    _record_continuation_gate_for_action(
        action,
        settings=settings,
        bundle=bundle,
        gate_status="eligible",
        session_service=service,
    )
    _consume_continuation_identity_for_action(
        action,
        settings=settings,
        bundle=bundle,
        session_service=service,
    )
    return _result(
        action,
        action_status=ActionStatus.COMPLETED,
        effect=Effect.SESSION_RESUMED,
        reply_code=ReplyCode.ACTION_RESULT,
        message="resume request accepted",
        facts=bundle.facts,
    )


def _execute_summarize(
    action: WatchdogAction,
    *,
    client: AControlAgentClient,
    session_service: SessionService | None = None,
    store: Any | None = None,
    approval_store: Any | None = None,
    decision_store: Any | None = None,
) -> WatchdogActionResult:
    bundle = _build_action_read_bundle(
        action,
        client=client,
        session_service=session_service,
        store=store,
        approval_store=approval_store,
        decision_store=decision_store,
    )
    summary = str((bundle.task or {}).get("last_summary") or "").strip() or "no summary available"
    return _result(
        action,
        action_status=ActionStatus.COMPLETED,
        effect=Effect.SUMMARY_GENERATED,
        reply_code=ReplyCode.ACTION_RESULT,
        message=summary,
        facts=bundle.facts,
    )


def _execute_force_handoff(
    action: WatchdogAction,
    *,
    settings: Settings,
    client: AControlAgentClient,
    session_service: SessionService | None = None,
    store: Any | None = None,
    approval_store: Any | None = None,
    decision_store: Any | None = None,
) -> WatchdogActionResult:
    bundle = _build_action_read_bundle(
        action,
        client=client,
        session_service=session_service,
        store=store,
        approval_store=approval_store,
        decision_store=decision_store,
    )
    hard_block = _continuation_hard_block_result(action, bundle=bundle)
    if hard_block is not None:
        _record_continuation_gate_for_action(
            action,
            settings=settings,
            bundle=bundle,
            gate_status="suppressed",
            suppression_reason=hard_block.message,
            session_service=session_service,
        )
        return hard_block
    verdict = validate_action_transition("force_handoff", task=bundle.task)
    if not verdict["allowed"]:
        _record_continuation_gate_for_action(
            action,
            settings=settings,
            bundle=bundle,
            gate_status="suppressed",
            suppression_reason="force_handoff_not_allowed",
            session_service=session_service,
        )
        return _rejected_transition(action, message="force_handoff is not allowed from current state", facts=bundle.facts)
    service, in_flight = _preflight_continuation_identity_for_action(
        action,
        settings=settings,
        bundle=bundle,
        session_service=session_service,
    )
    if in_flight is not None:
        return in_flight
    reason = str(action.arguments.get("reason") or "force_handoff")
    try:
        body = client.trigger_handoff(action.project_id, reason=reason)
    except (httpx.RequestError, RuntimeError, OSError) as exc:
        _invalidate_continuation_identity_for_action(
            action,
            settings=settings,
            bundle=bundle,
            session_service=service,
            suppression_reason="control_link_error",
        )
        raise SessionSpineUpstreamError(
            {"code": "CONTROL_LINK_ERROR", "message": "handoff 调用失败：无法连接 A-Control-Agent"}
        ) from exc
    if not body.get("success"):
        _invalidate_continuation_identity_for_action(
            action,
            settings=settings,
            bundle=bundle,
            session_service=service,
            suppression_reason="control_link_error",
        )
        error = body.get("error")
        if isinstance(error, dict):
            raise SessionSpineUpstreamError(dict(error))
        raise SessionSpineUpstreamError(
            {"code": "CONTROL_LINK_ERROR", "message": "handoff 调用失败"}
        )
    _record_continuation_gate_for_action(
        action,
        settings=settings,
        bundle=bundle,
        gate_status="eligible",
        session_service=service,
    )
    _consume_continuation_identity_for_action(
        action,
        settings=settings,
        bundle=bundle,
        session_service=service,
    )
    return _result(
        action,
        action_status=ActionStatus.COMPLETED,
        effect=Effect.HANDOFF_TRIGGERED,
        reply_code=ReplyCode.ACTION_RESULT,
        message="handoff triggered",
        facts=bundle.facts,
    )


def _execute_retry_with_conservative_path(
    action: WatchdogAction,
    *,
    settings: Settings,
    client: AControlAgentClient,
    session_service: SessionService | None = None,
    store: Any | None = None,
    approval_store: Any | None = None,
    decision_store: Any | None = None,
) -> WatchdogActionResult:
    bundle = _build_action_read_bundle(
        action,
        client=client,
        session_service=session_service,
        store=store,
        approval_store=approval_store,
        decision_store=decision_store,
    )
    hard_block = _continuation_hard_block_result(action, bundle=bundle)
    if hard_block is not None:
        _record_continuation_gate_for_action(
            action,
            settings=settings,
            bundle=bundle,
            gate_status="suppressed",
            suppression_reason=hard_block.message,
            session_service=session_service,
        )
        return hard_block
    verdict = validate_action_transition("retry_with_conservative_path", task=bundle.task)
    if not verdict["allowed"]:
        _record_continuation_gate_for_action(
            action,
            settings=settings,
            bundle=bundle,
            gate_status="suppressed",
            suppression_reason="retry_with_conservative_path_not_allowed",
            session_service=session_service,
        )
        return _rejected_transition(
            action,
            message="retry_with_conservative_path is not allowed from current state",
            facts=bundle.facts,
        )
    service, in_flight = _preflight_continuation_identity_for_action(
        action,
        settings=settings,
        bundle=bundle,
        session_service=session_service,
    )
    if in_flight is not None:
        return in_flight
    template = steer_template_registry()["break_loop"]
    try:
        steer_body = post_steer(
            settings.a_agent_base_url,
            settings.a_agent_token,
            action.project_id,
            message=template.message,
            reason=template.reason_code,
            stuck_level=int((bundle.task or {}).get("stuck_level", 0) or 0),
            timeout=settings.http_timeout_s,
        )
        _validate_steer_response_or_raise(steer_body)
    except (httpx.HTTPError, RuntimeError, SessionSpineUpstreamError) as exc:
        _invalidate_continuation_identity_for_action(
            action,
            settings=settings,
            bundle=bundle,
            session_service=service,
            suppression_reason=(
                str(getattr(exc, "error", {}).get("code") or "").strip().lower()
                if isinstance(exc, SessionSpineUpstreamError)
                else "control_link_error"
            )
            or "control_link_error",
        )
        if isinstance(exc, SessionSpineUpstreamError):
            raise
        raise SessionSpineUpstreamError(
            {"code": "CONTROL_LINK_ERROR", "message": "steer 调用失败：无法连接 A-Control-Agent"}
        ) from exc
    _record_continuation_gate_for_action(
        action,
        settings=settings,
        bundle=bundle,
        gate_status="eligible",
        session_service=service,
    )
    _consume_continuation_identity_for_action(
        action,
        settings=settings,
        bundle=bundle,
        session_service=service,
    )
    return _result(
        action,
        action_status=ActionStatus.COMPLETED,
        effect=Effect.CONSERVATIVE_RETRY_REQUESTED,
        reply_code=ReplyCode.ACTION_RESULT,
        message="conservative retry requested",
        facts=bundle.facts,
    )


def _execute_operator_guidance(
    action: WatchdogAction,
    *,
    settings: Settings,
    client: AControlAgentClient,
    session_service: SessionService | None = None,
    store: Any | None = None,
    approval_store: Any | None = None,
    decision_store: Any | None = None,
) -> WatchdogActionResult:
    normalized = _normalize_operator_guidance_arguments(action)
    if isinstance(normalized, WatchdogActionResult):
        return normalized
    message, reason_code, stuck_level = normalized
    bundle = _build_action_read_bundle(
        action,
        client=client,
        session_service=session_service,
        store=store,
        approval_store=approval_store,
        decision_store=decision_store,
    )
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
        _validate_steer_response_or_raise(steer_body)
    except (httpx.HTTPError, RuntimeError, SessionSpineUpstreamError) as exc:
        _invalidate_branch_switch_token_for_action(
            action,
            settings=settings,
            bundle=bundle,
            session_service=session_service,
            suppression_reason="control_link_error",
        )
        if isinstance(exc, SessionSpineUpstreamError):
            raise
        raise SessionSpineUpstreamError(
            {"code": "CONTROL_LINK_ERROR", "message": "steer 调用失败：无法连接 A-Control-Agent"}
        ) from exc
    _consume_branch_switch_token_for_action(
        action,
        settings=settings,
        bundle=bundle,
        session_service=session_service,
    )
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
    session_service: SessionService | None = None,
    store: Any | None = None,
    approval_store: Any | None = None,
    decision_store: Any | None = None,
) -> WatchdogActionResult:
    bundle = _build_action_read_bundle(
        action,
        client=client,
        session_service=session_service,
        store=store,
        approval_store=approval_store,
        decision_store=decision_store,
    )
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
    session_service: SessionService | None = None,
) -> WatchdogActionResult:
    outcome = perform_recovery_execution(
        action.project_id,
        settings=settings,
        client=client,
        session_service=session_service,
    )
    facts = list(outcome.facts)
    if outcome.action == "noop":
        message_by_reason = {
            "context_not_critical": "recovery not executed because context is not critical",
            "recovery_in_flight": "recovery not executed because recovery is already in flight",
            "project_not_active": "recovery not executed because project is not active",
            "project_state_unavailable": (
                "recovery not executed because authoritative project state is unavailable"
            ),
            "pending_approval": "recovery not executed because approval is pending",
            "paused": "recovery not executed because session is paused",
            "waiting_for_direction": (
                "recovery not executed because session is waiting for direction"
            ),
            "task_terminal": "recovery not executed because session is already complete",
        }
        message = message_by_reason.get(
            outcome.noop_reason or "",
            "recovery not executed because continuation is blocked",
        )
        return _result(
            action,
            action_status=ActionStatus.NOOP,
            effect=Effect.NOOP,
            reply_code=ReplyCode.RECOVERY_EXECUTION_RESULT,
            message=message,
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
    session_service: SessionService | None = None,
    store: Any | None = None,
    approval_store: Any | None = None,
    decision_store: Any | None = None,
) -> WatchdogActionResult:
    approval_id = str(action.arguments.get("approval_id") or "") or None
    receipt_key = receipt_key_for_action(action, approval_id)
    def _execute() -> WatchdogActionResult:
        if action.action_code == ActionCode.CONTINUE_SESSION:
            return _execute_continue(
                action,
                settings=settings,
                client=client,
                session_service=session_service,
                store=store,
                approval_store=approval_store,
                decision_store=decision_store,
            )
        if action.action_code == ActionCode.PAUSE_SESSION:
            return _execute_pause(
                action,
                client=client,
                session_service=session_service,
                store=store,
                approval_store=approval_store,
                decision_store=decision_store,
            )
        if action.action_code == ActionCode.RESUME_SESSION:
            return _execute_resume_session(
                action,
                settings=settings,
                client=client,
                session_service=session_service,
                store=store,
                approval_store=approval_store,
                decision_store=decision_store,
            )
        if action.action_code == ActionCode.SUMMARIZE_SESSION:
            return _execute_summarize(
                action,
                client=client,
                session_service=session_service,
                store=store,
                approval_store=approval_store,
                decision_store=decision_store,
            )
        if action.action_code == ActionCode.FORCE_HANDOFF:
            return _execute_force_handoff(
                action,
                settings=settings,
                client=client,
                session_service=session_service,
                store=store,
                approval_store=approval_store,
                decision_store=decision_store,
            )
        if action.action_code == ActionCode.RETRY_WITH_CONSERVATIVE_PATH:
            return _execute_retry_with_conservative_path(
                action,
                settings=settings,
                client=client,
                session_service=session_service,
                store=store,
                approval_store=approval_store,
                decision_store=decision_store,
            )
        if action.action_code == ActionCode.POST_OPERATOR_GUIDANCE:
            return _execute_operator_guidance(
                action,
                settings=settings,
                client=client,
                session_service=session_service,
                store=store,
                approval_store=approval_store,
                decision_store=decision_store,
            )
        if action.action_code == ActionCode.REQUEST_RECOVERY:
            return _execute_request_recovery(
                action,
                client=client,
                session_service=session_service,
                store=store,
                approval_store=approval_store,
                decision_store=decision_store,
            )
        if action.action_code == ActionCode.EXECUTE_RECOVERY:
            return _execute_recovery(
                action,
                settings=settings,
                client=client,
                session_service=session_service,
            )
        if action.action_code == ActionCode.EVALUATE_SUPERVISION:
            return execute_supervision_evaluation(action, settings=settings, client=client)
        if action.action_code == ActionCode.APPROVE_APPROVAL:
            return _execute_approval_action(action, client=client, decision="approve")
        if action.action_code == ActionCode.REJECT_APPROVAL:
            return _execute_approval_action(action, client=client, decision="reject")
        return _result(
            action,
            action_status=ActionStatus.NOT_AVAILABLE,
            effect=Effect.NOOP,
            reply_code=ReplyCode.ACTION_NOT_AVAILABLE,
            message=f"unsupported action: {action.action_code}",
        )

    return receipt_store.create_or_get(receipt_key, _execute)
