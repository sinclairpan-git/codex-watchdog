from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import httpx
from fastapi.testclient import TestClient

from watchdog.main import create_app
from watchdog.settings import Settings


def test_watchdog_healthz() -> None:
    app = create_app(Settings(api_token="wt", codex_runtime_base_url="http://127.0.0.1:9"))
    c = TestClient(app)
    r = c.get("/healthz")
    assert r.status_code == 200


def test_watchdog_startup_continues_when_session_spine_refresh_is_slow(
    tmp_path,
    monkeypatch,
) -> None:
    import watchdog.main as watchdog_main

    monkeypatch.setattr(watchdog_main, "STARTUP_BACKGROUND_STEP_TIMEOUT_SECONDS", 0.01)
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_base_url="http://127.0.0.1:9",
            data_dir=str(tmp_path),
        ),
        start_background_workers=True,
    )

    def slow_refresh() -> None:
        time.sleep(0.1)

    app.state.session_spine_runtime.refresh_all = slow_refresh
    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200


@patch("watchdog.services.runtime_client.client.httpx.Client")
def test_progress_ok(mock_cls: MagicMock) -> None:
    mock_inst = MagicMock()
    mock_cls.return_value.__enter__.return_value = mock_inst
    mock_inst.get.return_value.json.return_value = {
        "success": True,
        "data": {
            "status": "running",
            "phase": "planning",
            "last_summary": "",
            "files_touched": [],
            "pending_approval": False,
            "context_pressure": "low",
            "last_progress_at": None,
        },
    }
    app = create_app(Settings(api_token="wt", codex_runtime_token="at"))
    c = TestClient(app)
    r = c.get(
        "/api/v1/watchdog/tasks/x/progress",
        headers={"Authorization": "Bearer wt"},
    )
    assert r.status_code == 200
    b = r.json()
    assert b["success"] is True
    assert b["data"]["status"] == "running"


@patch("watchdog.services.runtime_client.client.httpx.Client")
def test_progress_runtime_unreachable(mock_cls: MagicMock) -> None:
    mock_inst = MagicMock()
    mock_cls.return_value.__enter__.return_value = mock_inst
    mock_inst.get.side_effect = httpx.ConnectError("refused", request=MagicMock())

    app = create_app(Settings(api_token="wt"))
    c = TestClient(app)
    r = c.get(
        "/api/v1/watchdog/tasks/x/progress",
        headers={"Authorization": "Bearer wt"},
    )
    assert r.status_code == 200
    b = r.json()
    assert b["success"] is False
    assert b["error"]["code"] == "CONTROL_LINK_ERROR"


@patch("watchdog.services.runtime_client.client.httpx.Client")
def test_events_snapshot_proxy_ok(mock_cls: MagicMock) -> None:
    mock_inst = MagicMock()
    mock_cls.return_value.__enter__.return_value = mock_inst
    mock_response = MagicMock()
    mock_response.headers = {"content-type": "text/event-stream; charset=utf-8"}
    mock_response.text = 'event: task_created\ndata: {"project_id":"x"}\n\n'
    mock_inst.get.return_value = mock_response

    app = create_app(Settings(api_token="wt", codex_runtime_token="at"))
    c = TestClient(app)
    r = c.get(
        "/api/v1/watchdog/tasks/x/events?follow=false",
        headers={"Authorization": "Bearer wt"},
    )

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert "event: task_created" in r.text


@patch("watchdog.services.runtime_client.client.httpx.Client")
def test_events_stream_proxy_ok(mock_cls: MagicMock) -> None:
    mock_inst = MagicMock()
    mock_cls.return_value.__enter__.return_value = mock_inst
    snapshot = MagicMock()
    snapshot.headers = {"content-type": "text/event-stream; charset=utf-8"}
    snapshot.text = 'event: task_created\ndata: {"project_id":"x"}\n\n'
    mock_inst.get.return_value = snapshot

    stream_response = MagicMock()
    stream_response.headers = {"content-type": "text/event-stream; charset=utf-8"}
    stream_response.iter_text.return_value = iter(
        [
            'event: task_created\ndata: {"project_id":"x"}\n\n',
            'event: resume\ndata: {"project_id":"x"}\n\n',
        ]
    )
    mock_inst.stream.return_value.__enter__.return_value = stream_response

    app = create_app(Settings(api_token="wt", codex_runtime_token="at"))
    c = TestClient(app)
    r = c.get(
        "/api/v1/watchdog/tasks/x/events",
        headers={"Authorization": "Bearer wt"},
    )

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert "event: task_created" in r.text
    assert "event: resume" in r.text


@patch("watchdog.services.runtime_client.client.httpx.Client")
def test_events_proxy_runtime_unreachable(mock_cls: MagicMock) -> None:
    mock_inst = MagicMock()
    mock_cls.return_value.__enter__.return_value = mock_inst
    mock_inst.get.side_effect = httpx.ConnectError("refused", request=MagicMock())

    app = create_app(Settings(api_token="wt"))
    c = TestClient(app)
    r = c.get(
        "/api/v1/watchdog/tasks/x/events?follow=false",
        headers={"Authorization": "Bearer wt"},
    )

    assert r.status_code == 200
    assert r.json()["success"] is False
    assert r.json()["error"]["code"] == "CONTROL_LINK_ERROR"


@patch("watchdog.services.runtime_client.client.httpx.Client")
def test_events_proxy_relays_runtime_business_error(mock_cls: MagicMock) -> None:
    mock_inst = MagicMock()
    mock_cls.return_value.__enter__.return_value = mock_inst
    mock_response = MagicMock()
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json.return_value = {
        "success": False,
        "error": {"code": "NOT_FOUND", "message": "x"},
    }
    mock_inst.get.return_value = mock_response

    app = create_app(Settings(api_token="wt", codex_runtime_token="at"))
    c = TestClient(app)
    r = c.get(
        "/api/v1/watchdog/tasks/x/events?follow=false",
        headers={"Authorization": "Bearer wt"},
    )

    assert r.status_code == 200
    assert r.json()["success"] is False
    assert r.json()["error"]["code"] == "NOT_FOUND"
