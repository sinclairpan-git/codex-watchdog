from __future__ import annotations

from watchdog.contracts.session_spine.enums import (
    ActionCode,
    ActionStatus,
    AttentionState,
    Effect,
    ReplyCode,
    ReplyKind,
    SessionState,
)
from watchdog.contracts.session_spine.models import (
    FactRecord,
    ReplyModel,
    SessionProjection,
    TaskProgressView,
    WatchdogAction,
    WatchdogActionResult,
)
from watchdog.contracts.session_spine.versioning import (
    SESSION_SPINE_CONTRACT_VERSION,
    SESSION_SPINE_SCHEMA_VERSION,
)


def test_session_spine_version_constants_are_frozen() -> None:
    assert SESSION_SPINE_CONTRACT_VERSION == "watchdog-session-spine/v1alpha1"
    assert SESSION_SPINE_SCHEMA_VERSION == "2026-04-05.010"


def test_session_projection_distinguishes_stable_and_native_thread_ids() -> None:
    session = SessionProjection(
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="thr_native_1",
        session_state=SessionState.ACTIVE,
        activity_phase="executing",
        attention_state=AttentionState.NORMAL,
        headline="working",
        pending_approval_count=0,
        available_intents=["get_session", "continue_session"],
    )

    payload = session.model_dump(mode="json")

    assert payload["contract_version"] == SESSION_SPINE_CONTRACT_VERSION
    assert payload["schema_version"] == SESSION_SPINE_SCHEMA_VERSION
    assert payload["thread_id"] == "session:repo-a"
    assert payload["native_thread_id"] == "thr_native_1"
    assert payload["session_state"] == "active"


def test_reply_and_action_models_expose_stable_semantic_keys() -> None:
    fact = FactRecord(
        fact_id="fact_approval_pending",
        fact_code="approval_pending",
        fact_kind="blocker",
        severity="needs_human",
        summary="approval required",
        detail="waiting for approval",
        source="approval_store",
        observed_at="2026-04-05T05:22:00Z",
        related_ids={"approval_id": "appr_001"},
    )
    progress = TaskProgressView(
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="thr_native_1",
        activity_phase="executing",
        summary="editing files",
        files_touched=["src/example.py"],
        context_pressure="low",
        stuck_level=0,
        primary_fact_codes=["approval_pending"],
        blocker_fact_codes=["approval_pending"],
        last_progress_at="2026-04-05T05:20:00Z",
    )
    reply = ReplyModel(
        reply_kind=ReplyKind.EXPLANATION,
        reply_code=ReplyCode.STUCK_EXPLANATION,
        intent_code="why_stuck",
        message="waiting for approval",
        progress=progress,
        facts=[fact],
    )
    action = WatchdogAction(
        action_code=ActionCode.REQUEST_RECOVERY,
        project_id="repo-a",
        operator="openclaw",
        idempotency_key="idem-1",
        arguments={},
        note="check recovery availability",
    )
    result = WatchdogActionResult(
        action_code=action.action_code,
        project_id=action.project_id,
        approval_id=None,
        idempotency_key=action.idempotency_key,
        action_status=ActionStatus.COMPLETED,
        effect=Effect.ADVISORY_ONLY,
        reply_code=ReplyCode.RECOVERY_AVAILABILITY,
        message="recovery is available",
        facts=[fact],
    )

    reply_payload = reply.model_dump(mode="json")
    result_payload = result.model_dump(mode="json")

    assert reply_payload["reply_kind"] == "explanation"
    assert reply_payload["reply_code"] == "stuck_explanation"
    assert reply_payload["facts"][0]["fact_code"] == "approval_pending"
    assert result_payload["action_status"] == "completed"
    assert result_payload["effect"] == "advisory_only"
    assert result_payload["reply_code"] == "recovery_availability"
