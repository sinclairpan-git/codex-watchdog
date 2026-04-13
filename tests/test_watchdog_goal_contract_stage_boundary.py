from __future__ import annotations

from watchdog.services.session_service.service import SessionService
from watchdog.services.session_service.store import SessionServiceStore


def test_goal_contract_bootstrap_uses_stage_context_only_when_phase_goal_missing(
    tmp_path,
) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    service = GoalContractService(session_service)

    contract = service.bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="补 recovery 测试",
        task_prompt="围绕最小黄金路径补 recovery 测试",
        last_user_instruction="先把 recovery 写点找出来",
        phase="implementation",
        stage="implementation",
        active_goal="补 recovery/handoff provenance 红测",
        last_summary="正在定位 recovery/handoff 写点",
        explicit_deliverables=["补 recovery provenance 红测"],
        completion_signals=["相关 pytest 通过"],
    )

    assert contract.current_phase_goal == "补 recovery/handoff provenance 红测"


def test_stage_goal_conflict_records_event_and_blocks_auto_progress(tmp_path) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    service = GoalContractService(session_service)

    contract = service.bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="补测试和接入 session_service",
        task_prompt="继续围绕 recovery/handoff/lineage 最小黄金路径推进",
        last_user_instruction="继续当前顺序",
        phase="implementation",
        last_summary="正在补 red test",
        current_phase_goal="补 recovery/handoff/lineage 真相链路",
        explicit_deliverables=["补 recovery/handoff/lineage 真相链路"],
        completion_signals=["相关 pytest 通过"],
    )

    outcome = service.ensure_stage_alignment(
        project_id="repo-a",
        session_id="session:repo-a",
        stage="implementation",
        active_goal="直接切去实现 Brain 决策闭环",
    )

    assert outcome.blocked is True
    assert outcome.conflict_event_id is not None
    assert "补 recovery/handoff/lineage 真相链路" in outcome.conflict_summary
    assert "直接切去实现 Brain 决策闭环" in outcome.conflict_summary

    latest = service.get_current_contract(project_id="repo-a", session_id="session:repo-a")
    assert latest is not None
    assert latest.version == contract.version
    assert latest.current_phase_goal == contract.current_phase_goal

    conflict_events = session_service.list_events(
        session_id="session:repo-a",
        event_type="stage_goal_conflict_detected",
    )
    assert len(conflict_events) == 1
    assert conflict_events[0].payload["current_phase_goal"] == contract.current_phase_goal
    assert conflict_events[0].payload["stage_active_goal"] == "直接切去实现 Brain 决策闭环"
