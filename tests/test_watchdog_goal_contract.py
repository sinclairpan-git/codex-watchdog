from __future__ import annotations

from watchdog.services.session_service.service import SessionService
from watchdog.services.session_service.store import SessionServiceStore


def test_goal_contract_lifecycle_rebuilds_latest_version_from_session_events(
    tmp_path,
) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    service = GoalContractService(session_service)

    created = service.bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="补测试和接入 session_service",
        task_prompt="先把 recovery/handoff/lineage 的实际写出位点找出来，再围绕最小黄金路径补测试和接入 session_service。",
        last_user_instruction="先把 recovery/handoff/lineage 的实际写出位点找出来",
        phase="implementation",
        last_summary="正在补 recovery provenance 红测",
        explicit_deliverables=[
            "补 recovery/handoff/lineage 真相链路测试",
        ],
        completion_signals=[
            "相关 pytest 通过",
        ],
    )
    revised = service.revise_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        expected_version=created.version,
        current_phase_goal="完成 goal contract 生命周期最小闭环",
        explicit_deliverables=[
            "补 recovery/handoff/lineage 真相链路测试",
            "把 goal contract 接入 session service canonical 写面",
        ],
    )
    adopted = service.adopt_contract_for_child_session(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        child_session_id="session:repo-a:child-1",
        expected_version=revised.version,
        recovery_transaction_id="recovery-tx:1",
        source_packet_id="packet:handoff-v9",
    )

    assert created.version == "goal-v1"
    assert revised.version == "goal-v2"
    assert adopted.version == "goal-v2"

    latest_parent = service.get_current_contract(
        project_id="repo-a",
        session_id="session:repo-a",
    )
    latest_child = service.get_current_contract(
        project_id="repo-a",
        session_id="session:repo-a:child-1",
    )
    assert latest_parent is not None
    assert latest_child is not None
    assert latest_parent.version == "goal-v2"
    assert latest_parent.current_phase_goal == "完成 goal contract 生命周期最小闭环"
    assert latest_child.version == "goal-v2"
    assert latest_child.current_phase_goal == latest_parent.current_phase_goal

    parent_events = [
        event.event_type
        for event in session_service.list_events(session_id="session:repo-a")
        if event.event_type.startswith("goal_contract_")
    ]
    child_events = [
        event.event_type
        for event in session_service.list_events(session_id="session:repo-a:child-1")
        if event.event_type.startswith("goal_contract_")
    ]
    assert parent_events == ["goal_contract_created", "goal_contract_revised"]
    assert child_events == ["goal_contract_adopted_by_child_session"]


def test_goal_contract_incomplete_contract_stays_observe_only(tmp_path) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    service = GoalContractService(session_service)

    service.bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="继续当前任务",
        task_prompt="保持推进",
        last_user_instruction="继续",
        phase="implementation",
        last_summary="继续推进",
        explicit_deliverables=[],
        completion_signals=[],
    )

    readiness = service.evaluate_readiness(
        project_id="repo-a",
        session_id="session:repo-a",
    )

    assert readiness.mode == "observe_only"
    assert readiness.missing_fields == [
        "explicit_deliverables",
        "completion_signals",
    ]
