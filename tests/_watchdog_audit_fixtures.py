from __future__ import annotations

from pathlib import Path

from watchdog.contracts.session_spine.enums import ActionCode, ActionStatus, Effect, ReplyCode
from watchdog.contracts.session_spine.models import FactRecord, WatchdogActionResult
from watchdog.services.approvals.service import (
    ApprovalResponseStore,
    CanonicalApprovalRecord,
    CanonicalApprovalResponseRecord,
    CanonicalApprovalStore,
    build_canonical_approval_record,
)
from watchdog.services.delivery.envelopes import (
    build_envelopes_for_approval_response,
    build_envelopes_for_decision,
)
from watchdog.services.delivery.store import DeliveryOutboxStore
from watchdog.services.policy.decisions import CanonicalDecisionRecord, PolicyDecisionStore
from watchdog.storage.action_receipts import ActionReceiptStore, receipt_key


def _fact(*, observed_at: str, fact_code: str = "approval_decided") -> FactRecord:
    return FactRecord(
        fact_id=f"fact:{fact_code}:{observed_at}",
        fact_code=fact_code,
        fact_kind="action",
        severity="info",
        summary=fact_code,
        detail=fact_code,
        source="watchdog_action",
        observed_at=observed_at,
    )


def _receipt_result(
    *,
    action_code: ActionCode,
    project_id: str,
    approval_id: str | None,
    idempotency_key: str,
    effect: Effect,
    observed_at: str,
) -> WatchdogActionResult:
    return WatchdogActionResult(
        action_code=action_code,
        project_id=project_id,
        approval_id=approval_id,
        idempotency_key=idempotency_key,
        action_status=ActionStatus.COMPLETED,
        effect=effect,
        reply_code=ReplyCode.ACTION_RESULT,
        message=f"{action_code} completed",
        facts=[_fact(observed_at=observed_at)],
    )


def seed_audit_chain(
    data_dir: Path,
    *,
    with_resident_expert_consultation: bool = False,
) -> dict[str, str]:
    policy_store = PolicyDecisionStore(data_dir / "policy_decisions.json")
    approval_store = CanonicalApprovalStore(data_dir / "canonical_approvals.json")
    response_store = ApprovalResponseStore(data_dir / "approval_responses.json")
    delivery_store = DeliveryOutboxStore(data_dir / "delivery_outbox.json")
    receipt_store = ActionReceiptStore(data_dir / "action_receipts.json")

    decision = CanonicalDecisionRecord(
        decision_id="decision:forensic-1",
        decision_key="session:repo-a|fact-v9|policy-v1|require_user_decision|execute_recovery|appr_001",
        session_id="session:repo-a",
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="thr_native_1",
        approval_id="appr_001",
        action_ref="execute_recovery",
        trigger="resident_supervision",
        decision_result="require_user_decision",
        risk_class="human_gate",
        decision_reason="approval required before recovery execution",
        matched_policy_rules=["human_gate"],
        why_not_escalated=None,
        why_escalated="destructive recovery needs approval",
        uncertainty_reasons=[],
        policy_version="policy-v1",
        fact_snapshot_version="fact-v9",
        idempotency_key="session:repo-a|fact-v9|policy-v1|require_user_decision|execute_recovery|appr_001",
        created_at="2026-04-07T00:00:00Z",
        operator_notes=["approval requested"],
        evidence={
            "facts": [
                {
                    "fact_id": "fact:recovery_available",
                    "fact_code": "recovery_available",
                    "fact_kind": "signal",
                    "severity": "info",
                    "summary": "recovery available",
                    "detail": "recovery available",
                    "source": "watchdog",
                    "observed_at": "2026-04-07T00:00:00Z",
                    "related_ids": {},
                }
            ],
            "decision": {
                "decision_result": "require_user_decision",
                "action_ref": "execute_recovery",
                "approval_id": "appr_001",
            },
            **(
                {
                    "resident_expert_consultation": {
                        "consultation_ref": "decision:forensic-1",
                        "consulted_at": "2026-04-07T00:00:00Z",
                        "coverage_status": "degraded",
                        "degraded_expert_ids": ["hermes-agent-expert"],
                        "experts": [
                            {
                                "expert_id": "managed-agent-expert",
                                "status": "available",
                                "runtime_handle": "agent:managed:1",
                                "last_seen_at": "2026-04-06T23:59:30Z",
                                "last_consulted_at": "2026-04-07T00:00:00Z",
                                "last_consultation_ref": "decision:forensic-1",
                            },
                            {
                                "expert_id": "hermes-agent-expert",
                                "status": "stale",
                                "runtime_handle": "agent:hermes:1",
                                "last_seen_at": "2026-04-06T23:55:00Z",
                                "last_consulted_at": "2026-04-07T00:00:00Z",
                                "last_consultation_ref": "decision:forensic-1",
                            },
                        ],
                    }
                }
                if with_resident_expert_consultation
                else {}
            ),
        },
    )
    policy_store.put(decision)

    canonical_approval = build_canonical_approval_record(decision)

    approval = CanonicalApprovalRecord(
        approval_id="appr_001",
        envelope_id=canonical_approval.envelope_id,
        approval_kind="canonical_user_decision",
        requested_action="execute_recovery",
        requested_action_args={"resume": True},
        approval_token=canonical_approval.approval_token,
        decision_options=["approve", "reject", "execute_action"],
        policy_version="policy-v1",
        fact_snapshot_version="fact-v9",
        idempotency_key=f"{decision.idempotency_key}|approval",
        project_id="repo-a",
        session_id="session:repo-a",
        thread_id="session:repo-a",
        native_thread_id="thr_native_1",
        status="approved",
        created_at="2026-04-07T00:00:01Z",
        decided_at="2026-04-07T00:00:03Z",
        decided_by="openclaw:user-1",
        operator_notes=["approval approved by operator"],
        decision=decision,
    )
    approval_store.put(approval)

    approval_receipt = _receipt_result(
        action_code=ActionCode.APPROVE_APPROVAL,
        project_id="repo-a",
        approval_id="appr_001",
        idempotency_key="session:repo-a|fact-v9|policy-v1|require_user_decision|execute_recovery|appr_001|approval|approve",
        effect=Effect.APPROVAL_DECIDED,
        observed_at="2026-04-07T00:00:04Z",
    )
    execution_receipt = _receipt_result(
        action_code=ActionCode.EXECUTE_RECOVERY,
        project_id="repo-a",
        approval_id=None,
        idempotency_key=decision.idempotency_key,
        effect=Effect.HANDOFF_AND_RESUME,
        observed_at="2026-04-07T00:00:05Z",
    )

    response = CanonicalApprovalResponseRecord(
        response_id="approval-response:forensic-1",
        envelope_id=approval.envelope_id,
        approval_id=approval.approval_id,
        response_action="approve",
        client_request_id="client-request-1",
        idempotency_key=f"{approval.envelope_id}|approve|client-request-1",
        project_id="repo-a",
        approval_status="approved",
        operator="openclaw:user-1",
        note="approved from host runtime",
        created_at="2026-04-07T00:00:03Z",
        operator_notes=["response=approve operator=openclaw:user-1"],
        approval_result=approval_receipt,
        execution_result=execution_receipt,
    )
    response_store.put(response)

    receipt_store.put(
        receipt_key(
            action_code=approval_receipt.action_code,
            project_id=approval_receipt.project_id,
            approval_id=approval_receipt.approval_id,
            idempotency_key=approval_receipt.idempotency_key,
        ),
        approval_receipt,
    )
    receipt_store.put(
        receipt_key(
            action_code=execution_receipt.action_code,
            project_id=execution_receipt.project_id,
            approval_id=execution_receipt.approval_id,
            idempotency_key=execution_receipt.idempotency_key,
        ),
        execution_receipt,
    )

    approval_delivery = delivery_store.enqueue_envelopes(build_envelopes_for_decision(decision))[0]
    approval_delivery = approval_delivery.model_copy(
        update={
            "created_at": "2026-04-07T00:00:02Z",
            "delivery_status": "delivered",
            "delivery_attempt": 1,
            "receipt_id": "receipt:approval-envelope",
            "operator_notes": ["delivery delivered attempt=1"],
        }
    )
    delivery_store.update_delivery_record(approval_delivery)

    approval_result_delivery = delivery_store.enqueue_envelopes(
        build_envelopes_for_approval_response(approval, response)
    )[0]
    approval_result_delivery = approval_result_delivery.model_copy(
        update={
            "created_at": "2026-04-07T00:00:06Z",
            "delivery_status": "delivered",
            "delivery_attempt": 1,
            "receipt_id": "receipt:approval-result",
            "operator_notes": ["delivery delivered attempt=1"],
        }
    )
    delivery_store.update_delivery_record(approval_result_delivery)

    return {
        "session_id": decision.session_id,
        "decision_id": decision.decision_id,
        "approval_id": approval.approval_id,
        "approval_envelope_id": approval.envelope_id,
        "approval_result_envelope_id": approval_result_delivery.envelope_id,
        "response_id": response.response_id,
        "receipt_id": "receipt:approval-result",
        "approval_receipt_key": receipt_key(
            action_code=approval_receipt.action_code,
            project_id=approval_receipt.project_id,
            approval_id=approval_receipt.approval_id,
            idempotency_key=approval_receipt.idempotency_key,
        ),
        "execution_receipt_key": receipt_key(
            action_code=execution_receipt.action_code,
            project_id=execution_receipt.project_id,
            approval_id=execution_receipt.approval_id,
            idempotency_key=execution_receipt.idempotency_key,
        ),
    }
