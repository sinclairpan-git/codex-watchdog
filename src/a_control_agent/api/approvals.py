from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from a_control_agent.api.deps import require_token
from a_control_agent.envelope import err, ok
from a_control_agent.storage.approvals_store import ApprovalsStore
from a_control_agent.storage.tasks_store import TaskStore

router = APIRouter(prefix="/approvals", tags=["approvals"])


def get_approval_store(request: Request) -> ApprovalsStore:
    return request.app.state.approvals_store


def get_task_store(request: Request) -> TaskStore:
    return request.app.state.task_store


def get_bridge(request: Request) -> Any:
    return getattr(request.app.state, "codex_bridge", None)


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
async def decide(
    approval_id: str,
    request: Request,
    body: dict[str, Any],
    store: ApprovalsStore = Depends(get_approval_store),
    task_store: TaskStore = Depends(get_task_store),
    bridge: Any = Depends(get_bridge),
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
    current = store.get(approval_id)
    if current is None:
        return err(
            request.headers.get("x-request-id"),
            {"code": "NOT_FOUND_OR_NOT_PENDING", "message": approval_id},
        )
    request_id = current.get("bridge_request_id")
    if current.get("status") == "approved" and current.get("decided_by") == "policy-auto":
        if decision != "approve":
            return err(
                request.headers.get("x-request-id"),
                {
                    "code": "INVALID_ARGUMENT",
                    "message": "policy-auto approvals only support approve callback replay",
                },
                data=current,
            )
        if isinstance(request_id, str) and request_id and bridge is not None:
            try:
                await bridge.resolve_pending_approval(request_id, decision="approve", note=note)
            except Exception as exc:
                return err(
                    request.headers.get("x-request-id"),
                    {"code": "APPROVAL_CALLBACK_FAILED", "message": str(exc)},
                    data=current,
                )
            return ok(request.headers.get("x-request-id"), current)
    if current.get("status") != "pending":
        return err(
            request.headers.get("x-request-id"),
            {"code": "NOT_FOUND_OR_NOT_PENDING", "message": approval_id},
        )
    if isinstance(request_id, str) and request_id and bridge is not None:
        try:
            await bridge.resolve_pending_approval(request_id, decision=str(decision), note=note)
        except Exception as exc:
            return err(
                request.headers.get("x-request-id"),
                {"code": "APPROVAL_CALLBACK_FAILED", "message": str(exc)},
                data=current,
            )
    rec = store.apply_decision(approval_id, decision=str(decision), operator=str(operator), note=note)
    if rec is None:
        return err(
            request.headers.get("x-request-id"),
            {"code": "NOT_FOUND_OR_NOT_PENDING", "message": approval_id},
        )
    project_id = rec.get("project_id")
    if isinstance(project_id, str) and project_id:
        task_store.merge_update(
            project_id,
            {
                "pending_approval": False,
                "approval_risk": None,
            },
        )
        task_store.append_event(
            project_id,
            thread_id=str(rec.get("thread_id") or ""),
            event_type="approval_decided",
            event_source="a_control_agent",
            payload_json={
                "approval_id": approval_id,
                "decision": decision,
                "operator": operator,
                "note": note,
            },
        )
    return ok(request.headers.get("x-request-id"), rec)
