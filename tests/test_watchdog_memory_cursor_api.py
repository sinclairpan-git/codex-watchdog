from __future__ import annotations

from fastapi.testclient import TestClient

from watchdog.main import create_app
from watchdog.settings import Settings


def _body(*, active_goal: str) -> dict[str, object]:
    return {
        "request": {
            "project_id": "repo-a",
            "repo_fingerprint": "fingerprint:repo-a",
            "stage": "verification",
            "task_kind": "closeout",
            "capability_request": "release-gate",
            "active_goal": active_goal,
            "current_phase_goal": active_goal,
            "requested_packet_kind": "stage-aware",
        },
        "quality": {
            "key_fact_recall": 0.9,
            "irrelevant_summary_precision": 0.8,
            "token_budget_utilization": 0.4,
            "expansion_miss_rate": 0.1,
        },
    }


def test_ai_autosdlc_cursor_api_returns_disabled_preview_by_default(tmp_path) -> None:
    app = create_app(Settings(api_token="wt", data_dir=str(tmp_path)))
    client = TestClient(app)

    response = client.post(
        "/api/v1/watchdog/memory/preview/ai-autosdlc-cursor",
        json=_body(active_goal="补齐 release gate"),
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["contract_name"] == "ai-autosdlc-cursor"
    assert payload["data"]["enabled"] is False
    assert payload["data"]["resident_capsule"] == []
    assert payload["data"]["packet_inputs"]["refs"] == []


def test_ai_autosdlc_cursor_api_returns_stage_aware_payload_when_enabled(tmp_path) -> None:
    app = create_app(
        Settings(
            api_token="wt",
            data_dir=str(tmp_path),
            memory_preview_ai_autosdlc_cursor_enabled=True,
        )
    )
    app.state.memory_hub_service.upsert_resident_memory(
        project_id="repo-a",
        memory_key="goal.current",
        summary="补齐 release gate",
        source_ref="session:event:goal-1",
        source_scope="project-local",
        source_runtime="watchdog",
    )
    app.state.memory_hub_service.store_archive_entry(
        project_id="repo-a",
        session_id="session:repo-a",
        summary="补齐 release gate recent recovery",
        source_ref="archive:repo-a:release-gate-1",
        raw_content="full transcript",
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/watchdog/memory/preview/ai-autosdlc-cursor",
        json=_body(active_goal="补齐 release gate"),
        headers={"Authorization": "Bearer wt"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["enabled"] is True
    assert payload["data"]["goal_alignment"]["status"] == "aligned"
    assert payload["data"]["resident_capsule"][0]["summary"] == "补齐 release gate"
    assert payload["data"]["packet_inputs"]["refs"][0]["source_ref"] == "archive:repo-a:release-gate-1"
