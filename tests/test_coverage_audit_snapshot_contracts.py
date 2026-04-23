from __future__ import annotations

import importlib
import textwrap
from pathlib import Path

import pytest


def _load_snapshot_contracts_module():
    try:
        return importlib.import_module("watchdog.validation.coverage_audit_snapshot_contracts")
    except ModuleNotFoundError as exc:
        pytest.fail(f"missing coverage audit snapshot validator module: {exc}")


def _write(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(contents).lstrip(), encoding="utf-8")


def test_coverage_audit_snapshot_contracts_pass_in_repo() -> None:
    module = _load_snapshot_contracts_module()

    assert module.validate_coverage_audit_snapshot_contracts() == []


def test_coverage_audit_snapshot_contracts_flag_missing_closeout_status_doc(tmp_path: Path) -> None:
    module = _load_snapshot_contracts_module()

    _write(
        tmp_path / "docs/superpowers/specs/2026-04-14-coverage-audit-matrix.md",
        """
        # 覆盖性审计矩阵（需求文档 + 计划 + 架构）

        > 历史快照（2026-04-14）。
        > 本文档已被 `WI-048` 到 `WI-056` 的 formal closeout 替代。
        > 当前真值入口：`docs/architecture/coverage-audit-closeout-status.md`
        """,
    )

    violations = module.validate_coverage_audit_snapshot_contracts(tmp_path)

    assert (
        "coverage audit snapshot missing required doc: docs/architecture/coverage-audit-closeout-status.md"
        in violations
    )


def test_coverage_audit_snapshot_contracts_flag_matrix_without_superseded_markers(
    tmp_path: Path,
) -> None:
    module = _load_snapshot_contracts_module()

    _write(
        tmp_path / "docs/superpowers/specs/2026-04-14-coverage-audit-matrix.md",
        """
        # 覆盖性审计矩阵（需求文档 + 计划 + 架构）
        """,
    )
    _write(
        tmp_path / "docs/architecture/coverage-audit-closeout-status.md",
        """
        # Coverage Audit Closeout Status

        `specs/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/matrix-owner-ledger.yaml`
        `WI-048`
        `WI-049`
        `WI-050`
        `WI-051`
        `WI-052`
        `WI-053`
        `WI-054`
        `WI-055`
        `.ai-sdlc/state/checkpoint.yml`
        `.ai-sdlc/project/config/project-state.yaml`
        `NO_BLOCKERS`
        """,
    )

    violations = module.validate_coverage_audit_snapshot_contracts(tmp_path)

    assert any(
        "coverage audit snapshot drift: docs/superpowers/specs/2026-04-14-coverage-audit-matrix.md missing required markers"
        in violation
        for violation in violations
    )
