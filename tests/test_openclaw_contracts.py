from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from watchdog.main import create_app
from watchdog.services.approvals.service import materialize_canonical_approval
from watchdog.services.delivery.envelopes import build_envelopes_for_decision
from watchdog.services.delivery.http_client import OpenClawDeliveryClient
from watchdog.services.policy.decisions import CanonicalDecisionRecord
from watchdog.settings import Settings


def _load_runtime_module():
    module_path = Path(__file__).resolve().parents[1] / "examples" / "openclaw_webhook_runtime.py"
    spec = importlib.util.spec_from_file_location("openclaw_webhook_runtime_example", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _RejectOnlyAClient:
    def list_tasks(self) -> list[dict[str, object]]:
        return []

    def decide_approval(
        self,
        approval_id: str,
        *,
        decision: str,
        operator: str,
        note: str = "",
    ) -> dict[str, object]:
        return {
            "success": True,
            "data": {
                "approval_id": approval_id,
                "decision": decision,
                "operator": operator,
                "note": note,
                "status": "approved" if decision == "approve" else "rejected",
            },
        }


def _decision(
    *,
    decision_result: str = "require_user_decision",
    action_ref: str = "execute_recovery",
    approval_id: str | None = "appr_001",
) -> CanonicalDecisionRecord:
    return CanonicalDecisionRecord(
        decision_id="decision:028",
        decision_key=(
            "session:repo-a|fact-v7|policy-v1|"
            f"{decision_result}|{action_ref}|{approval_id or ''}"
        ),
        session_id="session:repo-a",
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="thr_native_1",
        approval_id=approval_id,
        action_ref=action_ref,
        trigger="resident_supervision",
        decision_result=decision_result,
        risk_class="human_gate",
        decision_reason="manual approval required",
        matched_policy_rules=["human_gate"],
        why_not_escalated=None,
        why_escalated="manual decision required",
        uncertainty_reasons=[],
        policy_version="policy-v1",
        fact_snapshot_version="fact-v7",
        idempotency_key=(
            "session:repo-a|fact-v7|policy-v1|"
            f"{decision_result}|{action_ref}|{approval_id or ''}"
        ),
        created_at="2026-04-07T00:00:00Z",
        operator_notes=[],
        evidence={
            "facts": [],
            "matched_policy_rules": ["human_gate"],
            "decision": {
                "decision_result": decision_result,
                "action_ref": action_ref,
                "approval_id": approval_id,
            },
        },
    )


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        api_token="watchdog-token",
        data_dir=str(tmp_path),
        openclaw_webhook_base_url="http://openclaw.test",
        openclaw_webhook_token="watchdog-to-openclaw",
    )


def test_delivery_client_emits_frozen_webhook_headers_and_receipt_shape(
    tmp_path: Path,
) -> None:
    envelope = build_envelopes_for_decision(_decision(decision_result="block_and_alert", approval_id=None))[0]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer watchdog-to-openclaw"
        assert request.headers["X-Watchdog-Delivery-Id"] == envelope.envelope_id
        assert request.headers["X-Watchdog-Timestamp"]
        assert request.headers["X-Watchdog-Signature"].startswith("unsigned:")
        assert request.url.path == "/openclaw/v1/watchdog/envelopes"
        body = request.read().decode()
        assert '"envelope_type":"notification"' in body
        return httpx.Response(
            200,
            json={
                "accepted": True,
                "envelope_id": envelope.envelope_id,
                "receipt_id": "rcpt_028",
                "received_at": "2026-04-07T00:00:10Z",
            },
        )

    client = OpenClawDeliveryClient(
        settings=_settings(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    result = client.deliver_envelope(envelope)

    assert result.delivery_status == "delivered"
    assert result.receipt_id == "rcpt_028"


def test_openclaw_response_api_requires_full_contract_and_validates_token(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings=settings, a_client=_RejectOnlyAClient())
    approval = materialize_canonical_approval(
        _decision(),
        approval_store=app.state.canonical_approval_store,
    )

    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {settings.api_token}"}

        missing_fields = client.post(
            "/api/v1/watchdog/openclaw/responses",
            json={
                "envelope_id": approval.envelope_id,
                "response_action": "reject",
                "client_request_id": "req-028-missing",
            },
            headers=headers,
        )
        bad_token = client.post(
            "/api/v1/watchdog/openclaw/responses",
            json={
                "envelope_id": approval.envelope_id,
                "envelope_type": "approval",
                "approval_id": approval.approval_id,
                "decision_id": approval.decision.decision_id,
                "response_action": "reject",
                "response_token": "approval-token:wrong",
                "user_ref": "user:alice",
                "channel_ref": "feishu:chat:1",
                "client_request_id": "req-028-bad-token",
            },
            headers=headers,
        )
        accepted = client.post(
            "/api/v1/watchdog/openclaw/responses",
            json={
                "envelope_id": approval.envelope_id,
                "envelope_type": "approval",
                "approval_id": approval.approval_id,
                "decision_id": approval.decision.decision_id,
                "response_action": "reject",
                "response_token": approval.approval_token,
                "user_ref": "user:alice",
                "channel_ref": "feishu:chat:1",
                "client_request_id": "req-028-ok",
                "operator": "openclaw",
                "note": "needs narrower scope",
            },
            headers=headers,
        )

    assert missing_fields.status_code == 200
    assert missing_fields.json()["success"] is False
    assert missing_fields.json()["error"]["code"] == "INVALID_ARGUMENT"

    assert bad_token.status_code == 200
    assert bad_token.json()["success"] is False
    assert bad_token.json()["error"]["code"] == "INVALID_ARGUMENT"

    assert accepted.status_code == 200
    assert accepted.json()["success"] is True
    assert accepted.json()["data"]["approval_status"] == "rejected"


def test_reference_runtime_maps_approval_envelope_and_posts_structured_response() -> None:
    runtime_module = _load_runtime_module()
    captured: list[httpx.Request] = []
    envelope = build_envelopes_for_decision(_decision())[0].model_dump(mode="json")

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={"success": True, "data": {"approval_status": "rejected"}},
        )

    runtime = runtime_module.OpenClawWebhookRuntime(
        watchdog_base_url="http://watchdog.test",
        watchdog_api_token="watchdog-token",
        transport=httpx.MockTransport(handler),
    )

    receipt = runtime.receive_envelope(
        envelope,
        headers={
            "Authorization": "Bearer watchdog-to-openclaw",
            "X-Watchdog-Delivery-Id": envelope["envelope_id"],
            "X-Watchdog-Timestamp": "2026-04-07T00:00:10Z",
            "X-Watchdog-Signature": "unsigned:test",
        },
    )
    rendered = runtime.render_envelope(envelope)
    response = runtime.respond_to_envelope(
        envelope,
        response_action="reject",
        client_request_id="req-028-runtime",
        user_ref="user:alice",
        channel_ref="feishu:chat:1",
        note="needs narrower scope",
    )

    assert receipt["accepted"] is True
    assert receipt["envelope_id"] == envelope["envelope_id"]
    assert receipt["receipt_id"]
    assert rendered["host_behavior"] == "request_approval"
    assert rendered["response_contract"]["response_token"] == envelope["approval_token"]
    assert response["success"] is True
    assert captured[0].url.path == "/api/v1/watchdog/openclaw/responses"
    assert json.loads(captured[0].content.decode()) == {
        "envelope_id": envelope["envelope_id"],
        "envelope_type": "approval",
        "approval_id": envelope["approval_id"],
        "decision_id": envelope["correlation_id"],
        "response_action": "reject",
        "response_token": envelope["approval_token"],
        "user_ref": "user:alice",
        "channel_ref": "feishu:chat:1",
        "client_request_id": "req-028-runtime",
        "operator": "openclaw",
        "note": "needs narrower scope",
    }
