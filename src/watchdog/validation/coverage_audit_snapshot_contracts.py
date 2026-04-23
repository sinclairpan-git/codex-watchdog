from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

COVERAGE_AUDIT_MATRIX = Path("docs/superpowers/specs/2026-04-14-coverage-audit-matrix.md")
COVERAGE_AUDIT_CLOSEOUT_STATUS = Path("docs/architecture/coverage-audit-closeout-status.md")


@dataclass(frozen=True)
class CoverageAuditContractCheck:
    name: str
    path: Path
    must_contain: tuple[str, ...]


COVERAGE_AUDIT_SNAPSHOT_CONTRACTS: tuple[CoverageAuditContractCheck, ...] = (
    CoverageAuditContractCheck(
        name="coverage_audit_matrix_is_historical_snapshot",
        path=COVERAGE_AUDIT_MATRIX,
        must_contain=(
            "历史快照（2026-04-14）",
            "已被 `WI-048` 到 `WI-056` 的 formal closeout 替代",
            "`docs/architecture/coverage-audit-closeout-status.md`",
        ),
    ),
    CoverageAuditContractCheck(
        name="coverage_audit_closeout_status_has_current_truth",
        path=COVERAGE_AUDIT_CLOSEOUT_STATUS,
        must_contain=(
            "`specs/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/matrix-owner-ledger.yaml`",
            "`WI-048`",
            "`WI-049`",
            "`WI-050`",
            "`WI-051`",
            "`WI-052`",
            "`WI-053`",
            "`WI-054`",
            "`WI-055`",
            "`.ai-sdlc/state/checkpoint.yml`",
            "`.ai-sdlc/project/config/project-state.yaml`",
            "`NO_BLOCKERS`",
        ),
    ),
)


def validate_coverage_audit_snapshot_contracts(repo_root: Path | None = None) -> list[str]:
    root = repo_root or Path(__file__).resolve().parents[3]
    cache: dict[Path, str] = {}
    violations: list[str] = []

    for check in COVERAGE_AUDIT_SNAPSHOT_CONTRACTS:
        doc_path = root / check.path
        if not doc_path.exists():
            violations.append(f"coverage audit snapshot missing required doc: {check.path}")
            continue

        contents = cache.setdefault(check.path, doc_path.read_text(encoding="utf-8"))
        missing = [marker for marker in check.must_contain if marker not in contents]
        if missing:
            joined = ", ".join(repr(marker) for marker in missing)
            violations.append(
                f"coverage audit snapshot drift: {check.path} missing required markers {joined}"
            )

    return violations
