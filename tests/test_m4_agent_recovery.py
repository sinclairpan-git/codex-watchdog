from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from a_control_agent.main import create_app
from a_control_agent.services.codex_input import fingerprint_input_text
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


def _continuation_packet(*, project_id: str = "p1") -> dict[str, object]:
    continuation_identity = f"{project_id}:session:{project_id}:thr_native_1:recover_current_branch"
    return {
        "packet_id": f"packet:continuation:{project_id}:1",
        "packet_version": "continuation-packet/v1",
        "packet_state": "issued",
        "decision_class": "recover_current_branch",
        "continuation_identity": continuation_identity,
        "project_id": project_id,
        "session_id": f"session:{project_id}",
        "native_thread_id": "thr_native_1",
        "route_key": f"{continuation_identity}:fact-v9",
        "target_route": {
            "route_kind": "same_thread",
            "target_project_id": project_id,
            "target_session_id": f"session:{project_id}",
            "target_thread_id": "thr_native_1",
            "target_work_item_id": "WI-085",
        },
        "project_total_goal": "把 watchdog 自动推进收口为 model-first continuation governance",
        "branch_goal": "实现 ContinuationPacket 真值对象并切断 markdown 回流",
        "current_progress_summary": "已经锁定 handoff_summary 回流口，正在把 recovery/resume 切到 packet truth。",
        "completed_work": ["T856 已完成，control-plane 已可投影 continuation truth。"],
        "remaining_tasks": [
            "让 handoff/resume 走 packet 主契约",
            "补 packet hash 与 render hash 回归",
        ],
        "first_action": "先读取 recovery packet，并只继续当前分支内的 recovery/handoff 改造。",
        "execution_mode": "resume_or_new_thread",
        "action_ref": "continue_current_branch",
        "action_args": {"resume_target_phase": "editing_source"},
        "expected_next_state": "running",
        "continue_boundary": "只继续当前分支，不切到别的 work item。",
        "stop_conditions": [
            "需要新的人工批准",
            "当前分支目标已完成并应切换下一 work item",
        ],
        "operator_boundary": "不要把渲染后的 markdown 重新当作 authoritative truth。",
        "source_refs": {
            "decision_source": "external_model",
            "goal_contract_version": "goal-v9",
            "authoritative_snapshot_version": "fact-v9",
            "snapshot_epoch": "session-seq:9",
            "decision_trace_ref": "trace:packet:1",
            "lineage_refs": ["decision:packet:1"],
        },
        "freshness": {
            "generated_at": "2026-04-21T01:20:00Z",
            "expires_at": "2026-04-21T02:20:00Z",
        },
        "dedupe": {
            "dedupe_key": f"dedupe:{project_id}:packet:1",
            "supersedes_packet_id": None,
        },
        "render_contract_ref": "continuation-packet-markdown/v1",
    }


def test_handoff_and_resume(tmp_path: Path) -> None:
    root = tmp_path / "d"
    s = Settings(api_token="t", data_dir=str(root))
    c = TestClient(create_app(s))
    h = {"Authorization": "Bearer t"}
    c.post(
        "/api/v1/tasks",
        json={"project_id": "p1", "cwd": "/", "task_title": "t", "phase": "editing_source"},
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
    handoff_text = hf.read_text(encoding="utf-8")
    assert b["data"]["source_packet_id"] in handoff_text
    assert "## 当前阻塞点" in handoff_text
    assert "## 下一步建议" in handoff_text
    assert "恢复阶段：editing_source" in handoff_text

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
        json={"project_id": "p1", "cwd": "/", "task_title": "t", "phase": "editing_source"},
        headers=h,
    ).json()["data"]
    handoff = c.post("/api/v1/tasks/p1/handoff", json={"reason": "ctx"}, headers=h)
    assert handoff.status_code == 200

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
        "resume_target_phase": "editing_source",
    }
    assert bridge.resume_calls == [created["thread_id"]]
    assert bridge.started_turns == [(created["thread_id"], "resume")]
    assert c.app.state.task_store.get("p1")["phase"] == "editing_source"


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
        json={
            "project_id": "p1",
            "cwd": "/",
            "task_title": "t",
            "phase": "editing_source",
            "last_user_instruction": "继续补 recovery 回归测试",
            "current_phase_goal": "让 child session 接过恢复后的执行上下文",
            "last_summary": "已定位 recovery 自动重入的重复触发点",
        },
        headers=h,
    ).json()["data"]
    handoff = c.post("/api/v1/tasks/p1/handoff", json={"reason": "ctx"}, headers=h)
    assert handoff.status_code == 200

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
        "resume_target_phase": "editing_source",
    }
    assert bridge.resume_calls == [created["thread_id"]]
    assert bridge.started_turns == [("thr_child_1", "resume")]
    assert c.app.state.task_store.get("p1")["thread_id"] == "thr_child_1"
    assert c.app.state.task_store.get("p1")["phase"] == "editing_source"
    assert c.app.state.task_store.get("p1")["last_user_instruction"] == "继续补 recovery 回归测试"
    assert c.app.state.task_store.get("p1")["current_phase_goal"] == (
        "让 child session 接过恢复后的执行上下文"
    )
    assert c.app.state.task_store.get("p1")["last_summary"] == (
        "已定位 recovery 自动重入的重复触发点"
    )


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


def test_handoff_prefers_supplied_continuation_packet_as_truth(tmp_path: Path) -> None:
    root = tmp_path / "d"
    s = Settings(api_token="t", data_dir=str(root))
    c = TestClient(create_app(s))
    h = {"Authorization": "Bearer t"}
    c.post(
        "/api/v1/tasks",
        json={
            "project_id": "p1",
            "cwd": "/",
            "task_title": "旧任务标题",
            "phase": "editing_source",
            "last_summary": "这是旧摘要，不该覆盖 packet 真值",
        },
        headers=h,
    )
    packet = _continuation_packet(project_id="p1")

    r = c.post(
        "/api/v1/tasks/p1/handoff",
        json={"reason": "ctx", "continuation_packet": packet},
        headers=h,
    )

    assert r.status_code == 200
    body = r.json()["data"]
    assert body["source_packet_id"] == packet["packet_id"]
    assert body["continuation_packet"]["packet_id"] == packet["packet_id"]
    handoff_text = Path(body["handoff_file"]).read_text(encoding="utf-8")
    assert "项目总目标：把 watchdog 自动推进收口为 model-first continuation governance" in handoff_text
    assert "当前分支目标：实现 ContinuationPacket 真值对象并切断 markdown 回流" in handoff_text
    assert "第一步动作：先读取 recovery packet，并只继续当前分支内的 recovery/handoff 改造。" in handoff_text
    assert "这是旧摘要，不该覆盖 packet 真值" not in handoff_text


def test_resume_prefers_continuation_packet_render_over_raw_handoff_summary(
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
    c.post(
        "/api/v1/tasks",
        json={"project_id": "p1", "cwd": "/", "task_title": "t", "phase": "editing_source"},
        headers=h,
    )
    packet = _continuation_packet(project_id="p1")

    resumed = c.post(
        "/api/v1/tasks/p1/resume",
        json={
            "mode": "resume_or_new_thread",
            "handoff_summary": "IGNORE THIS RAW SUMMARY",
            "continuation_packet": packet,
        },
        headers=h,
    )

    assert resumed.status_code == 200
    assert len(bridge.started_turns) == 1
    prompt = bridge.started_turns[0][1]
    assert "IGNORE THIS RAW SUMMARY" not in prompt
    assert "项目总目标：把 watchdog 自动推进收口为 model-first continuation governance" in prompt
    assert "第一步动作：先读取 recovery packet，并只继续当前分支内的 recovery/handoff 改造。" in prompt


def test_child_resume_preserves_last_summary_for_followup_handoff(tmp_path: Path) -> None:
    root = tmp_path / "d"
    bridge = _ResumeBridge(resumed_thread_id="thr_child_1")
    c = TestClient(
        create_app(
            Settings(api_token="t", data_dir=str(root)),
            codex_bridge=bridge,
        )
    )
    h = {"Authorization": "Bearer t"}
    c.post(
        "/api/v1/tasks",
        json={
            "project_id": "p1",
            "cwd": "/",
            "task_title": "t",
            "phase": "editing_source",
            "last_summary": "已定位 recovery 自动重入的重复触发点",
        },
        headers=h,
    )
    handoff = c.post("/api/v1/tasks/p1/handoff", json={"reason": "ctx"}, headers=h)
    assert handoff.status_code == 200

    resumed = c.post(
        "/api/v1/tasks/p1/resume",
        json={"mode": "resume_or_new_thread", "handoff_summary": "resume"},
        headers=h,
    )
    assert resumed.status_code == 200
    assert resumed.json()["data"]["resume_outcome"] == "new_child_session"

    followup_handoff = c.post("/api/v1/tasks/p1/handoff", json={"reason": "ctx-2"}, headers=h)

    assert followup_handoff.status_code == 200
    handoff_text = Path(followup_handoff.json()["data"]["handoff_file"]).read_text(encoding="utf-8")
    assert "当前摘要：已定位 recovery 自动重入的重复触发点" in handoff_text


def test_child_resume_preserves_files_touched_for_followup_handoff(tmp_path: Path) -> None:
    root = tmp_path / "d"
    bridge = _ResumeBridge(resumed_thread_id="thr_child_1")
    c = TestClient(
        create_app(
            Settings(api_token="t", data_dir=str(root)),
            codex_bridge=bridge,
        )
    )
    h = {"Authorization": "Bearer t"}
    c.post(
        "/api/v1/tasks",
        json={
            "project_id": "p1",
            "cwd": "/",
            "task_title": "t",
            "phase": "editing_source",
            "files_touched": [
                "src/watchdog/services/session_spine/facts.py",
                "src/a_control_agent/storage/handoff_manager.py",
            ],
        },
        headers=h,
    )
    handoff = c.post("/api/v1/tasks/p1/handoff", json={"reason": "ctx"}, headers=h)
    assert handoff.status_code == 200

    resumed = c.post(
        "/api/v1/tasks/p1/resume",
        json={"mode": "resume_or_new_thread", "handoff_summary": "resume"},
        headers=h,
    )
    assert resumed.status_code == 200
    assert resumed.json()["data"]["resume_outcome"] == "new_child_session"

    followup_handoff = c.post("/api/v1/tasks/p1/handoff", json={"reason": "ctx-2"}, headers=h)

    assert followup_handoff.status_code == 200
    handoff_text = Path(followup_handoff.json()["data"]["handoff_file"]).read_text(encoding="utf-8")
    assert "src/watchdog/services/session_spine/facts.py" in handoff_text
    assert "src/a_control_agent/storage/handoff_manager.py" in handoff_text
    assert "第一步动作：先检查最近已修改文件" in handoff_text
    assert (
        "## 已修改文件\n"
        "src/watchdog/services/session_spine/facts.py, src/a_control_agent/storage/handoff_manager.py"
    ) in handoff_text


def test_child_resume_surfaces_risk_and_error_context_without_reopening_pending_approval(
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
    c.post(
        "/api/v1/tasks",
        json={
            "project_id": "p1",
            "cwd": "/",
            "task_title": "t",
            "phase": "editing_source",
            "pending_approval": True,
            "approval_risk": "L2",
            "last_error_signature": "context overflow loop",
        },
        headers=h,
    )
    handoff = c.post("/api/v1/tasks/p1/handoff", json={"reason": "ctx"}, headers=h)
    assert handoff.status_code == 200

    resumed = c.post(
        "/api/v1/tasks/p1/resume",
        json={"mode": "resume_or_new_thread", "handoff_summary": "resume"},
        headers=h,
    )
    assert resumed.status_code == 200
    assert resumed.json()["data"]["resume_outcome"] == "new_child_session"

    resumed_task = c.app.state.task_store.get("p1")
    assert resumed_task is not None
    assert resumed_task["pending_approval"] is False
    assert resumed_task["approval_risk"] == "L2"
    assert resumed_task["last_error_signature"] == "context overflow loop"

    followup_handoff = c.post("/api/v1/tasks/p1/handoff", json={"reason": "ctx-2"}, headers=h)

    assert followup_handoff.status_code == 200
    handoff_text = Path(followup_handoff.json()["data"]["handoff_file"]).read_text(encoding="utf-8")
    assert "需要人工介入：当前没有待审批项；可在现有任务边界内继续执行。" in handoff_text
    assert "approval_risk=L2" in handoff_text
    assert "last_error_signature=context overflow loop" in handoff_text


def test_child_resume_handoff_uses_unknown_goal_contract_when_version_is_absent(
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
    c.post(
        "/api/v1/tasks",
        json={
            "project_id": "p1",
            "cwd": "/",
            "task_title": "t",
            "phase": "editing_source",
        },
        headers=h,
    )
    handoff = c.post("/api/v1/tasks/p1/handoff", json={"reason": "ctx"}, headers=h)
    assert handoff.status_code == 200

    resumed = c.post(
        "/api/v1/tasks/p1/resume",
        json={"mode": "resume_or_new_thread", "handoff_summary": "resume"},
        headers=h,
    )
    assert resumed.status_code == 200
    assert resumed.json()["data"]["resume_outcome"] == "new_child_session"

    followup_handoff = c.post("/api/v1/tasks/p1/handoff", json={"reason": "ctx-2"}, headers=h)

    assert followup_handoff.status_code == 200
    handoff_text = Path(followup_handoff.json()["data"]["handoff_file"]).read_text(encoding="utf-8")
    assert "任务约束：goal_contract_version=goal-contract:unknown" in handoff_text
    assert "goal_contract_version=None" not in handoff_text


def test_child_resume_preserves_manual_activity_and_service_input_context(tmp_path: Path) -> None:
    root = tmp_path / "d"
    bridge = _ResumeBridge(resumed_thread_id="thr_child_1")
    c = TestClient(
        create_app(
            Settings(api_token="t", data_dir=str(root)),
            codex_bridge=bridge,
        )
    )
    h = {"Authorization": "Bearer t"}
    c.post(
        "/api/v1/tasks",
        json={
            "project_id": "p1",
            "cwd": "/",
            "task_title": "t",
            "phase": "editing_source",
        },
        headers=h,
    )
    echoed_at = "2026-04-07T00:10:00Z"
    echoed_fingerprint = fingerprint_input_text("continue coding")
    c.app.state.task_store.merge_update(
        "p1",
        {
            "last_substantive_user_input_at": echoed_at,
            "last_substantive_user_input_fingerprint": echoed_fingerprint,
            "last_local_manual_activity_at": echoed_at,
            "recent_service_inputs": [
                {
                    "fingerprint": fingerprint_input_text("resume"),
                    "at": "2026-04-07T00:10:05Z",
                    "source": "a_control_agent",
                    "kind": "resume_summary",
                }
            ],
        },
    )
    handoff = c.post("/api/v1/tasks/p1/handoff", json={"reason": "ctx"}, headers=h)
    assert handoff.status_code == 200

    resumed = c.post(
        "/api/v1/tasks/p1/resume",
        json={"mode": "resume_or_new_thread", "handoff_summary": "resume"},
        headers=h,
    )
    assert resumed.status_code == 200
    assert resumed.json()["data"]["resume_outcome"] == "new_child_session"

    resumed_task = c.app.state.task_store.get("p1")

    assert resumed_task is not None
    assert resumed_task["last_substantive_user_input_at"] == echoed_at
    assert resumed_task["last_substantive_user_input_fingerprint"] == echoed_fingerprint
    assert resumed_task["last_local_manual_activity_at"] == echoed_at
    assert resumed_task["recent_service_inputs"] == [
        {
            "fingerprint": fingerprint_input_text("resume"),
            "at": "2026-04-07T00:10:05Z",
            "source": "a_control_agent",
            "kind": "resume_summary",
        }
    ]


def test_child_resume_preserves_stuck_and_failure_counters(tmp_path: Path) -> None:
    root = tmp_path / "d"
    bridge = _ResumeBridge(resumed_thread_id="thr_child_1")
    c = TestClient(
        create_app(
            Settings(api_token="t", data_dir=str(root)),
            codex_bridge=bridge,
        )
    )
    h = {"Authorization": "Bearer t"}
    c.post(
        "/api/v1/tasks",
        json={
            "project_id": "p1",
            "cwd": "/",
            "task_title": "t",
            "phase": "editing_source",
            "stuck_level": 4,
            "failure_count": 3,
        },
        headers=h,
    )
    handoff = c.post("/api/v1/tasks/p1/handoff", json={"reason": "ctx"}, headers=h)
    assert handoff.status_code == 200

    resumed = c.post(
        "/api/v1/tasks/p1/resume",
        json={"mode": "resume_or_new_thread", "handoff_summary": "resume"},
        headers=h,
    )
    assert resumed.status_code == 200
    assert resumed.json()["data"]["resume_outcome"] == "new_child_session"

    resumed_task = c.app.state.task_store.get("p1")

    assert resumed_task is not None
    assert resumed_task["stuck_level"] == 4
    assert resumed_task["failure_count"] == 3
