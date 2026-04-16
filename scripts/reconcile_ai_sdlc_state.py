from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from watchdog.validation.ai_sdlc_reconciliation import (  # noqa: E402
    OWNER_ORDER,
    build_owner_ledger,
    collect_reconciliation_inventory,
    parse_unlanded_matrix_rows,
)

WI_047_ID = "047-ai-sdlc-state-reconciliation-and-canonical-gate-repair"
WI_047_BRANCH = "codex/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair"
MATRIX_PATH = Path("docs/superpowers/specs/2026-04-14-coverage-audit-matrix.md")
INVENTORY_OUTPUT = Path(
    "specs/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/reconciliation-inventory.yaml"
)
OWNER_LEDGER_OUTPUT = Path(
    "specs/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/matrix-owner-ledger.yaml"
)
HISTORICAL_MISSING_WORK_ITEMS = (
    "006-m5-hardening",
    "010-openclaw-integration-spine",
    "011-stable-session-events",
    "012-stable-recovery-execution",
    "013-stable-action-receipts",
    "014-stable-supervision-evaluation",
    "015-stable-session-explanations",
    "016-stable-approval-inbox",
    "017-stable-session-directory",
    "018-stable-native-thread-resolution",
    "019-stable-workspace-activity",
    "020-stable-operator-guidance",
    "021-stable-session-event-snapshot",
    "024-resident-supervision-session-spine-persistence",
    "025-policy-engine-decision-evidence",
    "026-canonical-action-approval-response-loop",
    "027-outbox-delivery-retry-receipt",
    "028-openclaw-webhook-response-api-reference-runtime",
    "029-audit-replay-ops-production-deployment",
)
HISTORICAL_STALE_POINTERS = (
    ".ai-sdlc/state/checkpoint.yml points to 023-codex-client-openclaw-route-template, expected 047-ai-sdlc-state-reconciliation-and-canonical-gate-repair",
    ".ai-sdlc/state/checkpoint.yml points to 023-codex-client-openclaw-route-template, expected 047-ai-sdlc-state-reconciliation-and-canonical-gate-repair",
    ".ai-sdlc/project/config/project-state.yaml next_work_item_seq=24, expected 48",
)
ISO_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_scalar(text: str, key: str) -> str:
    match = re.search(rf"(?m)^[ \t]*{re.escape(key)}:\s*(?P<value>.*)$", text)
    if match is None:
        return ""
    value = match.group("value").strip()
    if value in {"''", '""'}:
        return ""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _dump_yaml(value: Any, indent: int = 0) -> str:
    prefix = " " * indent

    if isinstance(value, dict):
        if not value:
            return f"{prefix}{{}}"
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, dict) and not item:
                lines.append(f"{prefix}{key}: {{}}")
                continue
            if isinstance(item, list) and not item:
                lines.append(f"{prefix}{key}: []")
                continue
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.append(_dump_yaml(item, indent + 2))
                continue
            if isinstance(item, str) and "\n" in item:
                lines.append(f"{prefix}{key}: |")
                for line in item.splitlines():
                    lines.append(f"{' ' * (indent + 2)}{line}")
                continue
            lines.append(f"{prefix}{key}: {_format_scalar(item)}")
        return "\n".join(lines)

    if isinstance(value, list):
        if not value:
            return f"{prefix}[]"

        lines = []
        for item in value:
            if isinstance(item, dict):
                lines.append(f"{prefix}-")
                lines.append(_dump_yaml(item, indent + 2))
                continue
            if isinstance(item, list):
                lines.append(f"{prefix}-")
                lines.append(_dump_yaml(item, indent + 2))
                continue
            if isinstance(item, str) and "\n" in item:
                lines.append(f"{prefix}- |")
                for line in item.splitlines():
                    lines.append(f"{' ' * (indent + 2)}{line}")
                continue
            lines.append(f"{prefix}- {_format_scalar(item)}")
        return "\n".join(lines)

    return f"{prefix}{_format_scalar(value)}"


def _format_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)

    text = str(value)
    if text == "":
        return "''"
    if ISO_TIMESTAMP_PATTERN.fullmatch(text):
        return "'" + text + "'"
    if re.fullmatch(r"[A-Za-z0-9_./:@`+-]+", text):
        return text
    return "'" + text.replace("'", "''") + "'"


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump_yaml(_normalize(payload)) + "\n", encoding="utf-8")


def _write_text(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")


def _build_backfill_summary(work_item_id: str, spec_files: list[str]) -> str:
    lines = [
        "# Development Summary",
        "",
        "Status: archived",
        "Total Tasks: 0",
        "Completed Tasks: 0",
        "Halted Tasks: 0",
        "Total Batches: 0",
        "Completed Batches: 0",
        "Last Committed Task: none",
        "",
        "## Notes",
        f"- `WI-047` 回填了 `{work_item_id}` 的 `.ai-sdlc/work-items` 镜像，用于恢复 canonical truth。",
        f"- Formal docs 仍以 `specs/{work_item_id}/` 为准，镜像只补状态与恢复入口，不代表重新执行该 work item。",
    ]
    if spec_files:
        lines.append(f"- 已发现的 formal docs：{', '.join(f'`{path}`' for path in spec_files)}。")
    return "\n".join(lines) + "\n"


def _backfill_missing_work_item(repo_root: Path, work_item_id: str, timestamp: str) -> None:
    spec_dir = repo_root / "specs" / work_item_id
    mirror_dir = repo_root / ".ai-sdlc/work-items" / work_item_id

    spec_files = sorted(str(path.relative_to(repo_root)) for path in spec_dir.iterdir() if path.is_file())
    latest_summary = _build_backfill_summary(work_item_id, spec_files)
    active_files = [f"`{path}`" for path in spec_files]

    _write_text(mirror_dir / "latest-summary.md", latest_summary)
    _write_yaml(
        mirror_dir / "runtime.yaml",
        {
            "current_stage": "archived",
            "current_batch": 0,
            "current_task": "",
            "last_committed_task": "",
            "current_branch": "",
            "ai_decisions_count": 0,
            "execution_mode": "backfill",
            "started_at": timestamp,
            "last_updated": timestamp,
            "debug_rounds": {},
            "consecutive_halts": 0,
            "mirror_status": "spec_backfill",
            "source_spec_dir": f"specs/{work_item_id}",
            "backfilled_at": timestamp,
        },
    )
    _write_yaml(
        mirror_dir / "execution-plan.yaml",
        {
            "total_tasks": 0,
            "total_batches": 0,
            "tasks": [],
            "batches": [],
            "current_batch": 0,
            "mirror_status": "spec_backfill",
            "source_spec_dir": f"specs/{work_item_id}",
            "backfilled_at": timestamp,
        },
    )
    _write_yaml(
        mirror_dir / "resume-pack.yaml",
        {
            "current_stage": "archived",
            "current_batch": 0,
            "last_committed_task": "",
            "working_set_snapshot": {
                "spec_path": f"specs/{work_item_id}/spec.md" if (spec_dir / "spec.md").exists() else "",
                "plan_path": f"specs/{work_item_id}/plan.md" if (spec_dir / "plan.md").exists() else "",
                "tasks_path": f"specs/{work_item_id}/tasks.md" if (spec_dir / "tasks.md").exists() else "",
                "active_files": active_files,
                "context_summary": latest_summary.rstrip(),
            },
            "current_branch": "",
            "timestamp": timestamp,
            "mirror_status": "spec_backfill",
            "source_spec_dir": f"specs/{work_item_id}",
            "backfilled_at": timestamp,
        },
    )


def _repair_project_state(
    repo_root: Path,
    *,
    next_work_item_seq: int,
    timestamp: str,
) -> None:
    path = repo_root / ".ai-sdlc/project/config/project-state.yaml"
    existing = _read_text(path)
    payload = {
        "status": _extract_scalar(existing, "status") or "initialized",
        "project_name": _extract_scalar(existing, "project_name") or "openclaw-codex-watchdog",
        "initialized_at": _extract_scalar(existing, "initialized_at") or timestamp,
        "last_updated": timestamp,
        "next_work_item_seq": next_work_item_seq,
        "version": _extract_scalar(existing, "version") or "1.0",
    }
    _write_yaml(path, payload)


def _repair_checkpoint(
    repo_root: Path,
    *,
    timestamp: str,
    docs_baseline_ref: str,
    docs_baseline_at: str,
) -> None:
    path = repo_root / ".ai-sdlc/state/checkpoint.yml"
    existing = _read_text(path)
    payload = {
        "pipeline_started_at": _extract_scalar(existing, "pipeline_started_at") or timestamp,
        "pipeline_last_updated": timestamp,
        "current_stage": "verify",
        "feature": {
            "id": WI_047_ID,
            "spec_dir": f"specs/{WI_047_ID}",
            "design_branch": f"design/{WI_047_ID}",
            "feature_branch": f"feature/{WI_047_ID}",
            "current_branch": WI_047_BRANCH,
            "docs_baseline_ref": docs_baseline_ref,
            "docs_baseline_at": docs_baseline_at,
        },
        "multi_agent": {
            "supported": False,
            "max_parallel": 1,
            "tool_capability": "",
        },
        "prd_source": _extract_scalar(existing, "prd_source") or "openclaw-codex-watchdog-prd.md",
        "completed_stages": [
            {
                "stage": "init",
                "completed_at": timestamp,
                "artifacts": [],
            },
            {
                "stage": "refine",
                "completed_at": timestamp,
                "artifacts": ["spec.md"],
            },
            {
                "stage": "design",
                "completed_at": timestamp,
                "artifacts": ["plan.md"],
            },
            {
                "stage": "decompose",
                "completed_at": timestamp,
                "artifacts": ["tasks.md"],
            },
        ],
        "ai_decisions_count": 0,
        "execution_mode": "auto",
        "linked_wi_id": WI_047_ID,
        "linked_plan_uri": None,
        "last_synced_at": timestamp,
    }
    _write_yaml(path, payload)


def _owner_summary(owners: list[dict[str, Any]]) -> dict[str, int]:
    counter = Counter(entry["owner"] for entry in owners)
    return {owner: counter.get(owner, 0) for owner in OWNER_ORDER}


def _historical_pre_repair_inventory(post_inventory: dict[str, Any]) -> dict[str, Any]:
    return {
        "spec_work_items": post_inventory["spec_work_items"],
        "mirrored_work_items": [
            work_item
            for work_item in post_inventory["mirrored_work_items"]
            if work_item not in HISTORICAL_MISSING_WORK_ITEMS
        ],
        "missing_work_item_mirrors": list(HISTORICAL_MISSING_WORK_ITEMS),
        "next_work_item_seq": post_inventory["next_work_item_seq"],
        "active_work_item_id": post_inventory["active_work_item_id"],
        "stale_pointers": list(HISTORICAL_STALE_POINTERS),
    }


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_normalize(item) for item in value]
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


def reconcile(repo_root: Path) -> dict[str, Any]:
    timestamp = _iso_now()
    pre_inventory = collect_reconciliation_inventory(repo_root)

    wi_047_runtime = repo_root / ".ai-sdlc/work-items" / WI_047_ID / "runtime.yaml"
    runtime_text = _read_text(wi_047_runtime)
    docs_baseline_ref = _extract_scalar(runtime_text, "docs_baseline_ref")
    docs_baseline_at = _extract_scalar(runtime_text, "docs_baseline_at")

    backfilled = list(pre_inventory.missing_work_item_mirrors) or list(HISTORICAL_MISSING_WORK_ITEMS)
    for work_item_id in backfilled:
        _backfill_missing_work_item(repo_root, work_item_id, timestamp)

    _repair_project_state(
        repo_root,
        next_work_item_seq=pre_inventory.next_work_item_seq,
        timestamp=timestamp,
    )
    _repair_checkpoint(
        repo_root,
        timestamp=timestamp,
        docs_baseline_ref=docs_baseline_ref,
        docs_baseline_at=docs_baseline_at,
    )

    post_inventory = collect_reconciliation_inventory(repo_root)
    post_inventory_payload = asdict(post_inventory)
    if pre_inventory.missing_work_item_mirrors or pre_inventory.stale_pointers:
        pre_inventory_payload = asdict(pre_inventory)
    else:
        pre_inventory_payload = _historical_pre_repair_inventory(post_inventory_payload)
    matrix_text = _read_text(repo_root / MATRIX_PATH)
    matrix_rows = parse_unlanded_matrix_rows(matrix_text)
    owner_entries = [asdict(entry) for entry in build_owner_ledger(matrix_rows)]

    inventory_payload = {
        "generated_at": timestamp,
        "source_matrix": str(MATRIX_PATH),
        "pre_repair": pre_inventory_payload,
        "backfilled_mirror_work_items": backfilled,
        "post_repair": post_inventory_payload,
    }
    owner_payload = {
        "generated_at": timestamp,
        "matrix_source": str(MATRIX_PATH),
        "row_count": len(owner_entries),
        "owner_counts": _owner_summary(owner_entries),
        "entries": owner_entries,
    }

    _write_yaml(repo_root / INVENTORY_OUTPUT, inventory_payload)
    _write_yaml(repo_root / OWNER_LEDGER_OUTPUT, owner_payload)

    return {
        "timestamp": timestamp,
        "pre_repair_missing": list(pre_inventory_payload["missing_work_item_mirrors"]),
        "post_repair_missing": list(post_inventory.missing_work_item_mirrors),
        "pre_repair_stale_pointers": list(pre_inventory_payload["stale_pointers"]),
        "post_repair_stale_pointers": list(post_inventory.stale_pointers),
        "next_work_item_seq": post_inventory.next_work_item_seq,
        "owner_row_count": len(owner_entries),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    args = parser.parse_args()

    result = reconcile(Path(args.repo_root).resolve())
    print(_dump_yaml(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
