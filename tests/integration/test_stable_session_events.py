from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from watchdog.main import create_app
from watchdog.services.adapters.openclaw.adapter import OpenClawAdapter
from watchdog.settings import Settings
from watchdog.storage.action_receipts import ActionReceiptStore


class FakeAClient:
    def __init__(self) -> None:
        self.snapshot = (
            'id: evt_001\n'
            "event: task_created\n"
            'data: {"event_id":"evt_001","project_id":"repo-a","thread_id":"thr_native_1","event_type":"task_created","event_source":"a_control_agent","payload_json":{"status":"running","phase":"planning"},"created_at":"2026-04-05T10:00:00Z"}\n\n'
        )
        self.stream = [
            'id: evt_002\nevent: resume\ndata: {"event_id":"evt_002","project_id":"repo-a","thread_id":"thr_native_1","event_type":"resume","event_source":"a_control_agent","payload_json":{"mode":"resume_or_new_thread","status":"running","phase":"editing_source"},"created_at":"2026-04-05T10:01:00Z"}\n\n'
        ]

    def get_events_snapshot(
        self,
        project_id: str,
        *,
        poll_interval: float = 0.5,
    ) -> tuple[str, str]:
        assert project_id == "repo-a"
        _ = poll_interval
        return self.snapshot, "text/event-stream"

    def iter_events(
        self,
        project_id: str,
        *,
        poll_interval: float = 0.5,
    ):
        assert project_id == "repo-a"
        _ = poll_interval
        yield from self.stream


def _adapter(tmp_path: Path, client: FakeAClient) -> OpenClawAdapter:
    return OpenClawAdapter(
        settings=Settings(
            api_token="wt",
            a_agent_token="at",
            a_agent_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        client=client,
        receipt_store=ActionReceiptStore(tmp_path / "action_receipts.json"),
    )


def test_integration_stable_snapshot_matches_adapter_snapshot(tmp_path: Path) -> None:
    client = FakeAClient()
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=client,
    )
    http = TestClient(app)
    adapter = _adapter(tmp_path, client)

    resp = http.get(
        "/api/v1/watchdog/sessions/repo-a/events?follow=false",
        headers={"Authorization": "Bearer wt"},
    )
    events = adapter.list_session_events("repo-a")

    assert resp.status_code == 200
    assert "event: session_created" in resp.text
    assert len(events) == 1
    assert events[0].event_code == "session_created"


def test_integration_stable_follow_stream_coexists_with_legacy_raw_proxy(tmp_path: Path) -> None:
    client = FakeAClient()
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=client,
    )
    http = TestClient(app)
    adapter = _adapter(tmp_path, client)

    stable = http.get(
        "/api/v1/watchdog/sessions/repo-a/events",
        headers={"Authorization": "Bearer wt"},
    )
    legacy = http.get(
        "/api/v1/watchdog/tasks/repo-a/events?follow=false",
        headers={"Authorization": "Bearer wt"},
    )
    streamed = list(adapter.iter_session_events("repo-a"))

    assert stable.status_code == 200
    assert "event: session_resumed" in stable.text
    assert legacy.status_code == 200
    assert "event: task_created" in legacy.text
    assert len(streamed) == 1
    assert streamed[0].event_code == "session_resumed"
