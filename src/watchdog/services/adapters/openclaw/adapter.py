from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from watchdog.contracts.session_spine.models import (
    ActionReceiptQuery,
    ReplyModel,
    SessionEvent,
    WatchdogAction,
)
from watchdog.services.approvals.service import CanonicalApprovalStore
from watchdog.services.a_client.client import AControlAgentClient
from watchdog.services.adapters.openclaw.intents import (
    READ_INTENTS,
    WRITE_INTENT_TO_ACTION,
)
from watchdog.services.adapters.openclaw.reply_model import (
    build_action_not_available_reply,
    build_action_reply,
    build_approval_inbox_reply,
    build_approval_queue_reply,
    build_blocker_explanation_reply,
    build_control_link_error_reply,
    build_progress_reply,
    build_session_facts_reply,
    build_session_event_snapshot_reply,
    build_session_directory_reply,
    build_session_reply,
    build_stuck_explanation_reply,
    build_unsupported_intent_reply,
    build_workspace_activity_reply,
)
from watchdog.services.policy.decisions import PolicyDecisionStore
from watchdog.services.entrypoints.command_routing import (
    resolve_entry_message,
    resolve_entry_route,
)
from watchdog.services.session_service import SessionService
from watchdog.services.session_spine.actions import execute_watchdog_action
from watchdog.services.session_spine.events import (
    iter_session_events as iter_projected_session_events,
    list_session_events as list_projected_session_events,
)
from watchdog.services.session_spine.receipts import lookup_action_receipt
from watchdog.services.session_spine.service import (
    SessionSpineUpstreamError,
    build_approval_inbox_bundle,
    build_session_directory_bundle,
    build_session_read_bundle,
    build_session_read_bundle_by_native_thread,
    build_workspace_activity_bundle,
)
from watchdog.services.session_spine.store import SessionSpineStore
from watchdog.settings import Settings
from watchdog.storage.action_receipts import ActionReceiptStore


class OpenClawAdapter:
    """Compatibility-only OpenClaw adapter preserved alongside the primary Feishu control plane."""

    def __init__(
        self,
        *,
        settings: Settings,
        client: AControlAgentClient,
        receipt_store: ActionReceiptStore,
    ) -> None:
        self._settings = settings
        self._client = client
        self._receipt_store = receipt_store
        data_dir = Path(self._settings.data_dir)
        self._session_service = SessionService.from_data_dir(data_dir)
        self._session_spine_store = SessionSpineStore(data_dir / "session_spine.json")
        self._approval_store = CanonicalApprovalStore(data_dir / "canonical_approvals.json")
        self._decision_store = PolicyDecisionStore(data_dir / "policy_decisions.json")

    def handle_intent(
        self,
        intent_code: str,
        *,
        project_id: str | None = None,
        operator: str = "openclaw",
        idempotency_key: str | None = None,
        approval_id: str | None = None,
        note: str = "",
        arguments: dict[str, Any] | None = None,
    ) -> ReplyModel:
        try:
            if intent_code == "get_action_receipt":
                if not project_id:
                    return build_action_not_available_reply(intent_code, "project_id is required")
                receipt_arguments = dict(arguments or {})
                query_body: dict[str, Any] = {
                    "action_code": receipt_arguments.get("action_code"),
                    "project_id": project_id,
                    "approval_id": approval_id or receipt_arguments.get("approval_id"),
                    "idempotency_key": idempotency_key or receipt_arguments.get("idempotency_key"),
                }
                try:
                    query = ActionReceiptQuery.model_validate(query_body)
                except ValidationError:
                    return build_action_not_available_reply(
                        intent_code,
                        "action_code and idempotency_key are required",
                    )
                return lookup_action_receipt(query, receipt_store=self._receipt_store)
            if intent_code in READ_INTENTS:
                if intent_code == "list_sessions":
                    bundle = build_session_directory_bundle(
                        self._client,
                        session_service=self._session_service,
                        store=self._session_spine_store,
                        approval_store=self._approval_store,
                        decision_store=self._decision_store,
                    )
                    return build_session_directory_reply(bundle)
                if intent_code == "list_approval_inbox":
                    bundle = build_approval_inbox_bundle(
                        self._client,
                        project_id,
                        session_service=self._session_service,
                        store=self._session_spine_store,
                        approval_store=self._approval_store,
                    )
                    return build_approval_inbox_reply(bundle)
                if intent_code == "get_session_by_native_thread":
                    native_thread_id = str((arguments or {}).get("native_thread_id") or "")
                    if not native_thread_id:
                        return build_action_not_available_reply(
                            intent_code,
                            "arguments.native_thread_id is required",
                        )
                    bundle = build_session_read_bundle_by_native_thread(
                        self._client,
                        native_thread_id,
                        session_service=self._session_service,
                        store=self._session_spine_store,
                        approval_store=self._approval_store,
                        decision_store=self._decision_store,
                    )
                    return build_session_reply(bundle, intent_code=intent_code)
                if not project_id:
                    return build_action_not_available_reply(intent_code, "project_id is required")
                if intent_code == "list_session_events":
                    events = list_projected_session_events(self._client, project_id)
                    return build_session_event_snapshot_reply(events)
                if intent_code == "get_workspace_activity":
                    try:
                        recent_minutes = int((arguments or {}).get("recent_minutes") or 15)
                    except (TypeError, ValueError):
                        return build_action_not_available_reply(
                            intent_code,
                            "recent_minutes must be an integer",
                        )
                    bundle = build_workspace_activity_bundle(
                        self._client,
                        project_id,
                        recent_minutes=recent_minutes,
                    )
                    return build_workspace_activity_reply(bundle)
                bundle = build_session_read_bundle(
                    self._client,
                    project_id,
                    session_service=self._session_service,
                    store=self._session_spine_store,
                    approval_store=self._approval_store,
                    decision_store=self._decision_store,
                )
                if intent_code == "get_session":
                    return build_session_reply(bundle)
                if intent_code == "get_progress":
                    return build_progress_reply(bundle)
                if intent_code == "list_session_facts":
                    return build_session_facts_reply(bundle)
                if intent_code == "list_pending_approvals":
                    return build_approval_queue_reply(bundle)
                if intent_code == "why_stuck":
                    return build_stuck_explanation_reply(bundle)
                return build_blocker_explanation_reply(bundle)

            action_code = WRITE_INTENT_TO_ACTION.get(intent_code)
            if action_code is None:
                return build_unsupported_intent_reply(intent_code)
            if not project_id:
                return build_action_not_available_reply(intent_code, "project_id is required")
            if not idempotency_key:
                return build_action_not_available_reply(intent_code, "idempotency_key is required")
            action_arguments = dict(arguments or {})
            if approval_id:
                action_arguments["approval_id"] = approval_id
            action = WatchdogAction(
                action_code=action_code,
                project_id=project_id,
                operator=operator,
                idempotency_key=idempotency_key,
                arguments=action_arguments,
                note=note,
            )
            result = execute_watchdog_action(
                action,
                settings=self._settings,
                client=self._client,
                receipt_store=self._receipt_store,
            )
            return build_action_reply(intent_code, result)
        except SessionSpineUpstreamError as exc:
            return build_control_link_error_reply(
                intent_code,
                str(exc.error.get("message") or "control link error"),
            )

    def handle_message(
        self,
        message: str,
        *,
        project_id: str | None = None,
        native_thread_id: str | None = None,
        operator: str = "openclaw",
        idempotency_key: str | None = None,
        approval_id: str | None = None,
        note: str = "",
        arguments: dict[str, Any] | None = None,
    ) -> ReplyModel:
        intent_code = resolve_entry_message(message)
        if intent_code is None:
            return build_unsupported_intent_reply(str(message or ""))
        routed_intent = intent_code
        try:
            routed_intent, resolved_project_id, routed_arguments = resolve_entry_route(
                client=self._client,
                intent_code=intent_code,
                project_id=project_id,
                native_thread_id=native_thread_id,
                arguments=arguments,
            )
        except SessionSpineUpstreamError as exc:
            return build_control_link_error_reply(
                intent_code,
                str(exc.error.get("message") or "control link error"),
            )
        resolved_idempotency_key = idempotency_key
        if resolved_idempotency_key is None and routed_intent not in READ_INTENTS:
            resolved_idempotency_key = (
                "message:"
                f"{resolved_project_id or routed_arguments.get('native_thread_id') or 'global'}:"
                f"{operator}:{intent_code}:{str(message or '').strip()}"
            )
        reply = self.handle_intent(
            routed_intent,
            project_id=resolved_project_id,
            operator=operator,
            idempotency_key=resolved_idempotency_key,
            approval_id=approval_id,
            note=note,
            arguments=routed_arguments,
        )
        if reply.intent_code != intent_code:
            return reply.model_copy(update={"intent_code": intent_code})
        return reply

    def list_session_events(self, project_id: str) -> list[SessionEvent]:
        return list_projected_session_events(self._client, project_id)

    def iter_session_events(self, project_id: str) -> Iterator[SessionEvent]:
        yield from iter_projected_session_events(self._client, project_id)
