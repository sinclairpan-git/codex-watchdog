from __future__ import annotations

from pathlib import Path

import pytest

from watchdog.main import create_app
from watchdog.services.delivery.store import DeliveryOutboxRecord
from watchdog.services.goal_contract.service import GoalContractService
from watchdog.services.session_spine.recovery import perform_recovery_execution
from watchdog.settings import Settings


class _RecoveryAClient:
    def __init__(self, *, use_current_child_session_shape: bool = False) -> None:
        self.handoff_calls: list[tuple[str, str]] = []
        self.resume_calls: list[tuple[str, str, str]] = []
        self.use_current_child_session_shape = use_current_child_session_shape

    def get_envelope(self, project_id: str) -> dict[str, object]:
        return {
            "success": True,
            "data": {
                "project_id": project_id,
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "context exhausted after remote compact",
                "files_touched": ["src/example.py"],
                "context_pressure": "critical",
                "stuck_level": 2,
                "failure_count": 3,
                "last_progress_at": "2026-04-14T03:20:00Z",
            },
        }

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

    def trigger_handoff(
        self,
        project_id: str,
        *,
        reason: str,
        continuation_packet: dict[str, object] | None = None,
    ) -> dict[str, object]:
        _ = continuation_packet
        self.handoff_calls.append((project_id, reason))
        return {
            "success": True,
            "data": {
                "handoff_file": f"/tmp/{project_id}.handoff.md",
                "summary": "remote compact recovery",
                "goal_contract_version": "goal-contract:v2",
                "source_packet_id": "packet:handoff-recovery-1",
            },
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
        payload = {
            "project_id": project_id,
            "status": "running",
            "mode": mode,
            "resume_outcome": "new_child_session",
            "thread_id": "thr_child_1",
            "goal_contract_version": "goal-contract:v2",
        }
        if self.use_current_child_session_shape:
            payload["child_session_id"] = f"session:{project_id}:thr_child_1"
            payload["native_thread_id"] = "thr_child_1"
        else:
            payload["session_id"] = f"session:{project_id}:thr_child_1"
        return {
            "success": True,
            "data": payload,
        }


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        api_token="watchdog-token",
        codex_runtime_token="a-agent-token",
        codex_runtime_base_url="http://a-control.test",
        data_dir=str(tmp_path),
        recover_auto_resume=True,
    )


@pytest.mark.parametrize("use_current_child_session_shape", [False, True])
def test_recovery_continuation_supersedes_stale_interaction_without_manual_patch(
    tmp_path: Path,
    use_current_child_session_shape: bool,
) -> None:
    settings = _settings(tmp_path)
    client = _RecoveryAClient(use_current_child_session_shape=use_current_child_session_shape)
    app = create_app(settings=settings, runtime_client=client, start_background_workers=False)

    goal_contracts = GoalContractService(app.state.session_service)
    created = goal_contracts.bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="收口一期 e2e recovery",
        task_prompt="先锁定 recovery 的 child continuation，再补 golden path。",
        last_user_instruction="继续把 recovery 和 child continuation 串起来",
        phase="implementation",
        last_summary="准备进入 recovery e2e 红测",
        explicit_deliverables=["锁定 recovery golden path"],
        completion_signals=["相关 e2e pytest 通过"],
    )
    revised = goal_contracts.revise_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        expected_version=created.version,
        current_phase_goal="让 stale interaction 和 child continuation 进入同一条恢复主链",
    )

    app.state.delivery_outbox_store.update_delivery_record(
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

    client.trigger_handoff = lambda project_id, reason, continuation_packet=None: {  # type: ignore[method-assign]
        "success": True,
        "data": {
            "handoff_file": f"/tmp/{project_id}.handoff.md",
            "summary": "remote compact recovery",
            "goal_contract_version": revised.version,
            "source_packet_id": "packet:handoff-recovery-1",
        },
    }

    outcome = perform_recovery_execution(
        "repo-a",
        settings=settings,
        client=client,
        session_service=app.state.session_service,
    )

    assert outcome.action == "handoff_and_resume"
    lineage = app.state.session_service.list_lineage(parent_session_id="session:repo-a")
    assert len(lineage) == 1
    adoption_events = app.state.session_service.list_events(
        event_type="goal_contract_adopted_by_child_session"
    )
    assert len(adoption_events) == 1
    assert adoption_events[0].related_ids["child_session_id"] == "session:repo-a:thr_child_1"
    assert adoption_events[0].payload["child_session_id"] == "session:repo-a:thr_child_1"

    supersede_events = app.state.session_service.list_events(
        session_id="session:repo-a",
        event_type="interaction_context_superseded",
    )
    assert len(supersede_events) == 1

    active_contexts = [
        record
        for record in app.state.delivery_outbox_store.list_records()
        if record.envelope_payload.get("interaction_family_id") == "family-recovery-1"
        and record.delivery_status not in {"superseded", "delivery_failed"}
    ]
    assert len(active_contexts) == 1
    assert active_contexts[0].envelope_payload["interaction_context_id"] != "ctx-recovery-old"
