from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

import pytest

from a_control_agent.services.codex.app_server_bridge import CodexAppServerBridge
from a_control_agent.storage.approvals_store import ApprovalsStore
from a_control_agent.storage.tasks_store import TaskStore


class FakeTransport:
    def __init__(self, responses: dict[str, list[dict[str, Any]]]) -> None:
        self._responses = {method: deque(items) for method, items in responses.items()}
        self.started = False
        self.stopped = False
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.responses: list[tuple[str | int, dict[str, Any]]] = []

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(params or {})
        self.calls.append((method, payload))
        queue = self._responses.get(method)
        if not queue:
            raise AssertionError(f"unexpected request: {method}")
        return dict(queue.popleft())

    async def respond(self, request_id: str | int, result: dict[str, Any]) -> None:
        self.responses.append((request_id, dict(result)))


class FlakyRespondTransport(FakeTransport):
    def __init__(self, responses: dict[str, list[dict[str, Any]]]) -> None:
        super().__init__(responses)
        self.fail_next_respond = True

    async def respond(self, request_id: str | int, result: dict[str, Any]) -> None:
        if self.fail_next_respond:
            self.fail_next_respond = False
            raise RuntimeError("callback failed")
        await super().respond(request_id, result)


@pytest.mark.asyncio
async def test_bridge_initializes_and_resumes_known_thread() -> None:
    transport = FakeTransport(
        {
            "initialize": [{"server": "fake-codex"}],
            "thread/resume": [{"thread_id": "thr_live", "active_turn_id": None, "status": "idle"}],
        }
    )

    bridge = CodexAppServerBridge(transport=transport)

    await bridge.start()
    snapshot = await bridge.resume_thread("thr_live")

    assert transport.started is True
    assert snapshot["thread_id"] == "thr_live"
    assert bridge.thread_snapshot("thr_live") == snapshot
    assert bridge.active_turn_id("thr_live") is None

    await bridge.stop()
    assert transport.stopped is True


@pytest.mark.asyncio
async def test_bridge_tracks_active_turn_id_from_control_calls() -> None:
    transport = FakeTransport(
        {
            "initialize": [{"server": "fake-codex"}],
            "turn/start": [{"turn": {"id": "turn_1", "status": "inProgress", "items": [], "error": None}}],
            "turn/steer": [{"turnId": "turn_1"}],
        }
    )
    bridge = CodexAppServerBridge(transport=transport)

    await bridge.start()
    started = await bridge.start_turn("thr_live", prompt="continue")
    steered = await bridge.steer_turn("thr_live", message="stay focused")

    assert started["turn_id"] == "turn_1"
    assert steered["turn_id"] == "turn_1"
    assert bridge.active_turn_id("thr_live") == "turn_1"


@pytest.mark.asyncio
async def test_bridge_reads_thread_snapshot_and_derives_active_turn() -> None:
    transport = FakeTransport(
        {
            "initialize": [{"server": "fake-codex"}],
            "thread/read": [
                {
                    "thread": {
                        "id": "thr_live",
                        "status": {"type": "active", "activeFlags": []},
                        "turns": [
                            {"id": "turn_done", "status": "completed", "items": [], "error": None},
                            {"id": "turn_2", "status": "inProgress", "items": [], "error": None},
                        ],
                    }
                }
            ],
        }
    )
    bridge = CodexAppServerBridge(transport=transport)

    await bridge.start()
    snapshot = await bridge.read_thread("thr_live")

    assert snapshot["thread_id"] == "thr_live"
    assert snapshot["thread"]["status"] == {"type": "active", "activeFlags": []}
    assert bridge.active_turn_id("thr_live") == "turn_2"
    assert transport.calls[-1] == ("thread/read", {"threadId": "thr_live", "includeTurns": True})


@pytest.mark.asyncio
async def test_bridge_registers_and_resolves_command_approval(tmp_path: Path) -> None:
    task_store = TaskStore(tmp_path / "tasks.json")
    task_store.upsert_native_thread(
        {
            "project_id": "ai-demo",
            "thread_id": "thr_live",
            "cwd": str(tmp_path),
            "status": "running",
            "phase": "coding",
        }
    )
    approval_store = ApprovalsStore(tmp_path / "approvals.json")
    transport = FakeTransport({"initialize": [{"server": "fake-codex"}]})
    bridge = CodexAppServerBridge(
        transport=transport,
        approvals_store=approval_store,
        task_store=task_store,
        audit_path=tmp_path / "audit.jsonl",
    )

    await bridge.start()
    approval = await bridge.ingest_server_request(
        {
            "id": "req_123",
            "method": "item/commandExecution/requestApproval",
            "params": {
                "threadId": "thr_live",
                "turnId": "turn_1",
                "itemId": "item_1",
                "command": "curl https://example.com",
                "reason": "Need network access",
            },
        }
    )
    task = task_store.get("ai-demo")
    assert approval is not None
    assert approval["bridge_request_id"] == "req_123"
    assert task is not None
    assert task["pending_approval"] is True
    assert task["status"] == "waiting_human"
    assert task["approval_risk"] == "L2"

    callback = await bridge.resolve_pending_approval("req_123", decision="approve", note="ok")
    assert callback["decision"] == "accept"
    assert transport.responses == [("req_123", {"decision": "accept"})]


@pytest.mark.asyncio
async def test_bridge_auto_approves_low_risk_permissions_request(tmp_path: Path) -> None:
    task_store = TaskStore(tmp_path / "tasks.json")
    task_store.upsert_native_thread(
        {
            "project_id": "ai-demo",
            "thread_id": "thr_live",
            "cwd": str(tmp_path),
            "status": "running",
            "phase": "coding",
        }
    )
    approval_store = ApprovalsStore(tmp_path / "approvals.json")
    transport = FakeTransport({"initialize": [{"server": "fake-codex"}]})
    bridge = CodexAppServerBridge(
        transport=transport,
        approvals_store=approval_store,
        task_store=task_store,
    )

    await bridge.start()
    approval = await bridge.ingest_server_request(
        {
            "id": "req_perm_123",
            "method": "item/permissions/requestApproval",
            "params": {
                "threadId": "thr_live",
                "permissions": ["fs.read", "fs.write"],
                "reason": "Need elevated file access",
            },
        }
    )
    task = task_store.get("ai-demo")

    assert approval is not None
    assert approval["status"] == "approved"
    assert approval["decided_by"] == "policy-auto"
    assert approval_store.list_by_status("pending") == []
    assert task is not None
    assert task["pending_approval"] is False
    assert task["status"] == "running"
    assert task["phase"] == "coding"
    assert transport.responses == [
        (
            "req_perm_123",
            {
                "permissions": ["fs.read", "fs.write"],
                "scope": "session",
            },
        )
    ]


@pytest.mark.asyncio
async def test_bridge_preserves_auto_approved_callback_retry_after_respond_failure(
    tmp_path: Path,
) -> None:
    task_store = TaskStore(tmp_path / "tasks.json")
    task_store.upsert_native_thread(
        {
            "project_id": "ai-demo",
            "thread_id": "thr_live",
            "cwd": str(tmp_path),
            "status": "running",
            "phase": "coding",
        }
    )
    approval_store = ApprovalsStore(tmp_path / "approvals.json")
    transport = FlakyRespondTransport({"initialize": [{"server": "fake-codex"}]})
    bridge = CodexAppServerBridge(
        transport=transport,
        approvals_store=approval_store,
        task_store=task_store,
    )

    await bridge.start()
    approval = await bridge.ingest_server_request(
        {
            "id": "req_perm_retry",
            "method": "item/permissions/requestApproval",
            "params": {
                "threadId": "thr_live",
                "permissions": ["fs.read", "fs.write"],
                "reason": "Need elevated file access",
            },
        }
    )

    callback = await bridge.resolve_pending_approval("req_perm_retry", decision="approve", note="")

    assert approval is not None
    assert approval["status"] == "approved"
    assert approval["decided_by"] == "policy-auto"
    assert callback == {
        "request_id": "req_perm_retry",
        "permissions": ["fs.read", "fs.write"],
        "scope": "session",
    }
    assert transport.responses == [
        (
            "req_perm_retry",
            {
                "permissions": ["fs.read", "fs.write"],
                "scope": "session",
            },
        )
    ]


@pytest.mark.asyncio
async def test_bridge_restores_auto_approved_callback_retry_after_restart(
    tmp_path: Path,
) -> None:
    task_store = TaskStore(tmp_path / "tasks.json")
    task_store.upsert_native_thread(
        {
            "project_id": "ai-demo",
            "thread_id": "thr_live",
            "cwd": str(tmp_path),
            "status": "running",
            "phase": "coding",
        }
    )
    approval_store = ApprovalsStore(tmp_path / "approvals.json")
    first_transport = FlakyRespondTransport({"initialize": [{"server": "fake-codex"}]})
    first_bridge = CodexAppServerBridge(
        transport=first_transport,
        approvals_store=approval_store,
        task_store=task_store,
    )

    await first_bridge.start()
    approval = await first_bridge.ingest_server_request(
        {
            "id": "req_perm_restart",
            "method": "item/permissions/requestApproval",
            "params": {
                "threadId": "thr_live",
                "permissions": ["fs.read", "fs.write"],
                "reason": "Need elevated file access",
            },
        }
    )

    second_transport = FakeTransport({"initialize": [{"server": "fake-codex"}]})
    second_bridge = CodexAppServerBridge(
        transport=second_transport,
        approvals_store=approval_store,
        task_store=task_store,
    )

    await second_bridge.start()
    callback = await second_bridge.resolve_pending_approval(
        "req_perm_restart",
        decision="approve",
        note="retry callback",
    )

    assert approval is not None
    assert approval["status"] == "approved"
    assert approval["decided_by"] == "policy-auto"
    assert callback == {
        "request_id": "req_perm_restart",
        "permissions": ["fs.read", "fs.write"],
        "scope": "session",
    }
    assert second_transport.responses == [
        (
            "req_perm_restart",
            {
                "permissions": ["fs.read", "fs.write"],
                "scope": "session",
            },
        )
    ]
