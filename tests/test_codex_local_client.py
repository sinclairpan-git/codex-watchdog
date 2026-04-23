from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from a_control_agent.services.codex.client import LocalCodexClient, fingerprint_input_text


def _write_rollout(path: Path, events: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(f"{json.dumps(event, ensure_ascii=False)}\n" for event in events)
    path.write_text(payload, encoding="utf-8")


def _seed_codex_home(
    codex_home: Path,
    *,
    threads: list[dict[str, object]],
    active_workspaces: list[str] | None = None,
) -> None:
    codex_home.mkdir(parents=True, exist_ok=True)
    (codex_home / ".codex-global-state.json").write_text(
        json.dumps({"active-workspace-roots": active_workspaces or []}, ensure_ascii=False),
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
    for thread in threads:
        rollout_path = Path(str(thread["rollout_path"]))
        _write_rollout(rollout_path, list(thread["events"]))
        db.execute(
            """
            insert into threads (
                id, rollout_path, created_at, updated_at, cwd, title,
                archived, model, reasoning_effort, sandbox_policy, approval_mode
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(thread["thread_id"]),
                str(rollout_path),
                int(thread.get("created_at", thread["updated_at"])),
                int(thread["updated_at"]),
                str(thread["cwd"]),
                str(thread.get("task_title", "")),
                int(thread.get("archived", 0)),
                str(thread.get("model", "")),
                str(thread.get("reasoning_effort", "")),
                str(thread.get("sandbox", "")),
                str(thread.get("approval_policy", "")),
            ),
        )
    db.commit()
    db.close()


def test_local_codex_client_lists_active_workspace_threads(tmp_path: Path) -> None:
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    codex_home = tmp_path / ".codex"
    rollout_a = codex_home / "sessions/2026/04/05/rollout-a.jsonl"
    rollout_b = codex_home / "sessions/2026/04/05/rollout-b.jsonl"
    _seed_codex_home(
        codex_home,
        active_workspaces=[str(repo_a)],
        threads=[
            {
                "thread_id": "thr_repo_a",
                "cwd": str(repo_a),
                "task_title": "Fix repo-a",
                "updated_at": 200,
                "model": "gpt-5.4",
                "reasoning_effort": "high",
                "sandbox": "workspace-write",
                "approval_policy": "on-request",
                "rollout_path": rollout_a,
                "events": [
                    {
                        "timestamp": "2026-04-05T00:00:00Z",
                        "type": "session_meta",
                        "payload": {"id": "thr_repo_a", "cwd": str(repo_a)},
                    },
                    {
                        "timestamp": "2026-04-05T00:00:01Z",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "name": "apply_patch",
                            "arguments": "\n".join(
                                [
                                    "*** Begin Patch",
                                    "*** Update File: src/service.py",
                                    "@@",
                                    "-return 0",
                                    "+return 1",
                                    "*** Update File: tests/test_service.py",
                                    "@@",
                                    "-assert value == 0",
                                    "+assert value == 1",
                                    "*** End Patch",
                                ]
                            ),
                        },
                    },
                    {
                        "timestamp": "2026-04-05T00:00:02Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "agent_message",
                            "phase": "commentary",
                            "message": "editing repo-a files",
                        },
                    },
                    {
                        "timestamp": "2026-04-05T00:00:03Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "token_count",
                            "info": {
                                "total_token_usage": {"total_tokens": 180000},
                                "model_context_window": 200000,
                            },
                        },
                    },
                ],
            },
            {
                "thread_id": "thr_repo_b",
                "cwd": str(repo_b),
                "task_title": "Ignore repo-b",
                "updated_at": 300,
                "model": "gpt-5.4-mini",
                "sandbox": "workspace-write",
                "approval_policy": "never",
                "rollout_path": rollout_b,
                "events": [
                    {
                        "timestamp": "2026-04-05T00:01:00Z",
                        "type": "session_meta",
                        "payload": {"id": "thr_repo_b", "cwd": str(repo_b)},
                    }
                ],
            },
        ],
    )

    client = LocalCodexClient(codex_home=codex_home)
    sessions = client.list_threads()

    assert len(sessions) == 1
    session = sessions[0]
    assert session["thread_id"] == "thr_repo_a"
    assert session["project_id"] == "repo-a"
    assert session["task_title"] == "Fix repo-a"
    assert session["model"] == "gpt-5.4"
    assert session["reasoning_effort"] == "high"
    assert session["sandbox"] == "workspace-write"
    assert session["approval_policy"] == "on-request"
    assert session["phase"] == "editing_source"
    assert session["status"] == "running"
    assert session["context_pressure"] == "critical"
    assert session["files_touched"] == ["src/service.py", "tests/test_service.py"]
    assert session["last_summary"] == "editing repo-a files"


def test_local_codex_client_does_not_fallback_to_all_threads_when_active_workspaces_are_stale(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo-a"
    stale_active_root = tmp_path / "renamed-repo"
    repo.mkdir()
    codex_home = tmp_path / ".codex"
    rollout = codex_home / "sessions/2026/04/05/rollout-stale-root.jsonl"
    _seed_codex_home(
        codex_home,
        active_workspaces=[str(stale_active_root)],
        threads=[
            {
                "thread_id": "thr_repo_a",
                "cwd": str(repo),
                "task_title": "Old repo-a task",
                "updated_at": 200,
                "rollout_path": rollout,
                "events": [
                    {
                        "timestamp": "2026-04-05T00:00:00Z",
                        "type": "session_meta",
                        "payload": {"id": "thr_repo_a", "cwd": str(repo)},
                    }
                ],
            }
        ],
    )

    client = LocalCodexClient(codex_home=codex_home)

    assert client.list_threads() == []


def test_local_codex_client_does_not_use_home_directory_name_as_project_id(
    tmp_path: Path,
) -> None:
    codex_home = tmp_path / ".codex"
    home = Path.home()
    rollout = codex_home / "sessions/2026/04/05/rollout-home-cwd.jsonl"
    _seed_codex_home(
        codex_home,
        threads=[
            {
                "thread_id": "thr_home_cwd",
                "cwd": str(home),
                "task_title": "cd /Users/sinclairpan/个人/project/ai_sdlc",
                "updated_at": 200,
                "rollout_path": rollout,
                "events": [
                    {
                        "timestamp": "2026-04-05T00:00:00Z",
                        "type": "session_meta",
                        "payload": {"id": "thr_home_cwd", "cwd": str(home)},
                    }
                ],
            }
        ],
    )

    client = LocalCodexClient(codex_home=codex_home)
    session = client.describe_thread("thr_home_cwd")

    assert session["project_id"] == "unknown-project"
    assert client.list_threads() == []


def test_local_codex_client_marks_pending_approval_from_tool_calls(tmp_path: Path) -> None:
    repo = tmp_path / "repo-a"
    repo.mkdir()
    codex_home = tmp_path / ".codex"
    rollout = codex_home / "sessions/2026/04/05/rollout-approval.jsonl"
    _seed_codex_home(
        codex_home,
        active_workspaces=[str(repo)],
        threads=[
            {
                "thread_id": "thr_repo_a",
                "cwd": str(repo),
                "task_title": "Need approval",
                "updated_at": 200,
                "model": "gpt-5.4",
                "sandbox": "workspace-write",
                "approval_policy": "on-request",
                "rollout_path": rollout,
                "events": [
                    {
                        "timestamp": "2026-04-05T00:00:00Z",
                        "type": "session_meta",
                        "payload": {"id": "thr_repo_a", "cwd": str(repo)},
                    },
                    {
                        "timestamp": "2026-04-05T00:00:01Z",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "name": "exec_command",
                            "arguments": json.dumps(
                                {
                                    "cmd": "uv add --optional dev ruff",
                                    "sandbox_permissions": "require_escalated",
                                    "justification": "Do you want to download and install project dependencies?",
                                }
                            ),
                        },
                    },
                ],
            }
        ],
    )

    client = LocalCodexClient(codex_home=codex_home)
    session = client.describe_thread("thr_repo_a")

    assert session["thread_id"] == "thr_repo_a"
    assert session["phase"] == "approval"
    assert session["status"] == "waiting_human"
    assert session["pending_approval"] is True
    assert session["approval_risk"] == "L2"
    assert session["last_summary"] == "Awaiting approval: uv add --optional dev ruff"


def test_local_codex_client_tracks_last_substantive_user_input_and_ignores_environment_context(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo-a"
    repo.mkdir()
    codex_home = tmp_path / ".codex"
    rollout = codex_home / "sessions/2026/04/05/rollout-user-input.jsonl"
    manual_input = "继续，把 quiet window 的通知抑制补上。"
    _seed_codex_home(
        codex_home,
        active_workspaces=[str(repo)],
        threads=[
            {
                "thread_id": "thr_repo_a",
                "cwd": str(repo),
                "task_title": "Track local manual activity",
                "updated_at": 200,
                "model": "gpt-5.4",
                "sandbox": "workspace-write",
                "approval_policy": "on-request",
                "rollout_path": rollout,
                "events": [
                    {
                        "timestamp": "2026-04-05T00:00:00Z",
                        "type": "session_meta",
                        "payload": {"id": "thr_repo_a", "cwd": str(repo)},
                    },
                    {
                        "timestamp": "2026-04-05T00:00:01Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": (
                                        "<environment_context>\n"
                                        f"  <cwd>{repo}</cwd>\n"
                                        "  <shell>zsh</shell>\n"
                                        "  <current_date>2026-04-05</current_date>\n"
                                        "  <timezone>Asia/Shanghai</timezone>\n"
                                        "</environment_context>"
                                    ),
                                }
                            ],
                        },
                    },
                    {
                        "timestamp": "2026-04-05T00:00:02Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": manual_input}],
                        },
                    },
                ],
            }
        ],
    )

    client = LocalCodexClient(codex_home=codex_home)
    session = client.describe_thread("thr_repo_a")

    assert session["thread_id"] == "thr_repo_a"
    assert session["last_substantive_user_input_at"] == "2026-04-05T00:00:02Z"
    assert session["last_substantive_user_input_fingerprint"] == fingerprint_input_text(
        manual_input
    )
