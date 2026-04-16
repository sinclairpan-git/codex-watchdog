from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from watchdog.services.a_client.client import AControlAgentClient
from watchdog.services.adapters.openclaw.adapter import OpenClawAdapter
from watchdog.services.approvals.service import (
    ApprovalResponseStore,
    CanonicalApprovalRecord,
    CanonicalApprovalStore,
    CanonicalApprovalResponseRecord,
    respond_to_canonical_approval,
)
from watchdog.services.delivery.store import DeliveryOutboxRecord, DeliveryOutboxStore
from watchdog.services.goal_contract.models import GoalContractSnapshot
from watchdog.services.goal_contract.service import GoalContractService
from watchdog.services.session_service.service import SessionService
from watchdog.settings import Settings
from watchdog.storage.action_receipts import ActionReceiptStore


def _parse_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class FeishuControlError(ValueError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class FeishuControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: str = Field(min_length=1)
    interaction_context_id: str = Field(min_length=1)
    interaction_family_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    channel_kind: str = Field(min_length=1)
    occurred_at: str = Field(min_length=1)
    action_window_expires_at: str = Field(min_length=1)
    envelope_id: str | None = None
    approval_id: str | None = None
    decision_id: str | None = None
    response_action: str | None = None
    response_token: str | None = None
    client_request_id: str = Field(min_length=1)
    note: str = ""
    project_id: str | None = None
    native_thread_id: str | None = None
    session_id: str | None = None
    goal_message: str | None = None
    command_text: str | None = None


class FeishuControlService:
    def __init__(
        self,
        *,
        settings: Settings,
        client: AControlAgentClient,
        receipt_store: ActionReceiptStore,
        approval_store: CanonicalApprovalStore,
        response_store: ApprovalResponseStore,
        delivery_outbox_store: DeliveryOutboxStore,
        session_service: SessionService,
    ) -> None:
        self._settings = settings
        self._client = client
        self._receipt_store = receipt_store
        self._approval_store = approval_store
        self._response_store = response_store
        self._delivery_outbox_store = delivery_outbox_store
        self._session_service = session_service

    def handle_request(
        self,
        request: FeishuControlRequest,
    ) -> CanonicalApprovalResponseRecord | dict[str, object]:
        if request.event_type == "approval_response":
            return self.handle_approval_response(request)
        if request.event_type == "goal_contract_bootstrap":
            return self.handle_goal_contract_bootstrap(request)
        if request.event_type == "command_request":
            return self.handle_command_request(request)
        raise FeishuControlError(f"unsupported event_type: {request.event_type}")

    def handle_approval_response(
        self,
        request: FeishuControlRequest,
    ) -> CanonicalApprovalResponseRecord:
        if request.event_type != "approval_response":
            raise FeishuControlError("event_type must be approval_response")
        envelope_id = self._require_field(request.envelope_id, "envelope_id")
        response_action = self._require_field(request.response_action, "response_action")

        approval = self._approval_store.get(envelope_id)
        if approval is None:
            raise KeyError(f"unknown approval envelope: {envelope_id}")
        self._validate_approval_contract(approval, request)
        self._assert_dm_channel(request)
        self._assert_not_expired(approval, request)
        self._assert_not_superseded(approval, request)
        self._record_receipt(approval, request)

        return respond_to_canonical_approval(
            envelope_id=envelope_id,
            response_action=response_action,
            client_request_id=request.client_request_id,
            operator=request.actor_id,
            note=request.note,
            approval_store=self._approval_store,
            response_store=self._response_store,
            settings=self._settings,
            client=self._client,
            receipt_store=self._receipt_store,
            delivery_outbox_store=self._delivery_outbox_store,
            session_service=self._session_service,
        )

    def handle_goal_contract_bootstrap(
        self,
        request: FeishuControlRequest,
    ) -> dict[str, object]:
        self._assert_dm_channel(request)
        project_id = self._require_field(request.project_id, "project_id")
        session_id = self._require_field(request.session_id, "session_id")
        goal_message = self._require_field(request.goal_message, "goal_message")
        service = GoalContractService(self._session_service)
        existing = self._find_existing_goal_contract_event(
            session_id=session_id,
            client_request_id=request.client_request_id,
        )
        if existing is not None:
            contract_payload = existing.payload.get("contract")
            if not isinstance(contract_payload, dict):
                raise FeishuControlError("existing goal contract replay payload is invalid")
            contract = GoalContractSnapshot.model_validate(contract_payload)
            return {
                "event_type": request.event_type,
                "project_id": project_id,
                "session_id": session_id,
                "goal_contract_version": contract.version,
                "replayed": True,
            }
        current = service.get_current_contract(project_id=project_id, session_id=session_id)
        related_ids = {
            "feishu_event_id": request.client_request_id,
            "feishu_message_id": request.interaction_context_id,
            "feishu_actor_id": request.actor_id,
        }
        if current is None:
            contract = service.bootstrap_contract(
                project_id=project_id,
                session_id=session_id,
                task_title=goal_message,
                task_prompt=goal_message,
                last_user_instruction=goal_message,
                phase="bootstrap",
                last_summary="feishu dm bootstrap",
                explicit_deliverables=[goal_message],
                completion_signals=["autonomy golden path release blocker passes"],
                causation_id=request.client_request_id,
                related_ids=related_ids,
            )
        else:
            contract = service.revise_contract(
                project_id=project_id,
                session_id=session_id,
                expected_version=current.version,
                current_phase_goal=goal_message,
                explicit_deliverables=current.explicit_deliverables or [goal_message],
                completion_signals=current.completion_signals
                or ["autonomy golden path release blocker passes"],
                causation_id=request.client_request_id,
                related_ids=related_ids,
            )
        return {
            "event_type": request.event_type,
            "project_id": project_id,
            "session_id": session_id,
            "goal_contract_version": contract.version,
        }

    def handle_command_request(
        self,
        request: FeishuControlRequest,
    ):
        self._assert_dm_channel(request)
        command_text = self._require_field(request.command_text, "command_text")
        project_id = str(request.project_id or "").strip() or None
        native_thread_id = str(request.native_thread_id or "").strip() or None
        if project_id is None and native_thread_id is None:
            raise FeishuControlError("project_id or native_thread_id is required")
        adapter = OpenClawAdapter(
            settings=self._settings,
            client=self._client,
            receipt_store=self._receipt_store,
        )
        return adapter.handle_message(
            command_text,
            project_id=project_id,
            native_thread_id=native_thread_id,
            operator="feishu",
            idempotency_key=f"feishu:{request.client_request_id}",
        )

    def _find_existing_goal_contract_event(
        self,
        *,
        session_id: str,
        client_request_id: str,
    ):
        relevant = self._session_service.list_events(
            session_id=session_id,
            related_id_key="feishu_event_id",
            related_id_value=client_request_id,
        )
        goal_events = [
            event
            for event in relevant
            if event.event_type in {"goal_contract_created", "goal_contract_revised"}
        ]
        if not goal_events:
            return None
        return max(goal_events, key=lambda event: event.log_seq or 0)

    def _validate_approval_contract(
        self,
        approval: CanonicalApprovalRecord,
        request: FeishuControlRequest,
    ) -> None:
        if request.approval_id != approval.approval_id:
            raise FeishuControlError("approval_id does not match envelope_id")
        if request.decision_id != approval.decision.decision_id:
            raise FeishuControlError("decision_id does not match envelope_id")
        if request.response_token != approval.approval_token:
            raise FeishuControlError("response_token does not match envelope_id")

    @staticmethod
    def _require_field(value: str | None, field_name: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise FeishuControlError(f"{field_name} is required")
        return normalized

    @staticmethod
    def _assert_dm_channel(request: FeishuControlRequest) -> None:
        if request.channel_kind.strip().lower() != "dm":
            raise FeishuControlError("high-risk approval responses require dm channel")

    def _assert_not_expired(
        self,
        approval: CanonicalApprovalRecord,
        request: FeishuControlRequest,
    ) -> None:
        occurred_at = _parse_timestamp(request.occurred_at)
        expires_at = _parse_timestamp(request.action_window_expires_at)
        if occurred_at < expires_at:
            return
        self._session_service.record_event(
            event_type="interaction_window_expired",
            project_id=approval.project_id,
            session_id=approval.session_id,
            correlation_id=f"corr:interaction:{request.interaction_context_id}:expired",
            causation_id=request.client_request_id,
            related_ids={
                "approval_id": approval.approval_id,
                "decision_id": approval.decision.decision_id,
                "envelope_id": approval.envelope_id,
                "interaction_context_id": request.interaction_context_id,
                "interaction_family_id": request.interaction_family_id,
                "actor_id": request.actor_id,
            },
            occurred_at=request.occurred_at,
            payload={
                "channel_kind": request.channel_kind,
                "expired_at": request.action_window_expires_at,
                "received_at": request.occurred_at,
            },
        )
        raise FeishuControlError("interaction window expired")

    def _assert_not_superseded(
        self,
        approval: CanonicalApprovalRecord,
        request: FeishuControlRequest,
    ) -> None:
        active = self._active_context_for_family(request.interaction_family_id)
        active_context_id = None if active is None else active.envelope_payload.get("interaction_context_id")
        if active is None or active_context_id == request.interaction_context_id:
            return
        self._session_service.record_event(
            event_type="interaction_context_superseded",
            project_id=approval.project_id,
            session_id=approval.session_id,
            correlation_id=f"corr:interaction:{request.interaction_family_id}:superseded",
            causation_id=request.client_request_id,
            related_ids={
                "approval_id": approval.approval_id,
                "decision_id": approval.decision.decision_id,
                "envelope_id": approval.envelope_id,
                "interaction_context_id": request.interaction_context_id,
                "interaction_family_id": request.interaction_family_id,
                "actor_id": request.actor_id,
            },
            occurred_at=request.occurred_at,
            payload={
                "active_interaction_context_id": str(active_context_id or ""),
                "active_envelope_id": active.envelope_id,
                "channel_kind": request.channel_kind,
            },
        )
        raise FeishuControlError("interaction context has been superseded")

    def _record_receipt(
        self,
        approval: CanonicalApprovalRecord,
        request: FeishuControlRequest,
    ) -> None:
        self._session_service.record_event(
            event_type="notification_receipt_recorded",
            project_id=approval.project_id,
            session_id=approval.session_id,
            correlation_id=(
                f"corr:notification:{approval.envelope_id}:receipt:{request.client_request_id}"
            ),
            causation_id=request.client_request_id,
            related_ids={
                "approval_id": approval.approval_id,
                "decision_id": approval.decision.decision_id,
                "envelope_id": approval.envelope_id,
                "receipt_id": f"feishu-receipt:{request.client_request_id}",
                "interaction_context_id": request.interaction_context_id,
                "interaction_family_id": request.interaction_family_id,
                "actor_id": request.actor_id,
            },
            occurred_at=request.occurred_at,
            payload={
                "channel_kind": request.channel_kind,
                "receipt_id": f"feishu-receipt:{request.client_request_id}",
                "received_at": request.occurred_at,
                "delivery_status": "user_replied",
                "response_action": request.response_action,
            },
        )

    def _active_context_for_family(
        self,
        interaction_family_id: str,
    ) -> DeliveryOutboxRecord | None:
        candidates: list[DeliveryOutboxRecord] = []
        for record in self._delivery_outbox_store.list_records():
            payload = record.envelope_payload
            if payload.get("interaction_family_id") != interaction_family_id:
                continue
            if not payload.get("interaction_context_id"):
                continue
            if record.delivery_status in {"superseded", "delivery_failed"}:
                continue
            candidates.append(record)
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda record: (
                record.updated_at or record.created_at,
                record.outbox_seq,
            ),
        )
