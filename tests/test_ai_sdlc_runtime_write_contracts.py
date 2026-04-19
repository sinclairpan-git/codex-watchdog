from __future__ import annotations

import importlib
import textwrap
from pathlib import Path

import pytest


def _load_runtime_write_contracts_module():
    try:
        return importlib.import_module("watchdog.validation.ai_sdlc_runtime_write_contracts")
    except ModuleNotFoundError as exc:
        pytest.fail(f"missing runtime write contracts module: {exc}")


def _write(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(contents).lstrip(), encoding="utf-8")


def test_validate_runtime_write_entrypoints_flags_unapproved_runtime_writer(
    tmp_path: Path,
) -> None:
    runtime_write_contracts = _load_runtime_write_contracts_module()

    _write(
        tmp_path / "src/watchdog/services/runtime_writer.py",
        """
        from pathlib import Path

        def write_runtime(repo_root: Path) -> None:
            path = repo_root / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"
            path.write_text("current_stage: verify\\n", encoding="utf-8")
        """,
    )

    assert runtime_write_contracts.validate_runtime_write_entrypoints(tmp_path) == [
        "runtime write entrypoint (src/watchdog/services/runtime_writer.py): "
        "runtime.yaml writes must go through watchdog.validation.ai_sdlc_runtime_io.write_yaml_atomic"
    ]


def test_validate_runtime_write_entrypoints_ignores_test_only_runtime_writers(
    tmp_path: Path,
) -> None:
    runtime_write_contracts = _load_runtime_write_contracts_module()

    _write(
        tmp_path / "tests/test_runtime_writer.py",
        """
        from pathlib import Path

        def write_runtime(repo_root: Path) -> None:
            path = repo_root / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"
            path.write_text("current_stage: verify\\n", encoding="utf-8")
        """,
    )

    assert runtime_write_contracts.validate_runtime_write_entrypoints(tmp_path) == []


def test_validate_runtime_write_entrypoints_flags_unapproved_script_runtime_writer(
    tmp_path: Path,
) -> None:
    runtime_write_contracts = _load_runtime_write_contracts_module()

    _write(
        tmp_path / "scripts/runtime_writer.py",
        """
        from pathlib import Path

        def write_runtime(repo_root: Path) -> None:
            path = repo_root / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"
            path.write_text("current_stage: verify\\n", encoding="utf-8")
        """,
    )

    assert runtime_write_contracts.validate_runtime_write_entrypoints(tmp_path) == [
        "runtime write entrypoint (scripts/runtime_writer.py): "
        "runtime.yaml writes must go through watchdog.validation.ai_sdlc_runtime_io.write_yaml_atomic"
    ]


def test_validate_runtime_write_entrypoints_flags_separated_runtime_writer(
    tmp_path: Path,
) -> None:
    runtime_write_contracts = _load_runtime_write_contracts_module()

    _write(
        tmp_path / "src/watchdog/services/runtime_writer.py",
        """
        from pathlib import Path

        def write_runtime(repo_root: Path) -> None:
            runtime_path = repo_root / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"

            payload = "current_stage: verify\\n"

            runtime_path.write_text(payload, encoding="utf-8")
        """,
    )

    assert runtime_write_contracts.validate_runtime_write_entrypoints(tmp_path) == [
        "runtime write entrypoint (src/watchdog/services/runtime_writer.py): "
        "runtime.yaml writes must go through watchdog.validation.ai_sdlc_runtime_io.write_yaml_atomic"
    ]


def test_validate_runtime_write_entrypoints_flags_helper_indirection_runtime_writer(
    tmp_path: Path,
) -> None:
    runtime_write_contracts = _load_runtime_write_contracts_module()

    _write(
        tmp_path / "src/watchdog/services/runtime_writer.py",
        """
        from pathlib import Path

        def _write_yaml(path: Path, payload: str) -> None:
            path.write_text(payload, encoding="utf-8")

        def write_runtime(repo_root: Path) -> None:
            runtime_path = repo_root / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"
            _write_yaml(runtime_path, "current_stage: verify\\n")
        """,
    )

    assert runtime_write_contracts.validate_runtime_write_entrypoints(tmp_path) == [
        "runtime write entrypoint (src/watchdog/services/runtime_writer.py): "
        "runtime.yaml writes must go through watchdog.validation.ai_sdlc_runtime_io.write_yaml_atomic"
    ]


def test_validate_runtime_write_entrypoints_allows_guarded_runtime_helper(
    tmp_path: Path,
) -> None:
    runtime_write_contracts = _load_runtime_write_contracts_module()

    _write(
        tmp_path / "scripts/runtime_writer.py",
        """
        from pathlib import Path

        from watchdog.validation.ai_sdlc_runtime_io import write_yaml_atomic

        def _write_yaml(path: Path, payload: str) -> None:
            if path.name == "runtime.yaml":
                write_yaml_atomic(path, {"current_stage": payload})
                return
            path.write_text(payload, encoding="utf-8")
        """,
    )

    assert runtime_write_contracts.validate_runtime_write_entrypoints(tmp_path) == []


def test_validate_runtime_write_entrypoints_flags_method_indirection_runtime_writer(
    tmp_path: Path,
) -> None:
    runtime_write_contracts = _load_runtime_write_contracts_module()

    _write(
        tmp_path / "src/watchdog/services/runtime_writer.py",
        """
        from pathlib import Path

        class RuntimeWriter:
            def _write_yaml(self, path: Path, payload: str) -> None:
                path.write_text(payload, encoding="utf-8")

        def write_runtime(repo_root: Path) -> None:
            runtime_path = repo_root / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"
            RuntimeWriter()._write_yaml(runtime_path, "current_stage: verify\\n")
        """,
    )

    assert runtime_write_contracts.validate_runtime_write_entrypoints(tmp_path) == [
        "runtime write entrypoint (src/watchdog/services/runtime_writer.py): "
        "runtime.yaml writes must go through watchdog.validation.ai_sdlc_runtime_io.write_yaml_atomic"
    ]


def test_validate_runtime_write_entrypoints_flags_keyword_only_runtime_writer(
    tmp_path: Path,
) -> None:
    runtime_write_contracts = _load_runtime_write_contracts_module()

    _write(
        tmp_path / "src/watchdog/services/runtime_writer.py",
        """
        from pathlib import Path

        def _write_yaml(*, path: Path, payload: str) -> None:
            path.write_text(payload, encoding="utf-8")

        def write_runtime(repo_root: Path) -> None:
            runtime_path = repo_root / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"
            _write_yaml(path=runtime_path, payload="current_stage: verify\\n")
        """,
    )

    assert runtime_write_contracts.validate_runtime_write_entrypoints(tmp_path) == [
        "runtime write entrypoint (src/watchdog/services/runtime_writer.py): "
        "runtime.yaml writes must go through watchdog.validation.ai_sdlc_runtime_io.write_yaml_atomic"
    ]


def test_validate_runtime_write_entrypoints_flags_callable_alias_runtime_writer(
    tmp_path: Path,
) -> None:
    runtime_write_contracts = _load_runtime_write_contracts_module()

    _write(
        tmp_path / "src/watchdog/services/runtime_writer.py",
        """
        from pathlib import Path

        def _write_yaml(path: Path, payload: str) -> None:
            path.write_text(payload, encoding="utf-8")

        def write_runtime(repo_root: Path) -> None:
            runtime_path = repo_root / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"
            writer = _write_yaml
            writer(runtime_path, "current_stage: verify\\n")
        """,
    )

    assert runtime_write_contracts.validate_runtime_write_entrypoints(tmp_path) == [
        "runtime write entrypoint (src/watchdog/services/runtime_writer.py): "
        "runtime.yaml writes must go through watchdog.validation.ai_sdlc_runtime_io.write_yaml_atomic"
    ]


def test_validate_runtime_write_entrypoints_flags_factory_returned_callable_runtime_writer(
    tmp_path: Path,
) -> None:
    runtime_write_contracts = _load_runtime_write_contracts_module()

    _write(
        tmp_path / "src/watchdog/services/runtime_writer.py",
        """
        from pathlib import Path

        def _write_yaml(path: Path, payload: str) -> None:
            path.write_text(payload, encoding="utf-8")

        def make_writer():
            return _write_yaml

        def write_runtime(repo_root: Path) -> None:
            runtime_path = repo_root / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"
            writer = make_writer()
            writer(runtime_path, "current_stage: verify\\n")
        """,
    )

    assert runtime_write_contracts.validate_runtime_write_entrypoints(tmp_path) == [
        "runtime write entrypoint (src/watchdog/services/runtime_writer.py): "
        "runtime.yaml writes must go through watchdog.validation.ai_sdlc_runtime_io.write_yaml_atomic"
    ]


def test_validate_runtime_write_entrypoints_flags_lambda_runtime_writer(
    tmp_path: Path,
) -> None:
    runtime_write_contracts = _load_runtime_write_contracts_module()

    _write(
        tmp_path / "src/watchdog/services/runtime_writer.py",
        """
        from pathlib import Path

        def write_runtime(repo_root: Path) -> None:
            runtime_path = repo_root / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"
            writer = lambda path, payload: path.write_text(payload, encoding="utf-8")
            writer(runtime_path, "current_stage: verify\\n")
        """,
    )

    assert runtime_write_contracts.validate_runtime_write_entrypoints(tmp_path) == [
        "runtime write entrypoint (src/watchdog/services/runtime_writer.py): "
        "runtime.yaml writes must go through watchdog.validation.ai_sdlc_runtime_io.write_yaml_atomic"
    ]


def test_validate_runtime_write_entrypoints_flags_partial_runtime_writer(
    tmp_path: Path,
) -> None:
    runtime_write_contracts = _load_runtime_write_contracts_module()

    _write(
        tmp_path / "src/watchdog/services/runtime_writer.py",
        """
        from functools import partial
        from pathlib import Path

        def _write_yaml(path: Path, payload: str) -> None:
            path.write_text(payload, encoding="utf-8")

        def write_runtime(repo_root: Path) -> None:
            runtime_path = repo_root / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"
            writer = partial(_write_yaml, runtime_path)
            writer("current_stage: verify\\n")
        """,
    )

    assert runtime_write_contracts.validate_runtime_write_entrypoints(tmp_path) == [
        "runtime write entrypoint (src/watchdog/services/runtime_writer.py): "
        "runtime.yaml writes must go through watchdog.validation.ai_sdlc_runtime_io.write_yaml_atomic"
    ]


def test_validate_runtime_write_entrypoints_flags_partial_alias_runtime_writer(
    tmp_path: Path,
) -> None:
    runtime_write_contracts = _load_runtime_write_contracts_module()

    _write(
        tmp_path / "src/watchdog/services/runtime_writer.py",
        """
        from functools import partial as p
        from pathlib import Path

        def _write_yaml(path: Path, payload: str) -> None:
            path.write_text(payload, encoding="utf-8")

        def write_runtime(repo_root: Path) -> None:
            runtime_path = repo_root / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"
            writer = p(_write_yaml, runtime_path)
            writer("current_stage: verify\\n")
        """,
    )

    assert runtime_write_contracts.validate_runtime_write_entrypoints(tmp_path) == [
        "runtime write entrypoint (src/watchdog/services/runtime_writer.py): "
        "runtime.yaml writes must go through watchdog.validation.ai_sdlc_runtime_io.write_yaml_atomic"
    ]


def test_validate_runtime_write_entrypoints_flags_partialmethod_alias_runtime_writer(
    tmp_path: Path,
) -> None:
    runtime_write_contracts = _load_runtime_write_contracts_module()

    _write(
        tmp_path / "src/watchdog/services/runtime_writer.py",
        """
        from functools import partialmethod as pm
        from pathlib import Path

        def write_runtime(repo_root: Path) -> None:
            runtime_path = repo_root / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"

            class RuntimeWriter:
                def _write_yaml(self, path: Path, payload: str) -> None:
                    path.write_text(payload, encoding="utf-8")

                write_runtime_file = pm(_write_yaml, runtime_path)

            RuntimeWriter().write_runtime_file("current_stage: verify\\n")
        """,
    )

    assert runtime_write_contracts.validate_runtime_write_entrypoints(tmp_path) == [
        "runtime write entrypoint (src/watchdog/services/runtime_writer.py): "
        "runtime.yaml writes must go through watchdog.validation.ai_sdlc_runtime_io.write_yaml_atomic"
    ]


def test_validate_runtime_write_entrypoints_flags_partial_wrapper_alias_runtime_writer(
    tmp_path: Path,
) -> None:
    runtime_write_contracts = _load_runtime_write_contracts_module()

    _write(
        tmp_path / "src/watchdog/services/runtime_writer.py",
        """
        from functools import partial
        from pathlib import Path

        def _write_yaml(path: Path, payload: str) -> None:
            path.write_text(payload, encoding="utf-8")

        def write_runtime(repo_root: Path) -> None:
            runtime_path = repo_root / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"
            wrapper = partial
            writer = wrapper(_write_yaml, runtime_path)
            writer("current_stage: verify\\n")
        """,
    )

    assert runtime_write_contracts.validate_runtime_write_entrypoints(tmp_path) == [
        "runtime write entrypoint (src/watchdog/services/runtime_writer.py): "
        "runtime.yaml writes must go through watchdog.validation.ai_sdlc_runtime_io.write_yaml_atomic"
    ]


def test_validate_runtime_write_entrypoints_flags_partialmethod_wrapper_alias_runtime_writer(
    tmp_path: Path,
) -> None:
    runtime_write_contracts = _load_runtime_write_contracts_module()

    _write(
        tmp_path / "src/watchdog/services/runtime_writer.py",
        """
        from functools import partialmethod
        from pathlib import Path

        def write_runtime(repo_root: Path) -> None:
            runtime_path = repo_root / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"

            class RuntimeWriter:
                wrapper = partialmethod

                def _write_yaml(self, path: Path, payload: str) -> None:
                    path.write_text(payload, encoding="utf-8")

                write_runtime_file = wrapper(_write_yaml, runtime_path)

            RuntimeWriter().write_runtime_file("current_stage: verify\\n")
        """,
    )

    assert runtime_write_contracts.validate_runtime_write_entrypoints(tmp_path) == [
        "runtime write entrypoint (src/watchdog/services/runtime_writer.py): "
        "runtime.yaml writes must go through watchdog.validation.ai_sdlc_runtime_io.write_yaml_atomic"
    ]


def test_validate_runtime_write_entrypoints_flags_definition_time_decorator_runtime_writer(
    tmp_path: Path,
) -> None:
    runtime_write_contracts = _load_runtime_write_contracts_module()

    _write(
        tmp_path / "src/watchdog/services/runtime_writer.py",
        """
        from pathlib import Path

        def _decorate(path: Path):
            path.write_text("current_stage: verify\\n", encoding="utf-8")

            def _identity(func):
                return func

            return _identity

        def write_runtime(repo_root: Path) -> None:
            runtime_path = repo_root / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"

            @_decorate(runtime_path)
            def _writer() -> None:
                return None
        """,
    )

    assert runtime_write_contracts.validate_runtime_write_entrypoints(tmp_path) == [
        "runtime write entrypoint (src/watchdog/services/runtime_writer.py): "
        "runtime.yaml writes must go through watchdog.validation.ai_sdlc_runtime_io.write_yaml_atomic"
    ]


def test_validate_runtime_write_entrypoints_flags_definition_time_class_base_runtime_writer(
    tmp_path: Path,
) -> None:
    runtime_write_contracts = _load_runtime_write_contracts_module()

    _write(
        tmp_path / "src/watchdog/services/runtime_writer.py",
        """
        from pathlib import Path

        def _base(path: Path):
            path.write_text("current_stage: verify\\n", encoding="utf-8")
            return object

        def write_runtime(repo_root: Path) -> None:
            runtime_path = repo_root / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"

            class RuntimeWriter(_base(runtime_path)):
                pass
        """,
    )

    assert runtime_write_contracts.validate_runtime_write_entrypoints(tmp_path) == [
        "runtime write entrypoint (src/watchdog/services/runtime_writer.py): "
        "runtime.yaml writes must go through watchdog.validation.ai_sdlc_runtime_io.write_yaml_atomic"
    ]


def test_validate_runtime_write_entrypoints_flags_definition_time_default_runtime_writer(
    tmp_path: Path,
) -> None:
    runtime_write_contracts = _load_runtime_write_contracts_module()

    _write(
        tmp_path / "src/watchdog/services/runtime_writer.py",
        """
        from pathlib import Path

        def _write_yaml(path: Path) -> str:
            path.write_text("current_stage: verify\\n", encoding="utf-8")
            return "verify"

        def write_runtime(repo_root: Path) -> None:
            runtime_path = repo_root / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"

            def _writer(stage: str = _write_yaml(runtime_path)) -> None:
                return None
        """,
    )

    assert runtime_write_contracts.validate_runtime_write_entrypoints(tmp_path) == [
        "runtime write entrypoint (src/watchdog/services/runtime_writer.py): "
        "runtime.yaml writes must go through watchdog.validation.ai_sdlc_runtime_io.write_yaml_atomic"
    ]


def test_validate_runtime_write_entrypoints_flags_definition_time_annotation_runtime_writer(
    tmp_path: Path,
) -> None:
    runtime_write_contracts = _load_runtime_write_contracts_module()

    _write(
        tmp_path / "src/watchdog/services/runtime_writer.py",
        """
        from pathlib import Path

        def _annotate(path: Path):
            path.write_text("current_stage: verify\\n", encoding="utf-8")
            return str

        def write_runtime(repo_root: Path) -> None:
            runtime_path = repo_root / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"

            def _writer(stage: _annotate(runtime_path)) -> None:
                return None
        """,
    )

    assert runtime_write_contracts.validate_runtime_write_entrypoints(tmp_path) == [
        "runtime write entrypoint (src/watchdog/services/runtime_writer.py): "
        "runtime.yaml writes must go through watchdog.validation.ai_sdlc_runtime_io.write_yaml_atomic"
    ]


def test_validate_runtime_write_entrypoints_flags_class_wrapper_alias_runtime_writer(
    tmp_path: Path,
) -> None:
    runtime_write_contracts = _load_runtime_write_contracts_module()

    _write(
        tmp_path / "src/watchdog/services/runtime_writer.py",
        """
        from functools import partial
        from pathlib import Path

        class RuntimeWriter:
            wrapper = partial

            def _write_yaml(self, path: Path, payload: str) -> None:
                path.write_text(payload, encoding="utf-8")

            def write_runtime(self, repo_root: Path) -> None:
                runtime_path = repo_root / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"
                writer = self.wrapper(self._write_yaml, runtime_path)
                writer("current_stage: verify\\n")
        """,
    )

    assert runtime_write_contracts.validate_runtime_write_entrypoints(tmp_path) == [
        "runtime write entrypoint (src/watchdog/services/runtime_writer.py): "
        "runtime.yaml writes must go through watchdog.validation.ai_sdlc_runtime_io.write_yaml_atomic"
    ]


def test_validate_runtime_write_entrypoints_flags_async_with_runtime_writer(
    tmp_path: Path,
) -> None:
    runtime_write_contracts = _load_runtime_write_contracts_module()

    _write(
        tmp_path / "src/watchdog/services/runtime_writer.py",
        """
        from pathlib import Path

        async def write_runtime(repo_root: Path) -> None:
            runtime_path = repo_root / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"
            async with runtime_path.open("w", encoding="utf-8") as handle:
                return None
        """,
    )

    assert runtime_write_contracts.validate_runtime_write_entrypoints(tmp_path) == [
        "runtime write entrypoint (src/watchdog/services/runtime_writer.py): "
        "runtime.yaml writes must go through watchdog.validation.ai_sdlc_runtime_io.write_yaml_atomic"
    ]


def test_validate_runtime_write_entrypoints_flags_assert_runtime_writer(
    tmp_path: Path,
) -> None:
    runtime_write_contracts = _load_runtime_write_contracts_module()

    _write(
        tmp_path / "src/watchdog/services/runtime_writer.py",
        """
        from pathlib import Path

        def write_runtime(repo_root: Path) -> None:
            runtime_path = repo_root / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"
            assert open(runtime_path, "w", encoding="utf-8")
        """,
    )

    assert runtime_write_contracts.validate_runtime_write_entrypoints(tmp_path) == [
        "runtime write entrypoint (src/watchdog/services/runtime_writer.py): "
        "runtime.yaml writes must go through watchdog.validation.ai_sdlc_runtime_io.write_yaml_atomic"
    ]


def test_validate_runtime_write_entrypoints_flags_match_runtime_writer(
    tmp_path: Path,
) -> None:
    runtime_write_contracts = _load_runtime_write_contracts_module()

    _write(
        tmp_path / "src/watchdog/services/runtime_writer.py",
        """
        from pathlib import Path

        def write_runtime(repo_root: Path) -> None:
            runtime_path = repo_root / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"
            match 1:
                case 1 if open(runtime_path, "w", encoding="utf-8"):
                    return None
        """,
    )

    assert runtime_write_contracts.validate_runtime_write_entrypoints(tmp_path) == [
        "runtime write entrypoint (src/watchdog/services/runtime_writer.py): "
        "runtime.yaml writes must go through watchdog.validation.ai_sdlc_runtime_io.write_yaml_atomic"
    ]


def test_validate_runtime_write_entrypoints_flags_try_star_runtime_writer(
    tmp_path: Path,
) -> None:
    runtime_write_contracts = _load_runtime_write_contracts_module()

    _write(
        tmp_path / "src/watchdog/services/runtime_writer.py",
        """
        from pathlib import Path

        def write_runtime(repo_root: Path) -> None:
            runtime_path = repo_root / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"
            try:
                raise ExceptionGroup("boom", [ValueError("x")])
            except* ValueError:
                open(runtime_path, "w", encoding="utf-8")
        """,
    )

    assert runtime_write_contracts.validate_runtime_write_entrypoints(tmp_path) == [
        "runtime write entrypoint (src/watchdog/services/runtime_writer.py): "
        "runtime.yaml writes must go through watchdog.validation.ai_sdlc_runtime_io.write_yaml_atomic"
    ]


def test_validate_runtime_write_entrypoints_flags_except_type_runtime_writer(
    tmp_path: Path,
) -> None:
    runtime_write_contracts = _load_runtime_write_contracts_module()

    _write(
        tmp_path / "src/watchdog/services/runtime_writer.py",
        """
        from pathlib import Path

        def write_runtime(repo_root: Path) -> None:
            runtime_path = repo_root / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"
            try:
                raise ValueError("boom")
            except open(runtime_path, "w", encoding="utf-8"):
                return None
        """,
    )

    assert runtime_write_contracts.validate_runtime_write_entrypoints(tmp_path) == [
        "runtime write entrypoint (src/watchdog/services/runtime_writer.py): "
        "runtime.yaml writes must go through watchdog.validation.ai_sdlc_runtime_io.write_yaml_atomic"
    ]


def test_validate_runtime_write_entrypoints_flags_except_star_type_runtime_writer(
    tmp_path: Path,
) -> None:
    runtime_write_contracts = _load_runtime_write_contracts_module()

    _write(
        tmp_path / "src/watchdog/services/runtime_writer.py",
        """
        from pathlib import Path

        def write_runtime(repo_root: Path) -> None:
            runtime_path = repo_root / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"
            try:
                raise ExceptionGroup("boom", [ValueError("x")])
            except* open(runtime_path, "w", encoding="utf-8"):
                return None
        """,
    )

    assert runtime_write_contracts.validate_runtime_write_entrypoints(tmp_path) == [
        "runtime write entrypoint (src/watchdog/services/runtime_writer.py): "
        "runtime.yaml writes must go through watchdog.validation.ai_sdlc_runtime_io.write_yaml_atomic"
    ]


def test_validate_runtime_write_entrypoints_flags_nested_helper_class_wrapper_runtime_writer(
    tmp_path: Path,
) -> None:
    runtime_write_contracts = _load_runtime_write_contracts_module()

    _write(
        tmp_path / "src/watchdog/services/runtime_writer.py",
        """
        from functools import partial
        from pathlib import Path

        class RuntimeWriter:
            wrapper = partial

            def _write_yaml(self, path: Path, payload: str) -> None:
                path.write_text(payload, encoding="utf-8")

            def write_runtime(self, repo_root: Path) -> None:
                runtime_path = repo_root / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"

                def helper() -> None:
                    writer = self.wrapper(self._write_yaml, runtime_path)
                    writer("current_stage: verify\\n")

                helper()
        """,
    )

    assert runtime_write_contracts.validate_runtime_write_entrypoints(tmp_path) == [
        "runtime write entrypoint (src/watchdog/services/runtime_writer.py): "
        "runtime.yaml writes must go through watchdog.validation.ai_sdlc_runtime_io.write_yaml_atomic"
    ]


def test_validate_runtime_write_entrypoints_flags_while_runtime_writer(
    tmp_path: Path,
) -> None:
    runtime_write_contracts = _load_runtime_write_contracts_module()

    _write(
        tmp_path / "src/watchdog/services/runtime_writer.py",
        """
        from pathlib import Path

        def write_runtime(repo_root: Path) -> None:
            runtime_path = repo_root / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"
            while open(runtime_path, "w", encoding="utf-8"):
                return None
        """,
    )

    assert runtime_write_contracts.validate_runtime_write_entrypoints(tmp_path) == [
        "runtime write entrypoint (src/watchdog/services/runtime_writer.py): "
        "runtime.yaml writes must go through watchdog.validation.ai_sdlc_runtime_io.write_yaml_atomic"
    ]


def test_validate_runtime_write_entrypoints_flags_late_bound_nested_helper_runtime_writer(
    tmp_path: Path,
) -> None:
    runtime_write_contracts = _load_runtime_write_contracts_module()

    _write(
        tmp_path / "src/watchdog/services/runtime_writer.py",
        """
        from pathlib import Path

        def write_runtime(repo_root: Path) -> None:
            def helper() -> None:
                runtime_path.write_text("current_stage: verify\\n", encoding="utf-8")

            runtime_path = repo_root / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"
            helper()
        """,
    )

    assert runtime_write_contracts.validate_runtime_write_entrypoints(tmp_path) == [
        "runtime write entrypoint (src/watchdog/services/runtime_writer.py): "
        "runtime.yaml writes must go through watchdog.validation.ai_sdlc_runtime_io.write_yaml_atomic"
    ]


def test_validate_runtime_write_entrypoints_flags_late_bound_nested_class_runtime_writer(
    tmp_path: Path,
) -> None:
    runtime_write_contracts = _load_runtime_write_contracts_module()

    _write(
        tmp_path / "src/watchdog/services/runtime_writer.py",
        """
        from pathlib import Path

        def write_runtime(repo_root: Path) -> None:
            class RuntimeWriter:
                def write_runtime_file(self) -> None:
                    runtime_path.write_text("current_stage: verify\\n", encoding="utf-8")

            runtime_path = repo_root / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"
            RuntimeWriter().write_runtime_file()
        """,
    )

    assert runtime_write_contracts.validate_runtime_write_entrypoints(tmp_path) == [
        "runtime write entrypoint (src/watchdog/services/runtime_writer.py): "
        "runtime.yaml writes must go through watchdog.validation.ai_sdlc_runtime_io.write_yaml_atomic"
    ]


def test_validate_runtime_write_entrypoints_flags_late_bound_nested_class_wrapper_runtime_writer(
    tmp_path: Path,
) -> None:
    runtime_write_contracts = _load_runtime_write_contracts_module()

    _write(
        tmp_path / "src/watchdog/services/runtime_writer.py",
        """
        from functools import partial
        from pathlib import Path

        def write_runtime(repo_root: Path) -> None:
            class RuntimeWriter:
                wrapper = partial

                def _write_yaml(self, path: Path, payload: str) -> None:
                    path.write_text(payload, encoding="utf-8")

                def write_runtime_file(self) -> None:
                    writer = self.wrapper(self._write_yaml, runtime_path)
                    writer("current_stage: verify\\n")

            runtime_path = repo_root / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"
            RuntimeWriter().write_runtime_file()
        """,
    )

    assert runtime_write_contracts.validate_runtime_write_entrypoints(tmp_path) == [
        "runtime write entrypoint (src/watchdog/services/runtime_writer.py): "
        "runtime.yaml writes must go through watchdog.validation.ai_sdlc_runtime_io.write_yaml_atomic"
    ]
