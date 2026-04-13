from __future__ import annotations

from pathlib import Path
import threading

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
    ) -> dict[str, object]:
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
    ) -> dict[str, object]:
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

    client = FakeAClient(context_pressure="critical")

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
    client = FakeAClient(context_pressure="critical")
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
    assert client.handoff_calls == [("repo-a", "context_critical")]
    assert client.resume_calls == [("repo-a", "resume_or_new_thread", "")]

    recovery_records = app.state.session_service.list_recovery_transactions(
        parent_session_id="session:repo-a"
    )
    assert [record.status for record in recovery_records] == [
        "started",
        "packet_frozen",
        "child_created",
        "lineage_committed",
        "completed",
    ]

    lineage_records = app.state.session_service.list_lineage(
        parent_session_id="session:repo-a"
    )
    assert len(lineage_records) == 1
    assert lineage_records[0].relation == "resumes_after_interruption"


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
