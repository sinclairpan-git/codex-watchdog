from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from watchdog.main import create_app
from watchdog.services.delivery.http_client import OpenClawDeliveryClient
from watchdog.services.delivery.envelopes import build_envelopes_for_decision
from watchdog.services.delivery.feishu_client import FeishuAppDeliveryClient
from watchdog.services.policy.decisions import CanonicalDecisionRecord
from watchdog.settings import Settings


def _decision() -> CanonicalDecisionRecord:
    return CanonicalDecisionRecord(
        decision_id="decision:repo-a:fact-v7:auto_execute_and_notify",
        decision_key="session:repo-a|fact-v7|policy-v1|auto_execute_and_notify|execute_recovery|",
        session_id="session:repo-a",
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="thr_native_1",
        approval_id=None,
        action_ref="execute_recovery",
        trigger="resident_supervision",
        decision_result="auto_execute_and_notify",
        risk_class="none",
        decision_reason="frozen feishu delivery test",
        matched_policy_rules=["registered_action"],
        why_not_escalated="policy_allows_auto_execution",
        why_escalated=None,
        uncertainty_reasons=[],
        policy_version="policy-v1",
        fact_snapshot_version="fact-v7",
        idempotency_key="session:repo-a|fact-v7|policy-v1|auto_execute_and_notify|execute_recovery|",
        created_at="2026-04-16T12:20:00Z",
        operator_notes=[],
        evidence={"facts": [], "matched_policy_rules": ["registered_action"], "decision": {}},
    )


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        api_token="watchdog-token",
        data_dir=str(tmp_path),
        delivery_transport="feishu-app",
        feishu_base_url="https://open.feishu.cn",
        feishu_app_id="cli_test_app_id",
        feishu_app_secret="test-app-secret",
        feishu_receive_id="oc_test_chat_id",
        feishu_receive_id_type="chat_id",
    )


def test_feishu_app_delivery_client_uses_tenant_token_then_sends_message(
    tmp_path: Path,
) -> None:
    envelope = build_envelopes_for_decision(_decision())[1]
    calls: list[tuple[str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        calls.append((str(request.url), body))
        if request.url.path == "/open-apis/auth/v3/tenant_access_token/internal":
            assert body == {
                "app_id": "cli_test_app_id",
                "app_secret": "test-app-secret",
            }
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "msg": "success",
                    "tenant_access_token": "tenant-token-1",
                    "expire": 7200,
                },
            )
        assert request.url.path == "/open-apis/im/v1/messages"
        assert request.url.params["receive_id_type"] == "chat_id"
        assert request.headers["Authorization"] == "Bearer tenant-token-1"
        assert body["receive_id"] == "oc_test_chat_id"
        assert body["msg_type"] == "text"
        text_payload = json.loads(body["content"])
        assert "repo-a" in text_payload["text"]
        assert envelope.summary in text_payload["text"]
        return httpx.Response(
            200,
            json={
                "code": 0,
                "msg": "success",
                "data": {"message_id": "om_feishu_message_1"},
            },
        )

    client = FeishuAppDeliveryClient(
        settings=_settings(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    result = client.deliver_envelope(envelope)

    assert result.delivery_status == "delivered"
    assert result.receipt_id == "om_feishu_message_1"
    assert len(calls) == 2


def test_create_app_uses_feishu_delivery_client_when_transport_configured(tmp_path: Path) -> None:
    app = create_app(settings=_settings(tmp_path))

    assert isinstance(app.state.delivery_client, FeishuAppDeliveryClient)


def test_create_app_accepts_documented_feishu_transport_alias(tmp_path: Path) -> None:
    app = create_app(
        settings=Settings(
            api_token="watchdog-token",
            data_dir=str(tmp_path),
            delivery_transport="feishu",
            feishu_base_url="https://open.feishu.cn",
            feishu_app_id="cli_test_app_id",
            feishu_app_secret="test-app-secret",
            feishu_receive_id="oc_test_chat_id",
            feishu_receive_id_type="chat_id",
        )
    )

    assert isinstance(app.state.delivery_client, FeishuAppDeliveryClient)


def test_create_app_keeps_openclaw_delivery_client_by_default(tmp_path: Path) -> None:
    app = create_app(
        settings=Settings(
            api_token="watchdog-token",
            data_dir=str(tmp_path),
        )
    )

    assert isinstance(app.state.delivery_client, OpenClawDeliveryClient)


def test_feishu_app_delivery_client_classifies_token_503_as_retryable_failure(
    tmp_path: Path,
) -> None:
    envelope = build_envelopes_for_decision(_decision())[1]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/open-apis/auth/v3/tenant_access_token/internal":
            return httpx.Response(503, json={"code": 99991663, "msg": "temporary unavailable"})
        raise AssertionError("message send should not be reached when token fetch fails")

    client = FeishuAppDeliveryClient(
        settings=_settings(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    result = client.deliver_envelope(envelope)

    assert result.delivery_status == "retryable_failure"
    assert result.failure_code == "http_503"


def test_create_app_rejects_unknown_delivery_transport(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsupported delivery_transport"):
        create_app(
            settings=Settings(
                api_token="watchdog-token",
                data_dir=str(tmp_path),
                delivery_transport="feishu-appp",
            )
        )


def test_feishu_app_delivery_client_treats_token_429_as_retryable_failure(tmp_path: Path) -> None:
    envelope = build_envelopes_for_decision(_decision())[1]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/open-apis/auth/v3/tenant_access_token/internal":
            return httpx.Response(429, json={"code": 99991661, "msg": "rate limited"})
        raise AssertionError("message send should not be reached when token fetch fails")

    client = FeishuAppDeliveryClient(
        settings=_settings(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    result = client.deliver_envelope(envelope)

    assert result.delivery_status == "retryable_failure"
    assert result.failure_code == "http_429"


def test_feishu_app_delivery_client_treats_malformed_2xx_body_as_retryable_protocol_failure(
    tmp_path: Path,
) -> None:
    envelope = build_envelopes_for_decision(_decision())[1]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/open-apis/auth/v3/tenant_access_token/internal":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "msg": "success",
                    "tenant_access_token": "tenant-token-2",
                    "expire": 7200,
                },
            )
        return httpx.Response(200, text="not-json")

    client = FeishuAppDeliveryClient(
        settings=_settings(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    result = client.deliver_envelope(envelope)

    assert result.delivery_status == "retryable_failure"
    assert result.failure_code == "protocol_incomplete"
