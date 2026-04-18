from __future__ import annotations

from watchdog.contracts.session_spine.enums import (
    ActionCode,
    ActionStatus,
    AttentionState,
    Effect,
    EventCode,
    EventKind,
    ReplyCode,
    ReplyKind,
    SessionState,
    SupervisionReasonCode,
)
from watchdog.contracts.session_spine.models import (
    ActionReceiptQuery,
    FactRecord,
    ReplyModel,
    SessionEvent,
    SessionProjection,
    SupervisionEvaluation,
    TaskProgressView,
    WatchdogAction,
    WatchdogActionResult,
)
from watchdog.contracts.session_spine.versioning import (
    SESSION_EVENTS_SCHEMA_VERSION,
    SESSION_SPINE_CONTRACT_VERSION,
    SESSION_SPINE_SCHEMA_VERSION,
)
from watchdog.services.session_spine import replies as session_spine_replies
from watchdog.services.session_spine.service import SessionReadBundle


def test_session_spine_version_constants_are_frozen() -> None:
    assert SESSION_SPINE_CONTRACT_VERSION == "watchdog-session-spine/v1alpha1"
    assert SESSION_SPINE_SCHEMA_VERSION == "2026-04-05.022"
    assert SESSION_EVENTS_SCHEMA_VERSION == "2026-04-05.011"


def test_session_facts_contract_extension_is_stable() -> None:
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
    session = SessionProjection(
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="thr_native_1",
        session_state=SessionState.AWAITING_APPROVAL,
        activity_phase="approval",
        attention_state=AttentionState.NEEDS_HUMAN,
        headline="waiting for approval",
        pending_approval_count=1,
        available_intents=["list_session_facts", "explain_blocker"],
    )
    progress = TaskProgressView(
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="thr_native_1",
        activity_phase="approval",
        summary="waiting for approval",
        files_touched=["src/example.py"],
        context_pressure="low",
        stuck_level=0,
        primary_fact_codes=["approval_pending"],
        blocker_fact_codes=["approval_pending"],
        last_progress_at="2026-04-05T05:20:00Z",
    )
    assert hasattr(ReplyKind, "FACTS")
    assert hasattr(ReplyCode, "SESSION_FACTS")
    assert hasattr(session_spine_replies, "build_session_facts_reply")

    reply = session_spine_replies.build_session_facts_reply(
        SessionReadBundle(
            project_id="repo-a",
            task={"project_id": "repo-a", "thread_id": "thr_native_1"},
            approvals=[],
            facts=[fact],
            session=session,
            progress=progress,
            approval_queue=[],
        )
    )

    payload = reply.model_dump(mode="json")

    assert ReplyKind.FACTS == "facts"
    assert ReplyCode.SESSION_FACTS == "session_facts"
    assert payload["reply_kind"] == "facts"
    assert payload["reply_code"] == "session_facts"
    assert payload["intent_code"] == "list_session_facts"
    assert payload["message"] == "1 fact(s)"
    assert payload["facts"][0]["fact_code"] == "approval_pending"
    assert payload["facts"][0]["schema_version"] == SESSION_SPINE_SCHEMA_VERSION


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
        action_code=ActionCode.EXECUTE_RECOVERY,
        project_id="repo-a",
        operator="openclaw",
        idempotency_key="idem-1",
        arguments={},
        note="execute recovery",
    )
    result = WatchdogActionResult(
        action_code=action.action_code,
        project_id=action.project_id,
        approval_id=None,
        idempotency_key=action.idempotency_key,
        action_status=ActionStatus.COMPLETED,
        effect=Effect.HANDOFF_TRIGGERED,
        reply_code=ReplyCode.RECOVERY_EXECUTION_RESULT,
        message="recovery handoff triggered",
        facts=[fact],
    )

    reply_payload = reply.model_dump(mode="json")
    result_payload = result.model_dump(mode="json")

    assert reply_payload["reply_kind"] == "explanation"
    assert reply_payload["reply_code"] == "stuck_explanation"
    assert reply_payload["facts"][0]["fact_code"] == "approval_pending"
    assert result_payload["action_status"] == "completed"
    assert result_payload["effect"] == "handoff_triggered"
    assert result_payload["reply_code"] == "recovery_execution_result"


def test_action_receipt_query_and_reply_model_expose_stable_receipt_shape() -> None:
    fact = FactRecord(
        fact_id="fact_continue_posted",
        fact_code="steer_posted",
        fact_kind="action",
        severity="info",
        summary="continue posted",
        detail="continue request accepted",
        source="watchdog_action",
        observed_at="2026-04-05T05:23:00Z",
    )
    query = ActionReceiptQuery(
        action_code=ActionCode.CONTINUE_SESSION,
        project_id="repo-a",
        approval_id=None,
        idempotency_key="idem-continue-1",
    )
    result = WatchdogActionResult(
        action_code=ActionCode.CONTINUE_SESSION,
        project_id="repo-a",
        approval_id=None,
        idempotency_key="idem-continue-1",
        action_status=ActionStatus.COMPLETED,
        effect=Effect.STEER_POSTED,
        reply_code=ReplyCode.ACTION_RESULT,
        message="continue request accepted",
        facts=[fact],
    )
    reply = ReplyModel(
        reply_kind=ReplyKind.ACTION_RESULT,
        reply_code=ReplyCode.ACTION_RECEIPT,
        intent_code="get_action_receipt",
        message="stored action receipt found",
        action_result=result,
        facts=[fact],
    )

    query_payload = query.model_dump(mode="json")
    reply_payload = reply.model_dump(mode="json")

    assert query_payload["action_code"] == "continue_session"
    assert query_payload["idempotency_key"] == "idem-continue-1"
    assert reply_payload["reply_code"] == "action_receipt"
    assert reply_payload["action_result"]["effect"] == "steer_posted"
    assert reply_payload["facts"][0]["fact_code"] == "steer_posted"


def test_recovery_execution_enum_extensions_are_stable() -> None:
    assert ActionCode.EXECUTE_RECOVERY == "execute_recovery"
    assert ActionCode.POST_OPERATOR_GUIDANCE == "post_operator_guidance"
    assert ReplyCode.RECOVERY_EXECUTION_RESULT == "recovery_execution_result"
    assert Effect.HANDOFF_TRIGGERED == "handoff_triggered"
    assert Effect.HANDOFF_AND_RESUME == "handoff_and_resume"
    assert ActionCode.REQUEST_RECOVERY == "request_recovery"
    assert ReplyCode.RECOVERY_AVAILABILITY == "recovery_availability"
    assert Effect.ADVISORY_ONLY == "advisory_only"
    assert ReplyCode.ACTION_RECEIPT == "action_receipt"
    assert ReplyCode.ACTION_RECEIPT_NOT_FOUND == "action_receipt_not_found"


def test_supervision_evaluation_contract_extensions_are_stable() -> None:
    evaluation = SupervisionEvaluation(
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="thr_native_1",
        evaluated_at="2026-04-05T05:24:00Z",
        reason_code=SupervisionReasonCode.STUCK_SOFT,
        detail="idle 10.0 min",
        current_stuck_level=0,
        next_stuck_level=2,
        repo_recent_change_count=0,
        threshold_minutes=8.0,
        should_steer=True,
        steer_sent=True,
    )
    result = WatchdogActionResult(
        action_code=ActionCode.EVALUATE_SUPERVISION,
        project_id="repo-a",
        approval_id=None,
        idempotency_key="idem-supervision-1",
        action_status=ActionStatus.COMPLETED,
        effect=Effect.STEER_POSTED,
        reply_code=ReplyCode.SUPERVISION_EVALUATION,
        message="supervision evaluation completed",
        supervision_evaluation=evaluation,
    )

    payload = result.model_dump(mode="json")

    assert ActionCode.EVALUATE_SUPERVISION == "evaluate_supervision"
    assert ReplyCode.SUPERVISION_EVALUATION == "supervision_evaluation"
    assert SupervisionReasonCode.STUCK_SOFT == "stuck_soft"
    assert SupervisionReasonCode.TERMINAL_STATE == "terminal_state"
    assert payload["supervision_evaluation"]["thread_id"] == "session:repo-a"
    assert payload["supervision_evaluation"]["native_thread_id"] == "thr_native_1"
    assert payload["supervision_evaluation"]["reason_code"] == "stuck_soft"


def test_approval_inbox_contract_extension_is_stable() -> None:
    assert ReplyCode.APPROVAL_INBOX == "approval_inbox"
    assert ReplyKind.APPROVALS == "approvals"


def test_session_directory_contract_extension_is_stable() -> None:
    session = SessionProjection(
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="thr_native_1",
        session_state=SessionState.ACTIVE,
        activity_phase="editing_source",
        attention_state=AttentionState.NORMAL,
        headline="editing files",
        pending_approval_count=0,
        available_intents=["get_session", "continue_session"],
    )
    progress = TaskProgressView(
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="thr_native_1",
        activity_phase="editing_source",
        summary="editing files",
        files_touched=["src/example.py"],
        context_pressure="low",
        stuck_level=0,
        primary_fact_codes=[],
        blocker_fact_codes=[],
        last_progress_at="2026-04-05T05:20:00Z",
        recovery_outcome="same_thread_resume",
        recovery_status="completed",
        recovery_updated_at="2026-04-05T05:21:00Z",
        recovery_child_session_id=None,
    )
    reply = ReplyModel(
        reply_kind=ReplyKind.SESSION,
        reply_code=ReplyCode.SESSION_DIRECTORY,
        intent_code="list_sessions",
        message="1 session(s)",
        sessions=[session],
        progresses=[progress],
    )

    payload = reply.model_dump(mode="json")

    assert ReplyCode.SESSION_DIRECTORY == "session_directory"
    assert payload["reply_kind"] == "session"
    assert payload["sessions"][0]["project_id"] == "repo-a"
    assert payload["sessions"][0]["thread_id"] == "session:repo-a"
    assert payload["progresses"][0]["project_id"] == "repo-a"
    assert payload["progresses"][0]["recovery_outcome"] == "same_thread_resume"


def test_native_thread_resolution_reuses_session_projection_reply_contract() -> None:
    session = SessionProjection(
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="thr_native_1",
        session_state=SessionState.ACTIVE,
        activity_phase="editing_source",
        attention_state=AttentionState.NORMAL,
        headline="editing files",
        pending_approval_count=0,
        available_intents=["get_session", "continue_session"],
    )
    reply = ReplyModel(
        reply_kind=ReplyKind.SESSION,
        reply_code=ReplyCode.SESSION_PROJECTION,
        intent_code="get_session_by_native_thread",
        message="editing files",
        session=session,
    )

    payload = reply.model_dump(mode="json")

    assert payload["schema_version"] == SESSION_SPINE_SCHEMA_VERSION
    assert payload["reply_code"] == "session_projection"
    assert payload["intent_code"] == "get_session_by_native_thread"
    assert payload["session"]["native_thread_id"] == "thr_native_1"


def test_workspace_activity_contract_extension_is_stable() -> None:
    assert "WORKSPACE_ACTIVITY_VIEW" in ReplyCode.__members__
    assert "workspace_activity" in ReplyModel.model_fields


def test_session_event_snapshot_contract_extension_is_stable() -> None:
    event = SessionEvent(
        event_id="evt_001",
        event_code=EventCode.SESSION_CREATED,
        event_kind=EventKind.LIFECYCLE,
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="thr_native_1",
        source="a_control_agent",
        observed_at="2026-04-05T10:00:00Z",
        summary="session created in planning",
        attributes={"phase": "planning"},
    )
    reply = ReplyModel(
        reply_kind=ReplyKind.EVENTS,
        reply_code=ReplyCode.SESSION_EVENT_SNAPSHOT,
        intent_code="list_session_events",
        message="1 event(s)",
        events=[event],
    )

    payload = reply.model_dump(mode="json")

    assert ReplyKind.EVENTS == "events"
    assert ReplyCode.SESSION_EVENT_SNAPSHOT == "session_event_snapshot"
    assert payload["reply_kind"] == "events"
    assert payload["reply_code"] == "session_event_snapshot"
    assert payload["events"][0]["event_code"] == "session_created"
    assert payload["events"][0]["schema_version"] == SESSION_EVENTS_SCHEMA_VERSION
