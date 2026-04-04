from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from a_control_agent.api.deps import require_token
from a_control_agent.envelope import err, ok
from a_control_agent.storage.approvals_store import ApprovalsStore

router = APIRouter(prefix="/approvals", tags=["approvals"])


def get_approval_store(request: Request) -> ApprovalsStore:
    return request.app.state.approvals_store


@router.get("")
def list_approvals(
    request: Request,
    status: str | None = Query(default=None),
    store: ApprovalsStore = Depends(get_approval_store),
    _: None = Depends(require_token),
) -> dict[str, Any]:
    rows = store.list_by_status(status)
    return ok(request.headers.get("x-request-id"), {"items": rows, "count": len(rows)})


@router.post("")
def create_approval(
    request: Request,
    body: dict[str, Any],
    store: ApprovalsStore = Depends(get_approval_store),
    _: None = Depends(require_token),
) -> dict[str, Any]:
    pid = body.get("project_id")
    tid = body.get("thread_id")
    cmd = body.get("command")
    if not pid or not tid or not cmd:
        return err(
            request.headers.get("x-request-id"),
            {"code": "INVALID_ARGUMENT", "message": "project_id, thread_id, command required"},
        )
    rec = store.create_request(
        project_id=str(pid),
        thread_id=str(tid),
        command=str(cmd),
        reason=str(body.get("reason", "")),
        alternative=str(body.get("alternative", "")),
    )
    return ok(request.headers.get("x-request-id"), rec)


@router.post("/{approval_id}/decision")
def decide(
    approval_id: str,
    request: Request,
    body: dict[str, Any],
    store: ApprovalsStore = Depends(get_approval_store),
    _: None = Depends(require_token),
) -> dict[str, Any]:
    decision = body.get("decision")
    operator = body.get("operator", "unknown")
    note = str(body.get("note", ""))
    if decision not in ("approve", "reject"):
        return err(
            request.headers.get("x-request-id"),
            {"code": "INVALID_ARGUMENT", "message": "decision must be approve or reject"},
        )
    rec = store.apply_decision(
        approval_id,
        decision=str(decision),
        operator=str(operator),
        note=note,
    )
    if rec is None:
        return err(
            request.headers.get("x-request-id"),
            {"code": "NOT_FOUND_OR_NOT_PENDING", "message": approval_id},
        )
    return ok(request.headers.get("x-request-id"), rec)
