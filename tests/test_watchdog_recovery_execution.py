from __future__ import annotations

from watchdog.services.memory_hub.service import MemoryHubService
from watchdog.services.delivery.store import DeliveryOutboxRecord, DeliveryOutboxStore
from watchdog.services.session_service.service import SessionService
from watchdog.services.session_service.store import SessionServiceStore
from watchdog.services.future_worker.service import FutureWorkerExecutionService
from watchdog.services.session_spine.recovery import perform_recovery_execution
from watchdog.settings import Settings


class FakeAClient:
    def __init__(
        self,
        *,
        task: dict[str, object],
        resume_success: bool = True,
        handoff_data: dict[str, object] | None = None,
        resume_data: dict[str, object] | None = None,
        approvals: list[dict[str, object]] | None = None,
    ) -> None:
        self._task = dict(task)
        self._resume_success = resume_success
        self._handoff_data = dict(handoff_data or {})
        self._resume_data = dict(resume_data or {})
        self._approvals = [dict(approval) for approval in approvals or []]
        self.handoff_calls: list[tuple[str, str, dict[str, object] | None]] = []
        self.resume_calls: list[tuple[str, str, str, dict[str, object] | None]] = []

    def get_envelope(self, project_id: str) -> dict[str, object]:
        assert project_id == self._task["project_id"]
        return {"success": True, "data": dict(self._task)}

    def list_approvals(
        self,
        *,
        status: str | None = None,
        project_id: str | None = None,
        decided_by: str | None = None,
        callback_status: str | None = None,
    ) -> list[dict[str, object]]:
        _ = (decided_by, callback_status)
        approvals = [dict(approval) for approval in self._approvals]
        if status is not None:
            approvals = [
                dict(approval) for approval in approvals if approval.get("status") == status
            ]
        if project_id is not None:
            approvals = [
                dict(approval)
                for approval in approvals
                if approval.get("project_id") == project_id
            ]
        return approvals

    def trigger_handoff(
        self,
        project_id: str,
        *,
        reason: str,
        continuation_packet: dict[str, object] | None = None,
    ) -> dict[str, object]:
        self.handoff_calls.append((project_id, reason, dict(continuation_packet or {}) or None))
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
        self.resume_calls.append(
            (project_id, mode, handoff_summary, dict(continuation_packet or {}) or None)
        )
        if self._resume_success:
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
        return {"success": False, "error": {"code": "RESUME_FAILED", "message": "bridge unavailable"}}


def _expected_continuation_identity(project_id: str) -> str:
    return f"{project_id}:session:{project_id}:thr_native_1:recover_current_branch"


def test_perform_recovery_execution_returns_noop_without_side_effects(tmp_path) -> None:
    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        client=FakeAClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "steady progress",
                "files_touched": ["src/example.py"],
                "context_pressure": "medium",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T05:20:00Z",
            }
        ),
    )

    assert outcome.action == "noop"
    assert outcome.noop_reason == "context_not_critical"
    assert outcome.context_pressure == "medium"
    assert outcome.handoff is None
    assert outcome.resume is None
    assert outcome.resume_error is None


def test_perform_recovery_execution_loads_persisted_memory_hub_when_not_injected(tmp_path) -> None:
    MemoryHubService.from_data_dir(tmp_path).upsert_resident_memory(
        project_id="repo-a",
        memory_key="goal.current",
        summary="persisted memory capsule",
        source_ref="memory:test",
        source_scope="project-local",
        source_runtime="watchdog",
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        client=FakeAClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "steady progress",
                "files_touched": ["src/example.py"],
                "context_pressure": "medium",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T05:20:00Z",
            }
        ),
    )

    assert outcome.memory_advisory_context is not None
    resident_capsule = outcome.memory_advisory_context["resident_capsule"]
    assert len(resident_capsule) == 1
    assert resident_capsule[0]["summary"] == "persisted memory capsule"


def test_perform_recovery_execution_records_suppression_reason_when_recovery_is_in_flight(
    tmp_path,
) -> None:
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "handoff_in_progress",
            "phase": "handoff",
            "pending_approval": False,
            "last_summary": "handoff drafted",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 4,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
        session_service=session_service,
    )

    assert outcome.action == "noop"
    assert outcome.noop_reason == "recovery_in_flight"
    assert client.handoff_calls == []
    suppressed_events = session_service.list_events(
        session_id="session:repo-a",
        event_type="recovery_execution_suppressed",
    )
    assert len(suppressed_events) == 1
    assert suppressed_events[0].payload["suppression_reason"] == "recovery_in_flight"
    assert suppressed_events[0].payload["task_status"] == "handoff_in_progress"
    assert suppressed_events[0].payload["last_progress_at"] == "2026-04-05T05:20:00Z"
    gate_events = session_service.list_events(
        session_id="session:repo-a",
        event_type="continuation_gate_evaluated",
    )
    assert len(gate_events) == 1
    assert gate_events[0].payload["gate_status"] == "suppressed"
    assert gate_events[0].payload["suppression_reason"] == "recovery_in_flight"
    assert session_service.list_events(
        session_id="session:repo-a",
        event_type="continuation_replay_invalidated",
    ) == []


def test_perform_recovery_execution_records_dispatch_started_before_handoff(
    tmp_path,
) -> None:
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))

    class InspectingAClient(FakeAClient):
        def trigger_handoff(
            self,
            project_id: str,
            *,
            reason: str,
            continuation_packet: dict[str, object] | None = None,
        ) -> dict[str, object]:
            _ = continuation_packet
            dispatch_events = session_service.list_events(
                session_id="session:repo-a",
                event_type="recovery_dispatch_started",
            )
            assert len(dispatch_events) == 1
            assert dispatch_events[0].payload["recovery_reason"] == "context_critical"
            assert dispatch_events[0].payload["failure_signature"] == "critical"
            return super().trigger_handoff(project_id, reason=reason)

    client = InspectingAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "repeated failures",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=False,
        ),
        client=client,
        session_service=session_service,
    )

    assert outcome.action == "handoff_triggered"


def test_perform_recovery_execution_prefers_explicit_native_thread_id_for_resume_and_suppression(
    tmp_path,
) -> None:
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    in_flight_client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "session:repo-a",
            "native_thread_id": "thr_native_1",
            "status": "handoff_in_progress",
            "phase": "handoff",
            "pending_approval": False,
            "last_summary": "handoff drafted",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 4,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )

    suppression_outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=in_flight_client,
        session_service=session_service,
    )

    assert suppression_outcome.noop_reason == "recovery_in_flight"
    suppressed_events = session_service.list_events(
        session_id="session:repo-a",
        event_type="recovery_execution_suppressed",
    )
    assert suppressed_events[-1].related_ids["native_thread_id"] == "thr_native_1"

    resume_client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "session:repo-a",
            "native_thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "repeated failures",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        resume_data={
            "thread_id": "session:repo-a",
            "native_thread_id": "thr_native_1",
        },
    )

    resume_outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=resume_client,
        session_service=session_service,
    )

    assert resume_outcome.action == "handoff_and_resume"
    assert resume_outcome.resume_outcome == "same_thread_resume"


def test_perform_recovery_execution_returns_noop_when_project_is_not_active(
    tmp_path,
) -> None:
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "project_execution_state": "completed",
            "pending_approval": False,
            "last_summary": "branch already closed",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
        session_service=session_service,
    )

    assert outcome.action == "noop"
    assert outcome.noop_reason == "project_not_active"
    assert client.handoff_calls == []
    suppressed_events = session_service.list_events(
        session_id="session:repo-a",
        event_type="recovery_execution_suppressed",
    )
    assert len(suppressed_events) == 1
    assert suppressed_events[0].payload["suppression_reason"] == "project_not_active"
    assert suppressed_events[0].payload["project_execution_state"] == "completed"
    gate_events = session_service.list_events(
        session_id="session:repo-a",
        event_type="continuation_gate_evaluated",
    )
    assert len(gate_events) == 1
    assert gate_events[0].payload["gate_status"] == "suppressed"
    assert gate_events[0].payload["suppression_reason"] == "project_not_active"
    invalidated_events = session_service.list_events(
        session_id="session:repo-a",
        event_type="continuation_replay_invalidated",
    )
    assert len(invalidated_events) == 1
    assert invalidated_events[0].payload["invalidation_reason"] == "project_not_active"
    identity_invalidated = session_service.list_events(
        session_id="session:repo-a",
        event_type="continuation_identity_invalidated",
    )
    assert len(identity_invalidated) == 1
    assert identity_invalidated[0].payload["suppression_reason"] == "project_not_active"


def test_perform_recovery_execution_blocks_when_actionable_approval_exists_even_if_task_flag_is_false(
    tmp_path,
) -> None:
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "approval projection lagged behind task flag",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        approvals=[
            {
                "approval_id": "appr_001",
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "pending",
                "command": "execute_recovery",
                "reason": "manual approval still pending",
                "requested_at": "2026-04-05T05:21:00Z",
            }
        ],
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
        session_service=session_service,
    )

    assert outcome.action == "noop"
    assert outcome.noop_reason == "pending_approval"
    assert client.handoff_calls == []


def test_perform_recovery_execution_superseded_interaction_event_carries_native_thread_id(
    tmp_path,
) -> None:
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    delivery_store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    delivery_store.update_delivery_record(
        DeliveryOutboxRecord(
            envelope_id="notification-envelope:ctx-recovery-old",
            envelope_type="notification",
            correlation_id="corr:family-recovery-1:ctx-recovery-old",
            session_id="session:repo-a",
            project_id="repo-a",
            native_thread_id="thr_native_1",
            policy_version="policy-v1",
            fact_snapshot_version="fact-v7",
            idempotency_key="idem:ctx-recovery-old",
            audit_ref="audit:ctx-recovery-old",
            created_at="2026-04-14T03:10:00Z",
            updated_at="2026-04-14T03:10:00Z",
            outbox_seq=1,
            delivery_status="delivered",
            envelope_payload={
                "interaction_context_id": "ctx-recovery-old",
                "interaction_family_id": "family-recovery-1",
                "actor_id": "user:alice",
                "channel_kind": "dm",
            },
        )
    )
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "session:repo-a",
            "native_thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "repeated failures",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        handoff_data={"goal_contract_version": "goal-v9"},
        resume_data={
            "resume_outcome": "new_child_session",
            "session_id": "session:repo-a:child-v9",
        },
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
        session_service=session_service,
    )

    assert outcome.action == "handoff_and_resume"
    superseded_events = session_service.list_events(
        session_id="session:repo-a",
        event_type="interaction_context_superseded",
    )
    assert len(superseded_events) == 1
    assert superseded_events[0].related_ids["native_thread_id"] == "thr_native_1"


def test_perform_recovery_execution_superseded_interaction_event_uses_effective_native_thread_from_legacy_delivery_record(
    tmp_path,
) -> None:
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    delivery_store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    delivery_store.update_delivery_record(
        DeliveryOutboxRecord(
            envelope_id="notification-envelope:ctx-recovery-legacy",
            envelope_type="notification",
            correlation_id="corr:family-recovery-legacy:ctx-recovery-legacy",
            session_id="session:repo-a",
            project_id="repo-a",
            native_thread_id=None,
            policy_version="policy-v1",
            fact_snapshot_version="fact-v7",
            idempotency_key="idem:ctx-recovery-legacy",
            audit_ref="audit:ctx-recovery-legacy",
            created_at="2026-04-14T03:10:00Z",
            updated_at="2026-04-14T03:10:00Z",
            outbox_seq=1,
            delivery_status="delivered",
            envelope_payload={
                "interaction_context_id": "ctx-recovery-legacy",
                "interaction_family_id": "family-recovery-legacy",
                "actor_id": "user:alice",
                "channel_kind": "dm",
                "native_thread_id": "thr_native_legacy",
            },
        )
    )
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "session:repo-a",
            "native_thread_id": "thr_native_legacy",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "repeated failures",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        handoff_data={"goal_contract_version": "goal-v9"},
        resume_data={
            "resume_outcome": "new_child_session",
            "session_id": "session:repo-a:child-v9",
        },
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
        session_service=session_service,
    )

    assert outcome.action == "handoff_and_resume"
    superseded_events = session_service.list_events(
        session_id="session:repo-a",
        event_type="interaction_context_superseded",
    )
    assert len(superseded_events) == 1
    assert superseded_events[0].related_ids["native_thread_id"] == "thr_native_legacy"


def test_perform_recovery_execution_repeated_recovery_uses_unique_supersede_correlation_ids(
    tmp_path,
) -> None:
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    delivery_store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    delivery_store.update_delivery_record(
        DeliveryOutboxRecord(
            envelope_id="notification-envelope:ctx-recovery-repeat",
            envelope_type="notification",
            correlation_id="corr:family-recovery-repeat:ctx-recovery-repeat",
            session_id="session:repo-a",
            project_id="repo-a",
            native_thread_id="thr_native_1",
            policy_version="policy-v1",
            fact_snapshot_version="fact-v7",
            idempotency_key="idem:ctx-recovery-repeat",
            audit_ref="audit:ctx-recovery-repeat",
            created_at="2026-04-14T03:10:00Z",
            updated_at="2026-04-14T03:10:00Z",
            outbox_seq=1,
            delivery_status="delivered",
            envelope_payload={
                "interaction_context_id": "ctx-recovery-repeat",
                "interaction_family_id": "family-recovery-repeat",
                "actor_id": "user:alice",
                "channel_kind": "dm",
            },
        )
    )
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "session:repo-a",
            "native_thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "repeated failures",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        handoff_data={"goal_contract_version": "goal-v9"},
        resume_data={"resume_outcome": "same_thread_resume"},
    )

    first = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
        session_service=session_service,
    )
    second = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
        session_service=session_service,
    )

    assert first.action == "handoff_and_resume"
    assert second.action == "handoff_and_resume"
    superseded_events = session_service.list_events(
        session_id="session:repo-a",
        event_type="interaction_context_superseded",
    )
    assert len(superseded_events) == 2
    assert superseded_events[0].correlation_id != superseded_events[1].correlation_id


def test_perform_recovery_execution_treats_stable_session_thread_resume_as_same_thread(
    tmp_path,
) -> None:
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "session:repo-a",
            "native_thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "repeated failures",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        resume_data={
            "thread_id": "session:repo-a",
        },
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
        session_service=session_service,
    )

    assert outcome.action == "handoff_and_resume"
    assert outcome.resume_outcome == "same_thread_resume"
    recovery_records = session_service.list_recovery_transactions(
        parent_session_id="session:repo-a"
    )
    assert recovery_records[-1].child_session_id is None
    assert recovery_records[-1].metadata["resume_outcome"] == "same_thread_resume"
    assert session_service.list_lineage(
        recovery_transaction_id=recovery_records[-1].recovery_transaction_id
    ) == []


def test_perform_recovery_execution_reissued_interaction_uses_fresh_global_outbox_seq(
    tmp_path,
) -> None:
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    delivery_store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    delivery_store.update_delivery_record(
        DeliveryOutboxRecord(
            envelope_id="notification-envelope:unrelated-high-seq",
            envelope_type="notification",
            correlation_id="corr:repo-b:ctx-unrelated",
            session_id="session:repo-b",
            project_id="repo-b",
            native_thread_id="thr_native_repo_b",
            policy_version="policy-v1",
            fact_snapshot_version="fact-v8",
            idempotency_key="idem:ctx-unrelated",
            audit_ref="audit:ctx-unrelated",
            created_at="2026-04-14T03:05:00Z",
            updated_at="2026-04-14T03:05:00Z",
            outbox_seq=5,
            delivery_status="pending",
            envelope_payload={
                "interaction_context_id": "ctx-unrelated",
                "interaction_family_id": "family-unrelated",
                "actor_id": "user:bob",
                "channel_kind": "dm",
            },
        )
    )
    delivery_store.update_delivery_record(
        DeliveryOutboxRecord(
            envelope_id="notification-envelope:ctx-recovery-old",
            envelope_type="notification",
            correlation_id="corr:family-recovery-1:ctx-recovery-old",
            session_id="session:repo-a",
            project_id="repo-a",
            native_thread_id="thr_native_1",
            policy_version="policy-v1",
            fact_snapshot_version="fact-v7",
            idempotency_key="idem:ctx-recovery-old",
            audit_ref="audit:ctx-recovery-old",
            created_at="2026-04-14T03:10:00Z",
            updated_at="2026-04-14T03:10:00Z",
            outbox_seq=1,
            delivery_status="delivered",
            envelope_payload={
                "interaction_context_id": "ctx-recovery-old",
                "interaction_family_id": "family-recovery-1",
                "actor_id": "user:alice",
                "channel_kind": "dm",
            },
        )
    )
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "session:repo-a",
            "native_thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "repeated failures",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        handoff_data={"goal_contract_version": "goal-v9"},
        resume_data={
            "resume_outcome": "new_child_session",
            "session_id": "session:repo-a:child-v9",
        },
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
        session_service=session_service,
    )

    assert outcome.action == "handoff_and_resume"
    records = {record.envelope_id: record for record in delivery_store.list_records()}
    assert records["notification-envelope:ctx-recovery-old"].delivery_status == "superseded"
    assert records["notification-envelope:ctx-recovery-old:recovery"].outbox_seq == 6
    assert records["notification-envelope:ctx-recovery-old:recovery"].delivery_status == "pending"


def test_perform_recovery_execution_rewrites_reissued_payload_ids_to_match_record_metadata(
    tmp_path,
) -> None:
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    delivery_store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    delivery_store.update_delivery_record(
        DeliveryOutboxRecord(
            envelope_id="notification-envelope:ctx-recovery-old",
            envelope_type="notification",
            correlation_id="corr:family-recovery-1:ctx-recovery-old",
            session_id="session:repo-a",
            project_id="repo-a",
            native_thread_id="thr_native_1",
            policy_version="policy-v1",
            fact_snapshot_version="fact-v7",
            idempotency_key="idem:ctx-recovery-old",
            audit_ref="audit:ctx-recovery-old",
            created_at="2026-04-14T03:10:00Z",
            updated_at="2026-04-14T03:10:00Z",
            outbox_seq=1,
            delivery_status="delivered",
            envelope_payload={
                "envelope_id": "notification-envelope:ctx-recovery-old",
                "envelope_type": "notification",
                "correlation_id": "corr:family-recovery-1:ctx-recovery-old",
                "session_id": "session:repo-a",
                "project_id": "repo-a",
                "native_thread_id": "thr_native_1",
                "policy_version": "policy-v1",
                "fact_snapshot_version": "fact-v7",
                "idempotency_key": "idem:ctx-recovery-old",
                "audit_ref": "audit:ctx-recovery-old",
                "created_at": "2026-04-14T03:10:00Z",
                "interaction_context_id": "ctx-recovery-old",
                "interaction_family_id": "family-recovery-1",
                "actor_id": "user:alice",
                "channel_kind": "dm",
                "event_id": "event:ctx-recovery-old",
                "severity": "warning",
                "notification_kind": "progress_summary",
                "title": "old title",
                "summary": "old summary",
                "reason": "old reason",
            },
        )
    )
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "session:repo-a",
            "native_thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "repeated failures",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        handoff_data={"goal_contract_version": "goal-v9"},
        resume_data={
            "resume_outcome": "new_child_session",
            "session_id": "session:repo-a:child-v9",
        },
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
        session_service=session_service,
    )

    assert outcome.action == "handoff_and_resume"
    reissued = delivery_store.get_delivery_record("notification-envelope:ctx-recovery-old:recovery")
    assert reissued is not None
    assert reissued.envelope_payload["envelope_id"] == reissued.envelope_id
    assert reissued.envelope_payload["correlation_id"] == reissued.correlation_id
    assert reissued.envelope_payload["idempotency_key"] == reissued.idempotency_key
    assert reissued.envelope_payload["audit_ref"] == reissued.audit_ref
    assert reissued.envelope_payload["created_at"] == reissued.created_at
    assert reissued.envelope_payload["interaction_context_id"] == "ctx-recovery-old:recovery"


def test_perform_recovery_execution_retargets_reissued_interaction_to_child_session(
    tmp_path,
) -> None:
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    delivery_store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    delivery_store.update_delivery_record(
        DeliveryOutboxRecord(
            envelope_id="notification-envelope:ctx-recovery-old",
            envelope_type="notification",
            correlation_id="corr:family-recovery-1:ctx-recovery-old",
            session_id="session:repo-a",
            project_id="repo-a",
            native_thread_id="thr_native_1",
            policy_version="policy-v1",
            fact_snapshot_version="fact-v7",
            idempotency_key="idem:ctx-recovery-old",
            audit_ref="audit:ctx-recovery-old",
            created_at="2026-04-14T03:10:00Z",
            updated_at="2026-04-14T03:10:00Z",
            outbox_seq=1,
            delivery_status="delivered",
            envelope_payload={
                "envelope_id": "notification-envelope:ctx-recovery-old",
                "envelope_type": "notification",
                "correlation_id": "corr:family-recovery-1:ctx-recovery-old",
                "session_id": "session:repo-a",
                "project_id": "repo-a",
                "native_thread_id": "thr_native_1",
                "policy_version": "policy-v1",
                "fact_snapshot_version": "fact-v7",
                "idempotency_key": "idem:ctx-recovery-old",
                "audit_ref": "audit:ctx-recovery-old",
                "created_at": "2026-04-14T03:10:00Z",
                "interaction_context_id": "ctx-recovery-old",
                "interaction_family_id": "family-recovery-1",
                "actor_id": "user:alice",
                "channel_kind": "dm",
            },
        )
    )
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "session:repo-a",
            "native_thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "repeated failures",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        handoff_data={"goal_contract_version": "goal-v9"},
        resume_data={
            "resume_outcome": "new_child_session",
            "session_id": "session:repo-a:child-v9",
            "thread_id": "thr_child_v9",
        },
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
        session_service=session_service,
    )

    assert outcome.action == "handoff_and_resume"
    reissued = delivery_store.get_delivery_record("notification-envelope:ctx-recovery-old:recovery")
    assert reissued is not None
    assert reissued.session_id == "session:repo-a:child-v9"
    assert reissued.native_thread_id == "thr_child_v9"
    assert reissued.envelope_payload["session_id"] == "session:repo-a:child-v9"
    assert reissued.envelope_payload["native_thread_id"] == "thr_child_v9"


def test_perform_recovery_execution_reissued_interaction_uses_effective_native_thread_id_from_legacy_record(
    tmp_path,
) -> None:
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    delivery_store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    delivery_store.update_delivery_record(
        DeliveryOutboxRecord(
            envelope_id="notification-envelope:ctx-recovery-legacy-reissue",
            envelope_type="notification",
            correlation_id="corr:family-recovery-legacy-reissue:ctx",
            session_id="session:repo-a",
            project_id="repo-a",
            native_thread_id=None,
            policy_version="policy-v1",
            fact_snapshot_version="fact-v7",
            idempotency_key="idem:ctx-recovery-legacy-reissue",
            audit_ref="audit:ctx-recovery-legacy-reissue",
            created_at="2026-04-14T03:10:00Z",
            updated_at="2026-04-14T03:10:00Z",
            outbox_seq=1,
            delivery_status="delivered",
            envelope_payload={
                "envelope_id": "notification-envelope:ctx-recovery-legacy-reissue",
                "envelope_type": "notification",
                "correlation_id": "corr:family-recovery-legacy-reissue:ctx",
                "session_id": "session:repo-a",
                "project_id": "repo-a",
                "native_thread_id": "thr_native_legacy",
                "policy_version": "policy-v1",
                "fact_snapshot_version": "fact-v7",
                "idempotency_key": "idem:ctx-recovery-legacy-reissue",
                "audit_ref": "audit:ctx-recovery-legacy-reissue",
                "created_at": "2026-04-14T03:10:00Z",
                "interaction_context_id": "ctx-recovery-legacy-reissue",
                "interaction_family_id": "family-recovery-legacy-reissue",
                "actor_id": "user:alice",
                "channel_kind": "dm",
            },
        )
    )
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "session:repo-a",
            "native_thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "repeated failures",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        handoff_data={"goal_contract_version": "goal-v9"},
        resume_data={
            "resume_outcome": "new_child_session",
            "session_id": "session:repo-a:child-v9",
        },
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
        session_service=session_service,
    )

    assert outcome.action == "handoff_and_resume"
    reissued = delivery_store.get_delivery_record(
        "notification-envelope:ctx-recovery-legacy-reissue:recovery"
    )
    assert reissued is not None
    assert reissued.session_id == "session:repo-a:child-v9"
    assert reissued.native_thread_id == "thr_native_legacy"
    assert reissued.envelope_payload["native_thread_id"] == "thr_native_legacy"


def test_perform_recovery_execution_treats_stable_parent_session_id_as_same_thread_when_task_thread_is_native(
    tmp_path,
) -> None:
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "repeated failures",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        resume_data={
            "thread_id": "session:repo-a",
        },
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
        session_service=session_service,
    )

    assert outcome.action == "handoff_and_resume"
    assert outcome.resume_outcome == "same_thread_resume"
    recovery_records = session_service.list_recovery_transactions(
        parent_session_id="session:repo-a"
    )
    assert recovery_records[-1].child_session_id is None
    assert recovery_records[-1].metadata["resume_outcome"] == "same_thread_resume"


def test_perform_recovery_execution_preserves_handoff_when_resume_fails(tmp_path) -> None:
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "repeated failures",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        resume_success=False,
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
    )

    assert len(client.handoff_calls) == 1
    assert client.handoff_calls[0][0:2] == ("repo-a", "context_critical")
    assert client.handoff_calls[0][2] is not None
    assert len(client.resume_calls) == 1
    assert client.resume_calls[0][0:3] == ("repo-a", "resume_or_new_thread", "")
    assert client.resume_calls[0][3] == client.handoff_calls[0][2]
    assert outcome.action == "handoff_triggered"
    assert outcome.handoff is not None
    assert outcome.resume is None
    assert outcome.resume_error == "resume_call_failed"


def test_perform_recovery_execution_prefers_structured_packet_over_handoff_summary_in_auto_resume(
    tmp_path,
) -> None:
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "repeated failures",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        handoff_data={"summary": "resume from saved handoff"},
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
    )

    assert outcome.action == "handoff_and_resume"
    assert outcome.resume_outcome == "same_thread_resume"
    assert len(client.resume_calls) == 1
    assert client.resume_calls[0][0:3] == ("repo-a", "resume_or_new_thread", "")
    assert client.resume_calls[0][3] is not None


def test_perform_recovery_execution_builds_and_reuses_structured_continuation_packet(
    tmp_path,
) -> None:
    from watchdog.services.goal_contract.service import GoalContractService
    from watchdog.contracts.session_spine.models import FactRecord, SessionProjection, TaskProgressView
    from watchdog.services.session_spine.store import SessionSpineStore

    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    spine_store = SessionSpineStore(tmp_path / "session_spine.json")
    spine_store.put(
        project_id="repo-a",
        session=SessionProjection(
            project_id="repo-a",
            thread_id="session:repo-a",
            native_thread_id="thr_native_1",
            session_state="active",
            activity_phase="editing_source",
            attention_state="critical",
            headline="repeated failures",
            pending_approval_count=0,
            available_intents=["continue_session"],
        ),
        progress=TaskProgressView(
            project_id="repo-a",
            thread_id="session:repo-a",
            native_thread_id="thr_native_1",
            activity_phase="editing_source",
            summary="已经定位到 handoff_summary 回流口",
            files_touched=["src/watchdog/services/session_spine/recovery.py"],
            context_pressure="critical",
            stuck_level=2,
            primary_fact_codes=["context_critical"],
            blocker_fact_codes=[],
            last_progress_at="2026-04-05T05:20:00Z",
        ),
        facts=[
            FactRecord(
                fact_id="fact:context-critical",
                fact_code="context_critical",
                fact_kind="signal",
                severity="warning",
                summary="context_critical",
                detail="context_critical",
                source="watchdog",
                observed_at="2026-04-05T05:20:00Z",
            )
        ],
        approval_queue=[],
        last_refreshed_at="2026-04-05T05:20:01Z",
    )
    goal_contracts = GoalContractService(session_service)
    contract = goal_contracts.bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="补 packet truth",
        task_prompt="把 recovery 与 resume 都切到 structured ContinuationPacket。",
        last_user_instruction="继续把 handoff_summary 替换成 packet 主契约",
        phase="implementation",
        last_summary="已经定位到 handoff_summary 回流口",
        explicit_deliverables=["packet truth object", "packet render contract"],
        completion_signals=["相关 recovery / adapter 回归测试通过"],
    )
    revised = goal_contracts.revise_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        expected_version=contract.version,
        current_phase_goal="实现 ContinuationPacket 真值对象并切断 markdown 回流",
    )
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "已经定位到 handoff_summary 回流口",
            "files_touched": ["src/watchdog/services/session_spine/recovery.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
            "goal_contract_version": contract.version,
        },
        handoff_data={"summary": "legacy summary should not be authoritative"},
        resume_data={"resume_outcome": "same_thread_resume"},
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
        session_service=session_service,
    )

    assert outcome.action == "handoff_and_resume"
    assert len(client.handoff_calls) == 1
    handoff_packet = client.handoff_calls[0][2]
    assert handoff_packet is not None
    assert handoff_packet["packet_id"].startswith("packet:continuation:")
    assert handoff_packet["continuation_identity"] == _expected_continuation_identity("repo-a")
    assert handoff_packet["route_key"].endswith(":fact-v1")
    assert handoff_packet["project_total_goal"] == "把 recovery 与 resume 都切到 structured ContinuationPacket。"
    assert handoff_packet["branch_goal"] == "实现 ContinuationPacket 真值对象并切断 markdown 回流"
    assert handoff_packet["current_progress_summary"] == "已经定位到 handoff_summary 回流口"
    assert handoff_packet["remaining_tasks"] == ["相关 recovery / adapter 回归测试通过"]
    assert handoff_packet["first_action"].startswith("先检查最近已修改文件")
    assert handoff_packet["source_refs"]["goal_contract_version"] == revised.version
    assert handoff_packet["source_refs"]["authoritative_snapshot_version"] == "fact-v1"
    assert len(client.resume_calls) == 1
    assert client.resume_calls[0][3] == handoff_packet


def test_perform_recovery_execution_same_thread_resume_does_not_commit_lineage(
    tmp_path,
) -> None:
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "repeated failures",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
        session_service=session_service,
    )

    assert outcome.action == "handoff_and_resume"
    assert outcome.resume_outcome == "same_thread_resume"
    assert session_service.list_lineage(parent_session_id="session:repo-a") == []
    recovery_records = session_service.list_recovery_transactions(
        parent_session_id="session:repo-a"
    )
    assert [record.status for record in recovery_records] == [
        "started",
        "packet_frozen",
        "completed",
    ]
    assert recovery_records[-1].metadata["resume_outcome"] == "same_thread_resume"
    events = session_service.list_events(correlation_id=recovery_records[-1].correlation_id)
    assert [event.event_type for event in events] == [
        "recovery_tx_started",
        "handoff_packet_frozen",
        "continuation_identity_issued",
        "continuation_identity_consumed",
        "recovery_tx_completed",
    ]


def test_perform_recovery_execution_same_thread_resume_does_not_supersede_parent_future_workers(
    tmp_path,
) -> None:
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    future_workers = FutureWorkerExecutionService(session_service)
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "repeated failures",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
    )
    future_workers.request_worker(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        worker_task_ref="worker:task-running",
        decision_trace_ref="trace:running",
        goal_contract_version="goal-v9",
        scope="read_only",
        allowed_hands=["codex"],
        input_packet_refs=["packet:running"],
        retrieval_handles=["handle:running"],
        distilled_summary_ref="summary:running",
        execution_budget_ref="budget:running",
        occurred_at="2026-04-14T05:00:00Z",
    )
    future_workers.record_started(
        worker_task_ref="worker:task-running",
        project_id="repo-a",
        parent_session_id="session:repo-a",
        occurred_at="2026-04-14T05:01:00Z",
        worker_runtime_contract={"provider": "codex", "model": "gpt-5.4"},
    )
    future_workers.request_worker(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        worker_task_ref="worker:task-completed",
        decision_trace_ref="trace:completed",
        goal_contract_version="goal-v9",
        scope="read_only",
        allowed_hands=["codex"],
        input_packet_refs=["packet:completed"],
        retrieval_handles=["handle:completed"],
        distilled_summary_ref="summary:completed",
        execution_budget_ref="budget:completed",
        occurred_at="2026-04-14T05:02:00Z",
    )
    future_workers.record_started(
        worker_task_ref="worker:task-completed",
        project_id="repo-a",
        parent_session_id="session:repo-a",
        occurred_at="2026-04-14T05:03:00Z",
        worker_runtime_contract={"provider": "codex", "model": "gpt-5.4"},
    )
    future_workers.record_completed(
        worker_task_ref="worker:task-completed",
        project_id="repo-a",
        parent_session_id="session:repo-a",
        result_summary_ref="summary:worker:completed",
        artifact_refs=["artifact:completed"],
        input_contract_hash="sha256:input-completed",
        result_hash="sha256:result-completed",
        occurred_at="2026-04-14T05:05:00Z",
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
        session_service=session_service,
    )

    assert outcome.action == "handoff_and_resume"
    assert outcome.resume_outcome == "same_thread_resume"
    assert session_service.list_events(
        session_id="session:repo-a",
        event_type="future_worker_cancelled",
    ) == []
    assert session_service.list_events(
        session_id="session:repo-a",
        event_type="future_worker_result_rejected",
    ) == []


def test_perform_recovery_execution_persists_goal_contract_version_from_handoff(
    tmp_path,
) -> None:
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "repeated failures",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        handoff_data={"goal_contract_version": "goal-v9"},
        resume_data={
            "resume_outcome": "new_child_session",
            "session_id": "session:repo-a:child-v9",
        },
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
        session_service=session_service,
    )

    assert outcome.action == "handoff_and_resume"

    lineage_records = session_service.list_lineage(parent_session_id="session:repo-a")
    assert len(lineage_records) == 1
    assert lineage_records[0].goal_contract_version == "goal-v9"

    lineage_events = session_service.list_events(event_type="lineage_committed")
    assert len(lineage_events) == 1
    assert lineage_events[0].payload["goal_contract_version"] == "goal-v9"


def test_perform_recovery_execution_uses_goal_contract_version_from_continuation_packet(
    tmp_path,
) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    goal_contracts = GoalContractService(session_service)
    created = goal_contracts.bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="继承 continuation packet 里的 goal contract version",
        task_prompt="确保 recovery child session 会沿用 packet source_refs 里的 contract version。",
        last_user_instruction="继续当前 branch 的 recovery 继承链路。",
        phase="editing_source",
        last_summary="recovery handoff top-level 缺失 contract version。",
    )
    revised = goal_contracts.revise_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        expected_version=created.version,
        current_phase_goal="从 continuation packet source_refs 继承 goal contract version",
        last_user_instruction="继续沿用 packet source refs 的 goal contract truth。",
        last_summary="回归覆盖 handoff 顶层缺失 contract version 的恢复路径。",
        phase="editing_source",
    )
    continuation_packet = {
        "packet_id": "packet:continuation:repo-a:goal-v2",
        "packet_version": "continuation-packet/v1",
        "packet_state": "issued",
        "decision_class": "recover_current_branch",
        "continuation_identity": "repo-a:session:repo-a:thr_native_1:recover_current_branch",
        "project_id": "repo-a",
        "session_id": "session:repo-a",
        "native_thread_id": "thr_native_1",
        "route_key": "repo-a:session:repo-a:thr_native_1:recover_current_branch:fact-v9",
        "target_route": {
            "route_kind": "same_thread",
            "target_project_id": "repo-a",
            "target_session_id": "session:repo-a",
            "target_thread_id": "thr_native_1",
            "target_work_item_id": "WI-085",
        },
        "project_total_goal": "让 recovery child session 继承 active goal contract。",
        "branch_goal": "补 continuation packet source refs fallback。",
        "current_progress_summary": "handoff 顶层没有 goal contract version。",
        "completed_work": ["T856 control-plane projection complete"],
        "remaining_tasks": ["从 packet source refs 继承 goal_contract_version"],
        "first_action": "先读取 structured continuation packet。",
        "execution_mode": "resume_or_new_thread",
        "action_ref": "continue_current_branch",
        "action_args": {"resume_target_phase": "editing_source"},
        "expected_next_state": "running",
        "continue_boundary": "只继续当前分支",
        "stop_conditions": ["需要新的人工批准"],
        "operator_boundary": "不要把 markdown 当作 truth。",
        "source_refs": {
            "decision_source": "recovery_guard",
            "goal_contract_version": revised.version,
            "authoritative_snapshot_version": "fact-v9",
            "snapshot_epoch": "session-seq:9",
            "decision_trace_ref": "trace:packet:goal-v2",
            "lineage_refs": ["recovery-tx:goal-v2"],
        },
        "freshness": {
            "generated_at": "2026-04-21T01:20:00Z",
            "expires_at": "2026-04-21T02:20:00Z",
        },
        "dedupe": {
            "dedupe_key": "dedupe:repo-a:packet:goal-v2",
            "supersedes_packet_id": None,
        },
        "render_contract_ref": "continuation-packet-markdown/v1",
    }
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "repeated failures",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        handoff_data={
            "source_packet_id": "packet:handoff-v9",
            "goal_contract_version": created.version,
            "continuation_packet": continuation_packet,
        },
        resume_data={
            "resume_outcome": "new_child_session",
            "session_id": "session:repo-a:child-v9",
        },
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
        session_service=session_service,
    )

    assert outcome.action == "handoff_and_resume"
    lineage_records = session_service.list_lineage(parent_session_id="session:repo-a")
    assert len(lineage_records) == 1
    assert lineage_records[0].goal_contract_version == revised.version

    child_contract = goal_contracts.get_current_contract(
        project_id="repo-a",
        session_id=lineage_records[0].child_session_id,
    )
    assert child_contract is not None
    assert child_contract.version == revised.version


def test_perform_recovery_execution_uses_child_session_thread_when_native_missing(
    tmp_path,
) -> None:
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "session:repo-a",
            "native_thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "repeated failures",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        resume_data={
            "thread_id": "session:repo-a:child-v9",
        },
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
        session_service=session_service,
    )

    assert outcome.action == "handoff_and_resume"
    assert outcome.resume_outcome == "new_child_session"
    lineage_records = session_service.list_lineage(parent_session_id="session:repo-a")
    assert len(lineage_records) == 1
    assert lineage_records[0].child_session_id == "session:repo-a:child-v9"


def test_perform_recovery_execution_preserves_upstream_source_packet_id(
    tmp_path,
) -> None:
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "repeated failures",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        handoff_data={"source_packet_id": "packet:handoff-v9"},
        resume_data={
            "resume_outcome": "new_child_session",
            "session_id": "session:repo-a:child-v9",
        },
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
        session_service=session_service,
    )

    assert outcome.action == "handoff_and_resume"

    lineage_records = session_service.list_lineage(parent_session_id="session:repo-a")
    assert len(lineage_records) == 1
    assert lineage_records[0].source_packet_id == "packet:handoff-v9"

    frozen_events = session_service.list_events(event_type="handoff_packet_frozen")
    assert len(frozen_events) == 1
    assert frozen_events[0].related_ids["source_packet_id"] == "packet:handoff-v9"

    recovery_records = session_service.list_recovery_transactions(
        parent_session_id="session:repo-a"
    )
    assert recovery_records[-1].source_packet_id == "packet:handoff-v9"


def test_perform_recovery_execution_adopts_goal_contract_for_child_session(
    tmp_path,
) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    goal_contracts = GoalContractService(session_service)
    created = goal_contracts.bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="补 recovery 黄金路径测试",
        task_prompt="先把 recovery 写点找出来，再补最小黄金路径测试",
        last_user_instruction="继续按 recovery 顺序推进",
        phase="implementation",
        last_summary="正在补 recovery 红测",
        explicit_deliverables=["补 recovery/goal contract 接线测试"],
        completion_signals=["相关 pytest 通过"],
    )
    revised = goal_contracts.revise_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        expected_version=created.version,
        current_phase_goal="让 recovery 为 child session 写 adopt truth",
    )

    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "repeated failures",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        handoff_data={
            "goal_contract_version": revised.version,
            "source_packet_id": "packet:handoff-v9",
        },
        resume_data={
            "resume_outcome": "new_child_session",
            "session_id": "session:repo-a:child-v9",
            "native_thread_id": "thr_child_v9",
        },
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
        session_service=session_service,
    )

    assert outcome.action == "handoff_and_resume"

    lineage_records = session_service.list_lineage(parent_session_id="session:repo-a")
    assert len(lineage_records) == 1
    child_session_id = lineage_records[0].child_session_id

    child_contract = goal_contracts.get_current_contract(
        project_id="repo-a",
        session_id=child_session_id,
    )
    assert child_contract is not None
    assert child_contract.version == revised.version
    assert child_contract.current_phase_goal == "让 recovery 为 child session 写 adopt truth"

    adoption_events = session_service.list_events(
        session_id=child_session_id,
        event_type="goal_contract_adopted_by_child_session",
    )
    assert len(adoption_events) == 1
    assert adoption_events[0].related_ids["child_session_id"] == child_session_id
    assert adoption_events[0].related_ids["goal_contract_version"] == revised.version
    assert adoption_events[0].related_ids["source_packet_id"] == "packet:handoff-v9"
    assert adoption_events[0].related_ids["recovery_transaction_id"].startswith("recovery-tx:")
    assert adoption_events[0].related_ids["native_thread_id"] == "thr_child_v9"


def test_perform_recovery_execution_adopts_goal_contract_when_resume_uses_child_session_id(
    tmp_path,
) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    goal_contracts = GoalContractService(session_service)
    created = goal_contracts.bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="补 child session recover payload 兼容测试",
        task_prompt="锁定 child_session_id 形态的 recovery adoption。",
        last_user_instruction="继续补 recovery child_session_id 回归",
        phase="implementation",
        last_summary="正在补 current A response shape regression",
        explicit_deliverables=["补 child_session_id adoption 回归"],
        completion_signals=["相关 pytest 通过"],
    )
    revised = goal_contracts.revise_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        expected_version=created.version,
        current_phase_goal="让 current A response shape 也能 adopt 到 child session",
    )

    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "repeated failures",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        handoff_data={
            "goal_contract_version": revised.version,
            "source_packet_id": "packet:handoff-v9",
        },
        resume_data={
            "resume_outcome": "new_child_session",
            "child_session_id": "session:repo-a:thr_child_v9",
            "thread_id": "thr_child_v9",
            "native_thread_id": "thr_child_v9",
        },
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
        session_service=session_service,
    )

    assert outcome.action == "handoff_and_resume"
    assert outcome.resume_outcome == "new_child_session"

    lineage_records = session_service.list_lineage(parent_session_id="session:repo-a")
    assert len(lineage_records) == 1
    assert lineage_records[0].child_session_id == "session:repo-a:thr_child_v9"

    child_contract = goal_contracts.get_current_contract(
        project_id="repo-a",
        session_id="session:repo-a:thr_child_v9",
    )
    assert child_contract is not None
    assert child_contract.version == revised.version

    adoption_events = session_service.list_events(
        session_id="session:repo-a:thr_child_v9",
        event_type="goal_contract_adopted_by_child_session",
    )
    assert len(adoption_events) == 1
    assert adoption_events[0].related_ids["child_session_id"] == "session:repo-a:thr_child_v9"
    assert adoption_events[0].related_ids["native_thread_id"] == "thr_child_v9"
    assert adoption_events[0].related_ids["goal_contract_version"] == revised.version


def test_perform_recovery_execution_supersedes_parent_future_workers(tmp_path) -> None:
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    future_workers = FutureWorkerExecutionService(session_service)
    client = FakeAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "repeated failures",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        handoff_data={"goal_contract_version": "goal-v9"},
        resume_data={
            "resume_outcome": "new_child_session",
            "session_id": "session:repo-a:child-v9",
        },
    )

    future_workers.request_worker(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        worker_task_ref="worker:task-running",
        decision_trace_ref="trace:running",
        goal_contract_version="goal-v9",
        scope="read_only",
        allowed_hands=["codex"],
        input_packet_refs=["packet:running"],
        retrieval_handles=["handle:running"],
        distilled_summary_ref="summary:running",
        execution_budget_ref="budget:running",
        occurred_at="2026-04-14T05:00:00Z",
    )
    future_workers.record_started(
        worker_task_ref="worker:task-running",
        project_id="repo-a",
        parent_session_id="session:repo-a",
        occurred_at="2026-04-14T05:01:00Z",
        worker_runtime_contract={"provider": "codex", "model": "gpt-5.4"},
    )
    future_workers.request_worker(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        worker_task_ref="worker:task-completed",
        decision_trace_ref="trace:completed",
        goal_contract_version="goal-v9",
        scope="read_only",
        allowed_hands=["codex"],
        input_packet_refs=["packet:completed"],
        retrieval_handles=["handle:completed"],
        distilled_summary_ref="summary:completed",
        execution_budget_ref="budget:completed",
        occurred_at="2026-04-14T05:02:00Z",
    )
    future_workers.record_started(
        worker_task_ref="worker:task-completed",
        project_id="repo-a",
        parent_session_id="session:repo-a",
        occurred_at="2026-04-14T05:03:00Z",
        worker_runtime_contract={"provider": "codex", "model": "gpt-5.4"},
    )
    future_workers.record_completed(
        worker_task_ref="worker:task-completed",
        project_id="repo-a",
        parent_session_id="session:repo-a",
        result_summary_ref="summary:worker:completed",
        artifact_refs=["artifact:completed"],
        input_contract_hash="sha256:input-completed",
        result_hash="sha256:result-completed",
        occurred_at="2026-04-14T05:04:00Z",
    )

    outcome = perform_recovery_execution(
        "repo-a",
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
            recover_auto_resume=True,
        ),
        client=client,
        session_service=session_service,
    )

    assert outcome.action == "handoff_and_resume"

    cancelled_events = session_service.list_events(
        session_id="session:repo-a",
        event_type="future_worker_cancelled",
    )
    rejected_events = session_service.list_events(
        session_id="session:repo-a",
        event_type="future_worker_result_rejected",
    )

    assert len(cancelled_events) == 1
    assert cancelled_events[0].related_ids["worker_task_ref"] == "worker:task-running"
    assert cancelled_events[0].payload["reason"] == "recovery_superseded_by_child_session"
    assert len(rejected_events) == 1
    assert rejected_events[0].related_ids["worker_task_ref"] == "worker:task-completed"
    assert rejected_events[0].payload["reason"] == "recovery_superseded_by_child_session"
