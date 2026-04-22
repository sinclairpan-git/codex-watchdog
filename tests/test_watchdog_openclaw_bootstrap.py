from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from watchdog.main import create_app
from watchdog.services.delivery.envelopes import build_envelopes_for_decision
from watchdog.services.delivery.openclaw_webhook_store import (
    OpenClawWebhookEndpointStore,
    openclaw_webhook_endpoint_state_path,
)
from watchdog.services.delivery.store import DeliveryOutboxStore
from watchdog.services.policy.decisions import CanonicalDecisionRecord
from watchdog.settings import Settings


class _ClientStub:
    def get_envelope(self, project_id: str) -> dict[str, object]:
        raise AssertionError(project_id)

    def get_envelope_by_thread(self, thread_id: str) -> dict[str, object]:
        raise AssertionError(thread_id)

    def list_tasks(self) -> list[dict[str, object]]:
        return []

    def list_approvals(self, **_: object) -> list[dict[str, object]]:
        return []


def _decision_record(
    *,
    project_id: str = "repo-a",
    session_id: str = "session:repo-a",
    fact_snapshot_version: str = "fact-v7",
    decision_result: str = "require_user_decision",
) -> CanonicalDecisionRecord:
    return CanonicalDecisionRecord(
        decision_id=f"decision:{project_id}:{fact_snapshot_version}:{decision_result}",
        decision_key=(
            f"{session_id}|{fact_snapshot_version}|policy-v1|{decision_result}|execute_recovery|"
        ),
        session_id=session_id,
        project_id=project_id,
        thread_id=session_id,
        native_thread_id=f"native:{project_id}",
        approval_id=None,
        action_ref="execute_recovery",
        trigger="resident_supervision",
        decision_result=decision_result,
        risk_class="human_gate",
        decision_reason="critical block" if decision_result == "block_and_alert" else "manual approval required",
        matched_policy_rules=["registered_action"],
        why_not_escalated=None,
        why_escalated="critical block" if decision_result == "block_and_alert" else "manual decision required",
        uncertainty_reasons=[],
        policy_version="policy-v1",
        fact_snapshot_version=fact_snapshot_version,
        idempotency_key=(
            f"{session_id}|{fact_snapshot_version}|policy-v1|{decision_result}|execute_recovery|"
        ),
        created_at="2026-04-07T00:00:00Z",
        operator_notes=[],
        evidence={
            "facts": [
                {
                    "fact_id": "fact-1",
                    "fact_code": "recovery_available",
                    "fact_kind": "signal",
                    "severity": "info",
                    "summary": "recovery available",
                    "detail": "recovery available",
                    "source": "watchdog",
                    "observed_at": "2026-04-07T00:00:00Z",
                    "related_ids": {},
                }
            ],
            "matched_policy_rules": ["registered_action"],
            "decision": {
                "decision_result": decision_result,
                "action_ref": "execute_recovery",
                "approval_id": None,
            },
        },
    )


def test_bootstrap_openclaw_webhook_records_notification_requeue_event(tmp_path: Path) -> None:
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=_ClientStub(),
    )
    delivery_store: DeliveryOutboxStore = app.state.delivery_outbox_store
    client = TestClient(app)

    (notification_record,) = delivery_store.enqueue_envelopes(
        [build_envelopes_for_decision(_decision_record(decision_result="block_and_alert"))[0]]
    )
    delivery_store.update_delivery_record(
        notification_record.model_copy(
            update={
                "delivery_status": "delivery_failed",
                "delivery_attempt": 3,
                "failure_code": "transport_error",
                "next_retry_at": None,
                "operator_notes": ["delivery_dead_letter failure_code=transport_error attempts=3"],
                "envelope_payload": {
                    **notification_record.envelope_payload,
                    "interaction_context_id": "ctx-bootstrap-1",
                    "interaction_family_id": "family-bootstrap-1",
                    "actor_id": "user:bootstrap",
                    "channel_kind": "dm",
                    "action_window_expires_at": "2026-04-07T00:30:00Z",
                },
            }
        )
    )

    response = client.post(
        "/api/v1/watchdog/bootstrap/openclaw-webhook",
        headers={"Authorization": "Bearer wt"},
        json={
            "event_type": "openclaw_webhook_base_url_changed",
            "openclaw_webhook_base_url": "https://updated-openclaw.trycloudflare.com",
            "changed_at": "2026-04-07T19:00:00+08:00",
            "source": "b-host-openclaw",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["accepted"] is True

    retried = delivery_store.get_delivery_record(notification_record.envelope_id)
    assert retried is not None
    assert retried.delivery_status == "pending"
    assert retried.delivery_attempt == 0
    assert retried.failure_code is None
    assert retried.operator_notes[-1] == (
        "delivery_requeued reason=openclaw_webhook_base_url_changed "
        "previous_failure_code=transport_error"
    )

    events = app.state.session_service.list_events(
        session_id=notification_record.session_id,
        related_id_key="envelope_id",
        related_id_value=notification_record.envelope_id,
    )
    assert [event.event_type for event in events] == ["notification_requeued"]
    assert events[0].payload["reason"] == "openclaw_webhook_base_url_changed"
    assert events[0].payload["failure_code"] == "transport_error"
    assert events[0].payload["delivery_status"] == "pending"
    assert events[0].payload["delivery_attempt"] == 0
    assert events[0].related_ids["native_thread_id"] == "native:repo-a"
    assert events[0].related_ids["interaction_context_id"] == "ctx-bootstrap-1"
    assert events[0].related_ids["interaction_family_id"] == "family-bootstrap-1"
    assert events[0].related_ids["actor_id"] == "user:bootstrap"
    assert events[0].payload["interaction_context_id"] == "ctx-bootstrap-1"
    assert events[0].payload["interaction_family_id"] == "family-bootstrap-1"
    assert events[0].payload["actor_id"] == "user:bootstrap"


def test_bootstrap_openclaw_webhook_requeue_event_uses_effective_native_thread_from_legacy_delivery_record(
    tmp_path: Path,
) -> None:
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=_ClientStub(),
    )
    delivery_store: DeliveryOutboxStore = app.state.delivery_outbox_store
    client = TestClient(app)

    (notification_record,) = delivery_store.enqueue_envelopes(
        [build_envelopes_for_decision(_decision_record(decision_result="block_and_alert"))[0]]
    )
    delivery_store.update_delivery_record(
        notification_record.model_copy(
            update={
                "native_thread_id": None,
                "delivery_status": "delivery_failed",
                "delivery_attempt": 3,
                "failure_code": "transport_error",
                "next_retry_at": None,
                "operator_notes": ["delivery_dead_letter failure_code=transport_error attempts=3"],
                "envelope_payload": {
                    **notification_record.envelope_payload,
                    "interaction_context_id": "ctx-bootstrap-1",
                    "interaction_family_id": "family-bootstrap-1",
                    "actor_id": "user:bootstrap",
                    "channel_kind": "dm",
                    "action_window_expires_at": "2026-04-07T00:30:00Z",
                },
            }
        )
    )

    response = client.post(
        "/api/v1/watchdog/bootstrap/openclaw-webhook",
        headers={"Authorization": "Bearer wt"},
        json={
            "event_type": "openclaw_webhook_base_url_changed",
            "openclaw_webhook_base_url": "https://updated-openclaw.trycloudflare.com",
            "changed_at": "2026-04-07T19:00:00+08:00",
            "source": "b-host-openclaw",
        },
    )

    assert response.status_code == 200
    events = app.state.session_service.list_events(
        session_id=notification_record.session_id,
        related_id_key="envelope_id",
        related_id_value=notification_record.envelope_id,
    )
    assert [event.event_type for event in events] == ["notification_requeued"]
    assert events[0].related_ids["native_thread_id"] == "native:repo-a"


def test_bootstrap_openclaw_webhook_allows_repeated_notification_requeue_events(
    tmp_path: Path,
) -> None:
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=_ClientStub(),
    )
    delivery_store: DeliveryOutboxStore = app.state.delivery_outbox_store
    client = TestClient(app)

    (notification_record,) = delivery_store.enqueue_envelopes(
        [build_envelopes_for_decision(_decision_record(decision_result="block_and_alert"))[0]]
    )
    failed_record = notification_record.model_copy(
        update={
            "delivery_status": "delivery_failed",
            "delivery_attempt": 3,
            "failure_code": "transport_error",
            "next_retry_at": None,
            "updated_at": "2026-04-07T00:20:00Z",
            "operator_notes": ["delivery_dead_letter failure_code=transport_error attempts=3"],
        }
    )
    delivery_store.update_delivery_record(failed_record)

    first = client.post(
        "/api/v1/watchdog/bootstrap/openclaw-webhook",
        headers={"Authorization": "Bearer wt"},
        json={
            "event_type": "openclaw_webhook_base_url_changed",
            "openclaw_webhook_base_url": "https://updated-openclaw.trycloudflare.com",
            "changed_at": "2026-04-07T19:00:00+08:00",
            "source": "b-host-openclaw",
        },
    )
    assert first.status_code == 200

    retried = delivery_store.get_delivery_record(notification_record.envelope_id)
    assert retried is not None
    assert retried.delivery_attempt == 0
    delivery_store.update_delivery_record(
        retried.model_copy(
            update={
                "delivery_status": "delivery_failed",
                "delivery_attempt": 4,
                "failure_code": "transport_error",
                "next_retry_at": None,
                "updated_at": "2026-04-07T00:30:00Z",
                "operator_notes": list(retried.operator_notes)
                + ["delivery_dead_letter failure_code=transport_error attempts=4"],
            }
        )
    )

    second = client.post(
        "/api/v1/watchdog/bootstrap/openclaw-webhook",
        headers={"Authorization": "Bearer wt"},
        json={
            "event_type": "openclaw_webhook_base_url_changed",
            "openclaw_webhook_base_url": "https://updated-openclaw-2.trycloudflare.com",
            "changed_at": "2026-04-07T19:10:00+08:00",
            "source": "b-host-openclaw",
        },
    )

    assert second.status_code == 200
    events = app.state.session_service.list_events(
        session_id=notification_record.session_id,
        related_id_key="envelope_id",
        related_id_value=notification_record.envelope_id,
    )
    assert [event.event_type for event in events] == [
        "notification_requeued",
        "notification_requeued",
    ]
    assert [event.payload["delivery_attempt"] for event in events] == [0, 0]
    assert events[0].event_id != events[1].event_id


def test_bootstrap_openclaw_webhook_does_not_requeue_when_endpoint_is_unchanged(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    app = create_app(settings, a_client=_ClientStub())
    delivery_store: DeliveryOutboxStore = app.state.delivery_outbox_store
    client = TestClient(app)

    OpenClawWebhookEndpointStore(openclaw_webhook_endpoint_state_path(settings)).put(
        openclaw_webhook_base_url="https://same-openclaw.trycloudflare.com",
        changed_at="2026-04-07T18:00:00+08:00",
        source="b-host-openclaw",
        updated_at="2026-04-07T10:00:00Z",
    )

    (notification_record,) = delivery_store.enqueue_envelopes(
        [build_envelopes_for_decision(_decision_record(decision_result="block_and_alert"))[0]]
    )
    delivery_store.update_delivery_record(
        notification_record.model_copy(
            update={
                "delivery_status": "delivery_failed",
                "delivery_attempt": 3,
                "failure_code": "transport_error",
                "next_retry_at": None,
                "operator_notes": ["delivery_dead_letter failure_code=transport_error attempts=3"],
            }
        )
    )

    response = client.post(
        "/api/v1/watchdog/bootstrap/openclaw-webhook",
        headers={"Authorization": "Bearer wt"},
        json={
            "event_type": "openclaw_webhook_base_url_changed",
            "openclaw_webhook_base_url": "https://same-openclaw.trycloudflare.com",
            "changed_at": "2026-04-07T19:00:00+08:00",
            "source": "b-host-openclaw",
        },
    )

    assert response.status_code == 200
    retained = delivery_store.get_delivery_record(notification_record.envelope_id)
    assert retained is not None
    assert retained.delivery_status == "delivery_failed"
    assert retained.delivery_attempt == 3
    assert retained.failure_code == "transport_error"
    events = app.state.session_service.list_events(
        session_id=notification_record.session_id,
        related_id_key="envelope_id",
        related_id_value=notification_record.envelope_id,
    )
    assert events == []
