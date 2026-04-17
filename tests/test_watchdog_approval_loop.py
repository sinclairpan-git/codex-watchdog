from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import threading

from fastapi.testclient import TestClient
import pytest

from watchdog.main import create_app
from watchdog.services.policy.decisions import CanonicalDecisionRecord
from watchdog.settings import Settings
from watchdog.storage.action_receipts import ActionReceiptStore


class FakeAClient:
    def __init__(self, *, context_pressure: str = "critical") -> None:
        self._context_pressure = context_pressure
        self.decision_calls: list[tuple[str, str, str, str]] = []
        self.handoff_calls: list[tuple[str, str]] = []
        self.resume_calls: list[tuple[str, str, str]] = []

    def get_envelope(self, project_id: str) -> dict[str, object]:
        return {
            "success": True,
            "data": {
                "project_id": project_id,
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "approval",
                "pending_approval": True,
                "last_summary": "waiting for approval",
                "files_touched": ["src/example.py"],
                "context_pressure": self._context_pressure,
                "stuck_level": 2,
                "failure_count": 3,
                "last_progress_at": "2026-04-05T05:20:00Z",
            },
        }

    def decide_approval(
        self,
        approval_id: str,
        *,
        decision: str,
        operator: str,
        note: str = "",
    ) -> dict[str, object]:
        self.decision_calls.append((approval_id, decision, operator, note))
        return {
            "success": True,
            "data": {
                "approval_id": approval_id,
                "status": "approved" if decision == "approve" else "rejected",
                "operator": operator,
                "note": note,
            },
        }

    def trigger_handoff(
        self,
        project_id: str,
        *,
        reason: str,
    ) -> dict[str, object]:
        self.handoff_calls.append((project_id, reason))
        return {
            "success": True,
            "data": {"handoff_file": f"/tmp/{project_id}.handoff.md", "summary": "handoff"},
        }

    def trigger_resume(
        self,
        project_id: str,
        *,
        mode: str,
        handoff_summary: str,
    ) -> dict[str, object]:
        self.resume_calls.append((project_id, mode, handoff_summary))
        return {
            "success": True,
            "data": {"project_id": project_id, "status": "running", "mode": mode},
        }


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
    )


def _decision(
    *,
    decision_result: str = "require_user_decision",
    action_ref: str = "execute_recovery",
    approval_id: str = "appr_001",
) -> CanonicalDecisionRecord:
    return CanonicalDecisionRecord(
        decision_id="decision:needs-human",
        decision_key=(
            "session:repo-a|fact-v7|policy-v1|require_user_decision|execute_recovery|appr_001"
        ),
        session_id="session:repo-a",
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="thr_native_1",
        approval_id=approval_id,
        action_ref=action_ref,
        trigger="resident_supervision",
        decision_result=decision_result,
        risk_class="human_gate",
        decision_reason="session requires explicit human decision",
        matched_policy_rules=["human_gate"],
        why_not_escalated=None,
        why_escalated="human_gate matched persisted facts",
        uncertainty_reasons=[],
        policy_version="policy-v1",
        fact_snapshot_version="fact-v7",
        idempotency_key=(
            "session:repo-a|fact-v7|policy-v1|require_user_decision|execute_recovery|appr_001"
        ),
        created_at="2026-04-07T00:00:00Z",
        operator_notes=[],
        evidence={
            "goal_contract_version": "goal-v1",
            "decision": {
                "action_ref": action_ref,
                "decision_result": decision_result,
            }
        },
    )


def test_materialize_canonical_approval_reuses_same_record_for_same_decision(tmp_path: Path) -> None:
    from watchdog.services.approvals.service import (
        CanonicalApprovalStore,
        materialize_canonical_approval,
    )
    from watchdog.services.delivery.store import DeliveryOutboxStore

    store = CanonicalApprovalStore(tmp_path / "canonical_approvals.json")
    delivery_store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")

    first = materialize_canonical_approval(
        _decision(),
        approval_store=store,
        delivery_outbox_store=delivery_store,
    )
    second = materialize_canonical_approval(
        _decision(),
        approval_store=store,
        delivery_outbox_store=delivery_store,
    )

    assert first.envelope_id == second.envelope_id
    assert first.approval_id == "appr_001"
    assert first.requested_action == "execute_recovery"
    assert first.decision_options == ["approve", "reject", "execute_action"]
    pending = delivery_store.list_pending_delivery_records(session_id=first.session_id)
    assert [record.envelope_type for record in pending] == ["approval"]
    assert pending[0].envelope_id == first.envelope_id
    assert first.goal_contract_version == "goal-v1"


def test_canonical_approval_store_keeps_previous_snapshot_when_atomic_replace_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from watchdog.services.approvals.service import (
        CanonicalApprovalStore,
        materialize_canonical_approval,
    )

    store_path = tmp_path / "canonical_approvals.json"
    store = CanonicalApprovalStore(store_path)
    seed = materialize_canonical_approval(
        _decision(),
        approval_store=store,
    )

    original_replace = Path.replace

    def fail_replace(self: Path, target: Path) -> Path:
        if self.parent == store_path.parent and self.name.startswith(f"{store_path.name}."):
            raise OSError("atomic replace failed")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_replace)

    newer_decision = _decision().model_copy(
        update={
            "decision_id": "decision:needs-human-v8",
            "decision_key": (
                "session:repo-a|fact-v8|policy-v1|require_user_decision|execute_recovery|appr_001"
            ),
            "fact_snapshot_version": "fact-v8",
            "idempotency_key": (
                "session:repo-a|fact-v8|policy-v1|require_user_decision|execute_recovery|appr_001"
            ),
            "created_at": "2026-04-07T00:05:00Z",
            "decision_reason": "session still requires explicit human decision after newer evidence",
            "why_escalated": "human_gate matched newer persisted facts",
            "evidence": {
                "decision": {
                    "action_ref": "execute_recovery",
                    "decision_result": "require_user_decision",
                },
                "goal_contract_version": "goal-v2",
                "requested_action_args": {"mode": "safe", "resume": True},
            },
        }
    )

    with pytest.raises(OSError, match="atomic replace failed"):
        materialize_canonical_approval(
            newer_decision,
            approval_store=store,
        )

    reparsed = CanonicalApprovalStore(store_path).list_records()
    assert [record.envelope_id for record in reparsed] == [seed.envelope_id]
    assert list(tmp_path.glob("*.tmp")) == []
    raw = json.loads(store_path.read_text(encoding="utf-8"))
    assert list(raw) == [seed.envelope_id]


def test_materialize_canonical_approval_refreshes_pending_record_for_newer_fact_snapshot(
    tmp_path: Path,
) -> None:
    from watchdog.services.approvals.service import (
        CanonicalApprovalStore,
        materialize_canonical_approval,
    )

    store = CanonicalApprovalStore(tmp_path / "canonical_approvals.json")
    first = materialize_canonical_approval(
        _decision(),
        approval_store=store,
    )
    second_decision = _decision().model_copy(
        update={
            "decision_id": "decision:needs-human-v8",
            "decision_key": (
                "session:repo-a|fact-v8|policy-v1|require_user_decision|execute_recovery|appr_001"
            ),
            "fact_snapshot_version": "fact-v8",
            "idempotency_key": (
                "session:repo-a|fact-v8|policy-v1|require_user_decision|execute_recovery|appr_001"
            ),
            "created_at": "2026-04-07T00:05:00Z",
            "decision_reason": "session still requires explicit human decision after newer evidence",
            "why_escalated": "human_gate matched newer persisted facts",
            "evidence": {
                "decision": {
                    "action_ref": "execute_recovery",
                    "decision_result": "require_user_decision",
                },
                "goal_contract_version": "goal-v2",
                "requested_action_args": {"mode": "safe", "resume": True},
            },
        }
    )

    second = materialize_canonical_approval(
        second_decision,
        approval_store=store,
    )

    assert second.approval_id == first.approval_id
    assert second.envelope_id == first.envelope_id
    assert second.approval_token == first.approval_token
    assert second.fact_snapshot_version == "fact-v8"
    assert second.idempotency_key == (
        "session:repo-a|fact-v8|policy-v1|require_user_decision|execute_recovery|appr_001|approval"
    )
    assert second.requested_action_args == {"mode": "safe", "resume": True}
    assert second.goal_contract_version == "goal-v2"
    assert second.decision.fact_snapshot_version == "fact-v8"
    assert second.decision.decision_reason == (
        "session still requires explicit human decision after newer evidence"
    )


def test_materialize_canonical_approval_does_not_reuse_resolved_candidate_closure_record(
    tmp_path: Path,
) -> None:
    from watchdog.services.approvals.service import (
        CanonicalApprovalStore,
        materialize_canonical_approval,
    )

    store = CanonicalApprovalStore(tmp_path / "canonical_approvals.json")
    first_decision = _decision(action_ref="post_operator_guidance", approval_id=None).model_copy(
        update={
            "decision_key": (
                "session:repo-a|fact-v7|policy-v1|require_user_decision|candidate_closure|"
                "post_operator_guidance|"
            ),
            "fact_snapshot_version": "fact-v7",
            "idempotency_key": (
                "session:repo-a|fact-v7|policy-v1|require_user_decision|candidate_closure|"
                "post_operator_guidance|"
            ),
            "evidence": {
                "goal_contract_version": "goal-v1",
                "requested_action_args": {
                    "message": "Review completion candidate for repo-a",
                    "reason_code": "candidate_closure",
                    "stuck_level": 0,
                },
            },
        }
    )
    first = materialize_canonical_approval(first_decision, approval_store=store)
    store.update(
        first.model_copy(
            update={
                "status": "approved",
                "decided_at": "2026-04-07T00:01:00Z",
                "decided_by": "operator",
            }
        )
    )

    second_decision = first_decision.model_copy(
        update={
            "decision_id": "decision:needs-human-v8",
            "decision_key": (
                "session:repo-a|fact-v8|policy-v1|require_user_decision|candidate_closure|"
                "post_operator_guidance|"
            ),
            "fact_snapshot_version": "fact-v8",
            "idempotency_key": (
                "session:repo-a|fact-v8|policy-v1|require_user_decision|candidate_closure|"
                "post_operator_guidance|"
            ),
        }
    )
    second = materialize_canonical_approval(second_decision, approval_store=store)

    assert second.envelope_id != first.envelope_id
    assert second.approval_id != first.approval_id
    assert second.fact_snapshot_version == "fact-v8"


def test_canonical_approval_freshness_rejects_expired_or_mismatched_scope() -> None:
    from watchdog.services.approvals.service import (
        build_canonical_approval_record,
        is_canonical_approval_fresh,
    )

    approval = build_canonical_approval_record(_decision()).model_copy(
        update={
            "goal_contract_version": "goal-v1",
            "expires_at": "2026-04-07T01:00:00Z",
        }
    )

    assert is_canonical_approval_fresh(
        approval,
        session_id="session:repo-a",
        project_id="repo-a",
        requested_action="execute_recovery",
        fact_snapshot_version="fact-v7",
        goal_contract_version="goal-v1",
        now="2026-04-07T00:30:00Z",
    )
    assert not is_canonical_approval_fresh(
        approval,
        session_id="session:repo-old",
        project_id="repo-a",
        requested_action="execute_recovery",
        fact_snapshot_version="fact-v7",
        goal_contract_version="goal-v1",
        now="2026-04-07T00:30:00Z",
    )
    assert not is_canonical_approval_fresh(
        approval,
        session_id="session:repo-a",
        project_id="repo-a",
        requested_action="continue_session",
        fact_snapshot_version="fact-v7",
        goal_contract_version="goal-v1",
        now="2026-04-07T00:30:00Z",
    )
    assert not is_canonical_approval_fresh(
        approval,
        session_id="session:repo-a",
        project_id="repo-a",
        requested_action="execute_recovery",
        fact_snapshot_version="fact-v8",
        goal_contract_version="goal-v1",
        now="2026-04-07T00:30:00Z",
    )
    assert not is_canonical_approval_fresh(
        approval,
        session_id="session:repo-a",
        project_id="repo-a",
        requested_action="execute_recovery",
        fact_snapshot_version="fact-v7",
        goal_contract_version="goal-v2",
        now="2026-04-07T00:30:00Z",
    )
    assert not is_canonical_approval_fresh(
        approval,
        session_id="session:repo-a",
        project_id="repo-a",
        requested_action="execute_recovery",
        fact_snapshot_version="fact-v7",
        goal_contract_version="goal-v1",
        now="2026-04-07T01:30:00Z",
    )


def test_canonical_approval_freshness_rejects_superseded_rejected_and_expired_status() -> None:
    from watchdog.services.approvals.service import (
        build_canonical_approval_record,
        is_canonical_approval_fresh,
    )

    approval = build_canonical_approval_record(_decision()).model_copy(
        update={
            "goal_contract_version": "goal-v1",
            "expires_at": "2026-04-07T01:00:00Z",
        }
    )

    for status in ("superseded", "rejected", "expired"):
        stale = approval.model_copy(update={"status": status})
        assert not is_canonical_approval_fresh(
            stale,
            session_id="session:repo-a",
            project_id="repo-a",
            requested_action="execute_recovery",
            fact_snapshot_version="fact-v7",
            goal_contract_version="goal-v1",
            now="2026-04-07T00:30:00Z",
        )


def test_materialize_canonical_approval_reuses_legacy_pending_record_for_same_approval_id(
    tmp_path: Path,
) -> None:
    from watchdog.services.approvals.service import (
        CanonicalApprovalStore,
        build_canonical_approval_record,
        materialize_canonical_approval,
    )

    store = CanonicalApprovalStore(tmp_path / "canonical_approvals.json")
    legacy_record = build_canonical_approval_record(_decision()).model_copy(
        update={
            "envelope_id": "approval-envelope:legacy",
            "approval_token": "approval-token:legacy",
        }
    )
    store.put(legacy_record)

    refreshed = materialize_canonical_approval(
        _decision().model_copy(
            update={
                "decision_id": "decision:needs-human-v8",
                "decision_key": (
                    "session:repo-a|fact-v8|policy-v1|require_user_decision|"
                    "execute_recovery|appr_001"
                ),
                "fact_snapshot_version": "fact-v8",
                "idempotency_key": (
                    "session:repo-a|fact-v8|policy-v1|require_user_decision|"
                    "execute_recovery|appr_001"
                ),
                "created_at": "2026-04-07T00:05:00Z",
                "decision_reason": "session still requires explicit human decision after newer evidence",
                "why_escalated": "human_gate matched newer persisted facts",
            }
        ),
        approval_store=store,
    )

    assert len(store.list_records()) == 1
    assert refreshed.approval_id == "appr_001"
    assert refreshed.envelope_id == "approval-envelope:legacy"
    assert refreshed.approval_token == "approval-token:legacy"
    assert refreshed.fact_snapshot_version == "fact-v8"
    assert refreshed.decision.fact_snapshot_version == "fact-v8"


def test_materialize_canonical_approval_reuses_legacy_pending_delivery_record_for_same_approval_id(
    tmp_path: Path,
) -> None:
    from watchdog.services.approvals.service import (
        CanonicalApprovalStore,
        build_canonical_approval_record,
        materialize_canonical_approval,
    )
    from watchdog.services.delivery.store import DeliveryOutboxStore

    store = CanonicalApprovalStore(tmp_path / "canonical_approvals.json")
    delivery_store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    legacy_record = build_canonical_approval_record(_decision()).model_copy(
        update={
            "envelope_id": "approval-envelope:legacy",
            "approval_token": "approval-token:legacy",
        }
    )
    store.put(legacy_record)

    refreshed = materialize_canonical_approval(
        _decision().model_copy(
            update={
                "decision_id": "decision:needs-human-v8",
                "decision_key": (
                    "session:repo-a|fact-v8|policy-v1|require_user_decision|"
                    "execute_recovery|appr_001"
                ),
                "fact_snapshot_version": "fact-v8",
                "idempotency_key": (
                    "session:repo-a|fact-v8|policy-v1|require_user_decision|"
                    "execute_recovery|appr_001"
                ),
                "created_at": "2026-04-07T00:05:00Z",
            }
        ),
        approval_store=store,
        delivery_outbox_store=delivery_store,
    )

    pending = delivery_store.list_pending_delivery_records(session_id=refreshed.session_id)

    assert [record.envelope_id for record in pending] == ["approval-envelope:legacy"]
    assert pending[0].fact_snapshot_version == "fact-v8"


def test_canonical_approval_store_reconciles_duplicate_pending_records_for_same_approval_id(
    tmp_path: Path,
) -> None:
    from watchdog.services.approvals.service import CanonicalApprovalStore, build_canonical_approval_record

    store = CanonicalApprovalStore(tmp_path / "canonical_approvals.json")
    older = build_canonical_approval_record(_decision()).model_copy(
        update={
            "envelope_id": "approval-envelope:old",
            "approval_token": "approval-token:old",
        }
    )
    newer = build_canonical_approval_record(
        _decision().model_copy(
            update={
                "decision_id": "decision:needs-human-v8",
                "decision_key": (
                    "session:repo-a|fact-v8|policy-v1|require_user_decision|"
                    "execute_recovery|appr_001"
                ),
                "fact_snapshot_version": "fact-v8",
                "idempotency_key": (
                    "session:repo-a|fact-v8|policy-v1|require_user_decision|"
                    "execute_recovery|appr_001"
                ),
                "created_at": "2026-04-07T00:05:00Z",
            }
        )
    ).model_copy(
        update={
            "envelope_id": "approval-envelope:new",
            "approval_token": "approval-token:new",
            "created_at": "2026-04-07T00:05:00Z",
        }
    )
    (tmp_path / "canonical_approvals.json").write_text(
        json.dumps(
            {
                older.envelope_id: older.model_dump(mode="json"),
                newer.envelope_id: newer.model_dump(mode="json"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    updated = store.reconcile_duplicate_pending_records_by_approval_id(
        decided_by="policy-startup-approval-id-reconcile",
    )
    older_persisted = store.get(older.envelope_id)
    newer_persisted = store.get(newer.envelope_id)

    assert [record.envelope_id for record in updated] == [older.envelope_id]
    assert older_persisted is not None
    assert older_persisted.status == "superseded"
    assert older_persisted.decided_by == "policy-startup-approval-id-reconcile"
    assert any(
        note.startswith("approval_superseded_by_duplicate_approval_id ")
        for note in older_persisted.operator_notes
    )
    assert newer_persisted is not None
    assert newer_persisted.status == "pending"


def test_canonical_approval_store_supersedes_only_older_pending_records(
    tmp_path: Path,
) -> None:
    from watchdog.services.approvals.service import (
        CanonicalApprovalStore,
        materialize_canonical_approval,
    )

    store = CanonicalApprovalStore(tmp_path / "canonical_approvals.json")
    older = materialize_canonical_approval(
        _decision(),
        approval_store=store,
    )
    newer = materialize_canonical_approval(
        _decision(
            action_ref="continue_session",
            approval_id="appr_002",
        ).model_copy(
            update={
                "decision_id": "decision:needs-human-v9",
                "decision_key": (
                    "session:repo-a|fact-v9|policy-v1|require_user_decision|"
                    "continue_session|appr_002"
                ),
                "fact_snapshot_version": "fact-v9",
                "idempotency_key": (
                    "session:repo-a|fact-v9|policy-v1|require_user_decision|"
                    "continue_session|appr_002"
                ),
                "created_at": "2026-04-07T00:05:00Z",
                "evidence": {
                    "decision": {
                        "action_ref": "continue_session",
                        "decision_result": "require_user_decision",
                    }
                },
            }
        ),
        approval_store=store,
    )

    updated = store.supersede_pending_records(
        session_id="session:repo-a",
        project_id="repo-a",
        fact_snapshot_version="fact-v8",
        reason="approval_superseded_by_decision decision:resume result=auto_execute_and_notify",
    )
    older_persisted = store.get(older.envelope_id)
    newer_persisted = store.get(newer.envelope_id)

    assert [record.envelope_id for record in updated] == [older.envelope_id]
    assert older_persisted is not None
    assert older_persisted.status == "superseded"
    assert older_persisted.decided_by == "policy-supersede"
    assert any(
        "approval_superseded_by_decision decision:resume result=auto_execute_and_notify"
        in note
        for note in older_persisted.operator_notes
    )
    assert newer_persisted is not None
    assert newer_persisted.status == "pending"


def test_canonical_approval_store_reconciles_pending_records_against_later_non_user_decisions(
    tmp_path: Path,
) -> None:
    from watchdog.services.approvals.service import (
        CanonicalApprovalStore,
        materialize_canonical_approval,
    )

    store = CanonicalApprovalStore(tmp_path / "canonical_approvals.json")
    approval = materialize_canonical_approval(
        _decision(),
        approval_store=store,
    )
    later_auto_decision = _decision(
        action_ref="continue_session",
        decision_result="auto_execute_and_notify",
    ).model_copy(
        update={
            "decision_id": "decision:auto-v9",
            "decision_key": (
                "session:repo-a|fact-v9|policy-v1|auto_execute_and_notify|"
                "continue_session|"
            ),
            "risk_class": "none",
            "decision_reason": "registered action and complete evidence",
            "matched_policy_rules": ["registered_action"],
            "why_not_escalated": "policy_allows_auto_execution",
            "why_escalated": None,
            "fact_snapshot_version": "fact-v9",
            "idempotency_key": (
                "session:repo-a|fact-v9|policy-v1|auto_execute_and_notify|"
                "continue_session|"
            ),
            "created_at": "2026-04-07T00:05:00Z",
            "evidence": {
                "decision": {
                    "action_ref": "continue_session",
                    "decision_result": "auto_execute_and_notify",
                    "approval_id": None,
                }
            },
        }
    )

    updated = store.reconcile_pending_records_against_decisions(
        [later_auto_decision],
        decided_by="policy-startup-reconcile",
    )
    persisted = store.get(approval.envelope_id)

    assert [record.envelope_id for record in updated] == [approval.envelope_id]
    assert persisted is not None
    assert persisted.status == "superseded"
    assert persisted.decided_by == "policy-startup-reconcile"
    assert any(
        "approval_superseded_by_historical_decision decision_id=decision:auto-v9"
        in note
        for note in persisted.operator_notes
    )


def test_canonical_approval_store_reconciles_repeated_pending_records_by_action_signature(
    tmp_path: Path,
) -> None:
    from watchdog.services.approvals.service import (
        CanonicalApprovalStore,
        materialize_canonical_approval,
    )

    store = CanonicalApprovalStore(tmp_path / "canonical_approvals.json")
    older = materialize_canonical_approval(
        _decision(),
        approval_store=store,
    )
    newer = materialize_canonical_approval(
        _decision(approval_id="appr_002").model_copy(
            update={
                "decision_id": "decision:needs-human-v8",
                "decision_key": (
                    "session:repo-a|fact-v8|policy-v1|require_user_decision|"
                    "execute_recovery|appr_002"
                ),
                "fact_snapshot_version": "fact-v8",
                "idempotency_key": (
                    "session:repo-a|fact-v8|policy-v1|require_user_decision|"
                    "execute_recovery|appr_002"
                ),
                "created_at": "2026-04-07T00:05:00Z",
            }
        ),
        approval_store=store,
    )

    updated = store.reconcile_duplicate_pending_records_by_action_signature(
        decided_by="policy-startup-action-signature-reconcile",
    )
    older_persisted = store.get(older.envelope_id)
    newer_persisted = store.get(newer.envelope_id)

    assert [record.envelope_id for record in updated] == [older.envelope_id]
    assert older_persisted is not None
    assert older_persisted.status == "superseded"
    assert older_persisted.decided_by == "policy-startup-action-signature-reconcile"
    assert any(
        note.startswith("approval_superseded_by_duplicate_action_signature ")
        for note in older_persisted.operator_notes
    )
    assert newer_persisted is not None
    assert newer_persisted.status == "pending"


def test_canonical_approval_store_keeps_distinct_pending_records_when_action_signature_changes(
    tmp_path: Path,
) -> None:
    from watchdog.services.approvals.service import (
        CanonicalApprovalStore,
        materialize_canonical_approval,
    )

    store = CanonicalApprovalStore(tmp_path / "canonical_approvals.json")
    older = materialize_canonical_approval(
        _decision(),
        approval_store=store,
    )
    newer = materialize_canonical_approval(
        _decision(approval_id="appr_002").model_copy(
            update={
                "decision_id": "decision:needs-human-v8",
                "decision_key": (
                    "session:repo-a|fact-v8|policy-v1|require_user_decision|"
                    "execute_recovery|appr_002"
                ),
                "fact_snapshot_version": "fact-v8",
                "idempotency_key": (
                    "session:repo-a|fact-v8|policy-v1|require_user_decision|"
                    "execute_recovery|appr_002"
                ),
                "created_at": "2026-04-07T00:05:00Z",
                "evidence": {
                    **_decision().evidence,
                    "requested_action_args": {"mode": "force"},
                },
            }
        ),
        approval_store=store,
    )

    updated = store.reconcile_duplicate_pending_records_by_action_signature(
        decided_by="policy-startup-action-signature-reconcile",
    )
    older_persisted = store.get(older.envelope_id)
    newer_persisted = store.get(newer.envelope_id)

    assert updated == []
    assert older_persisted is not None
    assert older_persisted.status == "pending"
    assert newer_persisted is not None
    assert newer_persisted.status == "pending"


def test_superseded_canonical_approval_cannot_be_responded_to(tmp_path: Path) -> None:
    from watchdog.services.approvals.service import (
        ApprovalResponseStore,
        CanonicalApprovalStore,
        materialize_canonical_approval,
        respond_to_canonical_approval,
    )

    client = FakeAClient(context_pressure="critical")
    approval_store = CanonicalApprovalStore(tmp_path / "canonical_approvals.json")
    response_store = ApprovalResponseStore(tmp_path / "approval_responses.json")
    approval = materialize_canonical_approval(
        _decision(),
        approval_store=approval_store,
    )
    approval_store.supersede_pending_records(
        session_id=approval.session_id,
        project_id=approval.project_id,
        fact_snapshot_version=approval.fact_snapshot_version,
        reason="approval_superseded_by_decision decision:resume result=auto_execute_and_notify",
    )

    with pytest.raises(
        ValueError,
        match="superseded approval cannot be approved, rejected, or executed",
    ):
        respond_to_canonical_approval(
            envelope_id=approval.envelope_id,
            response_action="approve",
            client_request_id="req-superseded",
            operator="alice",
            note="too late",
            approval_store=approval_store,
            response_store=response_store,
            settings=_settings(tmp_path),
            client=client,
            receipt_store=ActionReceiptStore(tmp_path / "action_receipts.json"),
        )

    assert client.decision_calls == []


def test_approve_response_is_idempotent_and_executes_requested_action_once(
    tmp_path: Path,
) -> None:
    from watchdog.services.approvals.service import (
        ApprovalResponseStore,
        CanonicalApprovalStore,
        materialize_canonical_approval,
        respond_to_canonical_approval,
    )
    from watchdog.services.delivery.store import DeliveryOutboxStore

    client = FakeAClient(context_pressure="critical")
    approval_store = CanonicalApprovalStore(tmp_path / "canonical_approvals.json")
    response_store = ApprovalResponseStore(tmp_path / "approval_responses.json")
    receipt_store = ActionReceiptStore(tmp_path / "action_receipts.json")
    delivery_store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    approval = materialize_canonical_approval(
        _decision(),
        approval_store=approval_store,
        delivery_outbox_store=delivery_store,
    )

    first = respond_to_canonical_approval(
        envelope_id=approval.envelope_id,
        response_action="approve",
        client_request_id="req-001",
        operator="alice",
        note="looks safe",
        approval_store=approval_store,
        response_store=response_store,
        settings=_settings(tmp_path),
        client=client,
        receipt_store=receipt_store,
        delivery_outbox_store=delivery_store,
    )
    second = respond_to_canonical_approval(
        envelope_id=approval.envelope_id,
        response_action="approve",
        client_request_id="req-001",
        operator="alice",
        note="looks safe",
        approval_store=approval_store,
        response_store=response_store,
        settings=_settings(tmp_path),
        client=client,
        receipt_store=receipt_store,
        delivery_outbox_store=delivery_store,
    )

    assert client.decision_calls == [("appr_001", "approve", "alice", "looks safe")]
    assert client.handoff_calls == [("repo-a", "context_critical")]
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.approval_status == "approved"
    assert first.execution_result is not None
    assert first.execution_result.effect == "handoff_triggered"
    pending = delivery_store.list_pending_delivery_records(session_id=approval.session_id)
    assert [record.envelope_type for record in pending] == ["approval", "notification"]
    assert pending[1].envelope_payload["notification_kind"] == "approval_result"


def test_reject_response_records_rejection_without_executing_requested_action(
    tmp_path: Path,
) -> None:
    from watchdog.services.approvals.service import (
        ApprovalResponseStore,
        CanonicalApprovalStore,
        materialize_canonical_approval,
        respond_to_canonical_approval,
    )
    from watchdog.services.delivery.store import DeliveryOutboxStore

    client = FakeAClient(context_pressure="critical")
    approval_store = CanonicalApprovalStore(tmp_path / "canonical_approvals.json")
    response_store = ApprovalResponseStore(tmp_path / "approval_responses.json")
    delivery_store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    approval = materialize_canonical_approval(
        _decision(),
        approval_store=approval_store,
        delivery_outbox_store=delivery_store,
    )

    result = respond_to_canonical_approval(
        envelope_id=approval.envelope_id,
        response_action="reject",
        client_request_id="req-002",
        operator="bob",
        note="needs more evidence",
        approval_store=approval_store,
        response_store=response_store,
        settings=_settings(tmp_path),
        client=client,
        receipt_store=ActionReceiptStore(tmp_path / "action_receipts.json"),
        delivery_outbox_store=delivery_store,
    )

    assert client.decision_calls == [("appr_001", "reject", "bob", "needs more evidence")]
    assert client.handoff_calls == []
    assert result.approval_status == "rejected"
    assert result.execution_result is None
    pending = delivery_store.list_pending_delivery_records(session_id=approval.session_id)
    assert [record.envelope_type for record in pending] == ["approval", "notification"]
    assert pending[1].envelope_payload["severity"] == "critical"


def test_materialize_canonical_approval_records_session_event(tmp_path: Path) -> None:
    from watchdog.services.approvals.service import (
        CanonicalApprovalStore,
        materialize_canonical_approval,
    )
    from watchdog.services.session_service.service import SessionService
    from watchdog.services.session_service.store import SessionServiceStore

    approval_store = CanonicalApprovalStore(tmp_path / "canonical_approvals.json")
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))

    approval = materialize_canonical_approval(
        _decision(),
        approval_store=approval_store,
        session_service=session_service,
    )

    events = session_service.list_events(
        session_id=approval.session_id,
        event_type="approval_requested",
    )

    assert len(events) == 1
    assert events[0].correlation_id == f"corr:approval:{approval.approval_id}"
    assert events[0].related_ids == {
        "approval_id": approval.approval_id,
        "decision_id": approval.decision.decision_id,
    }
    assert events[0].payload["requested_action"] == "execute_recovery"


def test_materialize_canonical_approval_reuses_existing_session_event_on_identical_replay(
    tmp_path: Path,
) -> None:
    from watchdog.services.approvals.service import (
        CanonicalApprovalStore,
        materialize_canonical_approval,
    )
    from watchdog.services.session_service.service import SessionService
    from watchdog.services.session_service.store import SessionServiceStore

    approval_store = CanonicalApprovalStore(tmp_path / "canonical_approvals.json")
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))

    first = materialize_canonical_approval(
        _decision(),
        approval_store=approval_store,
        session_service=session_service,
    )
    second = materialize_canonical_approval(
        _decision(),
        approval_store=approval_store,
        session_service=session_service,
    )
    events = session_service.list_events(
        session_id=first.session_id,
        event_type="approval_requested",
    )

    assert second.approval_id == first.approval_id
    assert second.envelope_id == first.envelope_id
    assert len(events) == 1
    assert events[0].related_ids == {
        "approval_id": first.approval_id,
        "decision_id": first.decision.decision_id,
    }
    assert events[0].payload["fact_snapshot_version"] == "fact-v7"


def test_materialize_canonical_approval_raises_on_legacy_session_event_drift_for_same_approval_id(
    tmp_path: Path,
) -> None:
    from watchdog.services.approvals.service import (
        CanonicalApprovalStore,
        build_canonical_approval_record,
        materialize_canonical_approval,
    )
    from watchdog.services.session_service.service import SessionService
    from watchdog.services.session_service.store import SessionServiceStore

    approval_store = CanonicalApprovalStore(tmp_path / "canonical_approvals.json")
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))

    legacy_record = build_canonical_approval_record(_decision()).model_copy(
        update={
            "envelope_id": "approval-envelope:legacy",
            "approval_token": "approval-token:legacy",
        }
    )
    approval_store.put(legacy_record)
    session_service.record_event(
        event_type="approval_requested",
        project_id=legacy_record.project_id,
        session_id=legacy_record.session_id,
        correlation_id=f"corr:approval:{legacy_record.approval_id}",
        causation_id=legacy_record.decision.decision_id,
        related_ids={
            "approval_id": legacy_record.approval_id,
            "decision_id": legacy_record.decision.decision_id,
        },
        payload={
            "requested_action": legacy_record.requested_action,
            "decision_options": list(legacy_record.decision_options),
            "fact_snapshot_version": legacy_record.fact_snapshot_version,
            "policy_version": legacy_record.policy_version,
        },
    )

    with pytest.raises(ValueError, match="conflicting session event for idempotency key"):
        materialize_canonical_approval(
            _decision().model_copy(
                update={
                    "decision_id": "decision:needs-human-v8",
                    "decision_key": (
                        "session:repo-a|fact-v8|policy-v1|require_user_decision|"
                        "execute_recovery|appr_001"
                    ),
                    "fact_snapshot_version": "fact-v8",
                    "idempotency_key": (
                        "session:repo-a|fact-v8|policy-v1|require_user_decision|"
                        "execute_recovery|appr_001"
                    ),
                    "created_at": "2026-04-07T00:05:00Z",
                    "evidence": {
                        **_decision().evidence,
                        "requested_action_args": {"mode": "safe"},
                        "goal_contract_version": "goal-v2",
                    },
                }
            ),
            approval_store=approval_store,
            session_service=session_service,
        )

    events = session_service.list_events(
        session_id=legacy_record.session_id,
        event_type="approval_requested",
    )
    assert len(events) == 1
    assert events[0].related_ids == {
        "approval_id": legacy_record.approval_id,
        "decision_id": legacy_record.decision.decision_id,
    }
    assert events[0].payload == {
        "requested_action": legacy_record.requested_action,
        "decision_options": list(legacy_record.decision_options),
        "fact_snapshot_version": legacy_record.fact_snapshot_version,
        "policy_version": legacy_record.policy_version,
    }


def test_materialize_canonical_approval_raises_on_session_event_drift(
    tmp_path: Path,
) -> None:
    from watchdog.services.approvals.service import (
        CanonicalApprovalStore,
        materialize_canonical_approval,
    )
    from watchdog.services.session_service.service import SessionService
    from watchdog.services.session_service.store import SessionServiceStore

    approval_store = CanonicalApprovalStore(tmp_path / "canonical_approvals.json")
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))

    initial_decision = _decision().model_copy(
        update={
            "evidence": {
                **_decision().evidence,
                "requested_action_args": {"mode": "safe"},
                "goal_contract_version": "goal-v1",
            }
        }
    )
    approval = materialize_canonical_approval(
        initial_decision,
        approval_store=approval_store,
        session_service=session_service,
    )
    refreshed_decision = initial_decision.model_copy(
        update={
            "evidence": {
                **initial_decision.evidence,
                "requested_action_args": {"mode": "force"},
                "goal_contract_version": "goal-v2",
            },
        }
    )

    with pytest.raises(ValueError, match="conflicting session event for idempotency key"):
        materialize_canonical_approval(
            refreshed_decision,
            approval_store=approval_store,
            session_service=session_service,
        )

    events = session_service.list_events(
        session_id=approval.session_id,
        event_type="approval_requested",
    )
    assert len(events) == 1
    assert events[0].related_ids["decision_id"] == approval.decision.decision_id
    assert events[0].payload["fact_snapshot_version"] == "fact-v7"
    assert events[0].payload["requested_action_args"] == {"mode": "safe"}
    assert events[0].payload["goal_contract_version"] == "goal-v1"


def test_materialize_canonical_approval_raises_when_fact_snapshot_advances_with_session_event_drift(
    tmp_path: Path,
) -> None:
    from watchdog.services.approvals.service import (
        CanonicalApprovalStore,
        materialize_canonical_approval,
    )
    from watchdog.services.session_service.service import SessionService
    from watchdog.services.session_service.store import SessionServiceStore

    approval_store = CanonicalApprovalStore(tmp_path / "canonical_approvals.json")
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))

    initial_decision = _decision().model_copy(
        update={
            "evidence": {
                **_decision().evidence,
                "requested_action_args": {"mode": "safe"},
                "goal_contract_version": "goal-v1",
            }
        }
    )
    initial = materialize_canonical_approval(
        initial_decision,
        approval_store=approval_store,
        session_service=session_service,
    )
    with pytest.raises(ValueError, match="conflicting session event for idempotency key"):
        materialize_canonical_approval(
            initial_decision.model_copy(
                update={
                    "decision_id": "decision:needs-human-v8",
                    "decision_key": (
                        "session:repo-a|fact-v8|policy-v1|require_user_decision|"
                        "execute_recovery|appr_001"
                    ),
                    "fact_snapshot_version": "fact-v8",
                    "idempotency_key": (
                        "session:repo-a|fact-v8|policy-v1|require_user_decision|"
                        "execute_recovery|appr_001"
                    ),
                    "created_at": "2026-04-07T00:05:00Z",
                    "evidence": {
                        **initial_decision.evidence,
                        "requested_action_args": {"mode": "force"},
                        "goal_contract_version": "goal-v2",
                    },
                }
            ),
            approval_store=approval_store,
            session_service=session_service,
        )

    events = session_service.list_events(
        session_id=initial.session_id,
        event_type="approval_requested",
    )

    assert len(events) == 1
    assert events[0].related_ids == {
        "approval_id": initial.approval_id,
        "decision_id": initial.decision.decision_id,
    }
    assert events[0].payload["fact_snapshot_version"] == "fact-v7"
    assert events[0].payload["requested_action_args"] == {"mode": "safe"}
    assert events[0].payload["goal_contract_version"] == "goal-v1"


def test_materialize_canonical_approval_reuses_existing_session_event_when_fact_snapshot_advances_without_truth_drift(
    tmp_path: Path,
) -> None:
    from watchdog.services.approvals.service import (
        CanonicalApprovalStore,
        materialize_canonical_approval,
    )
    from watchdog.services.session_service.service import SessionService
    from watchdog.services.session_service.store import SessionServiceStore

    approval_store = CanonicalApprovalStore(tmp_path / "canonical_approvals.json")
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))

    initial = materialize_canonical_approval(
        _decision(),
        approval_store=approval_store,
        session_service=session_service,
    )
    replayed = materialize_canonical_approval(
        _decision().model_copy(
            update={
                "decision_id": "decision:needs-human-v8",
                "decision_key": (
                    "session:repo-a|fact-v8|policy-v1|require_user_decision|"
                    "execute_recovery|appr_001"
                ),
                "fact_snapshot_version": "fact-v8",
                "idempotency_key": (
                    "session:repo-a|fact-v8|policy-v1|require_user_decision|"
                    "execute_recovery|appr_001"
                ),
                "created_at": "2026-04-07T00:05:00Z",
            }
        ),
        approval_store=approval_store,
        session_service=session_service,
    )

    events = session_service.list_events(
        session_id=initial.session_id,
        event_type="approval_requested",
    )

    assert len(events) == 1
    assert events[0].related_ids == {
        "approval_id": initial.approval_id,
        "decision_id": initial.decision.decision_id,
    }
    assert events[0].payload["fact_snapshot_version"] == "fact-v7"
    assert replayed.approval_id == initial.approval_id
    assert replayed.fact_snapshot_version == "fact-v8"


def test_materialize_canonical_approval_rejects_legacy_subset_reuse_when_same_decision_gains_truth_fields(
    tmp_path: Path,
) -> None:
    from watchdog.services.approvals.service import (
        CanonicalApprovalStore,
        materialize_canonical_approval,
    )
    from watchdog.services.session_service.service import SessionService
    from watchdog.services.session_service.store import SessionServiceStore

    approval_store = CanonicalApprovalStore(tmp_path / "canonical_approvals.json")
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))

    approval = materialize_canonical_approval(
        _decision(),
        approval_store=approval_store,
        session_service=session_service,
    )
    session_store = session_service._store
    with session_store._guard_io():
        data = session_store._read()
        data.events = [
            event.model_copy(
                update={
                    "payload": {
                        "requested_action": "execute_recovery",
                        "decision_options": ["approve", "reject", "execute_action"],
                        "fact_snapshot_version": "fact-v7",
                        "policy_version": "policy-v1",
                    }
                }
            )
            if event.event_type == "approval_requested"
            else event
            for event in data.events
        ]
        session_store._write(data)

    with pytest.raises(ValueError, match="conflicting session event for idempotency key"):
        materialize_canonical_approval(
            _decision().model_copy(
                update={
                    "evidence": {
                        **_decision().evidence,
                        "requested_action_args": {"mode": "safe"},
                        "goal_contract_version": "goal-v1",
                    }
                }
            ),
            approval_store=approval_store,
            session_service=session_service,
        )

    events = session_service.list_events(
        session_id=approval.session_id,
        event_type="approval_requested",
    )
    assert len(events) == 1
    assert "requested_action_args" not in events[0].payload
    assert "goal_contract_version" not in events[0].payload


def test_materialize_canonical_approval_rejects_hidden_drift_across_multiple_approval_requested_events(
    tmp_path: Path,
) -> None:
    from watchdog.services.approvals.service import (
        CanonicalApprovalStore,
        materialize_canonical_approval,
    )
    from watchdog.services.session_service.models import SessionEventRecord
    from watchdog.services.session_service.service import SessionService
    from watchdog.services.session_service.store import SessionServiceStore

    approval_store = CanonicalApprovalStore(tmp_path / "canonical_approvals.json")
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))

    materialize_canonical_approval(
        _decision(),
        approval_store=approval_store,
        session_service=session_service,
    )
    session_store = session_service._store
    with session_store._guard_io():
        data = session_store._read()
        original = next(event for event in data.events if event.event_type == "approval_requested")
        data.events.append(
            SessionEventRecord(
                event_id="event:manual-legacy-drift",
                project_id=original.project_id,
                session_id=original.session_id,
                event_type=original.event_type,
                occurred_at="2026-04-07T00:06:00Z",
                causation_id="decision:manual-legacy-drift",
                correlation_id=original.correlation_id,
                idempotency_key="idem:event:event:manual-legacy-drift",
                related_ids=dict(original.related_ids),
                payload={
                    **original.payload,
                    "requested_action_args": {"mode": "force"},
                    "goal_contract_version": "goal-v2",
                },
                log_seq=(original.log_seq or 0) + 1,
            )
        )
        data.next_log_seq += 1
        session_store._write(data)

    with pytest.raises(ValueError, match="conflicting session event for idempotency key"):
        materialize_canonical_approval(
            _decision(),
            approval_store=approval_store,
            session_service=session_service,
        )


def test_materialize_canonical_approval_reuses_existing_session_event_when_decision_id_changes(
    tmp_path: Path,
) -> None:
    from watchdog.services.approvals.service import (
        CanonicalApprovalStore,
        materialize_canonical_approval,
    )
    from watchdog.services.session_service.service import SessionService
    from watchdog.services.session_service.store import SessionServiceStore

    approval_store = CanonicalApprovalStore(tmp_path / "canonical_approvals.json")
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))

    initial = materialize_canonical_approval(
        _decision(),
        approval_store=approval_store,
        session_service=session_service,
    )
    replayed = materialize_canonical_approval(
        _decision().model_copy(
            update={
                "decision_id": "decision:needs-human-replayed",
                "decision_key": (
                    "session:repo-a|fact-v7|policy-v1|require_user_decision|"
                    "execute_recovery|appr_001|replayed"
                ),
                "idempotency_key": (
                    "session:repo-a|fact-v7|policy-v1|require_user_decision|"
                    "execute_recovery|appr_001|replayed"
                ),
                "created_at": "2026-04-07T00:06:00Z",
            }
        ),
        approval_store=approval_store,
        session_service=session_service,
    )

    events = session_service.list_events(
        session_id=initial.session_id,
        event_type="approval_requested",
    )

    assert len(events) == 1
    assert events[0].related_ids == {
        "approval_id": initial.approval_id,
        "decision_id": initial.decision.decision_id,
    }
    assert replayed.approval_id == initial.approval_id
    assert replayed.decision.decision_id == "decision:needs-human-replayed"


def test_expire_pending_canonical_approval_records_session_event_before_closing_record(
    tmp_path: Path,
) -> None:
    from watchdog.services.approvals.service import (
        CanonicalApprovalStore,
        expire_pending_canonical_approvals,
        materialize_canonical_approval,
    )
    from watchdog.services.session_service.service import SessionService
    from watchdog.services.session_service.store import SessionServiceStore

    approval_store = CanonicalApprovalStore(tmp_path / "canonical_approvals.json")
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    approval = materialize_canonical_approval(
        _decision(),
        approval_store=approval_store,
    )
    approval_store.update(
        approval.model_copy(
            update={
                "created_at": "2026-04-07T00:00:00Z",
            }
        )
    )

    original_update = approval_store.update
    observed_event_counts: list[int] = []

    def _checking_update(record):
        events = session_service.list_events(
            session_id=approval.session_id,
            event_type="approval_expired",
        )
        observed_event_counts.append(len(events))
        assert len(events) == 1
        return original_update(record)

    approval_store.update = _checking_update

    expired = expire_pending_canonical_approvals(
        approval_store=approval_store,
        session_service=session_service,
        now=datetime(2026, 4, 7, 0, 2, 0, tzinfo=UTC),
        expiration_seconds=60.0,
    )

    refreshed = approval_store.get(approval.envelope_id)
    events = session_service.list_events(
        session_id=approval.session_id,
        event_type="approval_expired",
    )

    assert len(expired) == 1
    assert refreshed is not None
    assert refreshed.status == "expired"
    assert refreshed.decided_by == "approval-timeout-reconcile"
    assert observed_event_counts == [1]
    assert len(events) == 1
    assert events[0].related_ids == {
        "approval_id": approval.approval_id,
        "decision_id": approval.decision.decision_id,
        "envelope_id": approval.envelope_id,
    }
    assert events[0].payload == {
        "approval_status": "expired",
        "requested_action": approval.requested_action,
        "expiration_reason": "timeout_elapsed",
    }


def test_startup_reconcile_expires_stale_pending_approvals(tmp_path: Path) -> None:
    from watchdog.main import _reconcile_stale_pending_approvals
    from watchdog.services.approvals.service import (
        materialize_canonical_approval,
        respond_to_canonical_approval,
    )

    settings = _settings(tmp_path).model_copy(update={"approval_expiration_seconds": 60.0})
    client = FakeAClient(context_pressure="critical")
    app = create_app(settings=settings, a_client=client)
    approval = materialize_canonical_approval(
        _decision(),
        approval_store=app.state.canonical_approval_store,
        delivery_outbox_store=app.state.delivery_outbox_store,
    )
    app.state.canonical_approval_store.update(
        approval.model_copy(update={"created_at": "2026-04-07T00:00:00Z"})
    )

    reconciled = _reconcile_stale_pending_approvals(app)
    refreshed = app.state.canonical_approval_store.get(approval.envelope_id)
    delivery_record = app.state.delivery_outbox_store.get_delivery_record(approval.envelope_id)
    events = app.state.session_service.list_events(
        session_id=approval.session_id,
        event_type="approval_expired",
    )

    assert reconciled == 1
    assert refreshed is not None
    assert refreshed.status == "expired"
    assert delivery_record is not None
    assert delivery_record.delivery_status == "superseded"
    assert any(
        note.startswith("delivery_superseded reason=approval_expired_by_timeout")
        for note in delivery_record.operator_notes
    )
    assert len(events) == 1
    assert events[0].related_ids["approval_id"] == approval.approval_id

    with pytest.raises(
        ValueError,
        match="expired approval cannot be approved, rejected, or executed",
    ):
        respond_to_canonical_approval(
            envelope_id=approval.envelope_id,
            response_action="approve",
            client_request_id="req-expired",
            operator="alice",
            note="too late",
            approval_store=app.state.canonical_approval_store,
            response_store=app.state.approval_response_store,
            settings=settings,
            client=client,
            receipt_store=ActionReceiptStore(tmp_path / "action_receipts.json"),
        )


@pytest.mark.parametrize(
    ("response_action", "expected_event_type", "expected_status"),
    [
        ("approve", "approval_approved", "approved"),
        ("reject", "approval_rejected", "rejected"),
    ],
)
def test_respond_to_canonical_approval_records_session_event(
    tmp_path: Path,
    response_action: str,
    expected_event_type: str,
    expected_status: str,
) -> None:
    from watchdog.services.approvals.service import (
        ApprovalResponseStore,
        CanonicalApprovalStore,
        materialize_canonical_approval,
        respond_to_canonical_approval,
    )
    from watchdog.services.session_service.service import SessionService
    from watchdog.services.session_service.store import SessionServiceStore

    client = FakeAClient(context_pressure="critical")
    approval_store = CanonicalApprovalStore(tmp_path / "canonical_approvals.json")
    response_store = ApprovalResponseStore(tmp_path / "approval_responses.json")
    receipt_store = ActionReceiptStore(tmp_path / "action_receipts.json")
    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    approval = materialize_canonical_approval(
        _decision(),
        approval_store=approval_store,
        session_service=session_service,
    )

    result = respond_to_canonical_approval(
        envelope_id=approval.envelope_id,
        response_action=response_action,
        client_request_id=f"req-{response_action}",
        operator="alice",
        note="looks safe",
        approval_store=approval_store,
        response_store=response_store,
        settings=_settings(tmp_path),
        client=client,
        receipt_store=receipt_store,
        session_service=session_service,
    )

    events = session_service.list_events(
        session_id=approval.session_id,
        event_type=expected_event_type,
    )
    override_events = session_service.list_events(
        session_id=approval.session_id,
        event_type="human_override_recorded",
    )

    assert result.approval_status == expected_status
    assert len(events) == 1
    assert len(override_events) == 1
    assert events[0].correlation_id == f"corr:approval:{approval.approval_id}"
    assert events[0].related_ids == {
        "approval_id": approval.approval_id,
        "decision_id": approval.decision.decision_id,
        "response_id": result.response_id,
    }
    assert events[0].payload["response_action"] == response_action
    assert override_events[0].related_ids == {
        "approval_id": approval.approval_id,
        "decision_id": approval.decision.decision_id,
        "response_id": result.response_id,
        "envelope_id": approval.envelope_id,
    }
    assert override_events[0].payload["response_action"] == response_action
    assert override_events[0].payload["approval_status"] == expected_status
    assert override_events[0].payload["operator"] == "alice"
    assert override_events[0].payload["note"] == "looks safe"
    assert override_events[0].payload["requested_action"] == approval.requested_action
    if response_action == "approve":
        assert override_events[0].payload["execution_status"] == "completed"
        assert override_events[0].payload["execution_effect"] == "handoff_triggered"


def test_openclaw_response_api_uses_response_tuple_as_idempotency_key(tmp_path: Path) -> None:
    from watchdog.services.approvals.service import materialize_canonical_approval

    settings = _settings(tmp_path)
    app = create_app(settings=settings, a_client=FakeAClient(context_pressure="critical"))
    approval = materialize_canonical_approval(
        _decision(),
        approval_store=app.state.canonical_approval_store,
    )

    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {settings.api_token}"}
        body = {
            "envelope_id": approval.envelope_id,
            "envelope_type": "approval",
            "approval_id": approval.approval_id,
            "decision_id": approval.decision.decision_id,
            "response_action": "approve",
            "response_token": approval.approval_token,
            "user_ref": "user:carol",
            "channel_ref": "feishu:chat:approval-room",
            "client_request_id": "req-003",
            "operator": "carol",
            "note": "ship it",
        }

        first = client.post("/api/v1/watchdog/openclaw/responses", json=body, headers=headers)
        second = client.post("/api/v1/watchdog/openclaw/responses", json=body, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["success"] is True
    assert first.json()["data"] == second.json()["data"]
    override_events = app.state.session_service.list_events(
        session_id=approval.session_id,
        event_type="human_override_recorded",
    )
    assert len(override_events) == 1
    assert override_events[0].payload["response_action"] == "approve"
    assert override_events[0].payload["operator"] == "carol"


def test_concurrent_approval_responses_execute_side_effects_once(tmp_path: Path) -> None:
    from watchdog.services.approvals.service import (
        ApprovalResponseStore,
        CanonicalApprovalStore,
        materialize_canonical_approval,
        respond_to_canonical_approval,
    )
    from watchdog.services.delivery.store import DeliveryOutboxStore

    client = FakeAClient(context_pressure="critical")
    approval_store = CanonicalApprovalStore(tmp_path / "canonical_approvals.json")
    response_store = ApprovalResponseStore(tmp_path / "approval_responses.json")
    receipt_store = ActionReceiptStore(tmp_path / "action_receipts.json")
    delivery_store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    approval = materialize_canonical_approval(
        _decision(),
        approval_store=approval_store,
        delivery_outbox_store=delivery_store,
    )

    barrier = threading.Barrier(3)
    results: list[object] = []

    def _worker() -> None:
        barrier.wait()
        results.append(
            respond_to_canonical_approval(
                envelope_id=approval.envelope_id,
                response_action="approve",
                client_request_id="req-concurrent",
                operator="alice",
                note="looks safe",
                approval_store=approval_store,
                response_store=response_store,
                settings=_settings(tmp_path),
                client=client,
                receipt_store=receipt_store,
                delivery_outbox_store=delivery_store,
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
    assert client.decision_calls == [("appr_001", "approve", "alice", "looks safe")]
    assert client.handoff_calls == [("repo-a", "context_critical")]
    pending = delivery_store.list_pending_delivery_records(session_id=approval.session_id)
    assert [record.envelope_type for record in pending] == ["approval", "notification"]


def test_canonical_approval_store_reuses_cached_snapshot_until_file_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from watchdog.services.approvals.service import (
        CanonicalApprovalStore,
        materialize_canonical_approval,
    )
    from watchdog.services.delivery.store import DeliveryOutboxStore

    store_path = tmp_path / "canonical_approvals.json"
    approval_store = CanonicalApprovalStore(store_path)
    delivery_store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    approval = materialize_canonical_approval(
        _decision(),
        approval_store=approval_store,
        delivery_outbox_store=delivery_store,
    )

    original_read_text = Path.read_text
    read_calls = 0

    def counting_read_text(self: Path, *args, **kwargs):
        nonlocal read_calls
        if self == store_path:
            read_calls += 1
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)

    assert approval_store.list_records()[0].approval_id == approval.approval_id
    assert approval_store.list_records()[0].approval_id == approval.approval_id
    assert read_calls == 0

    store_path.write_text(original_read_text(store_path, encoding="utf-8") + "\n", encoding="utf-8")

    assert approval_store.list_records()[0].approval_id == approval.approval_id
    assert read_calls == 1
