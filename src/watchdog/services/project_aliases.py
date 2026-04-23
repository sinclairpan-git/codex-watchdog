from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LEGACY_PROJECT_ID_ALIASES: dict[str, str] = {
    "openclaw-codex-watchdog": "codex-watchdog",
}

_LEGACY_TEXT_REPLACEMENTS: tuple[tuple[str, str], ...] = tuple(
    sorted(
        {
            "/Users/sinclairpan/project/openclaw-codex-watchdog": "/Users/sinclairpan/project/codex-watchdog",
            "https://github.com/sinclairpan-git/openclaw-codex-watchdog": "https://github.com/sinclairpan-git/codex-watchdog",
            "sinclairpan-git/openclaw-codex-watchdog": "sinclairpan-git/codex-watchdog",
            "openclaw-codex-watchdog-prd.md": "codex-watchdog-prd.md",
            **LEGACY_PROJECT_ID_ALIASES,
        }.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    )
)


def canonicalize_project_id(value: object) -> str:
    normalized = str(value or "").strip()
    return LEGACY_PROJECT_ID_ALIASES.get(normalized, normalized)


def _rewrite_text(value: str) -> str:
    rewritten = value
    for legacy, canonical in _LEGACY_TEXT_REPLACEMENTS:
        rewritten = rewritten.replace(legacy, canonical)
    return rewritten


def rewrite_legacy_project_aliases(value: Any) -> Any:
    if isinstance(value, str):
        return _rewrite_text(value)
    if isinstance(value, list):
        return [rewrite_legacy_project_aliases(item) for item in value]
    if isinstance(value, tuple):
        return tuple(rewrite_legacy_project_aliases(item) for item in value)
    if isinstance(value, dict):
        rewritten: dict[Any, Any] = {}
        for key, item in value.items():
            normalized_key = _rewrite_text(key) if isinstance(key, str) else key
            normalized_item = rewrite_legacy_project_aliases(item)
            existing = rewritten.get(normalized_key)
            if isinstance(existing, dict) and isinstance(normalized_item, dict):
                merged = dict(existing)
                merged.update(normalized_item)
                rewritten[normalized_key] = merged
            else:
                rewritten[normalized_key] = normalized_item
        return rewritten
    return value


def migrate_legacy_project_aliases_in_json_file(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return False
    if not raw.strip():
        return False
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return False
    rewritten = rewrite_legacy_project_aliases(payload)
    if rewritten == payload:
        return False
    path.write_text(json.dumps(rewritten, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def migrate_legacy_project_aliases_in_data_dir(data_dir: Path) -> list[Path]:
    if not data_dir.exists():
        return []
    migrated: list[Path] = []
    for path in sorted(data_dir.rglob("*.json")):
        if not path.is_file():
            continue
        if migrate_legacy_project_aliases_in_json_file(path):
            migrated.append(path)
    return migrated
