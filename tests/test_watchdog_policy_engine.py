from __future__ import annotations

from watchdog.contracts.session_spine.models import (
    ApprovalProjection,
    FactRecord,
    SessionProjection,
    TaskProgressView,
)
from watchdog.services.policy.engine import evaluate_persisted_session_policy
from watchdog.services.session_spine.store import PersistedSessionRecord


def _fact(
    fact_code: str,
    *,
    fact_kind: str = "signal",
    severity: str = "info",
) -> FactRecord:
    return FactRecord(
        fact_id=f"fact-{fact_code}",
        fact_code=fact_code,
        fact_kind=fact_kind,
        severity=severity,
        summary=fact_code,
        detail=f"{fact_code} detail",
        source="watchdog",
        observed_at="2026-04-07T00:00:00Z",
    )


def _record(
    *,
    facts: list[FactRecord],
    approval_queue: list[ApprovalProjection] | None = None,
    fact_snapshot_version: str = "fact-v7",
) -> PersistedSessionRecord:
    return PersistedSessionRecord(
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="thr_native_1",
        session_seq=7,
        fact_snapshot_version=fact_snapshot_version,
        last_refreshed_at="2026-04-07T00:00:00Z",
        session=SessionProjection(
            project_id="repo-a",
            thread_id="session:repo-a",
            native_thread_id="thr_native_1",
            session_state="active",
            activity_phase="editing_source",
            attention_state="normal",
            headline="editing files",
            pending_approval_count=len(approval_queue or []),
            available_intents=["continue"],
        ),
        progress=TaskProgressView(
            project_id="repo-a",
            thread_id="session:repo-a",
            native_thread_id="thr_native_1",
            activity_phase="editing_source",
            summary="editing files",
            files_touched=["src/example.py"],
            context_pressure="low",
            stuck_level=0,
            primary_fact_codes=[fact.fact_code for fact in facts],
            blocker_fact_codes=[],
            last_progress_at="2026-04-07T00:00:00Z",
        ),
        facts=facts,
        approval_queue=approval_queue or [],
    )


def test_policy_engine_routes_human_gate_to_require_user_decision() -> None:
    record = _record(facts=[_fact("approval_pending"), _fact("awaiting_human_direction")])

    decision = evaluate_persisted_session_policy(
        record,
        action_ref="continue_session",
        trigger="resident_supervision",
    )

    assert decision.decision_result == "require_user_decision"
    assert decision.risk_class == "human_gate"
    assert "human_gate" in decision.matched_policy_rules
    assert decision.why_escalated


def test_policy_engine_routes_controlled_uncertainty_to_block_and_alert() -> None:
    record = _record(facts=[_fact("mapping_incomplete", fact_kind="availability", severity="warning")])

    decision = evaluate_persisted_session_policy(
        record,
        action_ref="continue_session",
        trigger="resident_supervision",
    )

    assert decision.decision_result == "block_and_alert"
    assert decision.risk_class == "hard_block"
    assert decision.uncertainty_reasons == ["mapping_incomplete"]
    assert "controlled_uncertainty" in decision.matched_policy_rules


def test_policy_engine_allows_registered_action_when_evidence_is_complete() -> None:
    record = _record(facts=[_fact("recovery_available", fact_kind="action")])

    decision = evaluate_persisted_session_policy(
        record,
        action_ref="execute_recovery",
        trigger="resident_supervision",
    )

    assert decision.decision_result == "auto_execute_and_notify"
    assert decision.risk_class == "none"
    assert decision.why_not_escalated == "policy_allows_auto_execution"
    assert "registered_action" in decision.matched_policy_rules
