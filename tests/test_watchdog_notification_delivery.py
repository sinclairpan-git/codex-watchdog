from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from watchdog.services.delivery.envelopes import NotificationEnvelope
from watchdog.services.delivery.models import DeliveryAttemptResult
from watchdog.services.delivery.store import DeliveryOutboxStore
from watchdog.services.delivery.worker import DeliveryWorker
from watchdog.services.session_service import SessionService, SessionServiceStore
from watchdog.settings import Settings


class _SuccessClient:
    def deliver_record(self, record) -> DeliveryAttemptResult:
        return DeliveryAttemptResult(
            envelope_id=record.envelope_id,
            delivery_status="delivered",
            accepted=True,
            status_code=200,
            failure_code=None,
            receipt_id="receipt-1",
            received_at="2026-04-07T00:20:02Z",
        )


class _RetryableFailureClient:
    def deliver_record(self, record) -> DeliveryAttemptResult:
        return DeliveryAttemptResult(
            envelope_id=record.envelope_id,
            delivery_status="retryable_failure",
            accepted=False,
            status_code=503,
            failure_code="upstream_503",
            receipt_id=None,
            received_at=None,
        )


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        api_token="watchdog-token",
        data_dir=str(tmp_path),
    )


def _notification_with_interaction(
    *,
    interaction_context_id: str = "ctx-notify-1",
    interaction_family_id: str = "family-notify-1",
) -> NotificationEnvelope:
    return NotificationEnvelope(
        envelope_id=f"notification-envelope:{interaction_context_id}",
        correlation_id=f"notification:{interaction_context_id}",
        session_id="session:repo-a",
        project_id="repo-a",
        native_thread_id="thr_native_1",
        policy_version="policy-v1",
        fact_snapshot_version="fact-v7",
        idempotency_key=f"session:repo-a|fact-v7|progress_summary|{interaction_context_id}",
        audit_ref=f"audit:{interaction_context_id}",
        created_at="2026-04-07T00:20:00Z",
        occurred_at="2026-04-07T00:20:00Z",
        event_id=f"event:{interaction_context_id}",
        severity="info",
        notification_kind="progress_summary",
        title="progress update for repo-a",
        summary="still coding locally",
        reason="phase=editing_source; context=low; stuck=0",
        interaction_context_id=interaction_context_id,
        interaction_family_id=interaction_family_id,
        actor_id="user:carol",
        channel_kind="dm",
        action_window_expires_at="2026-04-07T00:30:00Z",
    )


def test_delivery_worker_carries_interaction_metadata_into_notification_events(
    tmp_path: Path,
) -> None:
    service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    (record,) = store.enqueue_envelopes([_notification_with_interaction()])
    worker = DeliveryWorker(
        store=store,
        delivery_client=_SuccessClient(),
        settings=_settings(tmp_path),
        session_service=service,
    )

    delivered = worker.process_next_ready(
        now=datetime(2026, 4, 7, 0, 20, 1, tzinfo=timezone.utc),
        session_id="session:repo-a",
    )

    assert delivered is not None
    events = service.list_events(
        session_id="session:repo-a",
        related_id_key="envelope_id",
        related_id_value=record.envelope_id,
    )
    assert [event.event_type for event in events] == [
        "notification_announced",
        "notification_delivery_succeeded",
        "notification_receipt_recorded",
    ]
    for event in events:
        assert event.related_ids["interaction_context_id"] == "ctx-notify-1"
        assert event.related_ids["interaction_family_id"] == "family-notify-1"
        assert event.related_ids["actor_id"] == "user:carol"


def test_delivery_worker_preserves_interaction_metadata_on_retryable_requeue(
    tmp_path: Path,
) -> None:
    service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    store = DeliveryOutboxStore(tmp_path / "delivery_outbox.json")
    (record,) = store.enqueue_envelopes(
        [_notification_with_interaction(interaction_context_id="ctx-notify-retry")]
    )
    worker = DeliveryWorker(
        store=store,
        delivery_client=_RetryableFailureClient(),
        settings=_settings(tmp_path),
        session_service=service,
    )

    retried = worker.process_next_ready(
        now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=timezone.utc),
        session_id="session:repo-a",
    )

    assert retried is not None
    events = service.list_events(
        session_id="session:repo-a",
        related_id_key="envelope_id",
        related_id_value=record.envelope_id,
    )
    assert [event.event_type for event in events] == [
        "notification_announced",
        "notification_delivery_failed",
        "notification_requeued",
    ]
    assert events[2].related_ids["interaction_context_id"] == "ctx-notify-retry"
    assert events[2].related_ids["interaction_family_id"] == "family-notify-1"
    assert events[2].payload["reason"] == "retryable_delivery_failure"
