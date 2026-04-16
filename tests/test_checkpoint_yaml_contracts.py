from __future__ import annotations

import importlib
import importlib.util
import textwrap
from pathlib import Path

import yaml
import pytest


def _load_checkpoint_contracts_module():
    try:
        return importlib.import_module("watchdog.validation.checkpoint_yaml_contracts")
    except ModuleNotFoundError as exc:
        pytest.fail(f"missing checkpoint yaml validator module: {exc}")


def _load_script_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(contents).lstrip(), encoding="utf-8")


def test_checkpoint_yaml_contracts_pass_in_repo() -> None:
    module = _load_checkpoint_contracts_module()

    assert module.validate_checkpoint_yaml_string_compatibility() == []


def test_checkpoint_yaml_contracts_flag_unquoted_iso_timestamps(tmp_path: Path) -> None:
    module = _load_checkpoint_contracts_module()

    _write(
        tmp_path / ".ai-sdlc/state/checkpoint.yml",
        """
        pipeline_started_at: 2026-04-05T20:04:50Z
        pipeline_last_updated: 2026-04-16T09:47:50Z
        current_stage: completed
        feature:
          id: 055-checkpoint-string-compatibility
          spec_dir: specs/055-checkpoint-string-compatibility
        completed_stages:
          -
            stage: init
            completed_at: 2026-04-16T07:02:24Z
            artifacts: []
        last_synced_at: 2026-04-16T09:47:50Z
        """,
    )

    violations = module.validate_checkpoint_yaml_string_compatibility(tmp_path)

    assert any("pipeline_started_at must remain YAML string" in item for item in violations)
    assert any("completed_stages[0].completed_at must remain YAML string" in item for item in violations)


def test_reconcile_state_serializer_quotes_iso_timestamps() -> None:
    root = Path(__file__).resolve().parents[1]
    module = _load_script_module(root / "scripts/reconcile_ai_sdlc_state.py", "reconcile_ai_sdlc_state")

    rendered = module._dump_yaml(  # noqa: SLF001
        {
            "pipeline_started_at": "2026-04-05T20:04:50Z",
            "pipeline_last_updated": "2026-04-16T09:47:50Z",
        }
    )

    payload = yaml.safe_load(rendered)

    assert "pipeline_started_at: '2026-04-05T20:04:50Z'" in rendered
    assert "pipeline_last_updated: '2026-04-16T09:47:50Z'" in rendered
    assert isinstance(payload["pipeline_started_at"], str)
    assert isinstance(payload["pipeline_last_updated"], str)
