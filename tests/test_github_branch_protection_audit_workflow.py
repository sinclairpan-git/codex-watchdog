from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github/workflows/branch-protection-audit.yml"


def test_repo_local_branch_protection_audit_workflow_exists_and_has_required_triggers() -> None:
    payload = _load_workflow()
    workflow_on = _workflow_on(payload)

    assert payload["name"] == "Branch Protection Audit"
    assert workflow_on["workflow_dispatch"] == {}
    assert workflow_on["schedule"] == [{"cron": "17 * * * *"}]


def test_repo_local_branch_protection_audit_workflow_runs_live_branch_protection_verify() -> None:
    payload = _load_workflow()

    job = payload["jobs"]["branch-protection-audit"]
    assert job["runs-on"] == "ubuntu-latest"
    assert job["steps"][-1] == {
        "env": {"GH_TOKEN": "${{ secrets.BRANCH_PROTECTION_AUDIT_TOKEN }}"},
        "run": "uv run python -m ai_sdlc verify github-branch-protection",
    }


def _load_workflow() -> dict:
    payload = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _workflow_on(payload: dict) -> dict:
    workflow_on = payload.get("on", payload.get(True))
    assert isinstance(workflow_on, dict)
    return workflow_on
