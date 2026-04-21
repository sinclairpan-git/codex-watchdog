from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError

from a_control_agent.api.deps import require_token
from a_control_agent.audit import append_jsonl
from a_control_agent.envelope import err, ok
from a_control_agent.settings import Settings
from a_control_agent.storage.handoff_manager import write_handoff_file
from a_control_agent.storage.tasks_store import TaskStore
from watchdog.services.session_spine.continuation_packet import (
    model_validate_continuation_packet,
    render_continuation_packet_prompt,
)
from watchdog.services.session_spine.task_state import (
    is_canonical_task_phase,
    normalize_task_phase,
)

router = APIRouter(prefix="/tasks", tags=["recovery"])
_SAME_THREAD_RESUME = "same_thread_resume"
_NEW_CHILD_SESSION = "new_child_session"


class _InvalidContinuationPacket(ValueError):
    pass


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
    resume_target_phase: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "project_id": project_id,
        "status": status,
        "mode": mode,
        "resume_outcome": resume_outcome,
        "thread_id": thread_id,
        "resume_target_phase": resume_target_phase,
    }
    if resume_outcome == _NEW_CHILD_SESSION:
        payload["parent_thread_id"] = parent_thread_id
        payload["child_session_id"] = f"session:{project_id}:{thread_id}"
    return payload


def _continuation_packet_from_body(body: dict[str, Any]) -> dict[str, Any] | None:
    raw = body.get("continuation_packet")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise _InvalidContinuationPacket("continuation_packet must be an object")
    return model_validate_continuation_packet(raw).model_dump(mode="json", exclude_none=True)


def _continuation_packet_validation_error(exc: ValidationError | _InvalidContinuationPacket) -> dict[str, str]:
    if isinstance(exc, _InvalidContinuationPacket):
        return {"code": "INVALID_ARGUMENT", "message": str(exc)}
    fields = [
        ".".join(str(part) for part in item["loc"])
        for item in exc.errors()
        if item.get("loc")
    ]
    if not fields:
        message = "continuation_packet must satisfy ContinuationPacket"
    else:
        message = f"missing or invalid continuation_packet fields: {', '.join(fields)}"
    return {"code": "INVALID_ARGUMENT", "message": message}


def _resume_target_phase(task: dict[str, Any] | None) -> str:
    phase = normalize_task_phase(task)
    if phase != "handoff":
        return phase
    if not isinstance(task, dict):
        return "planning"
    stored = normalize_task_phase({"phase": task.get("resume_target_phase")})
    if is_canonical_task_phase(stored) and stored != "handoff":
        return stored
    return "planning"


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
    try:
        continuation_packet = _continuation_packet_from_body(body)
    except (ValidationError, _InvalidContinuationPacket) as exc:
        return err(
            request.headers.get("x-request-id"),
            _continuation_packet_validation_error(exc),
        )
    rec = store.get(project_id)
    if rec is None:
        return err(
            request.headers.get("x-request-id"),
            {"code": "NOT_FOUND", "message": project_id},
        )
    resume_target_phase = _resume_target_phase(rec)
    store.merge_update(
        project_id,
        {
            "status": "handoff_in_progress",
            "phase": "handoff",
            "stuck_level": 4,
            "resume_target_phase": resume_target_phase,
        },
    )
    rec2 = store.get(project_id)
    assert rec2 is not None
    handoffs_dir = Path(settings.data_dir) / "handoffs"
    hf_path, summary, source_packet_id, resolved_packet = write_handoff_file(
        handoffs_dir,
        project_id,
        reason,
        dict(rec2),
        continuation_packet=continuation_packet,
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
            "resume_target_phase": rec2.get("resume_target_phase"),
            "continuation_packet_id": str(resolved_packet.get("packet_id") or source_packet_id),
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
                "resume_target_phase": resume_target_phase,
                "continuation_packet_id": str(resolved_packet.get("packet_id") or source_packet_id),
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
        "resume_target_phase": resume_target_phase,
        "continuation_packet": resolved_packet,
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
    try:
        continuation_packet = _continuation_packet_from_body(body)
    except (ValidationError, _InvalidContinuationPacket) as exc:
        return err(
            request.headers.get("x-request-id"),
            _continuation_packet_validation_error(exc),
        )
    rendered_prompt = (
        render_continuation_packet_prompt(continuation_packet)
        if continuation_packet is not None
        else summary
    )
    rec = store.get(project_id)
    if rec is None:
        return err(
            request.headers.get("x-request-id"),
            {"code": "NOT_FOUND", "message": project_id},
        )
    resume_target_phase = _resume_target_phase(rec)
    store.merge_update(
        project_id,
        {
            "status": "resuming",
            "context_pressure": str(rec.get("context_pressure", "low")),
            "phase": resume_target_phase,
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
            "payload": {
                "handoff_summary_len": len(rendered_prompt),
                "resume_target_phase": resume_target_phase,
                **(
                    {"source_packet_id": str(continuation_packet.get("packet_id") or "")}
                    if continuation_packet is not None
                    else {}
                ),
            },
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
            if rendered_prompt:
                if bridge.active_turn_id(resumed_thread_id):
                    await bridge.steer_turn(resumed_thread_id, message=rendered_prompt)
                else:
                    await bridge.start_turn(resumed_thread_id, prompt=rendered_prompt)
                store.record_service_input(
                    project_id,
                    message=rendered_prompt,
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
                "payload": {
                    "error": str(exc),
                    "resume_target_phase": resume_target_phase,
                },
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
        "last_user_instruction": str(rec.get("last_user_instruction") or ""),
        "current_phase_goal": str(rec.get("current_phase_goal") or ""),
        "last_summary": str(rec.get("last_summary") or ""),
        "files_touched": list(rec.get("files_touched") or []),
        "approval_risk": rec.get("approval_risk"),
        "last_error_signature": rec.get("last_error_signature"),
        "last_substantive_user_input_at": rec.get("last_substantive_user_input_at"),
        "last_substantive_user_input_fingerprint": rec.get(
            "last_substantive_user_input_fingerprint"
        ),
        "last_local_manual_activity_at": rec.get("last_local_manual_activity_at"),
        "recent_service_inputs": list(rec.get("recent_service_inputs") or []),
        "model": str(rec.get("model") or ""),
        "sandbox": str(rec.get("sandbox") or ""),
        "approval_policy": str(rec.get("approval_policy") or ""),
        "stuck_level": rec.get("stuck_level"),
        "failure_count": rec.get("failure_count"),
        "status": "running",
        "context_pressure": "medium",
        "phase": resume_target_phase,
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
                "phase": resume_target_phase,
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
                "handoff_summary_len": len(rendered_prompt),
                "resume_outcome": resume_outcome,
                "thread_id": resumed_thread_id or parent_thread_id,
                "resume_target_phase": resume_target_phase,
                **(
                    {"source_packet_id": str(continuation_packet.get("packet_id") or "")}
                    if continuation_packet is not None
                    else {}
                ),
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
                "handoff_summary_len": len(rendered_prompt),
                "status": rec3.get("status"),
                "phase": rec3.get("phase"),
                "resume_outcome": resume_outcome,
                "thread_id": str(rec3.get("thread_id") or ""),
                "resume_target_phase": resume_target_phase,
                **(
                    {"source_packet_id": str(continuation_packet.get("packet_id") or "")}
                    if continuation_packet is not None
                    else {}
                ),
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
        resume_target_phase=resume_target_phase,
    )
    if continuation_packet is not None:
        response_data["source_packet_id"] = str(continuation_packet.get("packet_id") or "")
        response_data["continuation_packet"] = continuation_packet
    return ok(
        request.headers.get("x-request-id"),
        response_data,
    )
