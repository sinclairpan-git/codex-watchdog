from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from _polling import wait_until
from a_control_agent.main import create_app
from a_control_agent.settings import Settings


def _seed_local_codex_home(codex_home: Path, *, thread_id: str, cwd: Path, rollout_path: Path) -> None:
    codex_home.mkdir(parents=True, exist_ok=True)
    (codex_home / ".codex-global-state.json").write_text(
        json.dumps({"active-workspace-roots": [str(cwd)]}),
        encoding="utf-8",
    )
    rollout_path.parent.mkdir(parents=True, exist_ok=True)
    rollout_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-04-05T00:00:00Z",
                        "type": "session_meta",
                        "payload": {"id": thread_id, "cwd": str(cwd)},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-04-05T00:00:01Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "agent_message",
                            "phase": "commentary",
                            "message": "syncing from local codex state",
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    db = sqlite3.connect(codex_home / "state_5.sqlite")
    db.execute(
        """
        create table threads (
            id text primary key,
            rollout_path text not null,
            created_at integer,
            updated_at integer,
            cwd text,
            title text,
            archived integer,
            model text,
            reasoning_effort text,
            sandbox_policy text,
            approval_mode text
        )
        """
    )
    db.execute(
        """
        insert into threads (
            id, rollout_path, created_at, updated_at, cwd, title,
            archived, model, reasoning_effort, sandbox_policy, approval_mode
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            thread_id,
            str(rollout_path),
            100,
            200,
            str(cwd),
            "Auto local session",
            0,
            "gpt-5.4",
            "high",
            "workspace-write",
            "on-request",
        ),
    )
    db.commit()
    db.close()


class CyclingCodexClient:
    def __init__(self, batches: list[list[dict[str, object]]]) -> None:
        self._batches = batches
        self._calls = 0

    def ping(self) -> bool:
        return True

    def list_threads(self) -> list[dict[str, object]]:
        idx = min(self._calls, len(self._batches) - 1)
        self._calls += 1
        return [dict(row) for row in self._batches[idx]]

    def describe_thread(self, thread_id: str) -> dict[str, object]:
        raise KeyError(thread_id)


def test_background_sync_refreshes_native_threads_periodically(tmp_path: Path) -> None:
    repo = tmp_path / "repo-a"
    repo.mkdir()
    settings = Settings(
        api_token="test-token",
        data_dir=str(tmp_path / "agent-data"),
        codex_sync_interval_seconds=0.01,
    )
    app = create_app(
        settings,
        codex_client=CyclingCodexClient(
            [
                [
                    {
                        "thread_id": "thr_native_1",
                        "cwd": str(repo),
                        "task_title": "Native Session",
                        "status": "running",
                        "phase": "planning",
                        "last_summary": "collecting context",
                    }
                ],
                [
                    {
                        "thread_id": "thr_native_1",
                        "cwd": str(repo),
                        "task_title": "Native Session",
                        "status": "waiting_human",
                        "phase": "approval",
                        "pending_approval": True,
                        "approval_risk": "L2",
                        "last_summary": "waiting for approval",
                    }
                ],
            ]
        ),
        start_background_workers=True,
    )
    headers = {"Authorization": "Bearer test-token"}

    with TestClient(app) as client:
        first = client.get("/api/v1/tasks/by-thread/thr_native_1", headers=headers)
        assert first.status_code == 200
        assert first.json()["data"]["phase"] == "planning"

        assert wait_until(
            lambda: client.get("/api/v1/tasks/by-thread/thr_native_1", headers=headers).json()["data"][
                "status"
            ]
            == "waiting_for_approval",
            timeout_s=0.5,
        )

        refreshed = client.get("/api/v1/tasks/by-thread/thr_native_1", headers=headers)

    body = refreshed.json()["data"]
    assert body["status"] == "waiting_for_approval"
    assert body["phase"] == "planning"
    assert body["pending_approval"] is True
    assert body["approval_risk"] == "L2"
    assert body["last_summary"] == "waiting for approval"


def test_background_sync_uses_local_codex_state_by_default(tmp_path: Path) -> None:
    repo = tmp_path / "repo-a"
    repo.mkdir()
    codex_home = tmp_path / ".codex"
    rollout_path = codex_home / "sessions/2026/04/05/rollout-a.jsonl"
    _seed_local_codex_home(
        codex_home,
        thread_id="thr_local_1",
        cwd=repo,
        rollout_path=rollout_path,
    )
    settings = Settings(
        api_token="test-token",
        data_dir=str(tmp_path / "agent-data"),
        codex_home=str(codex_home),
        codex_sync_interval_seconds=60,
    )
    headers = {"Authorization": "Bearer test-token"}

    with TestClient(create_app(settings, start_background_workers=True)) as client:
        response = client.get("/api/v1/tasks/by-thread/thr_local_1", headers=headers)

    body = response.json()["data"]
    assert body["project_id"] == "repo-a"
    assert body["thread_id"] == "thr_local_1"
    assert body["task_title"] == "Auto local session"
    assert body["phase"] == "planning"
    assert body["last_summary"] == "syncing from local codex state"
