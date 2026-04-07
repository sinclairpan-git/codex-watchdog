from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from watchdog.main import create_app
from watchdog.settings import Settings


SESSION_SPINE_STORE_FILENAME = "session_spine.json"


class FakeResidentAClient:
    def __init__(
        self,
        *,
        task: dict[str, object],
        approvals: list[dict[str, object]] | None = None,
    ) -> None:
        self._task = dict(task)
        self._approvals = [dict(approval) for approval in approvals or []]

    def list_tasks(self) -> list[dict[str, object]]:
        return [dict(self._task)]

    def get_envelope(self, project_id: str) -> dict[str, object]:
        assert project_id == self._task["project_id"]
        return {"success": True, "data": dict(self._task)}

    def list_approvals(
        self,
        *,
        status: str | None = None,
        project_id: str | None = None,
        decided_by: str | None = None,
        callback_status: str | None = None,
    ) -> list[dict[str, object]]:
        _ = (decided_by, callback_status)
        rows = [dict(approval) for approval in self._approvals]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if project_id:
            rows = [row for row in rows if row.get("project_id") == project_id]
        return rows


def _store_path(root: Path) -> Path:
    return root / SESSION_SPINE_STORE_FILENAME


def _read_store(root: Path) -> dict[str, object]:
    return json.loads(_store_path(root).read_text(encoding="utf-8"))


def test_background_runtime_persists_session_spine_and_keeps_fact_snapshot_version_stable(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        a_agent_token="at",
        a_agent_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "editing files",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2099-01-01T00:00:00Z",
        }
    )

    with TestClient(create_app(settings, a_client=a_client, start_background_workers=True)):
        pass

    first_store_path = _store_path(tmp_path)
    assert first_store_path.exists()
    first_snapshot = _read_store(tmp_path)
    first_version = first_snapshot["sessions"]["repo-a"]["fact_snapshot_version"]
    assert first_version
    assert first_snapshot["sessions"]["repo-a"]["session"]["thread_id"] == "session:repo-a"

    with TestClient(create_app(settings, a_client=a_client, start_background_workers=True)):
        pass

    second_snapshot = _read_store(tmp_path)
    assert second_snapshot["sessions"]["repo-a"]["fact_snapshot_version"] == first_version
