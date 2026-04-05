from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from watchdog.api.deps import require_token
from watchdog.contracts.session_spine.enums import ReplyCode, ReplyKind
from watchdog.contracts.session_spine.models import ReplyModel
from watchdog.envelope import err, ok
from watchdog.services.a_client.client import AControlAgentClient
from watchdog.services.session_spine.service import SessionSpineUpstreamError, build_session_read_bundle

router = APIRouter(prefix="/watchdog", tags=["session-spine"])


def get_client(request: Request) -> AControlAgentClient:
    return request.app.state.a_client


def _session_reply(bundle) -> ReplyModel:
    return ReplyModel(
        reply_kind=ReplyKind.SESSION,
        reply_code=ReplyCode.SESSION_PROJECTION,
        intent_code="get_session",
        message=bundle.session.headline,
        session=bundle.session,
        facts=bundle.facts,
    )


def _progress_reply(bundle) -> ReplyModel:
    return ReplyModel(
        reply_kind=ReplyKind.SESSION,
        reply_code=ReplyCode.TASK_PROGRESS_VIEW,
        intent_code="get_progress",
        message=bundle.progress.summary or bundle.session.headline,
        progress=bundle.progress,
        facts=bundle.facts,
    )


def _approvals_reply(bundle) -> ReplyModel:
    count = len(bundle.approval_queue)
    return ReplyModel(
        reply_kind=ReplyKind.APPROVALS,
        reply_code=ReplyCode.APPROVAL_QUEUE,
        intent_code="list_pending_approvals",
        message=f"{count} pending approval(s)",
        approvals=bundle.approval_queue,
        facts=bundle.facts,
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
    _: None = Depends(require_token),
) -> dict[str, object]:
    rid = request.headers.get("x-request-id")
    try:
        bundle = build_session_read_bundle(client, project_id)
    except SessionSpineUpstreamError as exc:
        return err(rid, exc.error)
    return ok(rid, _session_reply(bundle).model_dump(mode="json"))


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
    _: None = Depends(require_token),
) -> dict[str, object]:
    rid = request.headers.get("x-request-id")
    try:
        bundle = build_session_read_bundle(client, project_id)
    except SessionSpineUpstreamError as exc:
        return err(rid, exc.error)
    return ok(rid, _progress_reply(bundle).model_dump(mode="json"))


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
    _: None = Depends(require_token),
) -> dict[str, object]:
    rid = request.headers.get("x-request-id")
    try:
        bundle = build_session_read_bundle(client, project_id)
    except SessionSpineUpstreamError as exc:
        return err(rid, exc.error)
    return ok(rid, _approvals_reply(bundle).model_dump(mode="json"))
