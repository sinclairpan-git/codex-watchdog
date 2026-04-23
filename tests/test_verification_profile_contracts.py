from __future__ import annotations

import importlib
import textwrap
from pathlib import Path

import pytest


def _load_verification_profile_module():
    try:
        return importlib.import_module("watchdog.validation.verification_profile_contracts")
    except ModuleNotFoundError as exc:
        pytest.fail(f"missing verification profile validator module: {exc}")


def _write(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(contents).lstrip(), encoding="utf-8")


def test_verification_profile_contracts_pass_in_repo() -> None:
    module = _load_verification_profile_module()

    assert module.validate_verification_profile_surfaces() == []


def test_verification_profile_contracts_require_rule_surface_when_checklist_exists(
    tmp_path: Path,
) -> None:
    module = _load_verification_profile_module()

    _write(
        tmp_path / "docs/pull-request-checklist.zh.md",
        """
        docs-only
        rules-only
        truth-only
        code-change
        uv run ai-sdlc verify constraints
        python -m ai_sdlc program truth sync --dry-run
        uv run pytest
        uv run ruff check
        """,
    )

    violations = module.validate_verification_profile_surfaces(tmp_path)

    assert violations == [
        "verification profile surface missing: src/ai_sdlc/rules/verification.md"
    ]


def test_verification_profile_contracts_flag_marker_drift(tmp_path: Path) -> None:
    module = _load_verification_profile_module()

    _write(tmp_path / "docs/pull-request-checklist.zh.md", "docs-only\n")
    _write(tmp_path / "src/ai_sdlc/rules/verification.md", "docs-only\n")

    violations = module.validate_verification_profile_surfaces(tmp_path)

    assert any(
        "verification profile surface docs/pull-request-checklist.zh.md missing required markers"
        in violation
        for violation in violations
    )
