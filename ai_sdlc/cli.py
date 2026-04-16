from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from watchdog.validation import (  # noqa: E402
    validate_backlog_reference_sync,
    validate_checkpoint_yaml_string_compatibility,
    validate_coverage_audit_snapshot_contracts,
    validate_long_running_residual_contracts,
    validate_release_docs_consistency,
    validate_task_doc_status_contracts,
    validate_verification_profile_surfaces,
    validate_framework_contracts,
    validate_long_running_autonomy_docs,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ai_sdlc")
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify_parser = subparsers.add_parser("verify")
    verify_subparsers = verify_parser.add_subparsers(dest="verify_command", required=True)
    verify_constraints_parser = verify_subparsers.add_parser("constraints")
    verify_constraints_parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)

    args = parser.parse_args(argv)
    if args.command == "verify" and args.verify_command == "constraints":
        return _run_verify_constraints(args.repo_root)
    if args.command == "status":
        return _run_status(args.repo_root)
    parser.error("unsupported command")
    return 2


def _run_verify_constraints(repo_root: Path) -> int:
    violations = [
        *validate_checkpoint_yaml_string_compatibility(repo_root),
        *validate_coverage_audit_snapshot_contracts(repo_root),
        *validate_release_docs_consistency(repo_root),
        *validate_task_doc_status_contracts(repo_root),
        *validate_framework_contracts(repo_root),
        *validate_backlog_reference_sync(repo_root),
        *validate_verification_profile_surfaces(repo_root),
        *validate_long_running_autonomy_docs(repo_root),
        *validate_long_running_residual_contracts(repo_root),
    ]
    if violations:
        print("Constraint violations")
        for violation in violations:
            print(f"  BLOCKER: {violation}")
        return 1

    print("Constraints OK")
    return 0


def _run_status(repo_root: Path) -> int:
    checkpoint_text = (repo_root / ".ai-sdlc/state/checkpoint.yml").read_text(encoding="utf-8")
    project_state_text = (
        repo_root / ".ai-sdlc/project/config/project-state.yaml"
    ).read_text(encoding="utf-8")

    current_stage = _extract_scalar(checkpoint_text, "current_stage") or "unknown"
    current_branch = _extract_scalar(checkpoint_text, "current_branch") or "unknown"
    linked_wi_id = _extract_scalar(checkpoint_text, "linked_wi_id") or "unknown"
    next_work_item_seq = _extract_scalar(project_state_text, "next_work_item_seq") or "unknown"

    print(f"linked_wi_id={linked_wi_id}")
    print(f"current_stage={current_stage}")
    print(f"current_branch={current_branch}")
    print(f"next_work_item_seq={next_work_item_seq}")
    return 0


def _extract_scalar(text: str, key: str) -> str:
    match = re.search(rf"(?m)^[ \t]*{re.escape(key)}:\s*(?P<value>.*)$", text)
    if match is None:
        return ""
    value = match.group("value").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
