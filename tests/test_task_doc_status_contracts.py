from __future__ import annotations

import importlib
import textwrap
from pathlib import Path

import pytest


def _load_task_doc_module():
    try:
        return importlib.import_module("watchdog.validation.task_doc_status_contracts")
    except ModuleNotFoundError as exc:
        pytest.fail(f"missing task doc status validator module: {exc}")


def _write(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(contents).lstrip(), encoding="utf-8")


def test_task_doc_status_contracts_pass_in_repo() -> None:
    module = _load_task_doc_module()

    assert module.validate_task_doc_status_contracts() == []


def test_task_doc_status_contracts_flag_completed_wi_with_in_progress_task_doc(tmp_path: Path) -> None:
    module = _load_task_doc_module()

    _write(
        tmp_path / "specs/999-demo/tasks.md",
        """
        # tasks

        ## Task
        - **任务编号**：T999
        - **状态**：进行中
        """,
    )
    _write(
        tmp_path / ".ai-sdlc/work-items/999-demo/latest-summary.md",
        """
        # Development Summary

        Status: completed
        """,
    )
    _write(
        tmp_path / ".ai-sdlc/work-items/999-demo/execution-plan.yaml",
        """
        tasks:
        - task_id: T999
          status: completed
        """,
    )

    violations = module.validate_task_doc_status_contracts(tmp_path)

    assert any(
        "task doc status drift: specs/999-demo/tasks.md still contains unfinished status markers" in v
        for v in violations
    )


def test_task_doc_status_contracts_ignore_missing_completed_evidence(tmp_path: Path) -> None:
    module = _load_task_doc_module()

    _write(
        tmp_path / "specs/998-demo/tasks.md",
        """
        # tasks

        ## Task
        - **任务编号**：T998
        - **状态**：进行中
        """,
    )

    assert module.validate_task_doc_status_contracts(tmp_path) == []
