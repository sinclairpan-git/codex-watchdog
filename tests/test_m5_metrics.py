from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from a_control_agent.main import create_app
from a_control_agent.settings import Settings
from watchdog.main import create_app as create_watchdog_app
from watchdog.settings import Settings as WSettings


def test_a_metrics_contains_task_gauge(tmp_path: Path) -> None:
    root = tmp_path / "d"
    s = Settings(api_token="t", data_dir=str(root))
    c = TestClient(create_app(s))
    c.post(
        "/api/v1/tasks",
        json={"project_id": "p1", "cwd": "/", "task_title": "x"},
        headers={"Authorization": "Bearer t"},
    )
    r = c.get("/metrics")
    assert r.status_code == 200
    assert "aca_tasks_total 1" in r.text
    assert "aca_audit_events_total" in r.text


def test_watchdog_metrics_empty_audit(tmp_path: Path) -> None:
    s = WSettings(api_token="wt", data_dir=str(tmp_path / "wd"))
    c = TestClient(create_watchdog_app(s))
    r = c.get("/metrics")
    assert r.status_code == 200
    assert "watchdog_audit_events_total" in r.text
    assert "watchdog_auto_steer_total 0" in r.text
