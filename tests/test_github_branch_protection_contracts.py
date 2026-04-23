from __future__ import annotations

import json
import subprocess
from pathlib import Path

from watchdog.validation.github_branch_protection_contracts import (
    BRANCH_PROTECTION_AUDIT_WORKFLOW_REL,
    BRANCH_PROTECTION_CONTRACT_REL,
    validate_branch_protection_audit_workflow_surfaces,
    validate_branch_protection_contract_surfaces,
    validate_live_github_branch_protection,
)


def test_repo_local_branch_protection_contract_surfaces_pass_in_repo() -> None:
    violations = validate_branch_protection_contract_surfaces(Path(__file__).resolve().parents[1])

    assert violations == []


def test_repo_local_branch_protection_audit_workflow_surfaces_pass_in_repo() -> None:
    violations = validate_branch_protection_audit_workflow_surfaces(
        Path(__file__).resolve().parents[1]
    )

    assert violations == []


def test_branch_protection_contract_surfaces_require_contract_file_when_github_context_present(
    tmp_path: Path,
) -> None:
    (tmp_path / ".github").mkdir()

    violations = validate_branch_protection_contract_surfaces(tmp_path)

    assert violations == [
        "github branch protection contract missing: .github/branch-protection.main.json"
    ]


def test_branch_protection_audit_workflow_surfaces_reject_extra_trigger_job_and_step(
    tmp_path: Path,
) -> None:
    _write_audit_workflow(
        tmp_path,
        """name: Branch Protection Audit
permissions:
  contents: read
on:
  workflow_dispatch: {}
  schedule:
    - cron: "17 * * * *"
  push:
    branches:
      - main
jobs:
  branch-protection-audit:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: Require audit token
        env:
          GH_TOKEN: ${{ secrets.BRANCH_PROTECTION_AUDIT_TOKEN }}
        run: 'test -n "$GH_TOKEN" || (echo "Missing secret: BRANCH_PROTECTION_AUDIT_TOKEN" >&2; exit 1)'
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --dev
      - env:
          GH_TOKEN: ${{ secrets.BRANCH_PROTECTION_AUDIT_TOKEN }}
        run: uv run python -m ai_sdlc verify github-branch-protection
      - run: echo leaked
  exfiltrate:
    runs-on: ubuntu-latest
    steps:
      - run: echo nope
""",
    )

    violations = validate_branch_protection_audit_workflow_surfaces(tmp_path)

    assert violations == [
        "github branch protection audit workflow .github/workflows/branch-protection-audit.yml triggers must only contain workflow_dispatch and schedule",
        "github branch protection audit workflow .github/workflows/branch-protection-audit.yml jobs must only contain branch-protection-audit",
    ]


def test_branch_protection_audit_workflow_surfaces_reject_extra_top_level_keys(
    tmp_path: Path,
) -> None:
    _write_audit_workflow(
        tmp_path,
        """name: Branch Protection Audit
permissions:
  contents: read
defaults:
  run:
    shell: bash
on:
  workflow_dispatch: {}
  schedule:
    - cron: "17 * * * *"
jobs:
  branch-protection-audit:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: Require audit token
        env:
          GH_TOKEN: ${{ secrets.BRANCH_PROTECTION_AUDIT_TOKEN }}
        run: 'test -n "$GH_TOKEN" || (echo "Missing secret: BRANCH_PROTECTION_AUDIT_TOKEN" >&2; exit 1)'
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --dev
      - env:
          GH_TOKEN: ${{ secrets.BRANCH_PROTECTION_AUDIT_TOKEN }}
        run: uv run python -m ai_sdlc verify github-branch-protection
""",
    )

    violations = validate_branch_protection_audit_workflow_surfaces(tmp_path)

    assert violations == [
        "github branch protection audit workflow .github/workflows/branch-protection-audit.yml top-level keys must equal ['jobs', 'name', 'on', 'permissions']"
    ]


def test_live_github_branch_protection_matches_contract(tmp_path: Path) -> None:
    _write_default_contract(tmp_path)

    def fake_runner(
        args: list[str], *, cwd: Path, capture_output: bool, text: bool
    ) -> subprocess.CompletedProcess[str]:
        assert args == [
            "gh",
            "api",
            "repos/sinclairpan-git/codex-watchdog/branches/main/protection",
        ]
        assert cwd == tmp_path
        assert capture_output is True
        assert text is True
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps(
                {
                    "required_status_checks": {
                        "strict": True,
                        "checks": [
                            {"context": "verify-constraints", "app_id": None},
                            {"context": "test", "app_id": None},
                            {"context": "lint", "app_id": None},
                        ],
                        "contexts": ["verify-constraints", "test", "lint"],
                    },
                    "required_pull_request_reviews": {
                        "dismiss_stale_reviews": True,
                        "require_code_owner_reviews": False,
                        "require_last_push_approval": False,
                        "required_approving_review_count": 1,
                    },
                    "enforce_admins": {"enabled": True},
                    "required_linear_history": {"enabled": True},
                    "allow_force_pushes": {"enabled": False},
                    "allow_deletions": {"enabled": False},
                    "block_creations": {"enabled": False},
                    "required_conversation_resolution": {"enabled": True},
                }
            ),
            stderr="",
        )

    violations = validate_live_github_branch_protection(tmp_path, runner=fake_runner)

    assert violations == []


def _write_default_contract(tmp_path: Path) -> None:
    _write_contract(
        tmp_path,
        {
            "owner": "sinclairpan-git",
            "repo": "codex-watchdog",
            "branch": "main",
            "required_status_checks": {
                "strict": True,
                "checks": [
                    {"context": "lint", "app_id": None},
                    {"context": "test", "app_id": None},
                    {"context": "verify-constraints", "app_id": None},
                ],
                "contexts": ["verify-constraints", "test", "lint"],
            },
            "required_pull_request_reviews": {
                "dismiss_stale_reviews": True,
                "require_code_owner_reviews": False,
                "require_last_push_approval": False,
                "required_approving_review_count": 1,
            },
            "enforce_admins": True,
            "required_linear_history": True,
            "allow_force_pushes": False,
            "allow_deletions": False,
            "block_creations": False,
            "required_conversation_resolution": True,
        },
    )


def _write_contract(tmp_path: Path, payload: dict[str, object]) -> None:
    path = tmp_path / BRANCH_PROTECTION_CONTRACT_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_audit_workflow(tmp_path: Path, payload: str) -> None:
    path = tmp_path / BRANCH_PROTECTION_AUDIT_WORKFLOW_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
