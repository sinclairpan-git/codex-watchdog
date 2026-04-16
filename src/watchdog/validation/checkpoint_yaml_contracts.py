from __future__ import annotations

from pathlib import Path

import yaml

CHECKPOINT_REL = Path(".ai-sdlc/state/checkpoint.yml")


def validate_checkpoint_yaml_string_compatibility(repo_root: Path | None = None) -> list[str]:
    root = repo_root or Path(__file__).resolve().parents[3]
    path = root / CHECKPOINT_REL
    if not path.is_file():
        return []

    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    violations: list[str] = []

    if not isinstance(payload.get("pipeline_started_at"), str):
        violations.append("checkpoint.yml: pipeline_started_at must remain YAML string")
    if not isinstance(payload.get("pipeline_last_updated"), str):
        violations.append("checkpoint.yml: pipeline_last_updated must remain YAML string")

    completed_stages = payload.get("completed_stages") or []
    for idx, item in enumerate(completed_stages):
        if not isinstance(item, dict):
            continue
        if not isinstance(item.get("completed_at"), str):
            violations.append(
                f"checkpoint.yml: completed_stages[{idx}].completed_at must remain YAML string"
            )

    if not isinstance(payload.get("last_synced_at"), str):
        violations.append("checkpoint.yml: last_synced_at must remain YAML string")

    return violations
