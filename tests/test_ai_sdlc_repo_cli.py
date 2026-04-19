from __future__ import annotations

import tomllib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import ai_sdlc.cli as ai_sdlc_cli  # noqa: E402


def _no_violations(_repo_root: Path) -> list[str]:
    return []


def test_run_verify_constraints_reports_ok(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(ai_sdlc_cli, "validate_branch_protection_contract_surfaces", _no_violations)
    monkeypatch.setattr(
        ai_sdlc_cli, "validate_branch_protection_audit_workflow_surfaces", _no_violations
    )

    result = ai_sdlc_cli._run_verify_constraints(tmp_path)

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out == "Constraints OK\n"


def test_run_verify_github_branch_protection_reports_ok(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(ai_sdlc_cli, "validate_branch_protection_contract_surfaces", _no_violations)
    monkeypatch.setattr(ai_sdlc_cli, "validate_live_github_branch_protection", _no_violations)

    result = ai_sdlc_cli._run_verify_github_branch_protection(tmp_path)

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out == "GitHub branch protection OK\n"


def test_repo_local_wheel_target_includes_ai_sdlc_cli_package() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    packages = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]

    assert "ai_sdlc" in packages
