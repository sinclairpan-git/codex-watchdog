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


def test_integration_stable_snapshot_matches_adapter_snapshot_when_raw_event_id_is_missing(
    tmp_path: Path,
) -> None:
    client = FakeAClient()
    client.snapshot = (
        "event: resume\n"
        'data: {"project_id":"repo-a","thread_id":"thr_native_1","event_type":"resume","event_source":"a_control_agent","payload_json":{"mode":"resume_or_new_thread"},"created_at":"2026-04-05T10:00:00Z"}\n\n'
        "event: resume\n"
        'data: {"project_id":"repo-a","thread_id":"thr_native_1","event_type":"resume","event_source":"a_control_agent","payload_json":{"mode":"resume_or_new_thread"},"created_at":"2026-04-05T10:00:00Z"}\n\n'
    )
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
    assert resp.text.count("event: session_resumed") == 1
    assert "id: synthetic:" in resp.text
    assert len(events) == 1
    assert events[0].event_code == "session_resumed"
    assert events[0].event_id.startswith("synthetic:")


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
    assert "event: session_created" in stable.text
    assert "event: session_resumed" in stable.text
    assert legacy.status_code == 200
    assert "event: task_created" in legacy.text
    assert len(streamed) == 2
    assert streamed[0].event_code == "session_created"
    assert streamed[1].event_code == "session_resumed"


def test_integration_stable_follow_stream_dedupes_missing_event_id_replays_across_http_and_adapter(
    tmp_path: Path,
) -> None:
    client = FakeAClient()
    client.snapshot = (
        "event: resume\n"
        'data: {"project_id":"repo-a","thread_id":"thr_native_1","event_type":"resume","event_source":"a_control_agent","payload_json":{"mode":"resume_or_new_thread"},"created_at":"2026-04-05T10:00:00Z"}\n\n'
    )
    client.stream = [
        "event: resume\n"
        'data: {"project_id":"repo-a","thread_id":"thr_native_1","event_type":"resume","event_source":"a_control_agent","payload_json":{"mode":"resume_or_new_thread"},"created_at":"2026-04-05T10:00:00Z"}\n\n',
        "event: steer\n"
        'data: {"project_id":"repo-a","thread_id":"thr_native_1","event_type":"steer","event_source":"watchdog","payload_json":{"message":"stay focused","reason":"policy"},"created_at":"2026-04-05T10:01:00Z"}\n\n',
    ]
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
    streamed = list(adapter.iter_session_events("repo-a"))

    assert stable.status_code == 200
    assert stable.text.count("event: session_resumed") == 1
    assert stable.text.count("event: guidance_posted") == 1
    assert "id: synthetic:" in stable.text
    assert len(streamed) == 2
    assert streamed[0].event_code == "session_resumed"
    assert streamed[0].event_id.startswith("synthetic:")
    assert streamed[1].event_code == "guidance_posted"


def test_integration_stable_follow_stream_includes_canonical_child_adoption_before_raw_stream(
    tmp_path: Path,
) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    client = FakeAClient()
    app = create_app(
        Settings(api_token="wt", a_agent_token="at", a_agent_base_url="http://a.test", data_dir=str(tmp_path)),
        a_client=client,
    )
    contracts = GoalContractService(app.state.session_service)
    created = contracts.bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="继续 recovery",
        task_prompt="stable follow stream 先出 canonical event",
        last_user_instruction="继续补 stable follow canonical bootstrap",
        phase="implementation",
        last_summary="正在补 stable follow canonical bootstrap",
        explicit_deliverables=["stable follow stream 先出 canonical event"],
        completion_signals=["相关 pytest 通过"],
    )
    contracts.adopt_contract_for_child_session(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        child_session_id="session:repo-a:thr_child_1",
        child_native_thread_id="thr_child_1",
        expected_version=created.version,
        recovery_transaction_id="recovery-tx:1",
        source_packet_id="packet:handoff-1",
    )
    http = TestClient(app)
    adapter = _adapter(tmp_path, client)

    stable = http.get(
        "/api/v1/watchdog/sessions/repo-a/events",
        headers={"Authorization": "Bearer wt"},
    )
    streamed = list(adapter.iter_session_events("repo-a"))

    assert stable.status_code == 200
    assert '"child_session_id":"session:repo-a:thr_child_1"' in stable.text
    assert len(streamed) == 3
    assert streamed[0].event_code == "session_created"
    assert streamed[1].thread_id == "session:repo-a:thr_child_1"
    assert streamed[2].event_code == "session_resumed"
