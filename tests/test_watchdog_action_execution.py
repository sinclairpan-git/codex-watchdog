from __future__ import annotations

from pathlib import Path
import threading
from unittest.mock import patch

import pytest

from watchdog.services.policy.decisions import CanonicalDecisionRecord
from watchdog.settings import Settings
from watchdog.storage.action_receipts import ActionReceiptStore


class FakeAClient:
    def __init__(
        self,
        *,
        context_pressure: str = "critical",
        handoff_data: dict[str, object] | None = None,
        resume_data: dict[str, object] | None = None,
    ) -> None:
        self._context_pressure = context_pressure
        self._handoff_data = dict(handoff_data or {})
        self._resume_data = dict(resume_data or {})
        self.handoff_calls: list[tuple[str, str]] = []
        self.resume_calls: list[tuple[str, str, str]] = []

    def list_approvals(
        self,
        *,
        status: str | None = None,
        project_id: str | None = None,
        decided_by: str | None = None,
        callback_status: str | None = None,
    ) -> list[dict[str, object]]:
        _ = (status, project_id, decided_by, callback_status)
        return []

    def get_envelope(self, project_id: str) -> dict[str, object]:
        return {
            "success": True,
            "data": {
                "project_id": project_id,
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "editing files",
                "files_touched": ["src/example.py"],
                "context_pressure": self._context_pressure,
                "stuck_level": 2,
                "failure_count": 3,
                "last_progress_at": "2026-04-05T05:20:00Z",
            },
        }

    def trigger_handoff(
        self,
        project_id: str,
        *,
        reason: str,
        continuation_packet: dict[str, object] | None = None,
    ) -> dict[str, object]:
        _ = continuation_packet
        self.handoff_calls.append((project_id, reason))
        handoff_data = {
            "handoff_file": f"/tmp/{project_id}.handoff.md",
            "summary": "handoff",
        }
        handoff_data.update(self._handoff_data)
        return {
            "success": True,
            "data": handoff_data,
        }

    def trigger_resume(
        self,
        project_id: str,
        *,
        mode: str,
        handoff_summary: str,
        continuation_packet: dict[str, object] | None = None,
    ) -> dict[str, object]:
        _ = continuation_packet
        self.resume_calls.append((project_id, mode, handoff_summary))
        resume_data = {
            "project_id": project_id,
            "status": "running",
            "mode": mode,
        }
        resume_data.update(self._resume_data)
        return {
            "success": True,
            "data": resume_data,
        }


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
    )


def _receipt_store(tmp_path: Path) -> ActionReceiptStore:
    return ActionReceiptStore(tmp_path / "action_receipts.json")


def _decision(
    *,
    decision_result: str = "auto_execute_and_notify",
    action_ref: str = "execute_recovery",
    idempotency_key: str = "decision:repo-a|fact-v7|policy-v1|auto_execute_and_notify|execute_recovery|",
) -> CanonicalDecisionRecord:
    return CanonicalDecisionRecord(
        decision_id="decision:abc123",
        decision_key=idempotency_key,
        session_id="session:repo-a",
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="thr_native_1",
        approval_id=None,
        action_ref=action_ref,
        trigger="resident_supervision",
        decision_result=decision_result,
        risk_class="none",
        decision_reason="registered action and complete evidence",
        matched_policy_rules=["registered_action"],
        why_not_escalated="policy_allows_auto_execution",
        why_escalated=None,
        uncertainty_reasons=[],
        policy_version="policy-v1",
        fact_snapshot_version="fact-v7",
        idempotency_key=idempotency_key,
        created_at="2026-04-07T00:00:00Z",
        operator_notes=[],
        evidence={
            "decision": {
                "action_ref": action_ref,
                "decision_result": decision_result,
            }
        },
    )


def test_canonical_action_registry_only_resolves_formally_registered_actions() -> None:
    from watchdog.contracts.session_spine.enums import ActionCode
    from watchdog.services.actions.registry import get_registered_action

    recovery = get_registered_action("execute_recovery")
    assert recovery.action_ref == "execute_recovery"
    assert recovery.action_code == ActionCode.EXECUTE_RECOVERY

    guidance = get_registered_action("post_operator_guidance")
    assert guidance.action_code == ActionCode.POST_OPERATOR_GUIDANCE

    with pytest.raises(KeyError):
        get_registered_action("reject_approval")


def test_execute_canonical_decision_consumes_decision_record_without_rerunning_policy(
    tmp_path: Path,
) -> None:
    from watchdog.services.actions.executor import execute_canonical_decision

    client = FakeAClient(
        context_pressure="critical",
        resume_data={
            "resume_outcome": "new_child_session",
            "session_id": "session:repo-a:child-v9",
        },
    )

    result = execute_canonical_decision(
        _decision(action_ref="execute_recovery"),
        settings=_settings(tmp_path),
        client=client,
        receipt_store=_receipt_store(tmp_path),
    )

    assert client.handoff_calls == [("repo-a", "context_critical")]
    assert result.action_code == "execute_recovery"
    assert result.action_status == "completed"
    assert result.effect == "handoff_triggered"
    assert result.idempotency_key == (
        "decision:repo-a|fact-v7|policy-v1|auto_execute_and_notify|execute_recovery|"
    )


def test_execute_canonical_decision_is_idempotent_for_same_decision_record(
    tmp_path: Path,
) -> None:
    from watchdog.services.actions.executor import execute_canonical_decision

    client = FakeAClient(context_pressure="critical")
    store = _receipt_store(tmp_path)
    decision = _decision(action_ref="execute_recovery")

    first = execute_canonical_decision(
        decision,
        settings=_settings(tmp_path),
        client=client,
        receipt_store=store,
    )
    second = execute_canonical_decision(
        decision,
        settings=_settings(tmp_path),
        client=client,
        receipt_store=store,
    )

    assert client.handoff_calls == [("repo-a", "context_critical")]
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_execute_canonical_decision_is_atomic_under_concurrent_retries(
    tmp_path: Path,
) -> None:
    from watchdog.services.actions.executor import execute_canonical_decision

    client = FakeAClient(context_pressure="critical")
    store = _receipt_store(tmp_path)
    decision = _decision(action_ref="execute_recovery")
    barrier = threading.Barrier(3)
    results: list[object] = []

    def _worker() -> None:
        barrier.wait()
        results.append(
            execute_canonical_decision(
                decision,
                settings=_settings(tmp_path),
                client=client,
                receipt_store=store,
            )
        )

    first = threading.Thread(target=_worker)
    second = threading.Thread(target=_worker)
    first.start()
    second.start()
    barrier.wait()
    first.join()
    second.join()

    assert len(results) == 2
    assert results[0].model_dump(mode="json") == results[1].model_dump(mode="json")
    assert client.handoff_calls == [("repo-a", "context_critical")]


def test_execute_canonical_decision_rejects_non_executable_decision_result(
    tmp_path: Path,
) -> None:
    from watchdog.services.actions.executor import execute_canonical_decision

    with pytest.raises(ValueError, match="auto_execute_and_notify"):
        execute_canonical_decision(
            _decision(decision_result="require_user_decision"),
            settings=_settings(tmp_path),
            client=FakeAClient(),
            receipt_store=_receipt_store(tmp_path),
        )


def test_create_app_recovery_execution_records_canonical_truth_once(
    tmp_path: Path,
) -> None:
    from watchdog.main import create_app
    from watchdog.services.actions.executor import execute_canonical_decision

    settings = _settings(tmp_path).model_copy(update={"recover_auto_resume": True})
    client = FakeAClient(
        context_pressure="critical",
        resume_data={
            "resume_outcome": "new_child_session",
            "session_id": "session:repo-a:child-v9",
        },
    )
    app = create_app(settings, a_client=client, start_background_workers=False)
    decision = _decision(action_ref="execute_recovery")

    first = execute_canonical_decision(
        decision,
        settings=app.state.settings,
        client=app.state.a_client,
        receipt_store=app.state.action_receipt_store,
        session_service=app.state.session_service,
    )
    second = execute_canonical_decision(
        decision,
        settings=app.state.settings,
        client=app.state.a_client,
        receipt_store=app.state.action_receipt_store,
        session_service=app.state.session_service,
    )

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert len(client.handoff_calls) == 1
    assert client.handoff_calls[0] == ("repo-a", "context_critical")
    assert client.resume_calls == [("repo-a", "resume_or_new_thread", "")]

    recovery_records = app.state.session_service.list_recovery_transactions(
        parent_session_id="session:repo-a"
    )
    assert [record.status for record in recovery_records] == [
        "started",
        "packet_frozen",
        "child_created",
        "lineage_pending",
        "lineage_committed",
        "parent_cooling",
        "completed",
    ]

    lineage_records = app.state.session_service.list_lineage(
        parent_session_id="session:repo-a"
    )
    assert len(lineage_records) == 1
    assert lineage_records[0].relation == "resumes_after_interruption"


def test_execute_watchdog_continue_records_continuation_gate_verdict(
    tmp_path: Path,
) -> None:
    from watchdog.contracts.session_spine.enums import ActionCode
    from watchdog.contracts.session_spine.models import WatchdogAction
    from watchdog.services.session_service.service import SessionService
    from watchdog.services.session_service.store import SessionServiceStore
    from watchdog.services.session_spine.actions import execute_watchdog_action

    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    client = FakeAClient(context_pressure="low")
    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}
        result = execute_watchdog_action(
            WatchdogAction(
                action_code=ActionCode.CONTINUE_SESSION,
                project_id="repo-a",
                operator="operator",
                idempotency_key="idem:direct-continue",
                arguments={"message": "继续推进当前任务"},
            ),
            settings=_settings(tmp_path),
            client=client,
            receipt_store=_receipt_store(tmp_path),
            session_service=session_service,
        )

    assert result.action_status == "completed"
    gate_events = session_service.list_events(
        session_id="session:repo-a",
        event_type="continuation_gate_evaluated",
    )
    assert len(gate_events) == 1
    assert gate_events[0].payload["gate_status"] == "eligible"
    assert gate_events[0].payload["decision_source"] == "manual_action"
    assert gate_events[0].payload["decision_class"] == "continue_current_branch"
    assert gate_events[0].payload["action_ref"] == "continue_session"
    issued_events = session_service.list_events(
        session_id="session:repo-a",
        event_type="continuation_identity_issued",
    )
    consumed_events = session_service.list_events(
        session_id="session:repo-a",
        event_type="continuation_identity_consumed",
    )
    assert len(issued_events) == 1
    assert issued_events[0].payload["decision_source"] == "manual_action"
    assert issued_events[0].payload["decision_class"] == "continue_current_branch"
    assert issued_events[0].related_ids["continuation_identity"] == (
        "repo-a:session:repo-a:thr_native_1:continue_current_branch"
    )
    assert len(consumed_events) == 1
    assert consumed_events[0].payload["state"] == "consumed"
    assert "consumed_at" in consumed_events[0].payload


def test_execute_watchdog_resume_records_continuation_identity_lifecycle(
    tmp_path: Path,
) -> None:
    from watchdog.contracts.session_spine.enums import ActionCode
    from watchdog.contracts.session_spine.models import WatchdogAction
    from watchdog.services.session_service.service import SessionService
    from watchdog.services.session_service.store import SessionServiceStore
    from watchdog.services.session_spine.actions import execute_watchdog_action

    class ResumeReadyClient(FakeAClient):
        def get_envelope(self, project_id: str) -> dict[str, object]:
            envelope = super().get_envelope(project_id)
            envelope["data"]["status"] = "paused"
            return envelope

    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    client = ResumeReadyClient(context_pressure="low")
    result = execute_watchdog_action(
        WatchdogAction(
            action_code=ActionCode.RESUME_SESSION,
            project_id="repo-a",
            operator="operator",
            idempotency_key="idem:direct-resume",
            arguments={"handoff_summary": "resume from packet"},
        ),
        settings=_settings(tmp_path),
        client=client,
        receipt_store=_receipt_store(tmp_path),
        session_service=session_service,
    )

    assert result.action_status == "completed"
    issued_events = session_service.list_events(
        session_id="session:repo-a",
        event_type="continuation_identity_issued",
    )
    consumed_events = session_service.list_events(
        session_id="session:repo-a",
        event_type="continuation_identity_consumed",
    )
    assert len(issued_events) == 1
    assert issued_events[0].payload["decision_class"] == "recover_current_branch"
    assert len(consumed_events) == 1
    assert consumed_events[0].payload["state"] == "consumed"


def test_execute_watchdog_force_handoff_records_continuation_identity_lifecycle(
    tmp_path: Path,
) -> None:
    from watchdog.contracts.session_spine.enums import ActionCode
    from watchdog.contracts.session_spine.models import WatchdogAction
    from watchdog.services.session_service.service import SessionService
    from watchdog.services.session_service.store import SessionServiceStore
    from watchdog.services.session_spine.actions import execute_watchdog_action

    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    client = FakeAClient(context_pressure="low")
    result = execute_watchdog_action(
        WatchdogAction(
            action_code=ActionCode.FORCE_HANDOFF,
            project_id="repo-a",
            operator="operator",
            idempotency_key="idem:direct-force-handoff",
            arguments={"reason": "operator forced handoff"},
        ),
        settings=_settings(tmp_path),
        client=client,
        receipt_store=_receipt_store(tmp_path),
        session_service=session_service,
    )

    assert result.action_status == "completed"
    issued_events = session_service.list_events(
        session_id="session:repo-a",
        event_type="continuation_identity_issued",
    )
    consumed_events = session_service.list_events(
        session_id="session:repo-a",
        event_type="continuation_identity_consumed",
    )
    assert len(issued_events) == 1
    assert issued_events[0].payload["decision_class"] == "recover_current_branch"
    assert len(consumed_events) == 1
    assert consumed_events[0].payload["state"] == "consumed"


def test_execute_watchdog_retry_records_continuation_identity_lifecycle(
    tmp_path: Path,
) -> None:
    from watchdog.contracts.session_spine.enums import ActionCode
    from watchdog.contracts.session_spine.models import WatchdogAction
    from watchdog.services.session_service.service import SessionService
    from watchdog.services.session_service.store import SessionServiceStore
    from watchdog.services.session_spine.actions import execute_watchdog_action

    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    client = FakeAClient(context_pressure="low")
    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}
        result = execute_watchdog_action(
            WatchdogAction(
                action_code=ActionCode.RETRY_WITH_CONSERVATIVE_PATH,
                project_id="repo-a",
                operator="operator",
                idempotency_key="idem:direct-retry",
                arguments={},
            ),
            settings=_settings(tmp_path),
            client=client,
            receipt_store=_receipt_store(tmp_path),
            session_service=session_service,
        )

    assert result.action_status == "completed"
    issued_events = session_service.list_events(
        session_id="session:repo-a",
        event_type="continuation_identity_issued",
    )
    consumed_events = session_service.list_events(
        session_id="session:repo-a",
        event_type="continuation_identity_consumed",
    )
    assert len(issued_events) == 1
    assert issued_events[0].payload["decision_class"] == "recover_current_branch"
    assert len(consumed_events) == 1
    assert consumed_events[0].payload["state"] == "consumed"


def test_execute_watchdog_post_operator_guidance_consumes_branch_switch_token(
    tmp_path: Path,
) -> None:
    from watchdog.contracts.session_spine.enums import ActionCode
    from watchdog.contracts.session_spine.models import WatchdogAction
    from watchdog.services.session_service.service import SessionService
    from watchdog.services.session_service.store import SessionServiceStore
    from watchdog.services.session_spine.actions import execute_watchdog_action

    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    session_service.record_branch_switch_token_state(
        project_id="repo-a",
        session_id="session:repo-a",
        branch_switch_token="branch-switch:repo-a:86:fact-v1",
        state="issued",
        decision_source="external_model",
        decision_class="branch_complete_switch",
        authoritative_snapshot_version="fact-v1",
        snapshot_epoch="session-seq:1",
        goal_contract_version="goal-v1",
        causation_id="decision:branch-switch-issued",
    )
    client = FakeAClient(context_pressure="low")

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}
        result = execute_watchdog_action(
            WatchdogAction(
                action_code=ActionCode.POST_OPERATOR_GUIDANCE,
                project_id="repo-a",
                operator="operator",
                idempotency_key="idem:branch-switch-guidance",
                arguments={
                    "message": "切换到下一分支并继续执行权威 work item 86。",
                    "reason_code": "branch_complete_switch",
                    "stuck_level": 0,
                    "_continuation_governance": {
                        "decision_source": "external_model",
                        "decision_class": "branch_complete_switch",
                        "action_ref": "post_operator_guidance",
                        "authoritative_snapshot_version": "fact-v1",
                        "snapshot_epoch": "session-seq:1",
                        "goal_contract_version": "goal-v1",
                        "branch_switch_token": "branch-switch:repo-a:86:fact-v1",
                    },
                },
            ),
            settings=_settings(tmp_path),
            client=client,
            receipt_store=_receipt_store(tmp_path),
            session_service=session_service,
        )

    assert result.action_status == "completed"
    consumed_events = session_service.list_events(
        session_id="session:repo-a",
        event_type="branch_switch_token_consumed",
    )
    assert len(consumed_events) == 1
    assert consumed_events[0].related_ids == {
        "branch_switch_token": "branch-switch:repo-a:86:fact-v1",
        "continuation_identity": (
            "repo-a:session:repo-a:thr_native_1:branch_complete_switch"
        ),
    }
    assert consumed_events[0].payload["decision_class"] == "branch_complete_switch"
    assert "consumed_at" in consumed_events[0].payload


def test_execute_watchdog_post_operator_guidance_invalidates_branch_switch_token_on_failure(
    tmp_path: Path,
) -> None:
    from watchdog.contracts.session_spine.enums import ActionCode
    from watchdog.contracts.session_spine.models import WatchdogAction
    from watchdog.services.session_service.service import SessionService
    from watchdog.services.session_service.store import SessionServiceStore
    from watchdog.services.session_spine.actions import execute_watchdog_action
    from watchdog.services.session_spine.service import SessionSpineUpstreamError

    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    session_service.record_branch_switch_token_state(
        project_id="repo-a",
        session_id="session:repo-a",
        branch_switch_token="branch-switch:repo-a:86:fact-v1",
        state="issued",
        decision_source="external_model",
        decision_class="branch_complete_switch",
        authoritative_snapshot_version="fact-v1",
        snapshot_epoch="session-seq:1",
        goal_contract_version="goal-v1",
        causation_id="decision:branch-switch-issued",
    )
    client = FakeAClient(context_pressure="low")

    with (
        patch(
            "watchdog.services.session_spine.actions.post_steer",
            side_effect=RuntimeError("bridge unavailable"),
        ),
        pytest.raises(SessionSpineUpstreamError, match="CONTROL_LINK_ERROR"),
    ):
        execute_watchdog_action(
            WatchdogAction(
                action_code=ActionCode.POST_OPERATOR_GUIDANCE,
                project_id="repo-a",
                operator="operator",
                idempotency_key="idem:branch-switch-guidance-fail",
                arguments={
                    "message": "切换到下一分支并继续执行权威 work item 86。",
                    "reason_code": "branch_complete_switch",
                    "stuck_level": 0,
                    "_continuation_governance": {
                        "decision_source": "external_model",
                        "decision_class": "branch_complete_switch",
                        "action_ref": "post_operator_guidance",
                        "authoritative_snapshot_version": "fact-v1",
                        "snapshot_epoch": "session-seq:1",
                        "goal_contract_version": "goal-v1",
                        "branch_switch_token": "branch-switch:repo-a:86:fact-v1",
                    },
                },
            ),
            settings=_settings(tmp_path),
            client=client,
            receipt_store=_receipt_store(tmp_path),
            session_service=session_service,
        )

    invalidated_events = session_service.list_events(
        session_id="session:repo-a",
        event_type="branch_switch_token_invalidated",
    )
    assert len(invalidated_events) == 1
    assert invalidated_events[0].payload["suppression_reason"] == "control_link_error"
    assert invalidated_events[0].related_ids == {
        "branch_switch_token": "branch-switch:repo-a:86:fact-v1",
        "continuation_identity": (
            "repo-a:session:repo-a:thr_native_1:branch_complete_switch"
        ),
    }


def test_create_app_recovery_execution_preserves_handoff_provenance(
    tmp_path: Path,
) -> None:
    from watchdog.main import create_app
    from watchdog.services.actions.executor import execute_canonical_decision

    settings = _settings(tmp_path).model_copy(update={"recover_auto_resume": True})
    client = FakeAClient(
        context_pressure="critical",
        handoff_data={
            "goal_contract_version": "goal-v9",
            "source_packet_id": "packet:handoff-v9",
        },
        resume_data={"session_id": "session:repo-a:child-v9"},
    )
    app = create_app(settings, a_client=client, start_background_workers=False)

    execute_canonical_decision(
        _decision(action_ref="execute_recovery"),
        settings=app.state.settings,
        client=app.state.a_client,
        receipt_store=app.state.action_receipt_store,
        session_service=app.state.session_service,
    )

    lineage_records = app.state.session_service.list_lineage(
        parent_session_id="session:repo-a"
    )
    assert len(lineage_records) == 1
    assert lineage_records[0].child_session_id == "session:repo-a:child-v9"
    assert lineage_records[0].goal_contract_version == "goal-v9"
    assert lineage_records[0].source_packet_id == "packet:handoff-v9"

    frozen_events = app.state.session_service.list_events(event_type="handoff_packet_frozen")
    assert len(frozen_events) == 1
    assert frozen_events[0].related_ids["source_packet_id"] == "packet:handoff-v9"


def test_create_app_recovery_execution_accepts_current_child_session_id_resume_shape(
    tmp_path: Path,
) -> None:
    from watchdog.main import create_app
    from watchdog.services.actions.executor import execute_canonical_decision

    settings = _settings(tmp_path).model_copy(update={"recover_auto_resume": True})
    client = FakeAClient(
        context_pressure="critical",
        handoff_data={
            "goal_contract_version": "goal-v9",
            "source_packet_id": "packet:handoff-v9",
        },
        resume_data={
            "resume_outcome": "new_child_session",
            "child_session_id": "session:repo-a:thr_child_v9",
            "thread_id": "thr_child_v9",
            "native_thread_id": "thr_child_v9",
        },
    )
    app = create_app(settings, a_client=client, start_background_workers=False)

    execute_canonical_decision(
        _decision(action_ref="execute_recovery"),
        settings=app.state.settings,
        client=app.state.a_client,
        receipt_store=app.state.action_receipt_store,
        session_service=app.state.session_service,
    )

    lineage_records = app.state.session_service.list_lineage(
        parent_session_id="session:repo-a"
    )
    assert len(lineage_records) == 1
    assert lineage_records[0].child_session_id == "session:repo-a:thr_child_v9"
    assert lineage_records[0].goal_contract_version == "goal-v9"
    assert lineage_records[0].source_packet_id == "packet:handoff-v9"

    recovery_records = app.state.session_service.list_recovery_transactions(
        parent_session_id="session:repo-a"
    )
    assert recovery_records[-1].child_session_id == "session:repo-a:thr_child_v9"
    assert recovery_records[-1].metadata["resume_outcome"] == "new_child_session"


def test_runtime_action_extensions_are_stable() -> None:
    from watchdog.contracts.session_spine.enums import ActionCode

    assert ActionCode.PAUSE_SESSION == "pause_session"
    assert ActionCode.RESUME_SESSION == "resume_session"
    assert ActionCode.SUMMARIZE_SESSION == "summarize_session"
    assert ActionCode.FORCE_HANDOFF == "force_handoff"
    assert ActionCode.RETRY_WITH_CONSERVATIVE_PATH == "retry_with_conservative_path"
