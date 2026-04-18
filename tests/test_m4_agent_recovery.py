from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from a_control_agent.main import create_app
from a_control_agent.settings import Settings


class _ResumeBridge:
    def __init__(self, *, resumed_thread_id: str | None = None) -> None:
        self._resumed_thread_id = resumed_thread_id
        self.resume_calls: list[str] = []
        self.started_turns: list[tuple[str, str]] = []

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    def active_turn_id(self, thread_id: str) -> str | None:
        _ = thread_id
        return None

    async def resume_thread(self, thread_id: str) -> dict[str, str]:
        self.resume_calls.append(thread_id)
        return {"thread_id": self._resumed_thread_id or thread_id}

    async def start_turn(self, thread_id: str, *, prompt: str) -> dict[str, str]:
        self.started_turns.append((thread_id, prompt))
        return {"thread_id": thread_id, "turn_id": f"turn:{thread_id}"}


def test_handoff_and_resume(tmp_path: Path) -> None:
    root = tmp_path / "d"
    s = Settings(api_token="t", data_dir=str(root))
    c = TestClient(create_app(s))
    h = {"Authorization": "Bearer t"}
    c.post(
        "/api/v1/tasks",
        json={"project_id": "p1", "cwd": "/", "task_title": "t"},
        headers=h,
    )
    r = c.post("/api/v1/tasks/p1/handoff", json={"reason": "ctx"}, headers=h)
    assert r.status_code == 200
    b = r.json()
    assert b["success"] is True
    assert "handoff_file" in b["data"]
    assert "source_packet_id" in b["data"]
    assert len(b["data"]["summary"]) > 10
    hf = Path(b["data"]["handoff_file"])
    assert hf.is_file()
    assert b["data"]["source_packet_id"].startswith("packet:handoff:")
    assert b["data"]["source_packet_id"] in hf.read_text(encoding="utf-8")

    r2 = c.post(
        "/api/v1/tasks/p1/resume",
        json={"mode": "resume_or_new_thread", "handoff_summary": "x"},
        headers=h,
    )
    assert r2.json()["data"]["status"] == "running"
    assert r2.json()["data"]["resume_outcome"] == "same_thread_resume"


def test_resume_reports_same_thread_outcome_when_bridge_keeps_parent_thread(
    tmp_path: Path,
) -> None:
    root = tmp_path / "d"
    bridge = _ResumeBridge()
    c = TestClient(
        create_app(
            Settings(api_token="t", data_dir=str(root)),
            codex_bridge=bridge,
        )
    )
    h = {"Authorization": "Bearer t"}
    created = c.post(
        "/api/v1/tasks",
        json={"project_id": "p1", "cwd": "/", "task_title": "t"},
        headers=h,
    ).json()["data"]

    resumed = c.post(
        "/api/v1/tasks/p1/resume",
        json={"mode": "resume_or_new_thread", "handoff_summary": "resume"},
        headers=h,
    )

    assert resumed.status_code == 200
    assert resumed.json()["data"] == {
        "project_id": "p1",
        "status": "running",
        "mode": "resume_or_new_thread",
        "resume_outcome": "same_thread_resume",
        "thread_id": created["thread_id"],
    }
    assert bridge.resume_calls == [created["thread_id"]]
    assert bridge.started_turns == [(created["thread_id"], "resume")]


def test_resume_reports_new_child_session_outcome_when_bridge_switches_threads(
    tmp_path: Path,
) -> None:
    root = tmp_path / "d"
    bridge = _ResumeBridge(resumed_thread_id="thr_child_1")
    c = TestClient(
        create_app(
            Settings(api_token="t", data_dir=str(root)),
            codex_bridge=bridge,
        )
    )
    h = {"Authorization": "Bearer t"}
    created = c.post(
        "/api/v1/tasks",
        json={"project_id": "p1", "cwd": "/", "task_title": "t"},
        headers=h,
    ).json()["data"]

    resumed = c.post(
        "/api/v1/tasks/p1/resume",
        json={"mode": "resume_or_new_thread", "handoff_summary": "resume"},
        headers=h,
    )

    assert resumed.status_code == 200
    assert resumed.json()["data"] == {
        "project_id": "p1",
        "status": "running",
        "mode": "resume_or_new_thread",
        "resume_outcome": "new_child_session",
        "thread_id": "thr_child_1",
        "parent_thread_id": created["thread_id"],
        "child_session_id": "session:p1:thr_child_1",
    }
    assert bridge.resume_calls == [created["thread_id"]]
    assert bridge.started_turns == [("thr_child_1", "resume")]
    assert c.app.state.task_store.get("p1")["thread_id"] == "thr_child_1"


def test_handoff_unknown(tmp_path: Path) -> None:
    s = Settings(api_token="t", data_dir=str(tmp_path / "d"))
    c = TestClient(create_app(s))
    r = c.post(
        "/api/v1/tasks/x/handoff",
        json={"reason": "r"},
        headers={"Authorization": "Bearer t"},
    )
    assert r.json()["success"] is False


def test_handoff_preserves_goal_contract_version_when_task_has_it(tmp_path: Path) -> None:
    root = tmp_path / "d"
    s = Settings(api_token="t", data_dir=str(root))
    c = TestClient(create_app(s))
    h = {"Authorization": "Bearer t"}
    c.post(
        "/api/v1/tasks",
        json={
            "project_id": "p1",
            "cwd": "/",
            "task_title": "t",
            "goal_contract_version": "goal-v9",
        },
        headers=h,
    )

    r = c.post("/api/v1/tasks/p1/handoff", json={"reason": "ctx"}, headers=h)

    assert r.status_code == 200
    body = r.json()["data"]
    assert body["goal_contract_version"] == "goal-v9"
    assert "goal_contract_version=goal-v9" in Path(body["handoff_file"]).read_text(
        encoding="utf-8"
    )
