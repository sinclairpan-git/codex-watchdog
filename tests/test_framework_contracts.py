from __future__ import annotations

import importlib
import textwrap
from pathlib import Path

import pytest


def _load_framework_contracts_module():
    try:
        return importlib.import_module("watchdog.validation.framework_contracts")
    except ModuleNotFoundError as exc:
        pytest.fail(f"missing framework contracts validator module: {exc}")


def _write(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(contents).lstrip(), encoding="utf-8")


def test_framework_contracts_pass_in_repo() -> None:
    module = _load_framework_contracts_module()

    assert module.validate_framework_contracts() == []


def test_framework_contracts_require_canonical_backlog_for_initialized_repo(tmp_path: Path) -> None:
    module = _load_framework_contracts_module()

    _write(
        tmp_path / ".ai-sdlc/project/config/project-state.yaml",
        """
        status: initialized
        project_name: demo
        next_work_item_seq: 2
        """,
    )

    violations = module.validate_framework_contracts(tmp_path)

    assert (
        "missing canonical framework backlog docs/framework-defect-backlog.zh-CN.md"
        in violations
    )


def test_framework_contracts_flag_missing_required_backlog_fields(tmp_path: Path) -> None:
    module = _load_framework_contracts_module()

    _write(
        tmp_path / ".ai-sdlc/project/config/project-state.yaml",
        """
        status: initialized
        project_name: demo
        next_work_item_seq: 2
        """,
    )
    _write(
        tmp_path / "docs/framework-defect-backlog.zh-CN.md",
        """
        # Framework Defect Backlog

        ## FD-2026-04-05-001 示例缺陷
        - 现象: 示例
        - 风险等级: 高
        """,
    )

    violations = module.validate_framework_contracts(tmp_path)

    assert any(
        "framework-defect-backlog entry 'FD-2026-04-05-001 示例缺陷' missing required fields"
        in violation
        for violation in violations
    )


def test_canonical_classifier_returns_expected_formal_targets() -> None:
    module = _load_framework_contracts_module()

    assert module.classify_canonical_doc_path("architecture", name="full-loop-design") == Path(
        "docs/architecture/full-loop-design.md"
    )
    assert module.classify_canonical_doc_path(
        "spec",
        work_item_id="052-framework-defect-gate-and-path-discipline",
    ) == Path("specs/052-framework-defect-gate-and-path-discipline/spec.md")
    assert module.classify_canonical_doc_path(
        "tasks",
        work_item_id="052-framework-defect-gate-and-path-discipline",
    ) == Path("specs/052-framework-defect-gate-and-path-discipline/tasks.md")


def test_framework_contracts_reject_docs_superpowers_formal_targets(tmp_path: Path) -> None:
    module = _load_framework_contracts_module()

    (tmp_path / "docs/architecture").mkdir(parents=True)
    (tmp_path / "specs").mkdir(parents=True)

    violation = module.validate_formal_doc_candidate(
        tmp_path,
        artifact_kind="spec",
        candidate_path="docs/superpowers/specs/spec.md",
        work_item_id="052-framework-defect-gate-and-path-discipline",
    )

    assert violation == (
        "formal spec path must stay under "
        "specs/052-framework-defect-gate-and-path-discipline/spec.md, got docs/superpowers/specs/spec.md"
    )


def test_framework_backlog_reference_sync_passes_when_pipe_titles_match_spec_references(
    tmp_path: Path,
) -> None:
    module = _load_framework_contracts_module()

    _write(
        tmp_path / "docs/framework-defect-backlog.zh-CN.md",
        """
        # Framework Defect Backlog

        ## FD-2026-04-05-001 | 示例缺陷
        - 现象: 示例
        - 触发场景: 示例
        - 影响范围: 示例
        - 根因分类: 示例
        - 未来杜绝方案摘要: 示例
        - 建议改动层级: rule
        - 风险等级: 高
        - 可验证成功标准: 示例
        - 是否需要回归测试补充: 需要
        """,
    )
    _write(
        tmp_path / "specs/054-demo/spec.md",
        """
        承接 `FD-2026-04-05-001`。
        """,
    )

    assert module.validate_backlog_reference_sync(tmp_path) == []


def test_framework_backlog_reference_sync_flags_missing_defect_ids(tmp_path: Path) -> None:
    module = _load_framework_contracts_module()

    _write(
        tmp_path / "docs/framework-defect-backlog.zh-CN.md",
        """
        # Framework Defect Backlog

        ## FD-2026-04-05-001 | 示例缺陷
        - 现象: 示例
        - 触发场景: 示例
        - 影响范围: 示例
        - 根因分类: 示例
        - 未来杜绝方案摘要: 示例
        - 建议改动层级: rule
        - 风险等级: 高
        - 可验证成功标准: 示例
        - 是否需要回归测试补充: 需要
        """,
    )
    _write(
        tmp_path / "specs/054-demo/spec.md",
        """
        承接 `FD-2026-04-07-003`。
        """,
    )

    violations = module.validate_backlog_reference_sync(tmp_path)

    assert violations == [
        "breach_detected_but_not_logged: specs/054-demo/spec.md references missing backlog ids: FD-2026-04-07-003"
    ]
