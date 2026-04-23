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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeEventsClient(
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


def test_session_events_snapshot_route_dedupes_duplicate_raw_snapshot_event_ids(tmp_path) -> None:
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeEventsClient(
            snapshot=(
                'id: evt_001\n'
                "event: task_created\n"
                'data: {"event_id":"evt_001","project_id":"repo-a","thread_id":"thr_native_1","event_type":"task_created","event_source":"a_control_agent","payload_json":{"status":"running","phase":"planning"},"created_at":"2026-04-05T10:00:00Z"}\n\n'
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
    assert resp.text.count("event: session_created") == 1


def test_session_events_snapshot_route_dedupes_duplicate_raw_snapshot_events_without_event_id(
    tmp_path,
) -> None:
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeEventsClient(
            snapshot=(
                "event: resume\n"
                'data: {"project_id":"repo-a","thread_id":"thr_native_1","event_type":"resume","event_source":"a_control_agent","payload_json":{"mode":"resume_or_new_thread"},"created_at":"2026-04-05T10:02:00Z"}\n\n'
                "event: resume\n"
                'data: {"project_id":"repo-a","thread_id":"thr_native_1","event_type":"resume","event_source":"a_control_agent","payload_json":{"mode":"resume_or_new_thread"},"created_at":"2026-04-05T10:02:00Z"}\n\n'
            ),
        ),
    )
    c = TestClient(app)

    resp = c.get(
        "/api/v1/watchdog/sessions/repo-a/events?follow=false",
        headers={"Authorization": "Bearer wt"},
    )

    assert resp.status_code == 200
    assert resp.text.count("event: session_resumed") == 1
    assert "id: synthetic:" in resp.text


def test_session_events_follow_route_streams_stable_events(tmp_path) -> None:
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeEventsClient(
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


def test_session_events_follow_route_bootstraps_stable_snapshot_before_stream(
    tmp_path,
) -> None:
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeEventsClient(
            snapshot=(
                'id: evt_001\n'
                "event: task_created\n"
                'data: {"event_id":"evt_001","project_id":"repo-a","thread_id":"thr_native_1","event_type":"task_created","event_source":"a_control_agent","payload_json":{"status":"running","phase":"planning"},"created_at":"2026-04-05T10:00:00Z"}\n\n'
            ),
            stream_chunks=[
                'id: evt_002\nevent: resume\ndata: {"event_id":"evt_002","project_id":"repo-a","thread_id":"thr_native_1","event_type":"resume","event_source":"a_control_agent","payload_json":{"mode":"resume_or_new_thread"},"created_at":"2026-04-05T10:02:00Z"}\n\n',
            ],
        ),
    )
    c = TestClient(app)

    resp = c.get(
        "/api/v1/watchdog/sessions/repo-a/events",
        headers={"Authorization": "Bearer wt"},
    )

    assert resp.status_code == 200
    assert "event: session_created" in resp.text
    assert "event: session_resumed" in resp.text
    assert resp.text.index("event: session_created") < resp.text.index("event: session_resumed")


def test_session_events_follow_route_dedupes_replayed_snapshot_events_from_raw_stream(
    tmp_path,
) -> None:
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeEventsClient(
            snapshot=(
                'id: evt_001\n'
                "event: task_created\n"
                'data: {"event_id":"evt_001","project_id":"repo-a","thread_id":"thr_native_1","event_type":"task_created","event_source":"a_control_agent","payload_json":{"status":"running","phase":"planning"},"created_at":"2026-04-05T10:00:00Z"}\n\n'
            ),
            stream_chunks=[
                'id: evt_001\nevent: task_created\ndata: {"event_id":"evt_001","project_id":"repo-a","thread_id":"thr_native_1","event_type":"task_created","event_source":"a_control_agent","payload_json":{"status":"running","phase":"planning"},"created_at":"2026-04-05T10:00:00Z"}\n\n',
                'id: evt_002\nevent: resume\ndata: {"event_id":"evt_002","project_id":"repo-a","thread_id":"thr_native_1","event_type":"resume","event_source":"a_control_agent","payload_json":{"mode":"resume_or_new_thread"},"created_at":"2026-04-05T10:02:00Z"}\n\n',
            ],
        ),
    )
    c = TestClient(app)

    resp = c.get(
        "/api/v1/watchdog/sessions/repo-a/events",
        headers={"Authorization": "Bearer wt"},
    )

    assert resp.status_code == 200
    assert resp.text.count("event: session_created") == 1
    assert resp.text.count("event: session_resumed") == 1


def test_session_events_follow_route_dedupes_replayed_snapshot_events_without_event_id(
    tmp_path,
) -> None:
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeEventsClient(
            snapshot=(
                "event: resume\n"
                'data: {"project_id":"repo-a","thread_id":"thr_native_1","event_type":"resume","event_source":"a_control_agent","payload_json":{"mode":"resume_or_new_thread"},"created_at":"2026-04-05T10:02:00Z"}\n\n'
            ),
            stream_chunks=[
                "event: resume\n"
                'data: {"project_id":"repo-a","thread_id":"thr_native_1","event_type":"resume","event_source":"a_control_agent","payload_json":{"mode":"resume_or_new_thread"},"created_at":"2026-04-05T10:02:00Z"}\n\n',
                "event: steer\n"
                'data: {"project_id":"repo-a","thread_id":"thr_native_1","event_type":"steer","event_source":"watchdog","payload_json":{"message":"stay focused","reason":"policy"},"created_at":"2026-04-05T10:03:00Z"}\n\n',
            ],
        ),
    )
    c = TestClient(app)

    resp = c.get(
        "/api/v1/watchdog/sessions/repo-a/events",
        headers={"Authorization": "Bearer wt"},
    )

    assert resp.status_code == 200
    assert resp.text.count("event: session_resumed") == 1
    assert resp.text.count("event: guidance_posted") == 1
    assert "id: synthetic:" in resp.text


def test_session_events_follow_route_dedupes_duplicate_bootstrap_snapshot_event_ids(
    tmp_path,
) -> None:
    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeEventsClient(
            snapshot=(
                'id: evt_001\n'
                "event: task_created\n"
                'data: {"event_id":"evt_001","project_id":"repo-a","thread_id":"thr_native_1","event_type":"task_created","event_source":"a_control_agent","payload_json":{"status":"running","phase":"planning"},"created_at":"2026-04-05T10:00:00Z"}\n\n'
                'id: evt_001\n'
                "event: task_created\n"
                'data: {"event_id":"evt_001","project_id":"repo-a","thread_id":"thr_native_1","event_type":"task_created","event_source":"a_control_agent","payload_json":{"status":"running","phase":"planning"},"created_at":"2026-04-05T10:00:00Z"}\n\n'
            ),
            stream_chunks=[
                'id: evt_002\nevent: resume\ndata: {"event_id":"evt_002","project_id":"repo-a","thread_id":"thr_native_1","event_type":"resume","event_source":"a_control_agent","payload_json":{"mode":"resume_or_new_thread"},"created_at":"2026-04-05T10:02:00Z"}\n\n',
            ],
        ),
    )
    c = TestClient(app)

    resp = c.get(
        "/api/v1/watchdog/sessions/repo-a/events",
        headers={"Authorization": "Bearer wt"},
    )

    assert resp.status_code == 200
    assert resp.text.count("event: session_created") == 1
    assert resp.text.count("event: session_resumed") == 1


def test_session_events_follow_route_prepends_session_service_child_adoption_event(
    tmp_path,
) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=FakeEventsClient(
            snapshot="",
            stream_chunks=[
                'id: evt_002\nevent: resume\ndata: {"event_id":"evt_002","project_id":"repo-a","thread_id":"thr_native_1","event_type":"resume","event_source":"a_control_agent","payload_json":{"mode":"resume_or_new_thread"},"created_at":"2026-04-05T10:02:00Z"}\n\n',
            ],
        ),
    )
    goal_contracts = GoalContractService(app.state.session_service)
    created = goal_contracts.bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="继续 recovery",
        task_prompt="follow 流开头要先带 canonical child adoption",
        last_user_instruction="继续补 follow stream canonical bootstrap",
        phase="implementation",
        last_summary="正在补 follow stream canonical bootstrap",
        explicit_deliverables=["follow 流预置 canonical child adoption"],
        completion_signals=["相关 pytest 通过"],
    )
    goal_contracts.adopt_contract_for_child_session(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        child_session_id="session:repo-a:thr_child_1",
        child_native_thread_id="thr_child_1",
        expected_version=created.version,
        recovery_transaction_id="recovery-tx:1",
        source_packet_id="packet:handoff-1",
    )
    c = TestClient(app)

    resp = c.get(
        "/api/v1/watchdog/sessions/repo-a/events",
        headers={"Authorization": "Bearer wt"},
    )

    assert resp.status_code == 200
    assert '"child_session_id":"session:repo-a:thr_child_1"' in resp.text
    assert "event: session_resumed" in resp.text


def test_session_events_follow_route_falls_back_to_session_service_when_stream_start_fails(
    tmp_path,
) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    class BrokenEventsClient:
        def get_events_snapshot(
            self,
            project_id: str,
            *,
            poll_interval: float = 0.5,
        ):
            _ = (project_id, poll_interval)
            return "", "text/event-stream"

        def iter_events(
            self,
            project_id: str,
            *,
            poll_interval: float = 0.5,
        ):
            _ = (project_id, poll_interval)
            raise httpx.ConnectError("refused", request=httpx.Request("GET", "http://a.test"))

    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=BrokenEventsClient(),
    )
    goal_contracts = GoalContractService(app.state.session_service)
    created = goal_contracts.bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="继续 recovery",
        task_prompt="stream start 失败时 fallback 到 canonical event",
        last_user_instruction="继续补 follow stream fallback",
        phase="implementation",
        last_summary="正在补 follow stream fallback",
        explicit_deliverables=["follow stream fallback 到 canonical event"],
        completion_signals=["相关 pytest 通过"],
    )
    goal_contracts.adopt_contract_for_child_session(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        child_session_id="session:repo-a:thr_child_1",
        child_native_thread_id="thr_child_1",
        expected_version=created.version,
        recovery_transaction_id="recovery-tx:1",
        source_packet_id="packet:handoff-1",
    )
    c = TestClient(app)

    resp = c.get(
        "/api/v1/watchdog/sessions/repo-a/events",
        headers={"Authorization": "Bearer wt"},
    )

    assert resp.status_code == 200
    assert "event: session_resumed" in resp.text
    assert '"recovery_transaction_id":"recovery-tx:1"' in resp.text


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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=BrokenEventsClient(),
    )
    c = TestClient(app)

    resp = c.get(
        "/api/v1/watchdog/sessions/repo-a/events?follow=false",
        headers={"Authorization": "Bearer wt"},
    )

    assert resp.status_code == 200
    assert resp.json()["success"] is False
    assert resp.json()["error"]["code"] == "CONTROL_LINK_ERROR"


def test_session_events_snapshot_route_falls_back_to_session_service_when_upstream_failure(
    tmp_path,
) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

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
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=BrokenEventsClient(),
    )
    goal_contracts = GoalContractService(app.state.session_service)
    created = goal_contracts.bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="继续 recovery",
        task_prompt="fallback 到 canonical stable SSE snapshot",
        last_user_instruction="继续补 SSE snapshot fallback",
        phase="implementation",
        last_summary="正在补 SSE snapshot fallback",
        explicit_deliverables=["SSE snapshot fallback 到 session service"],
        completion_signals=["相关 pytest 通过"],
    )
    goal_contracts.adopt_contract_for_child_session(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        child_session_id="session:repo-a:thr_child_1",
        child_native_thread_id="thr_child_1",
        expected_version=created.version,
        recovery_transaction_id="recovery-tx:1",
        source_packet_id="packet:handoff-1",
    )
    c = TestClient(app)

    resp = c.get(
        "/api/v1/watchdog/sessions/repo-a/events?follow=false",
        headers={"Authorization": "Bearer wt"},
    )

    assert resp.status_code == 200
    assert "event: session_resumed" in resp.text
    assert '"child_session_id":"session:repo-a:thr_child_1"' in resp.text


def test_session_events_follow_route_returns_control_link_error_on_stream_start_failure(tmp_path) -> None:
    class BrokenEventsClient:
        def get_events_snapshot(
            self,
            project_id: str,
            *,
            poll_interval: float = 0.5,
        ):
            _ = (project_id, poll_interval)
            return "", "text/event-stream"

        def iter_events(
            self,
            project_id: str,
            *,
            poll_interval: float = 0.5,
        ):
            _ = (project_id, poll_interval)
            raise httpx.ConnectError("refused", request=httpx.Request("GET", "http://a.test"))

    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=BrokenEventsClient(),
    )
    c = TestClient(app)

    resp = c.get(
        "/api/v1/watchdog/sessions/repo-a/events",
        headers={"Authorization": "Bearer wt"},
    )

    assert resp.status_code == 200
    assert resp.json()["success"] is False
    assert resp.json()["error"]["code"] == "CONTROL_LINK_ERROR"


def test_session_events_follow_route_falls_back_to_session_service_when_first_stream_pull_fails(
    tmp_path,
) -> None:
    from watchdog.services.goal_contract.service import GoalContractService

    class DeferredBrokenEventsClient:
        def get_events_snapshot(
            self,
            project_id: str,
            *,
            poll_interval: float = 0.5,
        ):
            _ = (project_id, poll_interval)
            return "", "text/event-stream"

        def iter_events(
            self,
            project_id: str,
            *,
            poll_interval: float = 0.5,
        ):
            _ = (project_id, poll_interval)

            def _iter():
                raise httpx.ConnectError("refused", request=httpx.Request("GET", "http://a.test"))
                yield ""

            return _iter()

    app = create_app(
        Settings(api_token="wt", codex_runtime_token="at", codex_runtime_base_url="http://a.test", data_dir=str(tmp_path)),
        runtime_client=DeferredBrokenEventsClient(),
    )
    goal_contracts = GoalContractService(app.state.session_service)
    created = goal_contracts.bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="继续 recovery",
        task_prompt="first stream pull 失败时 fallback 到 canonical event",
        last_user_instruction="继续补 deferred follow stream fallback",
        phase="implementation",
        last_summary="正在补 deferred follow stream fallback",
        explicit_deliverables=["deferred follow stream fallback 到 canonical event"],
        completion_signals=["相关 pytest 通过"],
    )
    goal_contracts.adopt_contract_for_child_session(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        child_session_id="session:repo-a:thr_child_1",
        child_native_thread_id="thr_child_1",
        expected_version=created.version,
        recovery_transaction_id="recovery-tx:1",
        source_packet_id="packet:handoff-1",
    )
    c = TestClient(app)

    resp = c.get(
        "/api/v1/watchdog/sessions/repo-a/events",
        headers={"Authorization": "Bearer wt"},
    )

    assert resp.status_code == 200
    assert "event: session_resumed" in resp.text
    assert '"recovery_transaction_id":"recovery-tx:1"' in resp.text
