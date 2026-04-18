from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request

from a_control_agent.api.deps import require_token
from a_control_agent.audit import append_jsonl
from a_control_agent.envelope import err, ok
from a_control_agent.settings import Settings
from a_control_agent.storage.handoff_manager import write_handoff_file
from a_control_agent.storage.tasks_store import TaskStore

router = APIRouter(prefix="/tasks", tags=["recovery"])
_SAME_THREAD_RESUME = "same_thread_resume"
_NEW_CHILD_SESSION = "new_child_session"


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_store(request: Request) -> TaskStore:
    return request.app.state.task_store


def get_bridge(request: Request) -> Any:
    return getattr(request.app.state, "codex_bridge", None)


def _resume_outcome_for_thread(
    *,
    parent_thread_id: str,
    resumed_thread_id: str,
) -> str:
    if resumed_thread_id and resumed_thread_id != parent_thread_id:
        return _NEW_CHILD_SESSION
    return _SAME_THREAD_RESUME


def _resume_response_payload(
    *,
    project_id: str,
    status: str,
    mode: str,
    resume_outcome: str,
    thread_id: str,
    parent_thread_id: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "project_id": project_id,
        "status": status,
        "mode": mode,
        "resume_outcome": resume_outcome,
        "thread_id": thread_id,
    }
    if resume_outcome == _NEW_CHILD_SESSION:
        payload["parent_thread_id"] = parent_thread_id
        payload["child_session_id"] = f"session:{project_id}:{thread_id}"
    return payload


@router.post("/{project_id}/pause")
def pause(
    project_id: str,
    request: Request,
    settings: Settings = Depends(get_settings),
    store: TaskStore = Depends(get_store),
    _: None = Depends(require_token),
) -> dict[str, Any]:
    rec = store.get(project_id)
    if rec is None:
        return err(
            request.headers.get("x-request-id"),
            {"code": "NOT_FOUND", "message": project_id},
        )
    store.merge_update(
        project_id,
        {
            "status": "paused",
            "phase": str(rec.get("phase", "planning")),
        },
    )
    rec2 = store.get(project_id)
    thread_id = str((rec2 or rec).get("thread_id") or "")
    store.append_event(
        project_id,
        thread_id=thread_id,
        event_type="pause",
        event_source="a_control_agent",
        payload_json={
            "status": "paused",
            "phase": str((rec2 or rec).get("phase", "planning")),
        },
    )
    append_jsonl(
        Path(settings.data_dir) / "audit.jsonl",
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "project_id": project_id,
            "action": "pause",
            "source": "a_control_agent",
            "payload": {"status": "paused"},
        },
    )
    return ok(
        request.headers.get("x-request-id"),
        {
            "project_id": project_id,
            "status": "paused",
        },
    )


@router.post("/{project_id}/handoff")
def handoff(
    project_id: str,
    request: Request,
    body: dict[str, Any],
    settings: Settings = Depends(get_settings),
    store: TaskStore = Depends(get_store),
    _: None = Depends(require_token),
) -> dict[str, Any]:
    reason = str(body.get("reason", "unspecified"))
    rec = store.get(project_id)
    if rec is None:
        return err(
            request.headers.get("x-request-id"),
            {"code": "NOT_FOUND", "message": project_id},
        )
    store.merge_update(
        project_id,
        {"status": "handoff_in_progress", "phase": "handoff", "stuck_level": 4},
    )
    rec2 = store.get(project_id)
    assert rec2 is not None
    handoffs_dir = Path(settings.data_dir) / "handoffs"
    hf_path, summary, source_packet_id = write_handoff_file(
        handoffs_dir,
        project_id,
        reason,
        dict(rec2),
    )
    goal_contract_version = str(rec2.get("goal_contract_version") or "").strip() or None
    store.append_event(
        project_id,
        thread_id=str(rec2.get("thread_id") or ""),
        event_type="handoff",
        event_source="a_control_agent",
        payload_json={
            "reason": reason,
            "handoff_file": hf_path,
            "source_packet_id": source_packet_id,
            "status": rec2.get("status"),
            "phase": rec2.get("phase"),
            **(
                {"goal_contract_version": goal_contract_version}
                if goal_contract_version is not None
                else {}
            ),
        },
    )
    now = datetime.now(timezone.utc).isoformat()
    append_jsonl(
        Path(settings.data_dir) / "audit.jsonl",
        {
            "ts": now,
            "project_id": project_id,
            "action": "handoff",
            "reason": reason,
            "source": "a_control_agent",
            "payload": {
                "handoff_file": hf_path,
                "source_packet_id": source_packet_id,
                **(
                    {"goal_contract_version": goal_contract_version}
                    if goal_contract_version is not None
                    else {}
                ),
            },
        },
    )
    response_data = {
        "handoff_file": hf_path,
        "summary": summary,
        "source_packet_id": source_packet_id,
    }
    if goal_contract_version is not None:
        response_data["goal_contract_version"] = goal_contract_version
    return ok(
        request.headers.get("x-request-id"),
        response_data,
    )


@router.post("/{project_id}/resume")
async def resume(
    project_id: str,
    request: Request,
    body: dict[str, Any],
    settings: Settings = Depends(get_settings),
    store: TaskStore = Depends(get_store),
    bridge: Any = Depends(get_bridge),
    _: None = Depends(require_token),
) -> dict[str, Any]:
    mode = str(body.get("mode", "resume_or_new_thread"))
    summary = str(body.get("handoff_summary", ""))
    rec = store.get(project_id)
    if rec is None:
        return err(
            request.headers.get("x-request-id"),
            {"code": "NOT_FOUND", "message": project_id},
        )
    store.merge_update(
        project_id,
        {
            "status": "resuming",
            "context_pressure": str(rec.get("context_pressure", "low")),
            "phase": str(rec.get("phase", "planning")),
        },
    )
    now = datetime.now(timezone.utc).isoformat()
    append_jsonl(
        Path(settings.data_dir) / "audit.jsonl",
        {
            "ts": now,
            "project_id": project_id,
            "action": "resume_requested",
            "reason": mode,
            "source": "a_control_agent",
            "payload": {"handoff_summary_len": len(summary)},
        },
    )
    parent_thread_id = str(rec.get("thread_id") or "")
    resumed_thread_id = parent_thread_id
    resume_outcome = _SAME_THREAD_RESUME
    try:
        if bridge is not None and parent_thread_id:
            resume_snapshot = await bridge.resume_thread(parent_thread_id)
            if isinstance(resume_snapshot, dict):
                resumed_thread_id = (
                    str(resume_snapshot.get("thread_id") or "").strip()
                    or parent_thread_id
                )
            resume_outcome = _resume_outcome_for_thread(
                parent_thread_id=parent_thread_id,
                resumed_thread_id=resumed_thread_id,
            )
            if summary:
                if bridge.active_turn_id(resumed_thread_id):
                    await bridge.steer_turn(resumed_thread_id, message=summary)
                else:
                    await bridge.start_turn(resumed_thread_id, prompt=summary)
                store.record_service_input(
                    project_id,
                    message=summary,
                    source="a_control_agent",
                    kind="resume_summary",
                )
    except Exception as exc:
        store.merge_update(
            project_id,
            {
                "status": "failed",
                "phase": "handoff",
                "last_error_signature": str(exc),
            },
        )
        append_jsonl(
            Path(settings.data_dir) / "audit.jsonl",
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "project_id": project_id,
                "action": "resume_failed",
                "reason": mode,
                "source": "a_control_agent",
                "payload": {"error": str(exc)},
            },
        )
        rec_failed = store.get(project_id)
        return err(
            request.headers.get("x-request-id"),
            {"code": "RESUME_FAILED", "message": str(exc)},
            {
                "project_id": project_id,
                "status": rec_failed.get("status") if rec_failed else "failed",
                "mode": mode,
            },
        )
    next_state = {
        "project_id": project_id,
        "cwd": str(rec.get("cwd") or ""),
        "task_title": str(rec.get("task_title") or ""),
        "task_prompt": str(rec.get("task_prompt") or ""),
        "model": str(rec.get("model") or ""),
        "sandbox": str(rec.get("sandbox") or ""),
        "approval_policy": str(rec.get("approval_policy") or ""),
        "status": "running",
        "context_pressure": "medium",
        "phase": str(rec.get("phase", "planning")),
        "thread_id": resumed_thread_id or parent_thread_id,
        "goal_contract_version": rec.get("goal_contract_version"),
    }
    if resume_outcome == _NEW_CHILD_SESSION and resumed_thread_id:
        rec3 = store.upsert_native_thread(next_state)
    else:
        store.merge_update(
            project_id,
            {
                "status": "running",
                "context_pressure": "medium",
                "phase": str(rec.get("phase", "planning")),
            },
        )
        rec3 = store.get(project_id)
    append_jsonl(
        Path(settings.data_dir) / "audit.jsonl",
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "project_id": project_id,
            "action": "resume",
            "reason": mode,
            "source": "a_control_agent",
            "payload": {
                "handoff_summary_len": len(summary),
                "resume_outcome": resume_outcome,
                "thread_id": resumed_thread_id or parent_thread_id,
                **(
                    {"parent_thread_id": parent_thread_id}
                    if resume_outcome == _NEW_CHILD_SESSION and parent_thread_id
                    else {}
                ),
            },
        },
    )
    if rec3 is not None:
        store.append_event(
            project_id,
            thread_id=str(rec3.get("thread_id") or ""),
            event_type="resume",
            event_source="a_control_agent",
            payload_json={
                "mode": mode,
                "handoff_summary_len": len(summary),
                "status": rec3.get("status"),
                "phase": rec3.get("phase"),
                "resume_outcome": resume_outcome,
                "thread_id": str(rec3.get("thread_id") or ""),
                **(
                    {"parent_thread_id": parent_thread_id}
                    if resume_outcome == _NEW_CHILD_SESSION and parent_thread_id
                    else {}
                ),
            },
        )
    response_data = _resume_response_payload(
        project_id=project_id,
        status=rec3.get("status") if rec3 else "running",
        mode=mode,
        resume_outcome=resume_outcome,
        thread_id=str((rec3 or {}).get("thread_id") or resumed_thread_id or parent_thread_id),
        parent_thread_id=parent_thread_id,
    )
    return ok(
        request.headers.get("x-request-id"),
        response_data,
    )
