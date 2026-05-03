from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from a_control_agent.services.codex_input import fingerprint_input_text
from watchdog.services.project_aliases import canonicalize_project_id, rewrite_legacy_project_aliases


@runtime_checkable
class CodexClient(Protocol):
    """未来对接 Codex app-server 的最小协议面；默认实现不发起网络请求。"""

    def ping(self) -> bool:
        """控制面可达性探测（占位）。"""
        ...

    def list_threads(self) -> list[dict[str, Any]]:
        """当前可见线程列表。"""
        ...

    def describe_thread(self, thread_id: str) -> dict[str, Any]:
        """线程元数据摘要（占位）。"""
        ...


class NoOpCodexClient:
    """默认空实现：供未配置 Codex 时保持服务可启动。"""

    def ping(self) -> bool:
        return True

    def list_threads(self) -> list[dict[str, Any]]:
        return []

    def describe_thread(self, thread_id: str) -> dict[str, Any]:
        return {"thread_id": thread_id, "connected": False, "note": "no_codex_backend"}


def _normalize_path(raw: str) -> str:
    if not raw.strip():
        return ""
    return str(Path(raw).expanduser().resolve(strict=False))


def _same_path_casefold(left: Path, right: Path) -> bool:
    return str(left.resolve(strict=False)).casefold() == str(right.resolve(strict=False)).casefold()


def _project_id_from_cwd(cwd: str, *, codex_home: Path | None = None) -> str:
    normalized = str(cwd or "").strip()
    if not normalized:
        return "unknown-project"
    path = Path(normalized).expanduser().resolve(strict=False)
    if _same_path_casefold(path, Path.home()):
        return "unknown-project"
    if codex_home is not None and _same_path_casefold(path, codex_home):
        return "unknown-project"
    if path.name.strip().casefold() in {"codex", ".codex", Path.home().name.casefold()}:
        return "unknown-project"
    return canonicalize_project_id(path.name)


def _extract_output_text(content: Any) -> str:
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "output_text":
            text = str(item.get("text", "")).strip()
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


def _extract_input_text(content: Any) -> str:
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "input_text":
            text = str(item.get("text", "")).strip()
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


def _is_environment_context_message(text: str) -> bool:
    normalized = text.strip()
    if not normalized:
        return False
    return (
        normalized.startswith("<environment_context>")
        and normalized.endswith("</environment_context>")
    )


def _coerce_timestamp(raw: Any) -> str:
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(float(raw), tz=timezone.utc).isoformat()
    return ""


def _context_pressure(total_tokens: Any, context_window: Any) -> str:
    try:
        used = float(total_tokens)
        window = float(context_window)
    except (TypeError, ValueError):
        return "low"
    if window <= 0:
        return "low"
    ratio = used / window
    if ratio >= 0.9:
        return "critical"
    if ratio >= 0.75:
        return "high"
    if ratio >= 0.5:
        return "medium"
    return "low"


def _parse_tool_arguments(raw: Any) -> dict[str, Any] | str:
    if not isinstance(raw, str):
        return {}
    text = raw.strip()
    if not text:
        return {}
    if text.startswith("{") or text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return raw
        return parsed if isinstance(parsed, dict) else raw
    return raw


def _extract_files_from_patch(raw: str) -> list[str]:
    matches = re.findall(r"^\*\*\* (?:Update|Add|Delete) File: (.+)$", raw, flags=re.MULTILINE)
    seen: set[str] = set()
    files: list[str] = []
    for match in matches:
        path = match.strip()
        if path and path not in seen:
            files.append(path)
            seen.add(path)
    return files


def _phase_from_tool(name: str, arguments: dict[str, Any] | str) -> str | None:
    if name == "apply_patch":
        return "editing_source"
    if name in {"exec_command", "write_stdin"}:
        cmd = ""
        if isinstance(arguments, dict):
            cmd = str(arguments.get("cmd") or arguments.get("chars") or "")
        if any(token in cmd for token in ("pytest", "ruff", "mypy", "tox", "nox", "coverage", "unittest")):
            return "verifying"
        if any(token in cmd for token in ("rg ", "sed ", "ls ", "cat ", "find ", "git status")):
            return "planning"
        return "coding"
    if name == "update_plan":
        return "planning"
    return None


class LocalCodexClient:
    """基于本地 ~/.codex 状态发现并摘要当前 Codex 线程。"""

    def __init__(self, codex_home: str | Path = "~/.codex") -> None:
        self._codex_home = Path(codex_home).expanduser()
        self._state_db = self._codex_home / "state_5.sqlite"
        self._global_state = self._codex_home / ".codex-global-state.json"

    def ping(self) -> bool:
        return self._state_db.exists()

    def _load_active_workspaces(self) -> list[str]:
        if not self._global_state.exists():
            return []
        try:
            payload = json.loads(self._global_state.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        roots = payload.get("active-workspace-roots")
        if not isinstance(roots, list):
            return []
        normalized = [_normalize_path(str(root)) for root in roots if str(root).strip()]
        return [root for root in normalized if root]

    def _load_threads(self, thread_id: str | None = None) -> list[dict[str, Any]]:
        if not self.ping():
            return []
        query = """
            select
                id,
                rollout_path,
                cwd,
                title,
                updated_at,
                archived,
                model,
                reasoning_effort,
                sandbox_policy,
                approval_mode
            from threads
            where coalesce(archived, 0) = 0
        """
        params: tuple[Any, ...] = ()
        if thread_id is not None:
            query += " and id = ?"
            params = (thread_id,)
        query += " order by updated_at asc, id asc"
        try:
            with sqlite3.connect(self._state_db) as db:
                db.row_factory = sqlite3.Row
                rows = db.execute(query, params).fetchall()
        except sqlite3.Error:
            return []
        return [dict(row) for row in rows]

    def _filter_visible_threads(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        active_roots = self._load_active_workspaces()
        if not active_roots:
            return []
        visible: list[dict[str, Any]] = []
        for row in rows:
            cwd = _normalize_path(str(row.get("cwd") or ""))
            for root in active_roots:
                if cwd == root or cwd.startswith(f"{root}/"):
                    visible.append(row)
                    break
        return visible

    def _summarize_thread(self, row: dict[str, Any]) -> dict[str, Any]:
        cwd = str(rewrite_legacy_project_aliases(str(row.get("cwd") or "")))
        rollout_path = Path(str(row.get("rollout_path") or ""))
        project_id = _project_id_from_cwd(cwd, codex_home=self._codex_home)
        session = {
            "thread_id": str(row.get("id") or ""),
            "project_id": project_id,
            "cwd": cwd,
            "task_title": str(row.get("title") or ""),
            "model": str(row.get("model") or ""),
            "reasoning_effort": str(row.get("reasoning_effort") or ""),
            "sandbox": str(row.get("sandbox_policy") or ""),
            "approval_policy": str(row.get("approval_mode") or ""),
            "status": "running",
            "phase": "planning",
            "context_pressure": "low",
            "files_touched": [],
            "pending_approval": False,
            "approval_risk": None,
            "last_summary": "",
            "last_progress_at": _coerce_timestamp(row.get("updated_at")),
        }
        if not rollout_path.exists():
            return session

        touched: list[str] = []
        touched_seen: set[str] = set()
        approval_waiting: dict[str, str] = {}
        current_phase = str(session["phase"])
        current_status = str(session["status"])
        last_summary = ""
        last_progress_at = str(session["last_progress_at"])
        last_substantive_user_input_at = ""
        last_substantive_user_input_fingerprint = ""

        try:
            lines = rollout_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return session

        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            last_progress_at = _coerce_timestamp(event.get("timestamp")) or last_progress_at
            event_type = event.get("type")
            payload = event.get("payload")
            if not isinstance(payload, dict):
                continue

            if event_type == "response_item":
                item_type = str(payload.get("type") or "")
                if item_type == "message":
                    if payload.get("role") == "assistant":
                        text = _extract_output_text(payload.get("content"))
                        if text:
                            last_summary = text
                        phase = str(payload.get("phase") or "")
                        if phase == "final":
                            current_phase = "done"
                            current_status = "waiting_human"
                    elif payload.get("role") == "user":
                        text = _extract_input_text(payload.get("content"))
                        if text and not _is_environment_context_message(text):
                            last_substantive_user_input_at = _coerce_timestamp(
                                event.get("timestamp")
                            ) or last_substantive_user_input_at
                            last_substantive_user_input_fingerprint = fingerprint_input_text(text)
                elif item_type == "function_call":
                    name = str(payload.get("name") or "")
                    arguments = _parse_tool_arguments(payload.get("arguments"))
                    phase = _phase_from_tool(name, arguments)
                    if phase:
                        current_phase = phase
                        current_status = "running"
                    if name == "apply_patch" and isinstance(arguments, str):
                        for path in _extract_files_from_patch(arguments):
                            if path not in touched_seen:
                                touched.append(path)
                                touched_seen.add(path)
                    if isinstance(arguments, dict):
                        call_id = str(payload.get("call_id") or "")
                        if arguments.get("sandbox_permissions") == "require_escalated":
                            summary = str(arguments.get("cmd") or arguments.get("justification") or name or "approval needed").strip()
                            approval_waiting[call_id or summary] = summary
                elif item_type == "function_call_output":
                    call_id = str(payload.get("call_id") or "")
                    if call_id:
                        approval_waiting.pop(call_id, None)

            elif event_type == "event_msg":
                msg_type = str(payload.get("type") or payload.get("event_type") or "")
                if msg_type == "agent_message":
                    message = str(payload.get("message") or "").strip()
                    if message:
                        last_summary = message
                    if str(payload.get("phase") or "") == "final":
                        current_phase = "done"
                        current_status = "waiting_human"
                elif msg_type == "token_count":
                    info = payload.get("info", {})
                    if isinstance(info, dict):
                        usage = info.get("total_token_usage", {})
                        if isinstance(usage, dict):
                            total = usage.get("total_tokens")
                        else:
                            total = None
                        session["context_pressure"] = _context_pressure(total, info.get("model_context_window"))

        if approval_waiting:
            summary = next(reversed(approval_waiting.values()))
            current_phase = "approval"
            current_status = "waiting_human"
            session["pending_approval"] = True
            session["approval_risk"] = "L2"
            last_summary = f"Awaiting approval: {summary}"

        session["phase"] = current_phase
        session["status"] = current_status
        session["files_touched"] = touched
        session["last_summary"] = last_summary
        session["last_progress_at"] = last_progress_at
        if last_substantive_user_input_at:
            session["last_substantive_user_input_at"] = last_substantive_user_input_at
        if last_substantive_user_input_fingerprint:
            session["last_substantive_user_input_fingerprint"] = (
                last_substantive_user_input_fingerprint
            )
        return session

    def list_threads(self) -> list[dict[str, Any]]:
        rows = self._filter_visible_threads(self._load_threads())
        return [
            session
            for session in (self._summarize_thread(row) for row in rows)
            if session.get("project_id") != "unknown-project"
        ]

    def describe_thread(self, thread_id: str) -> dict[str, Any]:
        rows = self._load_threads(thread_id)
        if not rows:
            return {"thread_id": thread_id, "connected": False, "note": "unknown_thread"}
        return self._summarize_thread(rows[0])
