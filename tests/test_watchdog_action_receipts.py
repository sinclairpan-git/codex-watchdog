from __future__ import annotations

from pathlib import Path

from watchdog.contracts.session_spine.enums import (
    ActionCode,
    ActionStatus,
    Effect,
    ReplyCode,
)
from watchdog.contracts.session_spine.models import (
    ActionReceiptQuery,
    FactRecord,
    SupervisionEvaluation,
    WatchdogActionResult,
)
from watchdog.services.session_spine.receipts import lookup_action_receipt
from watchdog.storage.action_receipts import ActionReceiptStore, receipt_key


def _receipt_store(tmp_path: Path) -> ActionReceiptStore:
    return ActionReceiptStore(tmp_path / "action_receipts.json")


def _fact() -> FactRecord:
    return FactRecord(
        fact_id="fact_continue_posted",
        fact_code="steer_posted",
        fact_kind="action",
        severity="info",
        summary="continue posted",
        detail="continue request accepted",
        source="watchdog_action",
        observed_at="2026-04-05T05:23:00Z",
    )


def _result(
    *,
    action_code: ActionCode = ActionCode.CONTINUE_SESSION,
    project_id: str = "repo-a",
    approval_id: str | None = None,
    idempotency_key: str = "idem-continue-1",
) -> WatchdogActionResult:
    return WatchdogActionResult(
        action_code=action_code,
        project_id=project_id,
        approval_id=approval_id,
        idempotency_key=idempotency_key,
        action_status=ActionStatus.COMPLETED,
        effect=Effect.STEER_POSTED,
        reply_code=ReplyCode.ACTION_RESULT,
        message="continue request accepted",
        facts=[_fact()],
    )


def test_lookup_action_receipt_returns_stable_reply_for_existing_receipt(tmp_path: Path) -> None:
    store = _receipt_store(tmp_path)
    result = _result()
    store.put(
        receipt_key(
            action_code=result.action_code,
            project_id=result.project_id,
            approval_id=result.approval_id,
            idempotency_key=result.idempotency_key,
        ),
        result,
    )

    reply = lookup_action_receipt(
        ActionReceiptQuery(
            action_code=ActionCode.CONTINUE_SESSION,
            project_id="repo-a",
            idempotency_key="idem-continue-1",
        ),
        receipt_store=store,
    )

    assert reply.reply_code == "action_receipt"
    assert reply.reply_kind == "action_result"
    assert reply.action_result is not None
    assert reply.action_result.effect == "steer_posted"
    assert [fact.fact_code for fact in reply.facts] == ["steer_posted"]


def test_lookup_action_receipt_returns_not_found_when_receipt_is_missing(tmp_path: Path) -> None:
    reply = lookup_action_receipt(
        ActionReceiptQuery(
            action_code=ActionCode.CONTINUE_SESSION,
            project_id="repo-a",
            idempotency_key="missing-idem",
        ),
        receipt_store=_receipt_store(tmp_path),
    )

    assert reply.reply_code == "action_receipt_not_found"
    assert reply.reply_kind == "action_result"
    assert reply.action_result is None
    assert reply.facts == []


def test_lookup_action_receipt_uses_approval_id_as_part_of_stable_key(tmp_path: Path) -> None:
    store = _receipt_store(tmp_path)
    result = _result(
        action_code=ActionCode.APPROVE_APPROVAL,
        approval_id="appr_001",
        idempotency_key="idem-approval-1",
    )
    store.put(
        receipt_key(
            action_code=result.action_code,
            project_id=result.project_id,
            approval_id=result.approval_id,
            idempotency_key=result.idempotency_key,
        ),
        result,
    )

    missing = lookup_action_receipt(
        ActionReceiptQuery(
            action_code=ActionCode.APPROVE_APPROVAL,
            project_id="repo-a",
            idempotency_key="idem-approval-1",
        ),
        receipt_store=store,
    )
    found = lookup_action_receipt(
        ActionReceiptQuery(
            action_code=ActionCode.APPROVE_APPROVAL,
            project_id="repo-a",
            approval_id="appr_001",
            idempotency_key="idem-approval-1",
        ),
        receipt_store=store,
    )

    assert missing.reply_code == "action_receipt_not_found"
    assert found.reply_code == "action_receipt"
    assert found.action_result is not None
    assert found.action_result.approval_id == "appr_001"


def test_lookup_action_receipt_preserves_supervision_evaluation_payload(tmp_path: Path) -> None:
    store = _receipt_store(tmp_path)
    result = WatchdogActionResult(
        action_code=ActionCode.EVALUATE_SUPERVISION,
        project_id="repo-a",
        approval_id=None,
        idempotency_key="idem-supervision-1",
        action_status=ActionStatus.COMPLETED,
        effect=Effect.STEER_POSTED,
        reply_code=ReplyCode.SUPERVISION_EVALUATION,
        message="supervision evaluation completed",
        supervision_evaluation=SupervisionEvaluation(
            project_id="repo-a",
            thread_id="session:repo-a",
            native_thread_id="thr_native_1",
            evaluated_at="2026-04-05T05:24:00Z",
            reason_code="stuck_soft",
            detail="idle 10.0 min",
            current_stuck_level=0,
            next_stuck_level=2,
            repo_recent_change_count=0,
            threshold_minutes=8.0,
            should_steer=True,
            steer_sent=True,
        ),
        facts=[_fact()],
    )
    store.put(
        receipt_key(
            action_code=result.action_code,
            project_id=result.project_id,
            approval_id=result.approval_id,
            idempotency_key=result.idempotency_key,
        ),
        result,
    )

    reply = lookup_action_receipt(
        ActionReceiptQuery(
            action_code=ActionCode.EVALUATE_SUPERVISION,
            project_id="repo-a",
            idempotency_key="idem-supervision-1",
        ),
        receipt_store=store,
    )

    assert reply.reply_code == "action_receipt"
    assert reply.action_result is not None
    assert reply.action_result.supervision_evaluation is not None
    assert reply.action_result.supervision_evaluation.reason_code == "stuck_soft"
