from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError

from watchdog.api.deps import require_token
from watchdog.contracts.session_spine.enums import ActionCode
from watchdog.contracts.session_spine.models import WatchdogAction
from watchdog.envelope import err, ok
from watchdog.services.a_client.client import AControlAgentClient
from watchdog.services.session_spine.actions import execute_watchdog_action
from watchdog.services.session_spine.service import SessionSpineUpstreamError
from watchdog.settings import Settings
from watchdog.storage.action_receipts import ActionReceiptStore

router = APIRouter(prefix="/watchdog", tags=["session-spine-actions"])


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_client(request: Request) -> AControlAgentClient:
    return request.app.state.a_client


def get_receipt_store(request: Request) -> ActionReceiptStore:
    return request.app.state.action_receipt_store


def _parse_action(body: dict[str, Any]) -> WatchdogAction | None:
    try:
        return WatchdogAction.model_validate(body)
    except ValidationError:
        return None


def _alias_parse_error(body: dict[str, Any]) -> dict[str, str]:
    if not str(body.get("idempotency_key") or "").strip():
        return {"code": "INVALID_ARGUMENT", "message": "idempotency_key required"}
    return {"code": "INVALID_ARGUMENT", "message": "body must satisfy WatchdogAction"}


def _build_alias_action(
    *,
    action_code: ActionCode,
    project_id: str,
    body: dict[str, Any],
    approval_id: str | None = None,
    top_level_argument_keys: tuple[str, ...] = (),
) -> WatchdogAction | None:
    raw_arguments = body.get("arguments")
    if raw_arguments in (None, ""):
        arguments: dict[str, Any] = {}
    elif isinstance(raw_arguments, dict):
        arguments = dict(raw_arguments)
    else:
        return None
    for key in top_level_argument_keys:
        if key in body:
            arguments[key] = body.get(key)
    action_body: dict[str, Any] = {
        "action_code": action_code,
        "project_id": project_id,
        "operator": str(body.get("operator") or "openclaw"),
        "idempotency_key": str(body.get("idempotency_key") or ""),
        "arguments": arguments,
        "note": str(body.get("note") or ""),
    }
    if approval_id:
        action_body["arguments"]["approval_id"] = approval_id
    return _parse_action(action_body)


def _resolve_project_id_for_approval(client: AControlAgentClient, approval_id: str) -> str | None:
    try:
        approvals = client.list_approvals()
    except Exception:
        return None
    for approval in approvals:
        if str(approval.get("approval_id") or "") == approval_id:
            project_id = str(approval.get("project_id") or "")
            if project_id:
                return project_id
    return None


def handle_action(
    action: WatchdogAction,
    *,
    request: Request,
    settings: Settings,
    client: AControlAgentClient,
    receipt_store: ActionReceiptStore,
) -> dict[str, object]:
    rid = request.headers.get("x-request-id")
    session_service = request.app.state.session_service
    try:
        result = execute_watchdog_action(
            action,
            settings=settings,
            client=client,
            receipt_store=receipt_store,
            session_service=session_service,
        )
    except SessionSpineUpstreamError as exc:
        return err(rid, exc.error)
    return ok(rid, result.model_dump(mode="json"))


@router.post(
    "/actions",
    summary="Execute canonical watchdog action",
    description=(
        "Canonical stable write surface. Clients should prefer this route and "
        "submit a versioned WatchdogAction with a non-empty idempotency_key."
    ),
)
def post_action(
    request: Request,
    body: dict[str, Any],
    settings: Settings = Depends(get_settings),
    client: AControlAgentClient = Depends(get_client),
    receipt_store: ActionReceiptStore = Depends(get_receipt_store),
    _: None = Depends(require_token),
) -> dict[str, object]:
    action = _parse_action(body)
    if action is None:
        return err(
            request.headers.get("x-request-id"),
            {"code": "INVALID_ARGUMENT", "message": "body must satisfy WatchdogAction"},
        )
    return handle_action(
        action,
        request=request,
        settings=settings,
        client=client,
        receipt_store=receipt_store,
    )


@router.post(
    "/sessions/{project_id}/actions/continue",
    summary="Alias: continue session",
    description=(
        "Human-friendly wrapper over POST /api/v1/watchdog/actions. This route "
        "maps to action_code=continue_session and reuses the canonical handler."
    ),
)
def continue_session_alias(
    project_id: str,
    request: Request,
    body: dict[str, Any],
    settings: Settings = Depends(get_settings),
    client: AControlAgentClient = Depends(get_client),
    receipt_store: ActionReceiptStore = Depends(get_receipt_store),
    _: None = Depends(require_token),
) -> dict[str, object]:
    action = _build_alias_action(
        action_code=ActionCode.CONTINUE_SESSION,
        project_id=project_id,
        body=body,
    )
    if action is None:
        return err(request.headers.get("x-request-id"), _alias_parse_error(body))
    return handle_action(
        action,
        request=request,
        settings=settings,
        client=client,
        receipt_store=receipt_store,
    )


@router.post(
    "/sessions/{project_id}/actions/pause",
    summary="Alias: pause session",
    description=(
        "Human-friendly wrapper over POST /api/v1/watchdog/actions. This route "
        "maps to action_code=pause_session and reuses the canonical handler."
    ),
)
def pause_session_alias(
    project_id: str,
    request: Request,
    body: dict[str, Any],
    settings: Settings = Depends(get_settings),
    client: AControlAgentClient = Depends(get_client),
    receipt_store: ActionReceiptStore = Depends(get_receipt_store),
    _: None = Depends(require_token),
) -> dict[str, object]:
    action = _build_alias_action(
        action_code=ActionCode.PAUSE_SESSION,
        project_id=project_id,
        body=body,
    )
    if action is None:
        return err(request.headers.get("x-request-id"), _alias_parse_error(body))
    return handle_action(
        action,
        request=request,
        settings=settings,
        client=client,
        receipt_store=receipt_store,
    )


@router.post(
    "/sessions/{project_id}/actions/resume",
    summary="Alias: resume session",
    description=(
        "Human-friendly wrapper over POST /api/v1/watchdog/actions. This route "
        "maps to action_code=resume_session and folds top-level mode/handoff_summary "
        "fields into canonical action arguments."
    ),
)
def resume_session_alias(
    project_id: str,
    request: Request,
    body: dict[str, Any],
    settings: Settings = Depends(get_settings),
    client: AControlAgentClient = Depends(get_client),
    receipt_store: ActionReceiptStore = Depends(get_receipt_store),
    _: None = Depends(require_token),
) -> dict[str, object]:
    action = _build_alias_action(
        action_code=ActionCode.RESUME_SESSION,
        project_id=project_id,
        body=body,
        top_level_argument_keys=("mode", "handoff_summary"),
    )
    if action is None:
        return err(request.headers.get("x-request-id"), _alias_parse_error(body))
    return handle_action(
        action,
        request=request,
        settings=settings,
        client=client,
        receipt_store=receipt_store,
    )


@router.post(
    "/sessions/{project_id}/actions/summarize",
    summary="Alias: summarize session",
    description=(
        "Human-friendly wrapper over POST /api/v1/watchdog/actions. This route "
        "maps to action_code=summarize_session and reuses the canonical handler."
    ),
)
def summarize_session_alias(
    project_id: str,
    request: Request,
    body: dict[str, Any],
    settings: Settings = Depends(get_settings),
    client: AControlAgentClient = Depends(get_client),
    receipt_store: ActionReceiptStore = Depends(get_receipt_store),
    _: None = Depends(require_token),
) -> dict[str, object]:
    action = _build_alias_action(
        action_code=ActionCode.SUMMARIZE_SESSION,
        project_id=project_id,
        body=body,
    )
    if action is None:
        return err(request.headers.get("x-request-id"), _alias_parse_error(body))
    return handle_action(
        action,
        request=request,
        settings=settings,
        client=client,
        receipt_store=receipt_store,
    )


@router.post(
    "/sessions/{project_id}/actions/force-handoff",
    summary="Alias: force handoff",
    description=(
        "Human-friendly wrapper over POST /api/v1/watchdog/actions. This route "
        "maps to action_code=force_handoff and reuses the canonical handler."
    ),
)
def force_handoff_alias(
    project_id: str,
    request: Request,
    body: dict[str, Any],
    settings: Settings = Depends(get_settings),
    client: AControlAgentClient = Depends(get_client),
    receipt_store: ActionReceiptStore = Depends(get_receipt_store),
    _: None = Depends(require_token),
) -> dict[str, object]:
    action = _build_alias_action(
        action_code=ActionCode.FORCE_HANDOFF,
        project_id=project_id,
        body=body,
        top_level_argument_keys=("reason",),
    )
    if action is None:
        return err(request.headers.get("x-request-id"), _alias_parse_error(body))
    return handle_action(
        action,
        request=request,
        settings=settings,
        client=client,
        receipt_store=receipt_store,
    )


@router.post(
    "/sessions/{project_id}/actions/retry-with-conservative-path",
    summary="Alias: retry with conservative path",
    description=(
        "Human-friendly wrapper over POST /api/v1/watchdog/actions. This route "
        "maps to action_code=retry_with_conservative_path and reuses the canonical handler."
    ),
)
def retry_with_conservative_path_alias(
    project_id: str,
    request: Request,
    body: dict[str, Any],
    settings: Settings = Depends(get_settings),
    client: AControlAgentClient = Depends(get_client),
    receipt_store: ActionReceiptStore = Depends(get_receipt_store),
    _: None = Depends(require_token),
) -> dict[str, object]:
    action = _build_alias_action(
        action_code=ActionCode.RETRY_WITH_CONSERVATIVE_PATH,
        project_id=project_id,
        body=body,
    )
    if action is None:
        return err(request.headers.get("x-request-id"), _alias_parse_error(body))
    return handle_action(
        action,
        request=request,
        settings=settings,
        client=client,
        receipt_store=receipt_store,
    )


@router.post(
    "/sessions/{project_id}/actions/request-recovery",
    summary="Alias: request recovery availability",
    description=(
        "Human-friendly wrapper over POST /api/v1/watchdog/actions. This route "
        "maps to action_code=request_recovery and remains advisory-only."
    ),
)
def request_recovery_alias(
    project_id: str,
    request: Request,
    body: dict[str, Any],
    settings: Settings = Depends(get_settings),
    client: AControlAgentClient = Depends(get_client),
    receipt_store: ActionReceiptStore = Depends(get_receipt_store),
    _: None = Depends(require_token),
) -> dict[str, object]:
    action = _build_alias_action(
        action_code=ActionCode.REQUEST_RECOVERY,
        project_id=project_id,
        body=body,
    )
    if action is None:
        return err(request.headers.get("x-request-id"), _alias_parse_error(body))
    return handle_action(
        action,
        request=request,
        settings=settings,
        client=client,
        receipt_store=receipt_store,
    )


@router.post(
    "/sessions/{project_id}/actions/post-guidance",
    summary="Alias: post operator guidance",
    description=(
        "Human-friendly wrapper over POST /api/v1/watchdog/actions. This route "
        "maps to action_code=post_operator_guidance and folds top-level "
        "message/reason_code/stuck_level fields into canonical action arguments."
    ),
)
def post_operator_guidance_alias(
    project_id: str,
    request: Request,
    body: dict[str, Any],
    settings: Settings = Depends(get_settings),
    client: AControlAgentClient = Depends(get_client),
    receipt_store: ActionReceiptStore = Depends(get_receipt_store),
    _: None = Depends(require_token),
) -> dict[str, object]:
    action = _build_alias_action(
        action_code=ActionCode.POST_OPERATOR_GUIDANCE,
        project_id=project_id,
        body=body,
        top_level_argument_keys=("message", "reason_code", "stuck_level"),
    )
    if action is None:
        return err(request.headers.get("x-request-id"), _alias_parse_error(body))
    return handle_action(
        action,
        request=request,
        settings=settings,
        client=client,
        receipt_store=receipt_store,
    )


@router.post(
    "/sessions/{project_id}/actions/execute-recovery",
    summary="Alias: execute recovery",
    description=(
        "Human-friendly wrapper over POST /api/v1/watchdog/actions. This route "
        "maps to action_code=execute_recovery and triggers the stable recovery "
        "execution path."
    ),
)
def execute_recovery_alias(
    project_id: str,
    request: Request,
    body: dict[str, Any],
    settings: Settings = Depends(get_settings),
    client: AControlAgentClient = Depends(get_client),
    receipt_store: ActionReceiptStore = Depends(get_receipt_store),
    _: None = Depends(require_token),
) -> dict[str, object]:
    action = _build_alias_action(
        action_code=ActionCode.EXECUTE_RECOVERY,
        project_id=project_id,
        body=body,
    )
    if action is None:
        return err(request.headers.get("x-request-id"), _alias_parse_error(body))
    return handle_action(
        action,
        request=request,
        settings=settings,
        client=client,
        receipt_store=receipt_store,
    )


@router.post(
    "/sessions/{project_id}/actions/evaluate-supervision",
    summary="Alias: evaluate supervision",
    description=(
        "Human-friendly wrapper over POST /api/v1/watchdog/actions. This route "
        "maps to action_code=evaluate_supervision and reuses the canonical handler."
    ),
)
def evaluate_supervision_alias(
    project_id: str,
    request: Request,
    body: dict[str, Any],
    settings: Settings = Depends(get_settings),
    client: AControlAgentClient = Depends(get_client),
    receipt_store: ActionReceiptStore = Depends(get_receipt_store),
    _: None = Depends(require_token),
) -> dict[str, object]:
    action = _build_alias_action(
        action_code=ActionCode.EVALUATE_SUPERVISION,
        project_id=project_id,
        body=body,
    )
    if action is None:
        return err(request.headers.get("x-request-id"), _alias_parse_error(body))
    return handle_action(
        action,
        request=request,
        settings=settings,
        client=client,
        receipt_store=receipt_store,
    )


@router.post(
    "/approvals/{approval_id}/approve",
    summary="Alias: approve approval",
    description=(
        "Human-friendly wrapper over POST /api/v1/watchdog/actions. This route "
        "maps to action_code=approve_approval and reuses the canonical handler."
    ),
)
def approve_alias(
    approval_id: str,
    request: Request,
    body: dict[str, Any],
    settings: Settings = Depends(get_settings),
    client: AControlAgentClient = Depends(get_client),
    receipt_store: ActionReceiptStore = Depends(get_receipt_store),
    _: None = Depends(require_token),
) -> dict[str, object]:
    project_id = str(body.get("project_id") or "") or _resolve_project_id_for_approval(client, approval_id)
    if not project_id:
        return err(
            request.headers.get("x-request-id"),
            {"code": "INVALID_ARGUMENT", "message": "project_id required for approval alias"},
        )
    action = _build_alias_action(
        action_code=ActionCode.APPROVE_APPROVAL,
        project_id=project_id,
        body=body,
        approval_id=approval_id,
    )
    if action is None:
        return err(request.headers.get("x-request-id"), _alias_parse_error(body))
    return handle_action(
        action,
        request=request,
        settings=settings,
        client=client,
        receipt_store=receipt_store,
    )


@router.post(
    "/approvals/{approval_id}/reject",
    summary="Alias: reject approval",
    description=(
        "Human-friendly wrapper over POST /api/v1/watchdog/actions. This route "
        "maps to action_code=reject_approval and reuses the canonical handler."
    ),
)
def reject_alias(
    approval_id: str,
    request: Request,
    body: dict[str, Any],
    settings: Settings = Depends(get_settings),
    client: AControlAgentClient = Depends(get_client),
    receipt_store: ActionReceiptStore = Depends(get_receipt_store),
    _: None = Depends(require_token),
) -> dict[str, object]:
    project_id = str(body.get("project_id") or "") or _resolve_project_id_for_approval(client, approval_id)
    if not project_id:
        return err(
            request.headers.get("x-request-id"),
            {"code": "INVALID_ARGUMENT", "message": "project_id required for approval alias"},
        )
    action = _build_alias_action(
        action_code=ActionCode.REJECT_APPROVAL,
        project_id=project_id,
        body=body,
        approval_id=approval_id,
    )
    if action is None:
        return err(request.headers.get("x-request-id"), _alias_parse_error(body))
    return handle_action(
        action,
        request=request,
        settings=settings,
        client=client,
        receipt_store=receipt_store,
    )
