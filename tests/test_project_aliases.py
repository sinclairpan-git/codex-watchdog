from __future__ import annotations

import json
from pathlib import Path

from a_control_agent.main import create_app as create_runtime_app
from a_control_agent.settings import Settings as RuntimeSettings
from watchdog.services.project_aliases import (
    canonicalize_project_id,
    migrate_legacy_project_aliases_in_data_dir,
    rewrite_legacy_project_aliases,
)


def test_rewrite_legacy_project_aliases_rewrites_nested_strings_and_keys() -> None:
    payload = {
        "session:openclaw-codex-watchdog": {
            "project_id": "openclaw-codex-watchdog",
            "cwd": "/Users/sinclairpan/project/openclaw-codex-watchdog",
            "url": "https://github.com/sinclairpan-git/openclaw-codex-watchdog/pull/11",
            "fact_id": "openclaw-codex-watchdog:approval_pending",
        }
    }

    rewritten = rewrite_legacy_project_aliases(payload)

    assert "session:codex-watchdog" in rewritten
    assert rewritten["session:codex-watchdog"]["project_id"] == "codex-watchdog"
    assert rewritten["session:codex-watchdog"]["cwd"] == "/Users/sinclairpan/project/codex-watchdog"
    assert rewritten["session:codex-watchdog"]["url"] == "https://github.com/sinclairpan-git/codex-watchdog/pull/11"
    assert rewritten["session:codex-watchdog"]["fact_id"] == "codex-watchdog:approval_pending"
    assert canonicalize_project_id("openclaw-codex-watchdog") == "codex-watchdog"


def test_migrate_legacy_project_aliases_in_data_dir_rewrites_json_files(tmp_path: Path) -> None:
    data_dir = tmp_path / "watchdog-data"
    data_dir.mkdir()
    path = data_dir / "legacy.json"
    path.write_text(
        json.dumps(
            {
                "project_id": "openclaw-codex-watchdog",
                "session_id": "session:openclaw-codex-watchdog",
            }
        ),
        encoding="utf-8",
    )

    migrated = migrate_legacy_project_aliases_in_data_dir(data_dir)

    assert migrated == [path]
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["project_id"] == "codex-watchdog"
    assert payload["session_id"] == "session:codex-watchdog"


def test_a_control_create_app_migrates_legacy_json_files_on_startup(tmp_path: Path) -> None:
    data_dir = tmp_path / "agent-data"
    data_dir.mkdir()
    legacy = data_dir / "legacy.json"
    legacy.write_text(
        json.dumps({"project_id": "openclaw-codex-watchdog"}),
        encoding="utf-8",
    )

    create_runtime_app(
        RuntimeSettings(api_token="test-token", data_dir=str(data_dir)),
        start_background_workers=False,
    )

    payload = json.loads(legacy.read_text(encoding="utf-8"))
    assert payload["project_id"] == "codex-watchdog"
