from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from watchdog.main import create_app
from watchdog.settings import Settings


class FakeEventsClient:
    def __init__(self, *, snapshot: str, stream_chunks: list[str] | None = None) -> None:
        self._snapshot = snapshot
        self._stream_chunks = list(stream_chunks or [])

    def get_events_snapshot(
        self,
        project_id: str,
        *,
        poll_interval: float = 0.5,
    ) -> tuple[str, str]:
        assert project_id == "repo-a"
        _ = poll_interval
        return self._snapshot, "text/event-stream"

    def iter_events(
        self,
        project_id: str,
        *,
        poll_interval: float = 0.5,
    ):
        assert project_id == "repo-a"
        _ = poll_interval
        yield from self._stream_chunks


def test_session_events_snapshot_route_returns_stable_sse(tmp_path) -> None:
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=FakeEventsClient(
            snapshot=(
                'id: evt_001\n'
                "event: task_created\n"
                'data: {"event_id":"evt_001","project_id":"repo-a","thread_id":"thr_native_1","event_type":"task_created","event_source":"a_control_agent","payload_json":{"status":"running","phase":"planning"},"created_at":"2026-04-05T10:00:00Z"}\n\n'
            ),
        ),
    )
    c = TestClient(app)

    resp = c.get(
        "/api/v1/watchdog/sessions/repo-a/events?follow=false",
        headers={"Authorization": "Bearer wt"},
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert "event: session_created" in resp.text
    assert "payload_json" not in resp.text


def test_session_events_follow_route_streams_stable_events(tmp_path) -> None:
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=FakeEventsClient(
            snapshot="",
            stream_chunks=[
                'id: evt_002\nevent: steer\ndata: {"event_id":"evt_002","project_id":"repo-a","thread_id":"thr_native_1","event_type":"steer","event_source":"watchdog","payload_json":{"message":"stay focused","reason":"policy"},"created_at":"2026-04-05T10:01:00Z"}\n\n',
                'id: evt_003\nevent: approval_decided\ndata: {"event_id":"evt_003","project_id":"repo-a","thread_id":"thr_native_1","event_type":"approval_decided","event_source":"a_control_agent","payload_json":{"approval_id":"appr_001","decision":"reject","operator":"alice"},"created_at":"2026-04-05T10:02:00Z"}\n\n',
            ],
        ),
    )
    c = TestClient(app)

    resp = c.get(
        "/api/v1/watchdog/sessions/repo-a/events",
        headers={"Authorization": "Bearer wt"},
    )

    assert resp.status_code == 200
    assert "event: guidance_posted" in resp.text
    assert "event: approval_resolved" in resp.text
    assert '"decision":"reject"' in resp.text


def test_session_events_route_returns_control_link_error_on_upstream_failure(tmp_path) -> None:
    class BrokenEventsClient:
        def get_events_snapshot(
            self,
            project_id: str,
            *,
            poll_interval: float = 0.5,
        ):
            _ = (project_id, poll_interval)
            raise httpx.ConnectError("refused", request=httpx.Request("GET", "http://a.test"))

    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=BrokenEventsClient(),
    )
    c = TestClient(app)

    resp = c.get(
        "/api/v1/watchdog/sessions/repo-a/events?follow=false",
        headers={"Authorization": "Bearer wt"},
    )

    assert resp.status_code == 200
    assert resp.json()["success"] is False
    assert resp.json()["error"]["code"] == "CONTROL_LINK_ERROR"
