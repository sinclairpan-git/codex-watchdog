from __future__ import annotations

from fastapi.testclient import TestClient

from a_control_agent.main import create_app
from a_control_agent.settings import Settings


def test_create_l3_stays_pending(tmp_path) -> None:
    s = Settings(api_token="t", data_dir=str(tmp_path / "d"))
    c = TestClient(create_app(s))
    h = {"Authorization": "Bearer t"}
    r = c.post(
        "/api/v1/approvals",
        json={
            "project_id": "p",
            "thread_id": "thr",
            "command": "git push",
            "reason": "r",
        },
        headers=h,
    )
    assert r.status_code == 200
    b = r.json()
    assert b["success"] is True
    assert b["data"]["risk_level"] == "L3"
    assert b["data"]["status"] == "pending"


def test_create_l0_auto(tmp_path) -> None:
    s = Settings(api_token="t", data_dir=str(tmp_path / "d"))
    c = TestClient(create_app(s))
    h = {"Authorization": "Bearer t"}
    r = c.post(
        "/api/v1/approvals",
        json={
            "project_id": "p",
            "thread_id": "thr",
            "command": "pytest -q",
            "reason": "r",
        },
        headers=h,
    )
    b = r.json()
    assert b["data"]["status"] == "approved"
    assert b["data"]["decided_by"] == "policy-auto"


def test_list_and_decide(tmp_path) -> None:
    s = Settings(api_token="t", data_dir=str(tmp_path / "d"))
    c = TestClient(create_app(s))
    h = {"Authorization": "Bearer t"}
    x = c.post(
        "/api/v1/approvals",
        json={
            "project_id": "p",
            "thread_id": "thr",
            "command": "curl https://x",
            "reason": "r",
        },
        headers=h,
    ).json()
    aid = x["data"]["approval_id"]
    r = c.get("/api/v1/approvals?status=pending", headers=h)
    items = r.json()["data"]["items"]
    assert any(i["approval_id"] == aid for i in items)
    d = c.post(
        f"/api/v1/approvals/{aid}/decision",
        json={"decision": "approve", "operator": "human"},
        headers=h,
    )
    assert d.json()["data"]["status"] == "approved"
