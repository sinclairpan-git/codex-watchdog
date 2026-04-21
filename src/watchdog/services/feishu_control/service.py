from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field

from watchdog.services.a_client.client import AControlAgentClient
from watchdog.services.adapters.openclaw.adapter import OpenClawAdapter
from watchdog.services.adapters.openclaw.intents import GLOBAL_READ_INTENTS
from watchdog.services.entrypoints.command_routing import resolve_entry_message
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


def _maybe_parse_timestamp(value: str | None) -> datetime | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        return _parse_timestamp(normalized)
    except ValueError:
        return None


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _fact_snapshot_order(value: str) -> tuple[int, str]:
    match = re.fullmatch(r"fact-v(\d+)", value)
    if match is None:
        return (2**31 - 1, value)
    return (int(match.group(1)), value)


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
    receive_id: str | None = None
    receive_id_type: str | None = None


class FeishuControlService:
    _APPROVAL_ACTIONS = {
        "批准": "approve",
        "同意": "approve",
        "可以": "approve",
        "approve": "approve",
        "拒绝": "reject",
        "不同意": "reject",
        "不批准": "reject",
        "reject": "reject",
        "直接执行": "execute_action",
        "执行": "execute_action",
        "马上执行": "execute_action",
        "execute": "execute_action",
        "execute_action": "execute_action",
    }

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
            if self._normalize_goal_text(contract.current_phase_goal) != self._normalize_goal_text(
                goal_message
            ):
                raise FeishuControlError(
                    "goal bootstrap replay payload drifted from existing contract"
                )
            self._sync_goal_contract_metadata_to_a_task(
                project_id=project_id,
                goal_message=goal_message,
                contract=contract,
            )
            return {
                "event_type": request.event_type,
                "project_id": project_id,
                "session_id": session_id,
                "goal_contract_version": contract.version,
                "superseded_approval_count": 0,
                "replayed": True,
            }
        current = service.get_current_contract(project_id=project_id, session_id=session_id)
        related_ids = self._goal_bootstrap_related_ids(request)
        if current is None:
            contract = service.bootstrap_contract(
                project_id=project_id,
                session_id=session_id,
                task_title=goal_message,
                task_prompt=goal_message,
                last_user_instruction=goal_message,
                phase="bootstrap",
                last_summary=goal_message,
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
                current=current,
                current_phase_goal=goal_message,
                last_user_instruction=goal_message,
                last_summary=goal_message,
                explicit_deliverables=current.explicit_deliverables or [goal_message],
                completion_signals=current.completion_signals
                or ["autonomy golden path release blocker passes"],
                causation_id=request.client_request_id,
                related_ids=related_ids,
            )
        superseded = self._supersede_pending_approvals_for_goal_bootstrap(
            request=request,
            project_id=project_id,
            session_id=session_id,
            contract=contract,
        )
        self._sync_goal_contract_metadata_to_a_task(
            project_id=project_id,
            goal_message=goal_message,
            contract=contract,
        )
        return {
            "event_type": request.event_type,
            "project_id": project_id,
            "session_id": session_id,
            "goal_contract_version": contract.version,
            "superseded_approval_count": len(superseded),
        }

    def _sync_goal_contract_metadata_to_a_task(
        self,
        *,
        project_id: str,
        goal_message: str,
        contract: GoalContractSnapshot,
    ) -> None:
        try:
            envelope = self._client.get_envelope(project_id)
        except Exception:
            return
        if not isinstance(envelope, dict) or not envelope.get("success"):
            return
        task = envelope.get("data")
        if not isinstance(task, dict):
            return
        thread_id = str(task.get("thread_id") or "").strip()
        if not thread_id:
            return
        try:
            self._client.register_native_thread(
                {
                    "project_id": project_id,
                    "thread_id": thread_id,
                    "goal_contract_version": contract.version,
                    "current_phase_goal": contract.current_phase_goal,
                    "last_user_instruction": goal_message,
                    "last_summary": goal_message,
                }
            )
        except Exception:
            return

    def handle_command_request(
        self,
        request: FeishuControlRequest,
    ):
        self._assert_dm_channel(request)
        command_text = self._require_field(request.command_text, "command_text")
        project_id = str(request.project_id or "").strip() or None
        native_thread_id = str(request.native_thread_id or "").strip() or None
        session_id = str(request.session_id or "").strip() or None
        approval_response_action = self._approval_response_action_from_text(command_text)
        if approval_response_action is not None:
            approval = self._resolve_pending_approval_for_text_reply(
                request=request,
                project_id=project_id,
                session_id=session_id,
                native_thread_id=native_thread_id,
            )
            binding = self._latest_delivery_binding_for_envelope(approval.envelope_id)
            update = {
                "event_type": "approval_response",
                "envelope_id": approval.envelope_id,
                "approval_id": approval.approval_id,
                "decision_id": approval.decision.decision_id,
                "response_action": approval_response_action,
                "response_token": approval.approval_token,
                "project_id": approval.project_id,
                "session_id": approval.session_id,
                "native_thread_id": approval.effective_native_thread_id,
            }
            if binding is not None:
                for field in (
                    "interaction_context_id",
                    "interaction_family_id",
                    "action_window_expires_at",
                    "channel_kind",
                ):
                    value = str(binding.get(field) or "").strip()
                    if value:
                        update[field] = value
            return self.handle_approval_response(
                request.model_copy(update=update)
            )
        intent_code = resolve_entry_message(command_text)
        if (
            project_id is None
            and native_thread_id is None
            and intent_code not in GLOBAL_READ_INTENTS
        ):
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

    @classmethod
    def _approval_response_action_from_text(cls, command_text: str) -> str | None:
        normalized = " ".join(str(command_text or "").strip().lower().split())
        if not normalized:
            return None
        return cls._APPROVAL_ACTIONS.get(normalized)

    @staticmethod
    def _approval_recency_key(
        record: CanonicalApprovalRecord,
    ) -> tuple[tuple[int, str], datetime, str]:
        created_at = _parse_timestamp(record.created_at)
        return (_fact_snapshot_order(record.fact_snapshot_version), created_at, record.approval_id)

    def _pending_approval_candidates(
        self,
        *,
        project_id: str | None,
        session_id: str | None,
        native_thread_id: str | None,
    ) -> CanonicalApprovalRecord | None:
        normalized_project_id = str(project_id or "").strip() or None
        normalized_session_id = str(session_id or "").strip() or None
        normalized_native_thread_id = str(native_thread_id or "").strip() or None
        if normalized_project_id is None:
            normalized_project_id = str(self._settings.default_project_id or "").strip() or None
        candidates: list[CanonicalApprovalRecord] = []
        for record in self._approval_store.list_records():
            if record.status != "pending":
                continue
            if normalized_project_id is not None and record.project_id != normalized_project_id:
                continue
            if normalized_session_id is not None and record.session_id != normalized_session_id:
                continue
            if (
                normalized_native_thread_id is not None
                and str(record.effective_native_thread_id or "").strip()
                != normalized_native_thread_id
            ):
                continue
            candidates.append(record)
        return sorted(candidates, key=self._approval_recency_key, reverse=True)

    @staticmethod
    def _approval_reply_binding_error() -> FeishuControlError:
        return FeishuControlError("approval reply is ambiguous; reply to a specific pending approval")

    def _resolve_pending_approval_for_text_reply(
        self,
        *,
        request: FeishuControlRequest,
        project_id: str | None,
        session_id: str | None,
        native_thread_id: str | None,
    ) -> CanonicalApprovalRecord:
        candidates = self._pending_approval_candidates(
            project_id=project_id,
            session_id=session_id,
            native_thread_id=native_thread_id,
        )
        if not candidates:
            raise FeishuControlError("no pending approval matches this reply")

        bound_matches: list[CanonicalApprovalRecord] = []
        unbound_candidates: list[CanonicalApprovalRecord] = []
        has_delivery_bound_candidates = False
        for approval in candidates:
            binding = self._latest_delivery_binding_for_envelope(approval.envelope_id)
            if binding is None:
                unbound_candidates.append(approval)
                continue
            has_delivery_bound_candidates = True
            if self._delivery_binding_matches_request(binding=binding, request=request):
                bound_matches.append(approval)

        if len(bound_matches) == 1:
            return bound_matches[0]
        if len(bound_matches) > 1:
            raise self._approval_reply_binding_error()
        if has_delivery_bound_candidates:
            raise FeishuControlError("no pending approval matches this reply")
        if len(unbound_candidates) == 1:
            return unbound_candidates[0]
        raise self._approval_reply_binding_error()

    def _latest_delivery_binding_for_envelope(
        self,
        envelope_id: str,
    ) -> dict[str, str] | None:
        candidates: list[DeliveryOutboxRecord] = []
        for record in self._delivery_outbox_store.list_records():
            if record.envelope_id != envelope_id:
                continue
            if record.delivery_status in {"superseded", "delivery_failed"}:
                continue
            payload = record.envelope_payload if isinstance(record.envelope_payload, dict) else {}
            actor_id = str(payload.get("actor_id") or "").strip()
            receive_id = str(payload.get("receive_id") or "").strip()
            receive_id_type = str(payload.get("receive_id_type") or "").strip()
            if not actor_id and not (receive_id and receive_id_type):
                continue
            candidates.append(record)
        if not candidates:
            return None
        latest = max(
            candidates,
            key=lambda record: (
                record.updated_at or record.created_at,
                record.outbox_seq,
            ),
        )
        payload = latest.envelope_payload if isinstance(latest.envelope_payload, dict) else {}
        binding = {
            "actor_id": str(payload.get("actor_id") or "").strip(),
            "receive_id": str(payload.get("receive_id") or "").strip(),
            "receive_id_type": str(payload.get("receive_id_type") or "").strip(),
            "interaction_context_id": str(payload.get("interaction_context_id") or "").strip(),
            "interaction_family_id": str(payload.get("interaction_family_id") or "").strip(),
            "action_window_expires_at": str(payload.get("action_window_expires_at") or "").strip(),
            "channel_kind": str(payload.get("channel_kind") or "").strip(),
        }
        if not binding["actor_id"] and not (
            binding["receive_id"] and binding["receive_id_type"]
        ):
            return None
        return binding

    @staticmethod
    def _delivery_binding_matches_request(
        *,
        binding: dict[str, str],
        request: FeishuControlRequest,
    ) -> bool:
        request_actor_id = str(request.actor_id or "").strip()
        if binding.get("actor_id") and binding["actor_id"] != request_actor_id:
            return False
        request_receive_id = str(request.receive_id or "").strip()
        request_receive_id_type = str(request.receive_id_type or "").strip()
        if (
            binding.get("receive_id")
            and binding.get("receive_id_type")
            and request_receive_id
            and request_receive_id_type
            and (
                binding["receive_id"] != request_receive_id
                or binding["receive_id_type"] != request_receive_id_type
            )
        ):
            return False
        return True

    @staticmethod
    def _goal_bootstrap_related_ids(request: FeishuControlRequest) -> dict[str, str]:
        related_ids = {
            "feishu_event_id": request.client_request_id,
            "feishu_message_id": request.interaction_context_id,
            "feishu_actor_id": request.actor_id,
            "interaction_context_id": request.interaction_context_id,
            "interaction_family_id": request.interaction_family_id,
        }
        native_thread_id = str(request.native_thread_id or "").strip()
        if native_thread_id:
            related_ids["native_thread_id"] = native_thread_id
        receive_id = str(request.receive_id or "").strip()
        receive_id_type = str(request.receive_id_type or "").strip()
        if receive_id and receive_id_type:
            related_ids["feishu_receive_id"] = receive_id
            related_ids["feishu_receive_id_type"] = receive_id_type
            if receive_id_type == "chat_id":
                related_ids["feishu_chat_id"] = receive_id
        return related_ids

    def _supersede_pending_approvals_for_goal_bootstrap(
        self,
        *,
        request: FeishuControlRequest,
        project_id: str,
        session_id: str,
        contract: GoalContractSnapshot,
    ) -> list[CanonicalApprovalRecord]:
        reason = (
            "approval_superseded_by_goal_contract_bootstrap "
            f"goal_contract_version={contract.version} "
            f"feishu_event_id={request.client_request_id}"
        )
        superseded = self._approval_store.supersede_pending_records_for_goal_contract_transition(
            session_id=session_id,
            project_id=project_id,
            active_goal_contract_version=contract.version,
            reason=reason,
            decided_by="feishu-goal-bootstrap",
        )
        if not superseded:
            return []
        self._delivery_outbox_store.supersede_records(
            envelope_reasons={
                record.envelope_id: reason
                for record in superseded
            },
            updated_at=request.occurred_at,
        )
        recorder = (
            self._session_service.record_event_once
            if hasattr(self._session_service, "record_event_once")
            else self._session_service.record_event
        )
        recorder(
            event_type="approval_superseded_by_goal_contract_bootstrap",
            project_id=project_id,
            session_id=session_id,
            correlation_id=(
                "corr:approval-superseded-by-goal-bootstrap:"
                f"{session_id}:{request.client_request_id}"
            ),
            causation_id=request.client_request_id,
            related_ids={
                "goal_contract_version": contract.version,
                "feishu_event_id": request.client_request_id,
                "feishu_message_id": request.interaction_context_id,
                **(
                    {
                        "native_thread_id": next(
                            (
                                native_thread_id
                                for native_thread_id in (
                                    str(record.effective_native_thread_id or "").strip()
                                    for record in superseded
                                )
                                if native_thread_id
                            ),
                            "",
                        )
                    }
                    if any(
                        str(record.effective_native_thread_id or "").strip()
                        for record in superseded
                    )
                    else {}
                ),
            },
            occurred_at=request.occurred_at,
            payload={
                "goal_contract_version": contract.version,
                "superseded_approval_count": len(superseded),
                "approval_ids": [record.approval_id for record in superseded],
                "envelope_ids": [record.envelope_id for record in superseded],
            },
        )
        return superseded

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

    @staticmethod
    def _normalize_goal_text(value: str | None) -> str:
        return " ".join(str(value or "").split()).strip()

    def _assert_not_expired(
        self,
        approval: CanonicalApprovalRecord,
        request: FeishuControlRequest,
    ) -> None:
        occurred_at = _parse_timestamp(request.occurred_at)
        expires_at_raw = request.action_window_expires_at
        expires_at = _maybe_parse_timestamp(approval.expires_at)
        if expires_at is None and self._settings.approval_expiration_seconds > 0:
            created_at = _maybe_parse_timestamp(approval.created_at)
            if created_at is not None:
                expires_at = created_at + timedelta(
                    seconds=float(self._settings.approval_expiration_seconds)
                )
                expires_at_raw = _format_timestamp(expires_at)
        if expires_at is None:
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
                "native_thread_id": str(approval.effective_native_thread_id or "").strip(),
            },
            occurred_at=request.occurred_at,
            payload={
                "channel_kind": request.channel_kind,
                "expired_at": expires_at_raw,
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
                "native_thread_id": str(approval.effective_native_thread_id or "").strip(),
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
                "native_thread_id": str(approval.effective_native_thread_id or "").strip(),
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
