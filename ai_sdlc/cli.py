from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from watchdog.validation import (  # noqa: E402
    validate_branch_protection_audit_workflow_surfaces,
    validate_branch_protection_contract_surfaces,
    validate_live_github_branch_protection,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ai_sdlc")
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify_parser = subparsers.add_parser("verify")
    verify_subparsers = verify_parser.add_subparsers(dest="verify_command", required=True)

    verify_constraints_parser = verify_subparsers.add_parser("constraints")
    verify_constraints_parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)

    verify_branch_protection_parser = verify_subparsers.add_parser("github-branch-protection")
    verify_branch_protection_parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)

    args = parser.parse_args(argv)
    if args.command == "verify" and args.verify_command == "constraints":
        return _run_verify_constraints(args.repo_root)
    if args.command == "verify" and args.verify_command == "github-branch-protection":
        return _run_verify_github_branch_protection(args.repo_root)
    parser.error("unsupported command")
    return 2


def _run_verify_constraints(repo_root: Path) -> int:
    violations = [
        *validate_branch_protection_contract_surfaces(repo_root),
        *validate_branch_protection_audit_workflow_surfaces(repo_root),
    ]
    if violations:
        print("Constraint violations")
        for violation in violations:
            print(f"  BLOCKER: {violation}")
        return 1

    print("Constraints OK")
    return 0


def _run_verify_github_branch_protection(repo_root: Path) -> int:
    violations = validate_branch_protection_contract_surfaces(repo_root)
    if not violations:
        violations.extend(validate_live_github_branch_protection(repo_root))
    if violations:
        print("GitHub branch protection violations")
        for violation in violations:
            print(f"  BLOCKER: {violation}")
        return 1

    print("GitHub branch protection OK")
    return 0
