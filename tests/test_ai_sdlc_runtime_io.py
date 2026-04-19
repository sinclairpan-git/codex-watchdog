from __future__ import annotations

import importlib
from pathlib import Path

import pytest
import yaml


def _load_runtime_io_module():
    try:
        return importlib.import_module("watchdog.validation.ai_sdlc_runtime_io")
    except ModuleNotFoundError as exc:
        pytest.fail(f"missing runtime io module: {exc}")


def test_write_yaml_atomic_replaces_target_without_leaving_temp_files(tmp_path: Path) -> None:
    runtime_io = _load_runtime_io_module()
    target = tmp_path / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"

    runtime_io.write_yaml_atomic(
        target,
        {
            "current_stage": "verify",
            "current_batch": "2",
            "work_item_id": "050-runtime-truth-hardening",
        },
    )

    assert yaml.safe_load(target.read_text(encoding="utf-8")) == {
        "current_stage": "verify",
        "current_batch": "2",
        "work_item_id": "050-runtime-truth-hardening",
    }
    assert list(target.parent.glob("*.tmp")) == []


def test_write_yaml_atomic_keeps_previous_snapshot_when_replace_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_io = _load_runtime_io_module()
    target = tmp_path / ".ai-sdlc/work-items/050-runtime-truth-hardening/runtime.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("current_stage: verify\n", encoding="utf-8")

    original_replace = Path.replace

    def fail_replace(self: Path, target_path: Path) -> Path:
        if self.parent == target.parent and self.name.startswith(".runtime.yaml.") and self.suffix == ".tmp":
            raise OSError("atomic replace failed")
        return original_replace(self, target_path)

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(OSError, match="atomic replace failed"):
        runtime_io.write_yaml_atomic(target, {"current_stage": "execute"})

    assert target.read_text(encoding="utf-8") == "current_stage: verify\n"
    assert list(target.parent.glob("*.tmp")) == []
