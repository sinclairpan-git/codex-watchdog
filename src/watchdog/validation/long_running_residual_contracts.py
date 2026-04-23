from __future__ import annotations

from pathlib import Path

import yaml

LONG_RUNNING_RESIDUAL_LEDGER = Path("docs/architecture/long-running-residual-backlog-ledger.yaml")
LONG_RUNNING_RESIDUAL_STATUS = Path("docs/architecture/long-running-residual-backlog-status.md")
ALLOWED_DISPOSITIONS = {"satisfied", "superseded", "residual"}
NO_RESIDUAL_BLOCKERS = "NO_RESIDUAL_BLOCKERS"


def validate_long_running_residual_contracts(repo_root: Path | None = None) -> list[str]:
    root = repo_root or Path(__file__).resolve().parents[3]
    ledger_path = root / LONG_RUNNING_RESIDUAL_LEDGER
    status_path = root / LONG_RUNNING_RESIDUAL_STATUS

    if not ledger_path.exists() and not status_path.exists():
        return []

    violations: list[str] = []
    if not ledger_path.exists():
        violations.append(
            "long-running residual contract missing required doc: "
            f"{LONG_RUNNING_RESIDUAL_LEDGER.as_posix()}"
        )
        return violations
    if not status_path.exists():
        violations.append(
            "long-running residual contract missing required doc: "
            f"{LONG_RUNNING_RESIDUAL_STATUS.as_posix()}"
        )
        return violations

    ledger = yaml.safe_load(ledger_path.read_text(encoding="utf-8")) or {}
    if not isinstance(ledger, dict):
        return [
            "long-running residual contract drift: "
            f"{LONG_RUNNING_RESIDUAL_LEDGER.as_posix()} must parse to mapping"
        ]

    status_text = status_path.read_text(encoding="utf-8")
    ledger_marker = LONG_RUNNING_RESIDUAL_LEDGER.as_posix()
    if ledger_marker not in status_text:
        violations.append(
            "long-running residual contract drift: "
            f"status doc must point to canonical ledger {ledger_marker}"
        )

    residual_items = ledger.get("residual_items") or []
    if not isinstance(residual_items, list):
        return [
            "long-running residual contract drift: "
            f"{LONG_RUNNING_RESIDUAL_LEDGER.as_posix()} residual_items must be list"
        ]

    residual_count = 0
    for idx, item in enumerate(residual_items):
        if not isinstance(item, dict):
            violations.append(
                "long-running residual contract drift: "
                f"residual_items[{idx}] must be mapping"
            )
            continue
        residual_id = str(item.get("residual_id") or f"index-{idx}")
        source_refs = item.get("source_refs")
        formal_truth_refs = item.get("formal_truth_refs")
        disposition = item.get("disposition")
        if not isinstance(source_refs, list) or not source_refs:
            violations.append(
                "long-running residual contract drift: "
                f"residual item {residual_id} missing source_refs/formal_truth_refs"
            )
            continue
        if not isinstance(formal_truth_refs, list) or not formal_truth_refs:
            violations.append(
                "long-running residual contract drift: "
                f"residual item {residual_id} missing source_refs/formal_truth_refs"
            )
            continue
        if disposition not in ALLOWED_DISPOSITIONS:
            violations.append(
                "long-running residual contract drift: "
                f"residual item {residual_id} has invalid disposition {disposition!r}"
            )
            continue
        if disposition == "residual":
            residual_count += 1

    has_no_residual_marker = NO_RESIDUAL_BLOCKERS in status_text
    if residual_count > 0 and has_no_residual_marker:
        violations.append(
            "long-running residual contract drift: "
            "status doc claims NO_RESIDUAL_BLOCKERS but ledger still contains residual items"
        )
    if residual_count == 0 and not has_no_residual_marker:
        violations.append(
            "long-running residual contract drift: "
            "status doc must declare NO_RESIDUAL_BLOCKERS when ledger has no residual items"
        )

    return violations
