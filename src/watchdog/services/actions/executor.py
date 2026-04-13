from __future__ import annotations

from typing import Any

from watchdog.contracts.session_spine.models import WatchdogAction, WatchdogActionResult
from watchdog.services.a_client.client import AControlAgentClient
from watchdog.services.actions.registry import get_registered_action
from watchdog.services.policy.decisions import CanonicalDecisionRecord
from watchdog.services.policy.rules import DECISION_AUTO_EXECUTE_AND_NOTIFY
from watchdog.services.session_service.service import SessionService
from watchdog.services.session_spine.actions import execute_watchdog_action
from watchdog.settings import Settings
from watchdog.storage.action_receipts import ActionReceiptStore


def _extract_action_arguments(
    decision: CanonicalDecisionRecord,
    *,
    required_argument_keys: tuple[str, ...],
) -> dict[str, Any]:
    arguments: dict[str, Any] = {}
    evidence = decision.evidence if isinstance(decision.evidence, dict) else {}
    requested_action_args = evidence.get("requested_action_args")
    if isinstance(requested_action_args, dict):
        arguments.update(requested_action_args)
    decision_evidence = evidence.get("decision")
    if isinstance(decision_evidence, dict):
        action_arguments = decision_evidence.get("action_arguments")
        if isinstance(action_arguments, dict):
            arguments.update(action_arguments)
        for key in required_argument_keys:
            value = decision_evidence.get(key)
            if value is not None and key not in arguments:
                arguments[key] = value
    if decision.approval_id and "approval_id" not in arguments:
        arguments["approval_id"] = decision.approval_id
    return arguments


def build_watchdog_action_from_decision(
    decision: CanonicalDecisionRecord,
    *,
    operator: str = "openclaw",
) -> WatchdogAction:
    registration = get_registered_action(decision.action_ref)
    arguments = _extract_action_arguments(
        decision,
        required_argument_keys=registration.argument_keys,
    )
    return WatchdogAction(
        action_code=registration.action_code,
        project_id=decision.project_id,
        operator=operator,
        idempotency_key=decision.idempotency_key,
        arguments=arguments,
        note=decision.decision_reason,
    )


def execute_canonical_decision(
    decision: CanonicalDecisionRecord,
    *,
    settings: Settings,
    client: AControlAgentClient,
    receipt_store: ActionReceiptStore,
    session_service: SessionService | None = None,
    operator: str = "openclaw",
) -> WatchdogActionResult:
    if decision.decision_result != DECISION_AUTO_EXECUTE_AND_NOTIFY:
        raise ValueError(
            "canonical decision must be auto_execute_and_notify before execution"
        )
    return execute_registered_action_for_decision(
        decision,
        settings=settings,
        client=client,
        receipt_store=receipt_store,
        session_service=session_service,
        operator=operator,
    )


def execute_registered_action_for_decision(
    decision: CanonicalDecisionRecord,
    *,
    settings: Settings,
    client: AControlAgentClient,
    receipt_store: ActionReceiptStore,
    session_service: SessionService | None = None,
    operator: str = "openclaw",
) -> WatchdogActionResult:
    action = build_watchdog_action_from_decision(decision, operator=operator)
    return execute_watchdog_action(
        action,
        settings=settings,
        client=client,
        receipt_store=receipt_store,
        session_service=session_service,
    )
