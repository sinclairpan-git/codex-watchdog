from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from a_control_agent.audit import append_jsonl
from a_control_agent.services.codex.protocol import CodexTransport
from a_control_agent.storage.approvals_store import ApprovalsStore
from a_control_agent.storage.tasks_store import TaskStore


class CodexAppServerBridge:
    def __init__(
        self,
        *,
        transport: CodexTransport,
        approvals_store: ApprovalsStore | None = None,
        task_store: TaskStore | None = None,
        audit_path: Path | None = None,
    ) -> None:
        self._transport = transport
        self._approvals_store = approvals_store
        self._task_store = task_store
        self._audit_path = audit_path
        self._started = False
        self._thread_snapshots: dict[str, dict[str, Any]] = {}
        self._active_turn_ids: dict[str, str] = {}
        self._pending_approvals: dict[str, dict[str, Any]] = {}

    async def start(self) -> None:
        if self._started:
            return
        await self._transport.start()
        await self._transport.request("initialize", {})
        self._started = True
        self._append_audit("bridge_connected", payload={})

    async def stop(self) -> None:
        if not self._started:
            return
        await self._transport.stop()
        self._started = False
        self._append_audit("bridge_disconnected", payload={})

    def thread_snapshot(self, thread_id: str) -> dict[str, Any] | None:
        snapshot = self._thread_snapshots.get(thread_id)
        return dict(snapshot) if isinstance(snapshot, dict) else None

    def active_turn_id(self, thread_id: str) -> str | None:
        return self._active_turn_ids.get(thread_id)

    async def resume_thread(self, thread_id: str) -> dict[str, Any]:
        payload = await self._transport.request(
            "thread/resume",
            {"threadId": thread_id, "persistExtendedHistory": False},
        )
        return self._remember_thread(thread_id, payload)

    async def read_thread(self, thread_id: str) -> dict[str, Any]:
        payload = await self._transport.request(
            "thread/read",
            {"threadId": thread_id, "includeTurns": True},
        )
        return self._remember_thread(thread_id, payload)

    async def start_turn(self, thread_id: str, *, prompt: str) -> dict[str, Any]:
        payload = await self._transport.request(
            "turn/start",
            {"threadId": thread_id, "input": self._build_text_input(prompt)},
        )
        return self._remember_turn(thread_id, payload)

    async def steer_turn(self, thread_id: str, *, message: str) -> dict[str, Any]:
        params: dict[str, Any] = {
            "threadId": thread_id,
            "input": self._build_text_input(message),
        }
        expected_turn_id = self._active_turn_ids.get(thread_id)
        if expected_turn_id:
            params["expectedTurnId"] = expected_turn_id
        payload = await self._transport.request("turn/steer", params)
        return self._remember_turn(thread_id, payload)

    async def ingest_server_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        if self._approvals_store is None or self._task_store is None:
            return None
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params")
        if not isinstance(request_id, (str, int)) or not isinstance(method, str) or not isinstance(params, dict):
            return None
        if method not in {
            "item/commandExecution/requestApproval",
            "item/fileChange/requestApproval",
            "item/permissions/requestApproval",
        }:
            return None
        thread_id = str(params.get("threadId") or "")
        if not thread_id:
            return None
        task = self._task_store.get_by_thread(thread_id)
        if task is None:
            return None
        request_key = self._request_lookup_key(request_id)
        approval = self._approvals_store.create_request(
            project_id=str(task.get("project_id") or ""),
            thread_id=thread_id,
            command=self._approval_command(method, params),
            reason=str(params.get("reason") or method),
            alternative=str(params.get("alternative") or ""),
            bridge_request_id=request_key,
            bridge_request_id_type=self._request_id_type(request_id),
        )
        project_id = str(task.get("project_id") or "")
        approval_request = {
            "request_id": request_id,
            "method": method,
            "params": dict(params),
            "approval_id": approval["approval_id"],
            "thread_id": thread_id,
        }
        if approval.get("status") == "pending":
            self._pending_approvals[request_key] = approval_request
            self._task_store.merge_update(
                str(task.get("project_id") or ""),
                {
                    "pending_approval": True,
                    "approval_risk": approval["risk_level"],
                    "status": "waiting_human",
                    "phase": "approval",
                },
            )
            return approval
        self._pending_approvals[request_key] = approval_request
        callback = self._approval_callback_result(method, params, decision="approve", note="")
        try:
            await self._transport.respond(request_id, callback)
        except Exception as exc:
            deferred = self._approvals_store.mark_callback_deferred(
                str(approval["approval_id"]),
                error=repr(exc),
            )
            self._task_store.merge_update(
                project_id,
                {
                    "pending_approval": True,
                    "approval_risk": approval["risk_level"],
                },
            )
            self._task_store.append_event(
                project_id,
                thread_id=thread_id,
                event_type="approval_callback_deferred",
                event_source="codex_bridge",
                payload_json={
                    "approval_id": approval["approval_id"],
                    "request_id": request_id,
                    "error": repr(exc),
                },
            )
            self._append_audit(
                "approval_callback_deferred",
                payload={
                    "request_id": request_id,
                    "approval_id": approval["approval_id"],
                    "error": repr(exc),
                },
            )
            return deferred or approval
        delivered = self._approvals_store.mark_callback_delivered(str(approval["approval_id"]))
        self._pending_approvals.pop(request_key, None)
        return delivered or approval

    async def resolve_pending_approval(
        self,
        request_id: str,
        *,
        decision: str,
        note: str = "",
    ) -> dict[str, Any]:
        request_key = self._request_lookup_key(request_id)
        approval_request = self._pending_approvals.get(request_key)
        if approval_request is None:
            approval_request = self._restore_approval_request(request_id)
        if approval_request is None:
            raise KeyError(f"approval request not found: {request_id}")
        method = str((approval_request or {}).get("method") or "item/commandExecution/requestApproval")
        params = dict((approval_request or {}).get("params") or {})
        callback = self._approval_callback_result(method, params, decision=decision, note=note)
        response_request_id = self._approval_request_id(approval_request, fallback=request_id)
        await self._transport.respond(response_request_id, callback)
        self._pending_approvals.pop(request_key, None)
        approval_id = str((approval_request or {}).get("approval_id") or "")
        if approval_id and self._approvals_store is not None:
            row = self._approvals_store.get(approval_id)
            if self._is_deferred_policy_auto_approval(row):
                self._approvals_store.mark_callback_delivered(approval_id)
                project_id = str((row or {}).get("project_id") or "")
                if (
                    project_id
                    and self._task_store is not None
                    and not self._project_has_actionable_approval(project_id, exclude_approval_id=approval_id)
                ):
                    self._task_store.merge_update(
                        project_id,
                        {
                            "pending_approval": False,
                            "approval_risk": None,
                        },
                    )
        return {"request_id": response_request_id, **callback}

    def _restore_approval_request(self, request_id: str) -> dict[str, Any] | None:
        if self._approvals_store is None:
            return None
        for row in self._approvals_store.list_by_status(None):
            if row.get("bridge_request_id") != request_id:
                continue
            if not self._can_restore_approval_request(row):
                continue
            method = self._restore_approval_method(row)
            params = self._restore_approval_params(row, method)
            return {
                "request_id": self._restore_request_id(row),
                "method": method,
                "params": params,
                "approval_id": row.get("approval_id"),
                "thread_id": row.get("thread_id"),
            }
        return None

    def _can_restore_approval_request(self, row: dict[str, Any]) -> bool:
        status = str(row.get("status") or "")
        if status == "pending":
            return True
        return self._is_deferred_policy_auto_approval(row)

    def _is_deferred_policy_auto_approval(self, row: dict[str, Any] | None) -> bool:
        if not isinstance(row, dict):
            return False
        return (
            str(row.get("status") or "") == "approved"
            and str(row.get("decided_by") or "") == "policy-auto"
            and str(row.get("callback_status") or "") == "deferred"
        )

    def _project_has_actionable_approval(
        self,
        project_id: str,
        *,
        exclude_approval_id: str = "",
    ) -> bool:
        if self._approvals_store is None:
            return False
        for row in self._approvals_store.list_by_status(None):
            if str(row.get("project_id") or "") != project_id:
                continue
            if exclude_approval_id and str(row.get("approval_id") or "") == exclude_approval_id:
                continue
            status = str(row.get("status") or "")
            if status == "pending" or self._is_deferred_policy_auto_approval(row):
                return True
        return False

    def _restore_approval_method(self, row: dict[str, Any]) -> str:
        reason = str(row.get("reason") or "")
        command = str(row.get("command") or "")
        if command.startswith("permissions:") or reason == "item/permissions/requestApproval":
            return "item/permissions/requestApproval"
        if reason == "item/fileChange/requestApproval":
            return "item/fileChange/requestApproval"
        return "item/commandExecution/requestApproval"

    def _restore_approval_params(self, row: dict[str, Any], method: str) -> dict[str, Any]:
        if method == "item/permissions/requestApproval":
            command = str(row.get("command") or "")
            _, _, raw_permissions = command.partition(":")
            permissions = [item for item in raw_permissions.split(",") if item]
            return {"permissions": permissions}
        if method == "item/fileChange/requestApproval":
            return {
                "summary": str(row.get("command") or ""),
                "reason": str(row.get("reason") or ""),
            }
        return {"command": str(row.get("command") or "")}

    def _request_lookup_key(self, request_id: str | int) -> str:
        return str(request_id)

    def _request_id_type(self, request_id: str | int) -> str:
        return "int" if isinstance(request_id, int) else "str"

    def _restore_request_id(self, row: dict[str, Any]) -> str | int:
        request_id = str(row.get("bridge_request_id") or "")
        request_id_type = str(row.get("bridge_request_id_type") or "")
        if request_id_type == "int":
            try:
                return int(request_id)
            except ValueError:
                return request_id
        return request_id

    def _approval_request_id(
        self,
        approval_request: dict[str, Any],
        *,
        fallback: str,
    ) -> str | int:
        request_id = approval_request.get("request_id")
        if isinstance(request_id, (str, int)):
            return request_id
        return fallback

    def _remember_thread(self, thread_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        snapshot = dict(payload)
        thread_payload = snapshot.get("thread")
        if isinstance(thread_payload, dict):
            snapshot["thread_id"] = str(thread_payload.get("id") or thread_id)
        else:
            snapshot.setdefault("thread_id", thread_id)
        self._thread_snapshots[thread_id] = snapshot
        active_turn_id = self._extract_active_turn_id(snapshot)
        if isinstance(active_turn_id, str) and active_turn_id:
            self._active_turn_ids[thread_id] = active_turn_id
            snapshot["active_turn_id"] = active_turn_id
        else:
            self._active_turn_ids.pop(thread_id, None)
        return snapshot

    def _remember_turn(self, thread_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        snapshot = dict(payload)
        snapshot.setdefault("thread_id", thread_id)
        turn_id = self._extract_turn_id(snapshot)
        if isinstance(turn_id, str) and turn_id:
            self._active_turn_ids[thread_id] = turn_id
            snapshot["turn_id"] = turn_id
            snapshot["active_turn_id"] = turn_id
        self._thread_snapshots[thread_id] = {
            **(self._thread_snapshots.get(thread_id) or {}),
            **snapshot,
        }
        return snapshot

    def _extract_turn_id(self, payload: dict[str, Any]) -> str | None:
        for key in ("turn_id", "turnId", "active_turn_id"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        turn = payload.get("turn")
        if isinstance(turn, dict):
            value = turn.get("id")
            if isinstance(value, str) and value:
                return value
        return None

    def _extract_active_turn_id(self, payload: dict[str, Any]) -> str | None:
        turn_id = self._extract_turn_id(payload)
        if turn_id:
            return turn_id
        thread = payload.get("thread")
        if not isinstance(thread, dict):
            return None
        turns = thread.get("turns")
        if not isinstance(turns, list):
            return None
        for raw_turn in reversed(turns):
            if not isinstance(raw_turn, dict):
                continue
            status = raw_turn.get("status")
            if status == "inProgress":
                candidate = raw_turn.get("id")
                if isinstance(candidate, str) and candidate:
                    return candidate
        return None

    def _build_text_input(self, text: str) -> list[dict[str, Any]]:
        return [{"type": "text", "text": text, "text_elements": []}]

    def _approval_command(self, method: str, params: dict[str, Any]) -> str:
        if method == "item/commandExecution/requestApproval":
            command = params.get("command")
            if isinstance(command, str) and command:
                return command
        if method == "item/fileChange/requestApproval":
            return str(params.get("summary") or params.get("reason") or "file change approval")
        permissions = params.get("permissions")
        if isinstance(permissions, list) and permissions:
            return f"permissions:{','.join(str(item) for item in permissions)}"
        return str(params.get("reason") or method)

    def _approval_callback_result(
        self,
        method: str,
        params: dict[str, Any],
        *,
        decision: str,
        note: str,
    ) -> dict[str, Any]:
        if method == "item/permissions/requestApproval":
            permissions = params.get("permissions")
            if not isinstance(permissions, list):
                permissions = []
            if decision == "approve":
                return {"permissions": permissions, "scope": "session"}
            result: dict[str, Any] = {"permissions": [], "scope": "turn"}
            if note:
                result["note"] = note
            return result
        mapped_decision = "accept" if decision == "approve" else "decline"
        return {"decision": mapped_decision}

    def _append_audit(self, action: str, *, payload: dict[str, Any]) -> None:
        if self._audit_path is None:
            return
        append_jsonl(
            self._audit_path,
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "action": action,
                "source": "codex_bridge",
                "payload": payload,
            },
        )
