from __future__ import annotations

import importlib
import textwrap
from pathlib import Path

import pytest


def _load_residual_contracts_module():
    try:
        return importlib.import_module("watchdog.validation.long_running_residual_contracts")
    except ModuleNotFoundError as exc:
        pytest.fail(f"missing long-running residual validator module: {exc}")


def _write(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(contents).lstrip(), encoding="utf-8")


def test_long_running_residual_contracts_pass_in_repo() -> None:
    module = _load_residual_contracts_module()

    assert module.validate_long_running_residual_contracts() == []


def test_long_running_residual_contracts_flag_item_missing_evidence_refs(tmp_path: Path) -> None:
    module = _load_residual_contracts_module()

    _write(
        tmp_path / "docs/architecture/long-running-residual-backlog-ledger.yaml",
        """
        version: 1
        residual_items:
          - residual_id: RES-001
            source_refs:
              - openclaw-codex-watchdog-prd.md
            disposition: residual
            formal_truth_refs: []
            notes: example
        """,
    )
    _write(
        tmp_path / "docs/architecture/long-running-residual-backlog-status.md",
        """
        # Long-Running Residual Backlog Status

        Canonical ledger: `docs/architecture/long-running-residual-backlog-ledger.yaml`
        residual_count: 1
        """,
    )

    violations = module.validate_long_running_residual_contracts(tmp_path)

    assert any(
        "long-running residual contract drift: residual item RES-001 missing source_refs/formal_truth_refs"
        in violation
        for violation in violations
    )


def test_long_running_residual_contracts_flag_status_doc_mismatch(tmp_path: Path) -> None:
    module = _load_residual_contracts_module()

    _write(
        tmp_path / "docs/architecture/long-running-residual-backlog-ledger.yaml",
        """
        version: 1
        residual_items:
          - residual_id: RES-001
            source_refs:
              - openclaw-codex-watchdog-prd.md
            disposition: residual
            formal_truth_refs:
              - .ai-sdlc/state/checkpoint.yml
            notes: example
        """,
    )
    _write(
        tmp_path / "docs/architecture/long-running-residual-backlog-status.md",
        """
        # Long-Running Residual Backlog Status

        Canonical ledger: `docs/architecture/long-running-residual-backlog-ledger.yaml`
        NO_RESIDUAL_BLOCKERS
        """,
    )

    violations = module.validate_long_running_residual_contracts(tmp_path)

    assert any(
        "long-running residual contract drift: status doc claims NO_RESIDUAL_BLOCKERS but ledger still contains residual items"
        in violation
        for violation in violations
    )


def test_long_running_residual_contracts_allow_empty_ledger_with_no_residual_blockers(
    tmp_path: Path,
) -> None:
    module = _load_residual_contracts_module()

    _write(
        tmp_path / "docs/architecture/long-running-residual-backlog-ledger.yaml",
        """
        version: 1
        residual_items: []
        """,
    )
    _write(
        tmp_path / "docs/architecture/long-running-residual-backlog-status.md",
        """
        # Long-Running Residual Backlog Status

        Canonical ledger: `docs/architecture/long-running-residual-backlog-ledger.yaml`
        NO_RESIDUAL_BLOCKERS
        residual_count: 0
        """,
    )

    assert module.validate_long_running_residual_contracts(tmp_path) == []
