from __future__ import annotations

from watchdog.contracts.session_spine.enums import ReplyCode, ReplyKind
from watchdog.contracts.session_spine.models import ActionReceiptQuery, ReplyModel
from watchdog.storage.action_receipts import ActionReceiptStore, receipt_key


def lookup_action_receipt(
    query: ActionReceiptQuery,
    *,
    receipt_store: ActionReceiptStore,
) -> ReplyModel:
    result = receipt_store.get(
        receipt_key(
            action_code=str(query.action_code),
            project_id=query.project_id,
            approval_id=query.approval_id,
            idempotency_key=query.idempotency_key,
        )
    )
    if result is None:
        return ReplyModel(
            reply_kind=ReplyKind.ACTION_RESULT,
            reply_code=ReplyCode.ACTION_RECEIPT_NOT_FOUND,
            intent_code="get_action_receipt",
            message="action receipt not found",
        )
    return ReplyModel(
        reply_kind=ReplyKind.ACTION_RESULT,
        reply_code=ReplyCode.ACTION_RECEIPT,
        intent_code="get_action_receipt",
        message=result.message,
        action_result=result,
        facts=list(result.facts),
    )
