from __future__ import annotations

import importlib.util
import json
import logging
import warnings
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from pydantic import ValidationError

from watchdog.services.delivery.envelopes import (
    SESSION_DIRECTORY_PROJECT_ID,
    SESSION_DIRECTORY_SESSION_ID,
)
from watchdog.services.feishu_control import FeishuControlError, FeishuControlService
from watchdog.services.feishu_ingress.service import (
    FeishuIngressError,
    FeishuIngressNormalizationService,
    FeishuMessageCallback,
)
from watchdog.services.session_service import SessionService
from watchdog.settings import Settings

logger = logging.getLogger(__name__)


@contextmanager
def _suppress_lark_oapi_import_warnings():
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"websockets\.InvalidStatusCode is deprecated",
            category=DeprecationWarning,
        )
        warnings.filterwarnings(
            "ignore",
            message=r"websockets\.legacy is deprecated;.*",
            category=DeprecationWarning,
        )
        yield


class FeishuLongConnectionConfigError(RuntimeError):
    pass


class FeishuLongConnectionGateway:
    def __init__(
        self,
        *,
        settings: Settings,
        ingress: FeishuIngressNormalizationService,
        control_service: FeishuControlService,
        session_service: SessionService,
    ) -> None:
        self._settings = settings
        self._ingress = ingress
        self._control_service = control_service
        self._session_service = session_service

    @classmethod
    def from_app(cls, app: FastAPI) -> "FeishuLongConnectionGateway":
        return cls(
            settings=app.state.settings,
            ingress=FeishuIngressNormalizationService(
                settings=app.state.settings,
                client=app.state.runtime_client,
                session_spine_store=app.state.session_spine_store,
            ),
            control_service=FeishuControlService(
                settings=app.state.settings,
                client=app.state.runtime_client,
                receipt_store=app.state.action_receipt_store,
                approval_store=app.state.canonical_approval_store,
                response_store=app.state.approval_response_store,
                delivery_outbox_store=app.state.delivery_outbox_store,
                session_service=app.state.session_service,
            ),
            session_service=app.state.session_service,
        )

    def handle_message_event(self, payload: object) -> dict[str, object]:
        body = self._canonicalize_payload_for_long_connection(payload)
        refs = self._extract_message_actor_refs(body)
        logger.info(
            "feishu long-connection message received: chat_id=%s sender_open_id=%s",
            refs["chat_id"],
            refs["sender_open_id"],
        )
        event = FeishuMessageCallback.model_validate(body)
        normalized = self._ingress.normalize_message_event(event)
        result = self._control_service.handle_request(normalized)
        return {
            "accepted": True,
            "event_type": normalized.event_type,
            "chat_id": refs["chat_id"],
            "sender_open_id": refs["sender_open_id"],
            "data": result.model_dump(mode="json") if hasattr(result, "model_dump") else result,
        }

    def handle_bot_p2p_chat_entered_event(self, payload: object) -> dict[str, str]:
        body = self._canonicalize_payload_for_long_connection(payload)
        self._validate_callback_token(body)
        header = body.get("header")
        event_id = ""
        event = body.get("event")
        chat_id = ""
        operator_open_id = ""
        if isinstance(header, dict):
            event_id = str(header.get("event_id") or "").strip()
        if isinstance(event, dict):
            chat_id = str(event.get("chat_id") or "").strip()
            operator = event.get("operator_id")
            if isinstance(operator, dict):
                operator_open_id = str(operator.get("open_id") or "").strip()
        logger.info(
            "feishu long-connection p2p chat entered: chat_id=%s operator_open_id=%s",
            chat_id,
            operator_open_id,
        )
        related_ids: dict[str, str] = {}
        if event_id:
            related_ids["feishu_event_id"] = event_id
        if chat_id:
            related_ids["feishu_receive_id"] = chat_id
            related_ids["feishu_receive_id_type"] = "chat_id"
            related_ids["feishu_chat_id"] = chat_id
        if operator_open_id:
            related_ids["feishu_actor_id"] = operator_open_id
        correlation_seed = event_id or chat_id or operator_open_id or "feishu-p2p-entered"
        self._session_service.record_event_once(
            event_type="feishu_command_route_bound",
            project_id=SESSION_DIRECTORY_PROJECT_ID,
            session_id=SESSION_DIRECTORY_SESSION_ID,
            correlation_id=f"corr:feishu-portfolio-route:{correlation_seed}",
            causation_id=event_id or None,
            related_ids=related_ids,
            occurred_at=self._event_occurred_at(body),
            payload={
                "channel_kind": "feishu_long_connection",
                "command_text": "",
                "intent_code": "portfolio_route_binding",
            },
        )
        return {
            "accepted": "true",
            "chat_id": chat_id,
            "operator_open_id": operator_open_id,
        }

    def handle_card_action_callback(self, payload: object) -> dict[str, object]:
        body = self._canonicalize_payload_for_long_connection(payload)
        self._validate_callback_token(body)
        event_id = str(body.get("header", {}).get("event_id") or "").strip()
        logger.info("feishu long-connection card callback acknowledged: event_id=%s", event_id)
        return {
            "toast": {
                "type": "info",
                "content": "Watchdog 当前未启用飞书卡片动作回调。",
            }
        }

    def handle_url_preview_callback(self, payload: object) -> dict[str, object]:
        body = self._canonicalize_payload_for_long_connection(payload)
        self._validate_callback_token(body)
        event_id = str(body.get("header", {}).get("event_id") or "").strip()
        logger.info("feishu long-connection url preview callback acknowledged: event_id=%s", event_id)
        return {}

    def _validate_callback_token(self, payload: dict[str, Any]) -> None:
        header = payload.get("header")
        token = None
        if isinstance(header, dict):
            token = header.get("token")
        self._ingress.validate_event_token(str(token or ""))

    def _canonicalize_payload_for_long_connection(self, payload: object) -> dict[str, Any]:
        body = self._sdk_payload_to_mapping(payload)
        header = body.get("header")
        if isinstance(header, dict) and not str(header.get("token") or "").strip():
            expected = str(self._settings.feishu_verification_token or "").strip()
            if expected:
                header["token"] = expected
        return body

    @staticmethod
    def _extract_message_actor_refs(payload: dict[str, Any]) -> dict[str, str]:
        event = payload.get("event")
        if not isinstance(event, dict):
            return {"chat_id": "", "sender_open_id": ""}
        message = event.get("message")
        sender = event.get("sender")
        sender_id = sender.get("sender_id") if isinstance(sender, dict) else None
        return {
            "chat_id": str(message.get("chat_id") or "").strip() if isinstance(message, dict) else "",
            "sender_open_id": (
                str(sender_id.get("open_id") or "").strip() if isinstance(sender_id, dict) else ""
            ),
        }

    @staticmethod
    def _event_occurred_at(payload: dict[str, Any]) -> str | None:
        header = payload.get("header")
        if not isinstance(header, dict):
            return None
        raw_create_time = str(header.get("create_time") or "").strip()
        if not raw_create_time:
            return None
        try:
            if len(raw_create_time) >= 13:
                parsed = datetime.fromtimestamp(int(raw_create_time) / 1000, tz=UTC)
            else:
                parsed = datetime.fromtimestamp(int(raw_create_time), tz=UTC)
        except (TypeError, ValueError, OSError):
            return None
        return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    @staticmethod
    def sdk_available() -> bool:
        return importlib.util.find_spec("lark_oapi") is not None

    @staticmethod
    def _sdk_payload_to_mapping(payload: object) -> dict[str, Any]:
        try:
            with _suppress_lark_oapi_import_warnings():
                from lark_oapi.core.json import JSON
        except ImportError as exc:
            raise FeishuLongConnectionConfigError(
                "lark-oapi is required for Feishu long-connection mode"
            ) from exc

        raw = JSON.marshal(payload)
        if raw is None:
            raise FeishuLongConnectionConfigError("feishu long-connection payload is empty")
        try:
            body = json.loads(raw)
        except ValueError as exc:
            raise FeishuLongConnectionConfigError(
                "feishu long-connection payload is not valid json"
            ) from exc
        if not isinstance(body, dict):
            raise FeishuLongConnectionConfigError(
                "feishu long-connection payload must be a json object"
            )
        return body


class FeishuLongConnectionRuntime:
    def __init__(
        self,
        *,
        settings: Settings,
        gateway: FeishuLongConnectionGateway,
    ) -> None:
        self._settings = settings
        self._gateway = gateway

    def validate_configuration(self) -> None:
        if not self._settings.feishu_long_connection_enabled():
            raise FeishuLongConnectionConfigError(
                "feishu long-connection mode is not enabled"
            )
        missing_fields = [
            field_name
            for field_name, value in (
                ("feishu_app_id", self._settings.feishu_app_id),
                ("feishu_app_secret", self._settings.feishu_app_secret),
                ("feishu_verification_token", self._settings.feishu_verification_token),
            )
            if not str(value or "").strip()
        ]
        if missing_fields:
            raise FeishuLongConnectionConfigError(
                f"missing required Feishu long-connection settings: {', '.join(missing_fields)}"
            )
        if not self._gateway.sdk_available():
            raise FeishuLongConnectionConfigError(
                "lark-oapi is required for Feishu long-connection mode"
            )

    def run_forever(self) -> None:
        self.validate_configuration()
        dispatcher = self._build_dispatcher()
        try:
            with _suppress_lark_oapi_import_warnings():
                import lark_oapi as lark
        except ImportError as exc:
            raise FeishuLongConnectionConfigError(
                "lark-oapi is required for Feishu long-connection mode"
            ) from exc

        logger.info(
            "starting Feishu long-connection runtime: event_mode=%s callback_mode=%s",
            self._settings.feishu_event_ingress_mode,
            self._settings.feishu_callback_ingress_mode,
        )
        client = lark.ws.Client(
            self._settings.feishu_app_id,
            self._settings.feishu_app_secret,
            event_handler=dispatcher,
            domain=self._settings.feishu_base_url,
        )
        client.start()

    def _build_dispatcher(self):
        try:
            with _suppress_lark_oapi_import_warnings():
                import lark_oapi as lark
        except ImportError as exc:
            raise FeishuLongConnectionConfigError(
                "lark-oapi is required for Feishu long-connection mode"
            ) from exc

        builder = lark.EventDispatcherHandler.builder(
            "",
            str(self._settings.feishu_verification_token or "").strip(),
        )
        if self._settings.feishu_event_ingress_mode == "long_connection":
            builder.register_p2_im_message_receive_v1(self._handle_message_event)
            builder.register_p2_im_message_message_read_v1(self._handle_message_read_event)
            builder.register_p2_im_chat_access_event_bot_p2p_chat_entered_v1(
                self._handle_bot_p2p_chat_entered_event
            )
        if self._settings.feishu_callback_ingress_mode == "long_connection":
            builder.register_p2_card_action_trigger(self._handle_card_action_callback)
            builder.register_p2_url_preview_get(self._handle_url_preview_callback)
        return builder.build()

    def _handle_message_event(self, payload: object) -> None:
        try:
            result = self._gateway.handle_message_event(payload)
        except (FeishuIngressError, FeishuControlError, ValidationError, ValueError, KeyError) as exc:
            logger.warning("feishu long-connection message rejected: %s", exc)
            raise
        logger.info(
            "feishu long-connection message accepted: event_type=%s chat_id=%s sender_open_id=%s",
            result["event_type"],
            result["chat_id"],
            result["sender_open_id"],
        )

    def _handle_bot_p2p_chat_entered_event(self, payload: object) -> None:
        try:
            result = self._gateway.handle_bot_p2p_chat_entered_event(payload)
        except (FeishuIngressError, ValidationError, ValueError, KeyError) as exc:
            logger.warning("feishu long-connection p2p chat enter rejected: %s", exc)
            raise
        logger.info(
            "feishu long-connection p2p chat entered accepted: chat_id=%s operator_open_id=%s",
            result["chat_id"],
            result["operator_open_id"],
        )

    def _handle_message_read_event(self, payload: object) -> None:
        try:
            body = self._gateway._canonicalize_payload_for_long_connection(payload)
        except (FeishuIngressError, ValidationError, ValueError, KeyError) as exc:
            logger.warning("feishu long-connection message_read ignored after parse failure: %s", exc)
            return
        refs = self._gateway._extract_message_actor_refs(body)
        logger.debug(
            "feishu long-connection message_read ignored: chat_id=%s sender_open_id=%s",
            refs["chat_id"],
            refs["sender_open_id"],
        )

    def _handle_card_action_callback(self, payload: object):
        try:
            with _suppress_lark_oapi_import_warnings():
                from lark_oapi.event.callback.model.p2_card_action_trigger import (
                    P2CardActionTriggerResponse,
                )
        except ImportError as exc:
            raise FeishuLongConnectionConfigError(
                "lark-oapi is required for Feishu long-connection mode"
            ) from exc
        return P2CardActionTriggerResponse(self._gateway.handle_card_action_callback(payload))

    def _handle_url_preview_callback(self, payload: object):
        try:
            with _suppress_lark_oapi_import_warnings():
                from lark_oapi.event.callback.model.p2_url_preview_get import (
                    P2URLPreviewGetResponse,
                )
        except ImportError as exc:
            raise FeishuLongConnectionConfigError(
                "lark-oapi is required for Feishu long-connection mode"
            ) from exc
        return P2URLPreviewGetResponse(self._gateway.handle_url_preview_callback(payload))
