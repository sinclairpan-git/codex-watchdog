from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import ValidationError

from watchdog.api.deps import require_token
from watchdog.contracts.session_spine.models import ActionReceiptQuery
from watchdog.envelope import err, ok
from watchdog.services.a_client.client import AControlAgentClient
from watchdog.services.resident_experts.service import ResidentExpertRuntimeService
from watchdog.services.session_service import SessionService
from watchdog.services.session_spine.receipts import lookup_action_receipt
from watchdog.services.session_spine.replies import (
    build_approval_inbox_reply,
    build_approval_queue_reply,
    build_blocker_explanation_reply,
    build_progress_reply,
    build_session_facts_reply,
    build_session_event_snapshot_reply,
    build_session_directory_reply,
    build_session_reply,
    build_stuck_explanation_reply,
    build_workspace_activity_reply,
)
from watchdog.services.session_spine.events import list_session_events as list_projected_session_events
from watchdog.services.session_spine.service import (
    DEFAULT_SESSION_SPINE_FRESHNESS_WINDOW_SECONDS,
    SessionSpineUpstreamError,
    build_approval_inbox_bundle,
    build_session_directory_bundle,
    build_session_read_bundle,
    build_session_read_bundle_by_native_thread,
    build_workspace_activity_bundle,
)
from watchdog.services.session_spine.store import SessionSpineStore
from watchdog.services.session_spine.orchestration_store import ResidentOrchestrationStateStore
from watchdog.storage.action_receipts import ActionReceiptStore

router = APIRouter(prefix="/watchdog", tags=["session-spine"])


def get_client(request: Request) -> AControlAgentClient:
    return request.app.state.a_client


def get_receipt_store(request: Request) -> ActionReceiptStore:
    return request.app.state.action_receipt_store


def get_session_spine_store(request: Request) -> SessionSpineStore:
    return request.app.state.session_spine_store


def get_resident_orchestration_state_store(request: Request) -> ResidentOrchestrationStateStore:
    return request.app.state.resident_orchestration_state_store


def get_canonical_approval_store(request: Request) -> Any:
    return request.app.state.canonical_approval_store


def get_decision_store(request: Request) -> Any:
    return request.app.state.policy_decision_store


def get_session_service(request: Request) -> SessionService:
    return request.app.state.session_service


def get_resident_expert_runtime_service(request: Request) -> ResidentExpertRuntimeService:
    return request.app.state.resident_expert_runtime_service


def _get_session_spine_freshness_window_seconds(request: Request) -> float:
    return float(
        getattr(
            request.app.state.settings,
            "session_spine_freshness_window_seconds",
            DEFAULT_SESSION_SPINE_FRESHNESS_WINDOW_SECONDS,
        )
    )


def _get_auto_dispatch_cooldown_seconds(request: Request) -> float:
    return float(getattr(request.app.state.settings, "auto_continue_cooldown_seconds", 0.0))


def _parse_action_receipt_query(payload: dict[str, object]) -> ActionReceiptQuery | None:
    try:
        return ActionReceiptQuery.model_validate(payload)
    except ValidationError:
        return None


@router.get(
    "/approval-inbox",
    summary="List pending approvals across projects via stable contract",
    description=(
        "Stable read surface for a cross-project approval inbox. Returns a "
        "versioned ReplyModel carrying ApprovalProjection rows instead of the "
        "legacy raw approvals payload."
    ),
)
def get_approval_inbox(
    request: Request,
    project_id: str | None = None,
    client: AControlAgentClient = Depends(get_client),
    session_service: SessionService = Depends(get_session_service),
    store: SessionSpineStore = Depends(get_session_spine_store),
    approval_store: Any = Depends(get_canonical_approval_store),
    _: None = Depends(require_token),
) -> dict[str, object]:
    rid = request.headers.get("x-request-id")
    try:
        bundle = build_approval_inbox_bundle(
            client,
            project_id,
            session_service=session_service,
            store=store,
            approval_store=approval_store,
        )
    except SessionSpineUpstreamError as exc:
        return err(rid, exc.error)
    return ok(rid, build_approval_inbox_reply(bundle).model_dump(mode="json"))


@router.get(
    "/sessions",
    summary="List stable session directory",
    description=(
        "Stable read surface for cross-project session discovery. Returns a "
        "versioned ReplyModel carrying SessionProjection rows instead of the "
        "raw A-Control-Agent task list."
    ),
)
def list_sessions(
    request: Request,
    client: AControlAgentClient = Depends(get_client),
    session_service: SessionService = Depends(get_session_service),
    store: SessionSpineStore = Depends(get_session_spine_store),
    approval_store: Any = Depends(get_canonical_approval_store),
    decision_store: Any = Depends(get_decision_store),
    receipt_store: ActionReceiptStore = Depends(get_receipt_store),
    orchestration_state_store: ResidentOrchestrationStateStore = Depends(
        get_resident_orchestration_state_store
    ),
    resident_expert_runtime_service: ResidentExpertRuntimeService = Depends(
        get_resident_expert_runtime_service
    ),
    _: None = Depends(require_token),
) -> dict[str, object]:
    rid = request.headers.get("x-request-id")
    try:
        bundle = build_session_directory_bundle(
            client,
            session_service=session_service,
            store=store,
            approval_store=approval_store,
            decision_store=decision_store,
            receipt_store=receipt_store,
            orchestration_state_store=orchestration_state_store,
            dispatch_cooldown_seconds=_get_auto_dispatch_cooldown_seconds(request),
            resident_expert_runtime_service=resident_expert_runtime_service,
        )
    except SessionSpineUpstreamError as exc:
        return err(rid, exc.error)
    return ok(rid, build_session_directory_reply(bundle).model_dump(mode="json"))


@router.get(
    "/sessions/by-native-thread/{native_thread_id}",
    summary="Resolve stable session projection by native thread",
    description=(
        "Stable read surface for callers that only know the native thread_id. "
        "Returns the canonical ReplyModel carrying SessionProjection and FactRecord data."
    ),
)
def get_session_by_native_thread(
    native_thread_id: str,
    request: Request,
    client: AControlAgentClient = Depends(get_client),
    session_service: SessionService = Depends(get_session_service),
    store: SessionSpineStore = Depends(get_session_spine_store),
    approval_store: Any = Depends(get_canonical_approval_store),
    decision_store: Any = Depends(get_decision_store),
    receipt_store: ActionReceiptStore = Depends(get_receipt_store),
    orchestration_state_store: ResidentOrchestrationStateStore = Depends(
        get_resident_orchestration_state_store
    ),
    _: None = Depends(require_token),
) -> dict[str, object]:
    rid = request.headers.get("x-request-id")
    freshness_window_seconds = _get_session_spine_freshness_window_seconds(request)
    try:
        bundle = build_session_read_bundle_by_native_thread(
            client,
            native_thread_id,
            session_service=session_service,
            store=store,
            approval_store=approval_store,
            decision_store=decision_store,
            receipt_store=receipt_store,
            orchestration_state_store=orchestration_state_store,
            dispatch_cooldown_seconds=_get_auto_dispatch_cooldown_seconds(request),
            freshness_window_seconds=freshness_window_seconds,
        )
    except SessionSpineUpstreamError as exc:
        return err(rid, exc.error)
    return ok(
        rid,
        build_session_reply(
            bundle,
            intent_code="get_session_by_native_thread",
        ).model_dump(mode="json"),
    )


@router.get(
    "/sessions/{project_id}",
    summary="Get stable session projection",
    description=(
        "Stable read surface for OpenClaw and other callers. Returns a "
        "versioned ReplyModel carrying SessionProjection and FactRecord data."
    ),
)
def get_session(
    project_id: str,
    request: Request,
    client: AControlAgentClient = Depends(get_client),
    session_service: SessionService = Depends(get_session_service),
    store: SessionSpineStore = Depends(get_session_spine_store),
    approval_store: Any = Depends(get_canonical_approval_store),
    decision_store: Any = Depends(get_decision_store),
    receipt_store: ActionReceiptStore = Depends(get_receipt_store),
    orchestration_state_store: ResidentOrchestrationStateStore = Depends(
        get_resident_orchestration_state_store
    ),
    _: None = Depends(require_token),
) -> dict[str, object]:
    rid = request.headers.get("x-request-id")
    freshness_window_seconds = _get_session_spine_freshness_window_seconds(request)
    try:
        bundle = build_session_read_bundle(
            client,
            project_id,
            session_service=session_service,
            store=store,
            approval_store=approval_store,
            decision_store=decision_store,
            receipt_store=receipt_store,
            orchestration_state_store=orchestration_state_store,
            dispatch_cooldown_seconds=_get_auto_dispatch_cooldown_seconds(request),
            freshness_window_seconds=freshness_window_seconds,
        )
    except SessionSpineUpstreamError as exc:
        return err(rid, exc.error)
    return ok(rid, build_session_reply(bundle).model_dump(mode="json"))


@router.get(
    "/sessions/{project_id}/progress",
    summary="Get stable progress view",
    description=(
        "Stable read surface for progress-oriented intents. Returns a "
        "versioned ReplyModel carrying TaskProgressView and supporting facts."
    ),
)
def get_progress(
    project_id: str,
    request: Request,
    client: AControlAgentClient = Depends(get_client),
    session_service: SessionService = Depends(get_session_service),
    store: SessionSpineStore = Depends(get_session_spine_store),
    approval_store: Any = Depends(get_canonical_approval_store),
    decision_store: Any = Depends(get_decision_store),
    receipt_store: ActionReceiptStore = Depends(get_receipt_store),
    orchestration_state_store: ResidentOrchestrationStateStore = Depends(
        get_resident_orchestration_state_store
    ),
    _: None = Depends(require_token),
) -> dict[str, object]:
    rid = request.headers.get("x-request-id")
    freshness_window_seconds = _get_session_spine_freshness_window_seconds(request)
    try:
        bundle = build_session_read_bundle(
            client,
            project_id,
            session_service=session_service,
            store=store,
            approval_store=approval_store,
            decision_store=decision_store,
            receipt_store=receipt_store,
            orchestration_state_store=orchestration_state_store,
            dispatch_cooldown_seconds=_get_auto_dispatch_cooldown_seconds(request),
            freshness_window_seconds=freshness_window_seconds,
        )
    except SessionSpineUpstreamError as exc:
        return err(rid, exc.error)
    return ok(rid, build_progress_reply(bundle).model_dump(mode="json"))


@router.get(
    "/sessions/{project_id}/facts",
    summary="Get stable session facts truth source",
    description=(
        "Canonical stable facts read surface for OpenClaw and other callers. "
        "Returns a versioned ReplyModel carrying FactRecord rows without "
        "changing the explanation surfaces."
    ),
)
def get_session_facts(
    project_id: str,
    request: Request,
    client: AControlAgentClient = Depends(get_client),
    session_service: SessionService = Depends(get_session_service),
    store: SessionSpineStore = Depends(get_session_spine_store),
    approval_store: Any = Depends(get_canonical_approval_store),
    decision_store: Any = Depends(get_decision_store),
    receipt_store: ActionReceiptStore = Depends(get_receipt_store),
    orchestration_state_store: ResidentOrchestrationStateStore = Depends(
        get_resident_orchestration_state_store
    ),
    _: None = Depends(require_token),
) -> dict[str, object]:
    rid = request.headers.get("x-request-id")
    freshness_window_seconds = _get_session_spine_freshness_window_seconds(request)
    try:
        bundle = build_session_read_bundle(
            client,
            project_id,
            session_service=session_service,
            store=store,
            approval_store=approval_store,
            decision_store=decision_store,
            receipt_store=receipt_store,
            orchestration_state_store=orchestration_state_store,
            dispatch_cooldown_seconds=_get_auto_dispatch_cooldown_seconds(request),
            freshness_window_seconds=freshness_window_seconds,
        )
    except SessionSpineUpstreamError as exc:
        return err(rid, exc.error)
    return ok(rid, build_session_facts_reply(bundle).model_dump(mode="json"))


@router.get(
    "/sessions/{project_id}/workspace-activity",
    summary="Get stable workspace activity view",
    description=(
        "Stable read surface for workspace activity inspection. Returns a "
        "versioned ReplyModel carrying WorkspaceActivityView instead of the "
        "raw A-Control-Agent workspace activity envelope."
    ),
)
def get_workspace_activity(
    project_id: str,
    request: Request,
    recent_minutes: int = Query(default=15, ge=1, le=24 * 60),
    client: AControlAgentClient = Depends(get_client),
    _: None = Depends(require_token),
) -> dict[str, object]:
    rid = request.headers.get("x-request-id")
    try:
        bundle = build_workspace_activity_bundle(
            client,
            project_id,
            recent_minutes=recent_minutes,
        )
    except SessionSpineUpstreamError as exc:
        return err(rid, exc.error)
    return ok(rid, build_workspace_activity_reply(bundle).model_dump(mode="json"))


@router.get(
    "/sessions/{project_id}/pending-approvals",
    summary="List pending approvals via stable contract",
    description=(
        "Stable read surface for approval queue access. Returns a versioned "
        "ReplyModel instead of the raw legacy approvals payload."
    ),
)
def get_pending_approvals(
    project_id: str,
    request: Request,
    client: AControlAgentClient = Depends(get_client),
    session_service: SessionService = Depends(get_session_service),
    store: SessionSpineStore = Depends(get_session_spine_store),
    approval_store: Any = Depends(get_canonical_approval_store),
    decision_store: Any = Depends(get_decision_store),
    receipt_store: ActionReceiptStore = Depends(get_receipt_store),
    orchestration_state_store: ResidentOrchestrationStateStore = Depends(
        get_resident_orchestration_state_store
    ),
    _: None = Depends(require_token),
) -> dict[str, object]:
    rid = request.headers.get("x-request-id")
    freshness_window_seconds = _get_session_spine_freshness_window_seconds(request)
    try:
        bundle = build_session_read_bundle(
            client,
            project_id,
            session_service=session_service,
            store=store,
            approval_store=approval_store,
            decision_store=decision_store,
            receipt_store=receipt_store,
            orchestration_state_store=orchestration_state_store,
            dispatch_cooldown_seconds=_get_auto_dispatch_cooldown_seconds(request),
            freshness_window_seconds=freshness_window_seconds,
        )
    except SessionSpineUpstreamError as exc:
        return err(rid, exc.error)
    return ok(rid, build_approval_queue_reply(bundle).model_dump(mode="json"))


@router.get(
    "/sessions/{project_id}/event-snapshot",
    summary="Get stable session event snapshot",
    description=(
        "Stable JSON read surface for session events. Returns a versioned ReplyModel "
        "carrying SessionEvent rows. The snapshot merges projected raw task events with "
        "selected canonical Session Service events, synthesizes deterministic ids when "
        "raw events omit `event_id`, dedupes repeated event_ids, and keeps recovery and "
        "goal-contract lineage visible even when the control link is degraded."
    ),
)
def get_session_event_snapshot(
    project_id: str,
    request: Request,
    client: AControlAgentClient = Depends(get_client),
    session_service: SessionService = Depends(get_session_service),
    _: None = Depends(require_token),
) -> dict[str, object]:
    rid = request.headers.get("x-request-id")
    try:
        events = list_projected_session_events(
            client,
            project_id,
            session_service=session_service,
        )
    except SessionSpineUpstreamError as exc:
        return err(rid, exc.error)
    return ok(rid, build_session_event_snapshot_reply(events).model_dump(mode="json"))


@router.get(
    "/sessions/{project_id}/stuck-explanation",
    summary="Explain why a session appears stuck",
    description=(
        "Stable read surface for why_stuck. Returns the frozen ReplyModel "
        "shape with session, progress, and FactRecord context."
    ),
)
def get_stuck_explanation(
    project_id: str,
    request: Request,
    client: AControlAgentClient = Depends(get_client),
    session_service: SessionService = Depends(get_session_service),
    store: SessionSpineStore = Depends(get_session_spine_store),
    approval_store: Any = Depends(get_canonical_approval_store),
    decision_store: Any = Depends(get_decision_store),
    receipt_store: ActionReceiptStore = Depends(get_receipt_store),
    orchestration_state_store: ResidentOrchestrationStateStore = Depends(
        get_resident_orchestration_state_store
    ),
    _: None = Depends(require_token),
) -> dict[str, object]:
    rid = request.headers.get("x-request-id")
    freshness_window_seconds = _get_session_spine_freshness_window_seconds(request)
    try:
        bundle = build_session_read_bundle(
            client,
            project_id,
            session_service=session_service,
            store=store,
            approval_store=approval_store,
            decision_store=decision_store,
            receipt_store=receipt_store,
            orchestration_state_store=orchestration_state_store,
            dispatch_cooldown_seconds=_get_auto_dispatch_cooldown_seconds(request),
            freshness_window_seconds=freshness_window_seconds,
        )
    except SessionSpineUpstreamError as exc:
        return err(rid, exc.error)
    return ok(rid, build_stuck_explanation_reply(bundle).model_dump(mode="json"))


@router.get(
    "/sessions/{project_id}/blocker-explanation",
    summary="Explain the current primary blocker",
    description=(
        "Stable read surface for explain_blocker. Returns the frozen ReplyModel "
        "shape with session, progress, and FactRecord context."
    ),
)
def get_blocker_explanation(
    project_id: str,
    request: Request,
    client: AControlAgentClient = Depends(get_client),
    session_service: SessionService = Depends(get_session_service),
    store: SessionSpineStore = Depends(get_session_spine_store),
    approval_store: Any = Depends(get_canonical_approval_store),
    decision_store: Any = Depends(get_decision_store),
    receipt_store: ActionReceiptStore = Depends(get_receipt_store),
    orchestration_state_store: ResidentOrchestrationStateStore = Depends(
        get_resident_orchestration_state_store
    ),
    _: None = Depends(require_token),
) -> dict[str, object]:
    rid = request.headers.get("x-request-id")
    freshness_window_seconds = _get_session_spine_freshness_window_seconds(request)
    try:
        bundle = build_session_read_bundle(
            client,
            project_id,
            session_service=session_service,
            store=store,
            approval_store=approval_store,
            decision_store=decision_store,
            receipt_store=receipt_store,
            orchestration_state_store=orchestration_state_store,
            dispatch_cooldown_seconds=_get_auto_dispatch_cooldown_seconds(request),
            freshness_window_seconds=freshness_window_seconds,
        )
    except SessionSpineUpstreamError as exc:
        return err(rid, exc.error)
    return ok(rid, build_blocker_explanation_reply(bundle).model_dump(mode="json"))


@router.get(
    "/action-receipts",
    summary="Get stable action receipt",
    description=(
        "Canonical stable read surface for persisted action receipts. Reads the "
        "local receipt store by action_code, project_id, approval_id, and idempotency_key."
    ),
)
def get_action_receipt(
    action_code: str,
    project_id: str,
    idempotency_key: str,
    request: Request,
    approval_id: str | None = None,
    receipt_store: ActionReceiptStore = Depends(get_receipt_store),
    _: None = Depends(require_token),
) -> dict[str, object]:
    query = _parse_action_receipt_query(
        {
            "action_code": action_code,
            "project_id": project_id,
            "approval_id": approval_id,
            "idempotency_key": idempotency_key,
        }
    )
    if query is None:
        return err(
            request.headers.get("x-request-id"),
            {"code": "INVALID_ARGUMENT", "message": "query must satisfy ActionReceiptQuery"},
        )
    reply = lookup_action_receipt(query, receipt_store=receipt_store)
    return ok(request.headers.get("x-request-id"), reply.model_dump(mode="json"))


@router.get(
    "/sessions/{project_id}/action-receipts/{action_code}/{idempotency_key}",
    summary="Alias: get stable action receipt",
    description=(
        "Human-friendly wrapper over GET /api/v1/watchdog/action-receipts. This "
        "route reuses the canonical receipt lookup semantics."
    ),
)
def get_action_receipt_alias(
    project_id: str,
    action_code: str,
    idempotency_key: str,
    request: Request,
    approval_id: str | None = None,
    receipt_store: ActionReceiptStore = Depends(get_receipt_store),
    _: None = Depends(require_token),
) -> dict[str, object]:
    return get_action_receipt(
        action_code=action_code,
        project_id=project_id,
        approval_id=approval_id,
        idempotency_key=idempotency_key,
        request=request,
        receipt_store=receipt_store,
    )
