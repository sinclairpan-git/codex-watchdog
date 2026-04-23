from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from a_control_agent.audit import append_jsonl
from a_control_agent.services.codex_input import fingerprint_input_text
from watchdog.services.project_aliases import (
    canonicalize_project_id,
    rewrite_legacy_project_aliases,
)
from watchdog.services.session_spine.task_state import (
    is_canonical_task_phase,
    is_canonical_task_status,
    normalize_task_phase,
    normalize_task_status,
)


class TaskRecord(dict[str, Any]):
    """任务记录视图。"""


_RECENT_SERVICE_INPUT_LIMIT = 8
_CANONICAL_CONTEXT_PRESSURES = {"low", "medium", "high", "critical"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _derive_project_id(raw: Any, cwd: str, *, fallback: str = "") -> str:
    if isinstance(raw, str) and raw.strip():
        return canonicalize_project_id(raw.strip())
    if cwd.strip():
        name = Path(cwd).name.strip()
        if name:
            return canonicalize_project_id(name)
    if fallback.strip():
        return canonicalize_project_id(fallback.strip())
    return "unknown-project"


def _safe_int(value: Any, *, default: int = 0, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(parsed, minimum)
    if maximum is not None:
        parsed = min(parsed, maximum)
    return parsed


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no", ""}:
            return False
    return default


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized or normalized.lower() in {"none", "null"}:
        return None
    return normalized


def _normalize_files_touched(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    normalized: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            normalized.append(text)
    return normalized


def _canonicalize_task_record(
    rec: dict[str, Any],
    *,
    fallback_status: str = "created",
    fallback_phase: str = "planning",
) -> dict[str, Any]:
    rec["pending_approval"] = _coerce_bool(rec.get("pending_approval", False), default=False)
    status = normalize_task_status(rec)
    phase = normalize_task_phase(rec)
    rec["status"] = status if is_canonical_task_status(status) else fallback_status
    rec["phase"] = phase if is_canonical_task_phase(phase) else fallback_phase
    context_pressure = str(rec.get("context_pressure", "low") or "low")
    rec["context_pressure"] = (
        context_pressure if context_pressure in _CANONICAL_CONTEXT_PRESSURES else "low"
    )
    rec["stuck_level"] = _safe_int(rec.get("stuck_level", 0), default=0, minimum=0, maximum=4)
    rec["failure_count"] = _safe_int(rec.get("failure_count", 0), default=0, minimum=0)
    rec["files_touched"] = _normalize_files_touched(rec.get("files_touched"))
    rec["approval_risk"] = rec.get("approval_risk")
    rec["last_error_signature"] = rec.get("last_error_signature")
    rec["task_title"] = str(rec.get("task_title", ""))
    rec["task_prompt"] = str(rec.get("task_prompt", ""))
    rec["last_user_instruction"] = str(rec.get("last_user_instruction", ""))
    rec["current_phase_goal"] = str(rec.get("current_phase_goal", ""))
    rec["last_summary"] = str(rec.get("last_summary", ""))
    rec["goal_contract_version"] = _normalize_optional_text(rec.get("goal_contract_version"))
    return rec


class TaskStore:
    """文件型 JSON 持久化，支持 project_id 下的多 thread 记录。"""

    def __init__(self, path: Path, *, service_input_match_window_seconds: float = 120.0) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._audit_path = path.parent / "audit.jsonl"
        self._events_path = path.parent / "task_events.jsonl"
        self._service_input_match_window_seconds = max(
            float(service_input_match_window_seconds),
            0.0,
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._write(self._empty_payload())
        else:
            with self._lock:
                data, changed = self._load()
                if changed:
                    self._write(data)

    def _empty_payload(self) -> dict[str, Any]:
        return {"version": 2, "projects": {}, "tasks": {}}

    def _read_file(self) -> dict[str, Any]:
        raw = self._path.read_text(encoding="utf-8")
        return json.loads(raw) if raw.strip() else {}

    def _write(self, data: dict[str, Any]) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data, dict):
            return self._empty_payload()
        data = rewrite_legacy_project_aliases(data)

        if isinstance(data.get("tasks"), dict):
            raw_tasks = data.get("tasks", {})
        else:
            raw_tasks = data

        tasks: dict[str, dict[str, Any]] = {}
        for key, row in raw_tasks.items():
            if not isinstance(row, dict):
                continue
            rec = dict(row)
            thread_id = str(rec.get("thread_id") or key or f"thr_{uuid.uuid4().hex[:16]}")
            cwd = str(rec.get("cwd") or "")
            project_id = _derive_project_id(rec.get("project_id"), cwd, fallback=str(key))
            rec["project_id"] = project_id
            rec["thread_id"] = thread_id
            rec["created_at"] = str(rec.get("created_at") or rec.get("last_progress_at") or _now_iso())
            rec["recent_service_inputs"] = self._normalize_recent_service_inputs(
                rec.get("recent_service_inputs")
            )
            manual_activity_at = rec.get("last_local_manual_activity_at")
            rec["last_local_manual_activity_at"] = (
                str(manual_activity_at) if isinstance(manual_activity_at, str) and manual_activity_at else None
            )
            last_user_input_at = rec.get("last_substantive_user_input_at")
            if isinstance(last_user_input_at, str) and last_user_input_at:
                rec["last_substantive_user_input_at"] = last_user_input_at
            else:
                rec.pop("last_substantive_user_input_at", None)
            last_user_input_fingerprint = rec.get("last_substantive_user_input_fingerprint")
            if isinstance(last_user_input_fingerprint, str) and last_user_input_fingerprint:
                rec["last_substantive_user_input_fingerprint"] = last_user_input_fingerprint
            else:
                rec.pop("last_substantive_user_input_fingerprint", None)
            self._reconcile_local_manual_activity(rec)
            _canonicalize_task_record(rec)
            tasks[thread_id] = rec

        projects: dict[str, dict[str, Any]] = {}
        raw_projects = data.get("projects")
        if isinstance(raw_projects, dict):
            for project_id, meta in raw_projects.items():
                if not isinstance(meta, dict):
                    continue
                ordered_ids: list[str] = []
                for raw_tid in meta.get("thread_ids", []):
                    tid = str(raw_tid)
                    rec = tasks.get(tid)
                    if rec is None or rec.get("project_id") != project_id or tid in ordered_ids:
                        continue
                    ordered_ids.append(tid)
                for tid, rec in tasks.items():
                    if rec.get("project_id") == project_id and tid not in ordered_ids:
                        ordered_ids.append(tid)
                if not ordered_ids:
                    continue
                current_tid = str(meta.get("current_thread_id") or ordered_ids[-1])
                if current_tid not in ordered_ids:
                    current_tid = ordered_ids[-1]
                projects[str(project_id)] = {
                    "current_thread_id": current_tid,
                    "thread_ids": ordered_ids,
                }

        for tid, rec in tasks.items():
            project_id = str(rec["project_id"])
            entry = projects.setdefault(
                project_id,
                {"current_thread_id": tid, "thread_ids": []},
            )
            if tid not in entry["thread_ids"]:
                entry["thread_ids"].append(tid)
            if entry["current_thread_id"] not in entry["thread_ids"]:
                entry["current_thread_id"] = tid

        raw_active = data.get("active_native_thread_ids")
        result = {
            "version": 2,
            "projects": projects,
            "tasks": tasks,
        }
        if isinstance(raw_active, list):
            result["active_native_thread_ids"] = [
                str(thread_id)
                for thread_id in raw_active
                if str(thread_id).strip() and str(thread_id) in tasks
            ]
        return result

    def _load(self) -> tuple[dict[str, Any], bool]:
        raw = self._read_file()
        normalized = self._normalize(raw)
        return normalized, normalized != raw

    def _read(self) -> dict[str, Any]:
        data, changed = self._load()
        if changed:
            self._write(data)
        return data

    def _normalize_recent_service_inputs(self, raw: Any) -> list[dict[str, str]]:
        if not isinstance(raw, list):
            return []
        normalized: list[dict[str, str]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            fingerprint = str(item.get("fingerprint") or "").strip()
            at = str(item.get("at") or "").strip()
            if not fingerprint or not at:
                continue
            row = {
                "fingerprint": fingerprint,
                "at": at,
                "source": str(item.get("source") or ""),
                "kind": str(item.get("kind") or ""),
            }
            matched_input_at = str(item.get("matched_input_at") or "").strip()
            if matched_input_at:
                row["matched_input_at"] = matched_input_at
            normalized.append(row)
        return normalized[-_RECENT_SERVICE_INPUT_LIMIT:]

    def _new_record(
        self,
        project_id: str,
        thread_id: str,
        body: dict[str, Any],
        *,
        now: str,
    ) -> dict[str, Any]:
        body = rewrite_legacy_project_aliases(body)
        project_id = canonicalize_project_id(project_id)
        return _canonicalize_task_record({
            "project_id": project_id,
            "thread_id": thread_id,
            "cwd": str(body.get("cwd", "")),
            "task_title": str(body.get("task_title", "")),
            "task_prompt": str(body.get("task_prompt", "")),
            "last_user_instruction": str(body.get("last_user_instruction", "")),
            "current_phase_goal": str(body.get("current_phase_goal", "")),
            "model": str(body.get("model", "")),
            "sandbox": str(body.get("sandbox", "")),
            "approval_policy": str(body.get("approval_policy", "")),
            "status": str(body.get("status", "running") or "running"),
            "phase": str(body.get("phase", "planning") or "planning"),
            "context_pressure": str(body.get("context_pressure", "low") or "low"),
            "stuck_level": body.get("stuck_level", 0),
            "failure_count": body.get("failure_count", 0),
            "last_summary": str(body.get("last_summary", "")),
            "files_touched": list(body.get("files_touched", [])),
            "pending_approval": body.get("pending_approval", False),
            "approval_risk": body.get("approval_risk"),
            "last_error_signature": body.get("last_error_signature"),
            "goal_contract_version": str(body.get("goal_contract_version", "")).strip() or None,
            "last_progress_at": str(body.get("last_progress_at", now) or now),
            "created_at": str(body.get("created_at", now) or now),
            "last_local_manual_activity_at": body.get("last_local_manual_activity_at"),
            "recent_service_inputs": self._normalize_recent_service_inputs(
                body.get("recent_service_inputs")
            ),
        }, fallback_status="running", fallback_phase="planning")

    def _record_service_input_locked(
        self,
        rec: dict[str, Any],
        *,
        message: str,
        source: str,
        kind: str,
        at: str,
    ) -> None:
        fingerprint = fingerprint_input_text(message)
        recent = self._normalize_recent_service_inputs(rec.get("recent_service_inputs"))
        recent.append(
            {
                "fingerprint": fingerprint,
                "at": at,
                "source": source,
                "kind": kind,
            }
        )
        rec["recent_service_inputs"] = recent[-_RECENT_SERVICE_INPUT_LIMIT:]
        self._reconcile_local_manual_activity(rec)

    def _consume_recent_service_echo(
        self,
        rec: dict[str, Any],
        *,
        fingerprint: str,
        input_at: str,
    ) -> bool:
        input_dt = _parse_iso(input_at)
        if input_dt is None:
            return False
        recent = self._normalize_recent_service_inputs(rec.get("recent_service_inputs"))
        for index in range(len(recent) - 1, -1, -1):
            item = recent[index]
            if str(item.get("fingerprint") or "") != fingerprint:
                continue
            matched_input_at = str(item.get("matched_input_at") or "").strip()
            if matched_input_at:
                if matched_input_at == input_at:
                    rec["recent_service_inputs"] = recent
                    return True
                continue
            service_dt = _parse_iso(item.get("at"))
            if service_dt is None:
                continue
            age_seconds = (input_dt - service_dt).total_seconds()
            # Service input is recorded after the bridge accepts it, while the echoed
            # user message timestamp can drift slightly on either side of that write.
            if abs(age_seconds) <= self._service_input_match_window_seconds:
                recent[index]["matched_input_at"] = input_at
                rec["recent_service_inputs"] = recent
                return True
        rec["recent_service_inputs"] = recent
        return False

    def _reconcile_local_manual_activity(self, rec: dict[str, Any]) -> None:
        last_user_input_at = rec.get("last_substantive_user_input_at")
        last_user_input_fingerprint = rec.get("last_substantive_user_input_fingerprint")
        manual_activity_at = rec.get("last_local_manual_activity_at")
        if (
            not isinstance(last_user_input_at, str)
            or not last_user_input_at
            or not isinstance(last_user_input_fingerprint, str)
            or not last_user_input_fingerprint
            or manual_activity_at != last_user_input_at
        ):
            return
        if self._consume_recent_service_echo(
            rec,
            fingerprint=last_user_input_fingerprint,
            input_at=last_user_input_at,
        ):
            rec["last_local_manual_activity_at"] = None

    def _get_current_task(self, data: dict[str, Any], project_id: str) -> dict[str, Any] | None:
        project = data.get("projects", {}).get(project_id)
        if not isinstance(project, dict):
            return None
        thread_id = project.get("current_thread_id")
        if not isinstance(thread_id, str):
            return None
        task = data.get("tasks", {}).get(thread_id)
        return dict(task) if isinstance(task, dict) else None

    def _write_task(self, data: dict[str, Any], rec: dict[str, Any]) -> None:
        project_id = str(rec["project_id"])
        thread_id = str(rec["thread_id"])
        tasks = data.setdefault("tasks", {})
        projects = data.setdefault("projects", {})
        tasks[thread_id] = rec
        entry = projects.setdefault(project_id, {"current_thread_id": thread_id, "thread_ids": []})
        if thread_id not in entry["thread_ids"]:
            entry["thread_ids"].append(thread_id)
        entry["current_thread_id"] = thread_id

    def _append_event(
        self,
        *,
        project_id: str,
        thread_id: str,
        event_type: str,
        event_source: str,
        payload_json: dict[str, Any],
    ) -> dict[str, Any]:
        now = _now_iso()
        ev = {
            "event_id": f"evt_{uuid.uuid4().hex[:12]}",
            "project_id": project_id,
            "thread_id": thread_id,
            "event_type": event_type,
            "event_source": event_source,
            "payload_json": dict(payload_json),
            "created_at": now,
            "ts": now,
        }
        append_jsonl(self._events_path, ev)
        return ev

    def count_tasks(self) -> int:
        with self._lock:
            return len(self._read().get("tasks", {}))

    def count_projects(self) -> int:
        with self._lock:
            return len(self._read().get("projects", {}))

    def get(self, project_id: str) -> TaskRecord | None:
        with self._lock:
            rec = self._get_current_task(self._read(), project_id)
            return TaskRecord(rec) if rec else None

    def get_by_thread(self, thread_id: str) -> TaskRecord | None:
        with self._lock:
            row = self._read().get("tasks", {}).get(thread_id)
            return TaskRecord(dict(row)) if isinstance(row, dict) else None

    def list_tasks(self, *, active_only: bool = False) -> list[TaskRecord]:
        with self._lock:
            data = self._read()
            tasks = data.get("tasks", {})
            if active_only:
                if "active_native_thread_ids" in data:
                    active_ids = [
                        str(thread_id)
                        for thread_id in data.get("active_native_thread_ids", [])
                        if str(thread_id).strip()
                    ]
                    rows = [
                        tasks[thread_id]
                        for thread_id in active_ids
                        if isinstance(tasks.get(thread_id), dict)
                    ]
                else:
                    rows = tasks.values()
            else:
                rows = tasks.values()
            ordered = sorted(
                (dict(row) for row in rows if isinstance(row, dict)),
                key=lambda row: (str(row.get("created_at", "")), str(row.get("thread_id", ""))),
            )
            return [TaskRecord(row) for row in ordered]

    def set_active_native_thread_ids(self, thread_ids: list[str]) -> None:
        normalized: list[str] = []
        for thread_id in thread_ids:
            value = str(thread_id).strip()
            if value and value not in normalized:
                normalized.append(value)
        with self._lock:
            data = self._read()
            tasks = data.get("tasks", {})
            data["active_native_thread_ids"] = [
                thread_id for thread_id in normalized if thread_id in tasks
            ]
            self._write(data)

    def upsert_from_create(self, project_id: str, body: dict[str, Any]) -> TaskRecord:
        body = rewrite_legacy_project_aliases(body)
        project_id = canonicalize_project_id(project_id)
        with self._lock:
            data = self._read()
            thread_id = f"thr_{uuid.uuid4().hex[:16]}"
            now = _now_iso()
            rec = self._new_record(project_id, thread_id, body, now=now)
            self._write_task(data, rec)
            self._write(data)
        self._append_event(
            project_id=project_id,
            thread_id=thread_id,
            event_type="task_created",
            event_source="a_control_agent",
            payload_json={
                "project_id": project_id,
                "status": rec.get("status"),
                "phase": rec.get("phase"),
            },
        )
        return TaskRecord(dict(rec))

    def upsert_native_thread(self, thread: dict[str, Any]) -> TaskRecord:
        thread = rewrite_legacy_project_aliases(thread)
        cwd = str(thread.get("cwd", ""))
        project_id = _derive_project_id(thread.get("project_id"), cwd)
        thread_id = str(thread.get("thread_id") or f"thr_{uuid.uuid4().hex[:16]}")
        now = _now_iso()
        with self._lock:
            data = self._read()
            existing = data.get("tasks", {}).get(thread_id)
            rec = dict(existing) if isinstance(existing, dict) else self._new_record(project_id, thread_id, thread, now=now)
            fallback_status = str(rec.get("status") or "running")
            fallback_phase = str(rec.get("phase") or "planning")
            rec["project_id"] = project_id
            rec["thread_id"] = thread_id
            for key in (
                "cwd",
                "task_title",
                "task_prompt",
                "last_user_instruction",
                "current_phase_goal",
                "model",
                "sandbox",
                "approval_policy",
                "status",
                "phase",
                "context_pressure",
                "stuck_level",
                "failure_count",
                "last_summary",
                "files_touched",
                "pending_approval",
                "approval_risk",
                "last_error_signature",
                "goal_contract_version",
                "last_progress_at",
            ):
                value = thread.get(key)
                if value not in (None, ""):
                    rec[key] = value
            last_user_input_at = thread.get("last_substantive_user_input_at")
            if isinstance(last_user_input_at, str) and last_user_input_at:
                rec["last_substantive_user_input_at"] = last_user_input_at
            last_user_input_fingerprint = thread.get("last_substantive_user_input_fingerprint")
            if isinstance(last_user_input_fingerprint, str) and last_user_input_fingerprint:
                rec["last_substantive_user_input_fingerprint"] = last_user_input_fingerprint
            if (
                isinstance(last_user_input_at, str)
                and last_user_input_at
                and isinstance(last_user_input_fingerprint, str)
                and last_user_input_fingerprint
                and not self._consume_recent_service_echo(
                    rec,
                    fingerprint=last_user_input_fingerprint,
                    input_at=last_user_input_at,
                )
            ):
                rec["last_local_manual_activity_at"] = last_user_input_at
            self._reconcile_local_manual_activity(rec)
            rec.setdefault("created_at", now)
            rec.setdefault("context_pressure", "low")
            rec.setdefault("stuck_level", 0)
            rec.setdefault("failure_count", 0)
            rec.setdefault("files_touched", [])
            rec.setdefault("pending_approval", False)
            rec.setdefault("approval_risk", None)
            rec.setdefault("last_error_signature", None)
            rec.setdefault("recent_service_inputs", [])
            rec.setdefault("last_local_manual_activity_at", None)
            if not rec.get("last_progress_at"):
                rec["last_progress_at"] = now
            _canonicalize_task_record(
                rec,
                fallback_status=fallback_status,
                fallback_phase=fallback_phase,
            )
            self._write_task(data, rec)
            self._write(data)
        self._append_event(
            project_id=project_id,
            thread_id=thread_id,
            event_type="native_thread_registered",
            event_source="a_control_agent",
            payload_json={
                "project_id": project_id,
                "status": rec.get("status"),
                "phase": rec.get("phase"),
            },
        )
        append_jsonl(
            self._audit_path,
            {
                "ts": _now_iso(),
                "project_id": project_id,
                "action": "native_thread_registered",
                "reason": "native_thread_upsert",
                "source": "a_control_agent",
                "payload": {"thread_id": thread_id, "status": rec.get("status")},
            },
        )
        return TaskRecord(dict(rec))

    def apply_steer(
        self,
        project_id: str,
        *,
        message: str,
        source: str,
        reason: str,
        stuck_level: int | None = None,
        service_input_delivered: bool = True,
    ) -> TaskRecord | None:
        with self._lock:
            data = self._read()
            rec = self._get_current_task(data, project_id)
            if rec is None:
                return None
            now = _now_iso()
            rec["last_summary"] = f"[steer:{reason}] {message}"[:4000]
            rec["last_progress_at"] = now
            if stuck_level is not None:
                rec["stuck_level"] = int(stuck_level)
            if service_input_delivered:
                self._record_service_input_locked(
                    rec,
                    message=message,
                    source=source,
                    kind="steer",
                    at=now,
                )
            self._write_task(data, rec)
            self._write(data)

        self._append_event(
            project_id=project_id,
            thread_id=str(rec.get("thread_id", "")),
            event_type="steer",
            event_source=source,
            payload_json={"message": message, "reason": reason},
        )
        append_jsonl(
            self._audit_path,
            {
                "ts": now,
                "project_id": project_id,
                "action": "steer_injected",
                "reason": reason,
                "source": "a_control_agent",
                "payload": {"message": message[:500], "steer_source": source},
            },
        )
        return TaskRecord(dict(rec))

    def record_service_input(
        self,
        project_id: str,
        *,
        message: str,
        source: str,
        kind: str,
    ) -> TaskRecord | None:
        if not isinstance(message, str) or not message.strip():
            return self.get(project_id)
        with self._lock:
            data = self._read()
            rec = self._get_current_task(data, project_id)
            if rec is None:
                return None
            self._record_service_input_locked(
                rec,
                message=message,
                source=source,
                kind=kind,
                at=_now_iso(),
            )
            self._write_task(data, rec)
            self._write(data)
            return TaskRecord(dict(rec))

    def record_error_repeat(self, project_id: str, signature: str) -> TaskRecord | None:
        with self._lock:
            data = self._read()
            rec = self._get_current_task(data, project_id)
            if rec is None:
                return None
            prev = rec.get("last_error_signature")
            if prev == signature:
                rec["failure_count"] = int(rec.get("failure_count", 0)) + 1
            else:
                rec["failure_count"] = 1
            rec["last_error_signature"] = signature
            now = _now_iso()
            rec["last_progress_at"] = now
            _canonicalize_task_record(rec)
            self._write_task(data, rec)
            self._write(data)

        append_jsonl(
            self._audit_path,
            {
                "ts": _now_iso(),
                "project_id": project_id,
                "action": "loop_escalation",
                "reason": "error_repeat",
                "source": "a_control_agent",
                "payload": {"signature": signature, "failure_count": rec["failure_count"]},
            },
        )
        return TaskRecord(dict(rec))

    def merge_update(self, project_id: str, fields: dict[str, Any]) -> TaskRecord | None:
        with self._lock:
            data = self._read()
            rec = self._get_current_task(data, project_id)
            if rec is None:
                return None
            fallback_status = str(rec.get("status") or "running")
            fallback_phase = str(rec.get("phase") or "planning")
            rec.update(fields)
            rec["last_progress_at"] = _now_iso()
            _canonicalize_task_record(
                rec,
                fallback_status=fallback_status,
                fallback_phase=fallback_phase,
            )
            self._write_task(data, rec)
            self._write(data)
            return TaskRecord(dict(rec))

    def list_events(self, project_id: str) -> list[dict[str, Any]]:
        if not self._events_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for raw in self._events_path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            if str(row.get("project_id") or "") != project_id:
                continue
            rows.append(dict(row))
        rows.sort(
            key=lambda row: (
                str(row.get("created_at") or row.get("ts") or ""),
                str(row.get("event_id") or ""),
            )
        )
        return rows

    def append_event(
        self,
        project_id: str,
        *,
        thread_id: str,
        event_type: str,
        event_source: str,
        payload_json: dict[str, Any],
    ) -> dict[str, Any]:
        return self._append_event(
            project_id=project_id,
            thread_id=thread_id,
            event_type=event_type,
            event_source=event_source,
            payload_json=payload_json,
        )
