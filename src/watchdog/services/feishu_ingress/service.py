from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field

from watchdog.services.a_client.client import AControlAgentClient
from watchdog.services.feishu_control import FeishuControlRequest
from watchdog.settings import Settings


def _iso_z(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_ms_timestamp(value: str) -> str:
    try:
        millis = int(str(value or "").strip())
        return _iso_z(datetime.fromtimestamp(millis / 1000, tz=UTC))
    except (TypeError, ValueError, OSError, OverflowError) as exc:
        raise FeishuIngressError("invalid feishu event timestamp") from exc


class FeishuIngressError(ValueError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class FeishuURLVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1)
    token: str = Field(min_length=1)
    challenge: str = Field(min_length=1)


class FeishuEventHeader(BaseModel):
    model_config = ConfigDict(extra="allow")

    event_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    create_time: str = Field(min_length=1)
    token: str = Field(min_length=1)
    app_id: str = Field(min_length=1)
    tenant_key: str = Field(min_length=1)


class FeishuMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    message_id: str = Field(min_length=1)
    chat_type: str = Field(min_length=1)
    message_type: str = Field(min_length=1)
    content: str = Field(min_length=1)


class FeishuSenderId(BaseModel):
    model_config = ConfigDict(extra="allow")

    open_id: str | None = None
    user_id: str | None = None
    union_id: str | None = None


class FeishuSender(BaseModel):
    model_config = ConfigDict(extra="allow")

    sender_id: FeishuSenderId


class FeishuMessageEventPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    message: FeishuMessage
    sender: FeishuSender


class FeishuMessageCallback(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    schema_name: str = Field(alias="schema", min_length=1)
    header: FeishuEventHeader
    event: FeishuMessageEventPayload


class FeishuIngressNormalizationService:
    def __init__(self, *, settings: Settings, client: AControlAgentClient) -> None:
        self._settings = settings
        self._client = client

    def validate_url_verification(
        self,
        payload: FeishuURLVerificationRequest,
    ) -> dict[str, str]:
        expected = str(self._settings.feishu_verification_token or "").strip()
        if not expected:
            raise FeishuIngressError("feishu verification token is not configured")
        if payload.type != "url_verification":
            raise FeishuIngressError("type must be url_verification")
        if payload.token != expected:
            raise FeishuIngressError("invalid feishu verification token")
        return {"challenge": payload.challenge}

    def normalize_message_event(
        self,
        payload: FeishuMessageCallback,
    ) -> FeishuControlRequest:
        self._validate_event_token(payload.header.token)
        if payload.schema_name != "2.0":
            raise FeishuIngressError("unsupported feishu event schema")
        if payload.header.event_type != "im.message.receive_v1":
            raise FeishuIngressError("unsupported feishu event_type")
        if payload.event.message.message_type != "text":
            raise FeishuIngressError("only text message events are supported")

        text = self._extract_text(payload.event.message.content)
        target = self._resolve_binding(text)
        occurred_at = _parse_ms_timestamp(payload.header.create_time)
        expires_at = _iso_z(
            datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
            + timedelta(seconds=max(int(self._settings.feishu_interaction_window_seconds), 60))
        )
        actor_id = self._actor_id(payload.event.sender.sender_id)
        channel_kind = "dm" if payload.event.message.chat_type == "p2p" else "group"
        if target["event_type"] == "goal_contract_bootstrap" and channel_kind != "dm":
            raise FeishuIngressError("goal bootstrap requires dm channel")
        return FeishuControlRequest.model_validate(
            {
                "event_type": target["event_type"],
                "interaction_context_id": payload.event.message.message_id,
                "interaction_family_id": payload.event.message.message_id,
                "actor_id": actor_id,
                "channel_kind": channel_kind,
                "occurred_at": occurred_at,
                "action_window_expires_at": expires_at,
                "client_request_id": payload.header.event_id,
                "project_id": target.get("project_id"),
                "native_thread_id": target.get("native_thread_id"),
                "session_id": target.get("session_id"),
                "goal_message": target.get("goal_message"),
                "command_text": target.get("command_text"),
            }
        )

    def _validate_event_token(self, token: str) -> None:
        expected = str(self._settings.feishu_verification_token or "").strip()
        if not expected:
            raise FeishuIngressError("feishu verification token is not configured")
        if str(token or "").strip() != expected:
            raise FeishuIngressError("invalid feishu verification token")

    @staticmethod
    def _extract_text(content: str) -> str:
        try:
            payload = json.loads(content)
        except ValueError as exc:
            raise FeishuIngressError("invalid feishu text content") from exc
        text = str(payload.get("text") or "").strip()
        if not text:
            raise FeishuIngressError("feishu text content is empty")
        return text

    @staticmethod
    def _actor_id(sender_id: FeishuSenderId) -> str:
        for field in ("open_id", "user_id", "union_id"):
            value = str(getattr(sender_id, field) or "").strip()
            if value:
                return value
        raise FeishuIngressError("sender id is required")

    def _resolve_binding(self, text: str) -> dict[str, str]:
        message = text.strip()
        lowered = message.lower()
        lookup_thread_id: str | None = None
        project_id: str | None = None
        command_text = message
        tasks = [
            task
            for task in self._client.list_tasks()
            if str(task.get("status") or "").strip() not in {"completed", "failed", "paused", "cancelled"}
        ]
        if lowered.startswith("repo:") or lowered.startswith("project:"):
            head, _, rest = message.partition(" ")
            project_id = head.split(":", 1)[1].strip()
            command_text = rest.strip()
        elif lowered.startswith("thread:"):
            head, _, rest = message.partition(" ")
            lookup_thread_id = head.split(":", 1)[1].strip()
            command_text = rest.strip()
        elif len(tasks) == 1:
            task = tasks[0]
            project_id = str(task.get("project_id") or "").strip() or None
            lookup_thread_id = str(task.get("thread_id") or "").strip() or None
        else:
            raise FeishuIngressError("project binding is required for Feishu ingress")

        if lookup_thread_id:
            envelope = self._client.get_envelope_by_thread(lookup_thread_id)
        elif project_id:
            envelope = self._client.get_envelope(project_id)
        else:
            raise FeishuIngressError("project binding is required for Feishu ingress")
        data = envelope.get("data")
        if not isinstance(data, dict):
            raise FeishuIngressError("bound task envelope is invalid")
        resolved_project_id = str(data.get("project_id") or project_id or "").strip()
        resolved_thread_id = str(data.get("native_thread_id") or "").strip()
        session_id = str(data.get("thread_id") or lookup_thread_id or "").strip()
        if not resolved_project_id:
            raise FeishuIngressError("bound project_id is missing")
        if command_text.startswith("/goal "):
            goal_message = command_text.removeprefix("/goal").strip()
            if not goal_message:
                raise FeishuIngressError("goal bootstrap message is empty")
            if not session_id:
                raise FeishuIngressError("session_id is required for goal bootstrap")
            return {
                "event_type": "goal_contract_bootstrap",
                "project_id": resolved_project_id,
                "session_id": session_id,
                "goal_message": goal_message,
            }
        if not command_text:
            raise FeishuIngressError("command text is empty")
        payload = {
            "event_type": "command_request",
            "project_id": resolved_project_id,
            "command_text": command_text,
        }
        if resolved_thread_id:
            payload["native_thread_id"] = resolved_thread_id
        return payload
