from __future__ import annotations

import importlib
import textwrap
from pathlib import Path

import pytest


def _load_ci_gate_contracts_module():
    try:
        return importlib.import_module("watchdog.validation.ci_gate_contracts")
    except ModuleNotFoundError as exc:
        pytest.fail(f"missing ci gate validator module: {exc}")


def _write(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(contents).lstrip(), encoding="utf-8")


def test_ci_gate_contracts_pass_in_repo() -> None:
    module = _load_ci_gate_contracts_module()

    assert module.validate_ci_gate_surfaces() == []


def test_ci_gate_contracts_require_pr_gate_workflow_when_github_dir_exists(tmp_path: Path) -> None:
    module = _load_ci_gate_contracts_module()

    (tmp_path / ".github").mkdir(parents=True, exist_ok=True)

    violations = module.validate_ci_gate_surfaces(tmp_path)

    assert violations == ["ci gate surface missing: .github/workflows/pr-gate.yml"]


def test_ci_gate_contracts_flag_required_marker_drift(tmp_path: Path) -> None:
    module = _load_ci_gate_contracts_module()

    _write(
        tmp_path / ".github/workflows/pr-gate.yml",
        """
        name: PR Gate
        on:
          push:
            branches: ["main"]
        jobs:
          verify:
            runs-on: ubuntu-latest
            steps:
              - run: uv run pytest -q
        """,
    )

    violations = module.validate_ci_gate_surfaces(tmp_path)

    assert violations == [
        "ci gate surface .github/workflows/pr-gate.yml missing pull_request trigger",
        "ci gate surface .github/workflows/pr-gate.yml missing verify-constraints job",
        "ci gate surface .github/workflows/pr-gate.yml missing test job",
        "ci gate surface .github/workflows/pr-gate.yml missing lint job",
    ]


def test_ci_gate_contracts_require_pytest_marker(tmp_path: Path) -> None:
    module = _load_ci_gate_contracts_module()

    _write(
        tmp_path / ".github/workflows/pr-gate.yml",
        """
        name: PR Gate
        on:
          pull_request:
          push:
            branches: ["main"]
        jobs:
          verify-constraints:
            runs-on: ubuntu-latest
            steps:
              - run: uv run python -m ai_sdlc verify constraints
          test:
            needs: verify-constraints
            runs-on: ubuntu-latest
            steps:
              - run: echo "skip pytest"
          lint:
            needs: verify-constraints
            runs-on: ubuntu-latest
            steps:
              - run: uv run ruff check
        """,
    )

    violations = module.validate_ci_gate_surfaces(tmp_path)

    assert violations == [
        "ci gate surface .github/workflows/pr-gate.yml missing test command: uv run pytest"
    ]


def test_ci_gate_contracts_require_push_main_and_needs_dependency(tmp_path: Path) -> None:
    module = _load_ci_gate_contracts_module()

    _write(
        tmp_path / ".github/workflows/pr-gate.yml",
        """
        name: PR Gate
        on:
          pull_request:
          push:
            branches: ["release"]
        jobs:
          verify-constraints:
            runs-on: ubuntu-latest
            steps:
              - run: uv run python -m ai_sdlc verify constraints
          test:
            runs-on: ubuntu-latest
            steps:
              - run: uv run pytest -q
          lint:
            needs: verify-constraints
            runs-on: ubuntu-latest
            steps:
              - run: uv run ruff check
        """,
    )

    violations = module.validate_ci_gate_surfaces(tmp_path)

    assert violations == [
        "ci gate surface .github/workflows/pr-gate.yml missing push trigger for main",
        "ci gate surface .github/workflows/pr-gate.yml missing test needs verify-constraints",
    ]


def test_ci_gate_contracts_reject_unscoped_push_trigger(tmp_path: Path) -> None:
    module = _load_ci_gate_contracts_module()

    _write(
        tmp_path / ".github/workflows/pr-gate.yml",
        """
        name: PR Gate
        on:
          pull_request:
          push: {}
        jobs:
          verify-constraints:
            runs-on: ubuntu-latest
            steps:
              - run: uv run python -m ai_sdlc verify constraints
          test:
            needs: verify-constraints
            runs-on: ubuntu-latest
            steps:
              - run: uv run pytest -q
          lint:
            needs: verify-constraints
            runs-on: ubuntu-latest
            steps:
              - run: uv run ruff check
        """,
    )

    violations = module.validate_ci_gate_surfaces(tmp_path)

    assert violations == [
        "ci gate surface .github/workflows/pr-gate.yml missing push trigger for main"
    ]


def test_ci_gate_contracts_reject_filtered_pull_request_trigger(tmp_path: Path) -> None:
    module = _load_ci_gate_contracts_module()

    _write(
        tmp_path / ".github/workflows/pr-gate.yml",
        """
        name: PR Gate
        on:
          pull_request:
            branches: ["release"]
          push:
            branches: ["main"]
        jobs:
          verify-constraints:
            runs-on: ubuntu-latest
            steps:
              - run: uv run python -m ai_sdlc verify constraints
          test:
            needs: verify-constraints
            runs-on: ubuntu-latest
            steps:
              - run: uv run pytest -q
          lint:
            needs: verify-constraints
            runs-on: ubuntu-latest
            steps:
              - run: uv run ruff check
        """,
    )

    violations = module.validate_ci_gate_surfaces(tmp_path)

    assert violations == [
        "ci gate surface .github/workflows/pr-gate.yml missing unfiltered pull_request trigger"
    ]


def test_ci_gate_contracts_reject_job_level_bypass_controls(tmp_path: Path) -> None:
    module = _load_ci_gate_contracts_module()

    _write(
        tmp_path / ".github/workflows/pr-gate.yml",
        """
        name: PR Gate
        on:
          pull_request:
          push:
            branches: ["main"]
        jobs:
          verify-constraints:
            if: ${{ false }}
            continue-on-error: true
            runs-on: ubuntu-latest
            steps:
              - run: uv run python -m ai_sdlc verify constraints
          test:
            needs: verify-constraints
            runs-on: ubuntu-latest
            steps:
              - run: uv run pytest -q
          lint:
            needs: verify-constraints
            runs-on: ubuntu-latest
            steps:
              - run: uv run ruff check
        """,
    )

    violations = module.validate_ci_gate_surfaces(tmp_path)

    assert violations == [
        "ci gate surface .github/workflows/pr-gate.yml verify-constraints job must not define if",
        "ci gate surface .github/workflows/pr-gate.yml verify-constraints job must not define continue-on-error",
    ]


def test_ci_gate_contracts_reject_required_step_bypass_controls(tmp_path: Path) -> None:
    module = _load_ci_gate_contracts_module()

    _write(
        tmp_path / ".github/workflows/pr-gate.yml",
        """
        name: PR Gate
        on:
          pull_request:
          push:
            branches: ["main"]
        jobs:
          verify-constraints:
            runs-on: ubuntu-latest
            steps:
              - if: ${{ false }}
                run: uv run python -m ai_sdlc verify constraints
          test:
            needs: verify-constraints
            runs-on: ubuntu-latest
            steps:
              - continue-on-error: true
                run: uv run pytest -q
          lint:
            needs: verify-constraints
            runs-on: ubuntu-latest
            steps:
              - run: uv run ruff check
        """,
    )

    violations = module.validate_ci_gate_surfaces(tmp_path)

    assert violations == [
        "ci gate surface .github/workflows/pr-gate.yml verify-constraints command step must not define if",
        "ci gate surface .github/workflows/pr-gate.yml test command step must not define continue-on-error",
    ]


@pytest.mark.parametrize(
    ("command", "wrapped_run", "expected_violation"),
    [
        (
            "uv run python -m ai_sdlc verify constraints",
            'echo "uv run python -m ai_sdlc verify constraints"',
            "ci gate surface .github/workflows/pr-gate.yml missing verify-constraints command: "
            "uv run python -m ai_sdlc verify constraints",
        ),
        (
            "uv run pytest -q",
            "uv run pytest -q || true",
            "ci gate surface .github/workflows/pr-gate.yml missing test command: uv run pytest",
        ),
        (
            "uv run ruff check",
            "bash -lc 'uv run ruff check'",
            "ci gate surface .github/workflows/pr-gate.yml missing lint command: uv run ruff check",
        ),
    ],
)
def test_ci_gate_contracts_reject_shell_wrapped_required_commands(
    tmp_path: Path, command: str, wrapped_run: str, expected_violation: str
) -> None:
    module = _load_ci_gate_contracts_module()

    verify_run = "uv run python -m ai_sdlc verify constraints"
    test_run = "uv run pytest -q"
    lint_run = "uv run ruff check"
    if command == verify_run:
        verify_run = wrapped_run
    elif command == test_run:
        test_run = wrapped_run
    else:
        lint_run = wrapped_run

    _write(
        tmp_path / ".github/workflows/pr-gate.yml",
        f"""
        name: PR Gate
        on:
          pull_request:
          push:
            branches: ["main"]
        jobs:
          verify-constraints:
            runs-on: ubuntu-latest
            steps:
              - run: {verify_run}
          test:
            needs: verify-constraints
            runs-on: ubuntu-latest
            steps:
              - run: {test_run}
          lint:
            needs: verify-constraints
            runs-on: ubuntu-latest
            steps:
              - run: {lint_run}
        """,
    )

    violations = module.validate_ci_gate_surfaces(tmp_path)

    assert violations == [expected_violation]
