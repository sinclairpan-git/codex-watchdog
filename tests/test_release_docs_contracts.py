from __future__ import annotations

import importlib
import textwrap
from pathlib import Path

import pytest


def _load_release_docs_module():
    try:
        return importlib.import_module("watchdog.validation.release_docs_contracts")
    except ModuleNotFoundError as exc:
        pytest.fail(f"missing release docs validator module: {exc}")


def _write(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(contents).lstrip(), encoding="utf-8")


def test_release_docs_contracts_pass_in_repo() -> None:
    module = _load_release_docs_module()

    assert module.validate_release_docs_consistency() == []


def test_release_docs_contracts_flag_missing_required_entry_doc(tmp_path: Path) -> None:
    module = _load_release_docs_module()

    _write(
        tmp_path / "README.md",
        """
        # AI-SDLC

        `v0.6.0`

        - Windows offline bundle: `ai-sdlc-offline-0.6.0.zip`
        - macOS / Linux offline bundle: `ai-sdlc-offline-0.6.0.tar.gz`
        - Release notes: `docs/releases/v0.6.0.md`
        """,
    )

    violations = module.validate_release_docs_consistency(tmp_path)

    assert (
        "release docs consistency missing required entry doc: docs/releases/v0.6.0.md"
        in violations
    )


def test_release_docs_contracts_flag_readme_marker_drift(tmp_path: Path) -> None:
    module = _load_release_docs_module()

    _write(tmp_path / "README.md", "# AI-SDLC\n")
    _write(
        tmp_path / "docs/releases/v0.6.0.md",
        "# AI-SDLC v0.6.0 Release Notes\n\nWindows `.zip`\nmacOS / Linux `.tar.gz`\n",
    )
    _write(tmp_path / "USER_GUIDE.zh-CN.md", "v0.6.0\nWindows\nmacOS\nLinux\n.zip\n.tar.gz\n")
    _write(tmp_path / "packaging/offline/README.md", "v0.6.0\nWindows\n.zip\nLinux/macOS\n.tar.gz\n")
    _write(
        tmp_path / "docs/框架自迭代开发与发布约定.md",
        "README.md\ndocs/releases/v0.6.0.md\nUSER_GUIDE.zh-CN.md\npackaging/offline/README.md\n"
        "docs/pull-request-checklist.zh.md\nWindows\n.zip\nmacOS / Linux\n.tar.gz\n",
    )
    _write(
        tmp_path / "docs/pull-request-checklist.zh.md",
        "README.md\ndocs/releases/v0.6.0.md\nUSER_GUIDE.zh-CN.md\npackaging/offline/README.md\n"
        "v0.6.0\nWindows\n.zip\nmacOS / Linux\n.tar.gz\n",
    )

    violations = module.validate_release_docs_consistency(tmp_path)

    assert any(
        "release docs consistency drift: README.md missing required markers" in violation
        for violation in violations
    )


def test_release_docs_contracts_flag_checklist_marker_drift(tmp_path: Path) -> None:
    module = _load_release_docs_module()

    _write(
        tmp_path / "README.md",
        """
        # AI-SDLC

        `v0.6.0`

        - Windows offline bundle: `ai-sdlc-offline-0.6.0.zip`
        - macOS / Linux offline bundle: `ai-sdlc-offline-0.6.0.tar.gz`
        - Release notes: `docs/releases/v0.6.0.md`
        """,
    )
    _write(
        tmp_path / "docs/releases/v0.6.0.md",
        "# AI-SDLC v0.6.0 Release Notes\n\nv0.6.0\nWindows\n.zip\nmacOS / Linux\n.tar.gz\n",
    )
    _write(tmp_path / "USER_GUIDE.zh-CN.md", "v0.6.0\nWindows\nmacOS\nLinux\n.zip\n.tar.gz\n")
    _write(tmp_path / "packaging/offline/README.md", "v0.6.0\nWindows\n.zip\nLinux/macOS\n.tar.gz\n")
    _write(
        tmp_path / "docs/框架自迭代开发与发布约定.md",
        "README.md\ndocs/releases/v0.6.0.md\nUSER_GUIDE.zh-CN.md\npackaging/offline/README.md\n"
        "docs/pull-request-checklist.zh.md\nWindows\n.zip\nmacOS / Linux\n.tar.gz\n",
    )
    _write(tmp_path / "docs/pull-request-checklist.zh.md", "README.md\n")

    violations = module.validate_release_docs_consistency(tmp_path)

    assert any(
        "release docs consistency drift: docs/pull-request-checklist.zh.md missing required markers"
        in violation
        for violation in violations
    )
