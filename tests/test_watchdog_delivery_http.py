from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from watchdog.main import create_app
from watchdog.services.delivery.envelopes import build_envelopes_for_decision
from watchdog.services.delivery.http_client import (
    DeliveryAttemptResult,
    OpenClawDeliveryClient,
)
from watchdog.services.delivery.store import DeliveryOutboxStore
from watchdog.services.delivery.worker import DeliveryWorker
from watchdog.services.policy.decisions import CanonicalDecisionRecord
from watchdog.settings import Settings


class _IdleAClient:
    def list_tasks(self) -> list[dict[str, object]]:
        return []


def _decision(
    *,
    project_id: str = "repo-a",
    session_id: str = "session:repo-a",
    fact_snapshot_version: str = "fact-v7",
    decision_result: str = "block_and_alert",
    action_ref: str = "execute_recovery",
) -> CanonicalDecisionRecord:
    return CanonicalDecisionRecord(
        decision_id=f"decision:{project_id}:{fact_snapshot_version}:{decision_result}",
        decision_key=(
            f"{session_id}|{fact_snapshot_version}|policy-v1|{decision_result}|{action_ref}|"
        ),
        session_id=session_id,
        project_id=project_id,
        thread_id=session_id,
        native_thread_id="thr_native_1",
        approval_id=None,
        action_ref=action_ref,
        trigger="resident_supervision",
        decision_result=decision_result,
        risk_class="none",
        decision_reason="frozen delivery test",
        matched_policy_rules=["registered_action"],
        why_not_escalated="policy_allows_auto_execution",
        why_escalated=None,
        uncertainty_reasons=[],
        policy_version="policy-v1",
        fact_snapshot_version=fact_snapshot_version,
        idempotency_key=(
            f"{session_id}|{fact_snapshot_version}|policy-v1|{decision_result}|{action_ref}|"
        ),
        created_at="2026-04-07T00:00:00Z",
        operator_notes=[],
        evidence={"facts": [], "matched_policy_rules": ["registered_action"], "decision": {}},
    )


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=str(tmp_path),
        openclaw_webhook_base_url="http://openclaw.test",
        openclaw_webhook_token="watchdog-token",
        delivery_initial_backoff_seconds=5.0,
        delivery_max_attempts=3,
        progress_summary_max_age_seconds=315360000.0,
        auto_execute_notification_max_age_seconds=315360000.0,
    )


def test_http_delivery_accepts_only_complete_receipt_protocol(tmp_path: Path) -> None:
    envelope = build_envelopes_for_decision(_decision())[0]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer watchdog-token"
        assert request.headers["X-Watchdog-Delivery-Id"] == envelope.envelope_id
        return httpx.Response(
            200,
            json={
                "accepted": True,
                "envelope_id": envelope.envelope_id,
                "receipt_id": "rcpt_001",
                "received_at": "2026-04-07T00:00:10Z",
            },
        )

    client = OpenClawDeliveryClient(
        settings=_settings(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    result = client.deliver_envelope(envelope)

    assert result.delivery_status == "delivered"
    assert result.receipt_id == "rcpt_001"


def test_http_delivery_treats_incomplete_2xx_protocol_as_retryable_failure(tmp_path: Path) -> None:
    envelope = build_envelopes_for_decision(_decision())[0]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "accepted": True,
                "envelope_id": envelope.envelope_id,
                "received_at": "2026-04-07T00:00:10Z",
            },
        )

    client = OpenClawDeliveryClient(
        settings=_settings(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    result = client.deliver_envelope(envelope)

    assert result.delivery_status == "retryable_failure"
    assert result.failure_code == "protocol_incomplete"


def test_http_delivery_requires_received_at_for_success(tmp_path: Path) -> None:
    envelope = build_envelopes_for_decision(_decision())[0]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "accepted": True,
                "envelope_id": envelope.envelope_id,
                "receipt_id": "rcpt_001",
            },
        )

    client = OpenClawDeliveryClient(
        settings=_settings(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    result = client.deliver_envelope(envelope)

    assert result.delivery_status == "retryable_failure"
    assert result.failure_code == "protocol_incomplete"


def test_http_delivery_treats_retryable_transport_failures_as_retryable(tmp_path: Path) -> None:
    envelope = build_envelopes_for_decision(_decision())[0]

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    client = OpenClawDeliveryClient(
        settings=_settings(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    result = client.deliver_envelope(envelope)

    assert result.delivery_status == "retryable_failure"
    assert result.failure_code == "transport_timeout"


def test_http_delivery_prefers_persisted_openclaw_webhook_endpoint_over_env(tmp_path: Path) -> None:
    envelope = build_envelopes_for_decision(_decision())[0]
    (tmp_path / "openclaw_webhook_endpoint.json").write_text(
        json.dumps(
            {
                "openclaw_webhook_base_url": "https://dynamic-openclaw.example",
                "updated_at": "2026-04-07T11:00:00Z",
                "changed_at": "2026-04-07T10:59:59Z",
                "source": "b-host-openclaw",
            }
        ),
        encoding="utf-8",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://dynamic-openclaw.example/openclaw/v1/watchdog/envelopes"
        return httpx.Response(
            200,
            json={
                "accepted": True,
                "envelope_id": envelope.envelope_id,
                "receipt_id": "rcpt_dynamic_001",
                "received_at": "2026-04-07T00:00:10Z",
            },
        )

    client = OpenClawDeliveryClient(
        settings=_settings(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    result = client.deliver_envelope(envelope)

    assert result.delivery_status == "delivered"
    assert result.receipt_id == "rcpt_dynamic_001"


class _AlwaysRetryClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def deliver_record(self, record) -> DeliveryAttemptResult:
        self.calls.append(record.envelope_id)
        return DeliveryAttemptResult(
            envelope_id=record.envelope_id,
            delivery_status="retryable_failure",
            failure_code="upstream_503",
            accepted=False,
        )


def test_delivery_worker_applies_backoff_and_marks_failed_after_max_attempts(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    record = store.enqueue_envelopes(build_envelopes_for_decision(_decision()))[0]
    client = _AlwaysRetryClient()
    worker = DeliveryWorker(store=store, delivery_client=client, settings=settings)

    first = worker.process_next_ready(
        now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=timezone.utc),
        session_id=record.session_id,
    )
    second = worker.process_next_ready(
        now=datetime(2026, 4, 7, 0, 0, 6, tzinfo=timezone.utc),
        session_id=record.session_id,
    )
    third = worker.process_next_ready(
        now=datetime(2026, 4, 7, 0, 0, 17, tzinfo=timezone.utc),
        session_id=record.session_id,
    )

    assert first.delivery_status == "retrying"
    assert first.delivery_attempt == 1
    assert first.next_retry_at == "2026-04-07T00:00:05Z"

    assert second.delivery_status == "retrying"
    assert second.delivery_attempt == 2
    assert second.next_retry_at == "2026-04-07T00:00:16Z"

    assert third.delivery_status == "delivery_failed"
    assert third.delivery_attempt == 3
    assert third.failure_code == "upstream_503"
    assert client.calls == [record.envelope_id, record.envelope_id, record.envelope_id]


def test_background_delivery_worker_drains_pending_outbox_records(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings, a_client=_IdleAClient(), start_background_workers=True)
    records = app.state.delivery_outbox_store.enqueue_envelopes(
        build_envelopes_for_decision(_decision())
    )
    calls: list[str] = []

    class _DeliveredClient:
        def deliver_record(self, pending_record) -> DeliveryAttemptResult:
            calls.append(pending_record.envelope_id)
            return DeliveryAttemptResult(
                envelope_id=pending_record.envelope_id,
                delivery_status="delivered",
                accepted=True,
                receipt_id="rcpt_001",
            )

    app.state.delivery_worker._delivery_client = _DeliveredClient()

    with TestClient(app):
        time.sleep(0.05)

    delivered = [
        app.state.delivery_outbox_store.get_delivery_record(record.envelope_id) for record in records
    ]
    assert [record.delivery_status for record in delivered] == ["delivered"]
    assert [record.receipt_id for record in delivered] == ["rcpt_001"]
    assert calls == [record.envelope_id for record in records]
