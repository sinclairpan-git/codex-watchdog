from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from watchdog.main import create_app
from watchdog.services.delivery.http_client import OpenClawDeliveryClient
from watchdog.services.delivery.envelopes import NotificationEnvelope, build_envelopes_for_decision
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


def test_feishu_app_delivery_client_uses_envelope_receive_target_when_static_target_missing(
    tmp_path: Path,
) -> None:
    envelope = build_envelopes_for_decision(_decision())[1].model_copy(
        update={"receive_id": "ou_dynamic_operator", "receive_id_type": "open_id"}
    )
    settings = _settings(tmp_path).model_copy(update={"feishu_receive_id": None})
    calls: list[tuple[str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        calls.append((str(request.url), body))
        if request.url.path == "/open-apis/auth/v3/tenant_access_token/internal":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "msg": "success",
                    "tenant_access_token": "tenant-token-dynamic",
                    "expire": 7200,
                },
            )
        assert request.url.path == "/open-apis/im/v1/messages"
        assert request.url.params["receive_id_type"] == "open_id"
        assert request.headers["Authorization"] == "Bearer tenant-token-dynamic"
        assert body["receive_id"] == "ou_dynamic_operator"
        return httpx.Response(
            200,
            json={
                "code": 0,
                "msg": "success",
                "data": {"message_id": "om_feishu_message_dynamic"},
            },
        )

    client = FeishuAppDeliveryClient(
        settings=settings,
        transport=httpx.MockTransport(handler),
    )

    result = client.deliver_envelope(envelope)

    assert result.delivery_status == "delivered"
    assert result.receipt_id == "om_feishu_message_dynamic"
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


def test_feishu_render_text_formats_progress_update_for_human_reading(tmp_path: Path) -> None:
    envelope = NotificationEnvelope(
        envelope_id="notification-envelope:progress-readable",
        envelope_type="notification",
        event_id="event:progress-readable",
        correlation_id="corr:progress-readable",
        project_id="repo-a",
        session_id="session:repo-a",
        native_thread_id="thr_native_1",
        notification_kind="progress_summary",
        severity="info",
        title="progress update",
        summary="正在补齐飞书通知文案。",
        reason=(
            "phase=coding; context=critical; stuck=4; "
            "files=src/watchdog/services/delivery/feishu_client.py"
        ),
        occurred_at="2026-04-16T12:30:00Z",
        policy_version="policy-v1",
        fact_snapshot_version="fact-v8",
        idempotency_key="idem:progress-readable",
        audit_ref="audit:progress-readable",
        created_at="2026-04-16T12:30:00Z",
    )

    rendered = FeishuAppDeliveryClient(settings=_settings(tmp_path))._render_text(envelope)

    assert "Watchdog 任务进展更新" in rendered
    assert "发生了什么：正在补齐飞书通知文案。" in rendered
    assert (
        "系统参考：当前处于 coding 阶段；上下文压力为 critical；"
        "卡点等级为 4；涉及文件 src/watchdog/services/delivery/feishu_client.py"
    ) in rendered
    assert "phase=" not in rendered
    assert "context=" not in rendered
    assert "stuck=" not in rendered


def test_feishu_render_text_formats_approval_for_human_reading(tmp_path: Path) -> None:
    envelope = build_envelopes_for_decision(
        _decision().model_copy(
            update={
                "decision_result": "require_user_decision",
                "risk_class": "human_gate",
                "approval_id": "appr_001",
                "action_ref": "continue_session",
                "decision_reason": "session requires explicit human decision",
                "why_not_escalated": None,
                "why_escalated": "human gate matched",
            }
        )
    )[0]

    text = FeishuAppDeliveryClient(settings=_settings(tmp_path))._render_text(envelope)

    assert "Watchdog 需要你确认一项操作" in text
    assert "项目：repo-a" in text
    assert "会话：repo-a" in text
    assert "待确认操作：继续当前任务" in text
    assert "你现在可以这样干预：回复“批准”、“拒绝”或“直接执行”" in text
    assert "project=" not in text
    assert "session=" not in text
    assert "requested_action=" not in text
    assert "options=" not in text


def test_feishu_render_text_formats_decision_notification_for_human_reading(
    tmp_path: Path,
) -> None:
    envelope = build_envelopes_for_decision(_decision())[1]

    text = FeishuAppDeliveryClient(settings=_settings(tmp_path))._render_text(envelope)

    assert "Watchdog 自动决策更新" in text
    assert "自动决策：已自动执行「执行恢复流程」" in text
    assert "决策依据：frozen feishu delivery test" in text
    assert "你现在可以这样干预：回复“状态”查看详情，或回复“人工接管”" in text
    assert "decision=" not in text
    assert "action=" not in text
    assert "notification_kind=" not in text


def test_feishu_render_text_humanizes_progress_reason_key_values(tmp_path: Path) -> None:
    envelope = NotificationEnvelope(
        envelope_id="notification-envelope:test-progress",
        correlation_id="corr:test-progress",
        session_id="session:repo-a",
        project_id="repo-a",
        native_thread_id="thr_native_1",
        policy_version="policy-v1",
        fact_snapshot_version="fact-v8",
        idempotency_key="idem:test-progress",
        audit_ref="audit:test-progress",
        created_at="2026-04-17T12:20:00Z",
        event_id="event:test-progress",
        severity="warning",
        notification_kind="progress_summary",
        occurred_at="2026-04-17T12:20:00Z",
        title="progress update for repo-a",
        summary="正在补齐飞书通知文案。",
        reason="phase=coding; context=critical; stuck=4; files=src/watchdog/services/delivery/feishu_client.py",
    )

    text = FeishuAppDeliveryClient(settings=_settings(tmp_path))._render_text(envelope)

    assert "Watchdog 任务进展更新" in text
    assert "发生了什么：正在补齐飞书通知文案。" in text
    assert "系统参考：当前处于 coding 阶段；上下文压力为 critical；卡点等级为 4；涉及文件 src/watchdog/services/delivery/feishu_client.py" in text
    assert "phase=" not in text
    assert "context=" not in text
    assert "stuck=" not in text
