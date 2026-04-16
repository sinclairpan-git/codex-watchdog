from __future__ import annotations

from pathlib import Path

VERIFICATION_RULE_REL = Path("src/ai_sdlc/rules/verification.md")
PR_CHECKLIST_REL = Path("docs/pull-request-checklist.zh.md")
VERIFICATION_PROFILE_SURFACES: dict[Path, tuple[str, ...]] = {
    VERIFICATION_RULE_REL: (
        "docs-only",
        "rules-only",
        "truth-only",
        "code-change",
        "uv run ai-sdlc verify constraints",
        "python -m ai_sdlc program truth sync --dry-run",
        "uv run pytest",
        "uv run ruff check",
    ),
    PR_CHECKLIST_REL: (
        "docs-only",
        "rules-only",
        "truth-only",
        "code-change",
        "uv run ai-sdlc verify constraints",
        "python -m ai_sdlc program truth sync --dry-run",
        "uv run pytest",
        "uv run ruff check",
    ),
}


def validate_verification_profile_surfaces(repo_root: Path | None = None) -> list[str]:
    root = repo_root or Path(__file__).resolve().parents[3]
    present = [rel for rel in VERIFICATION_PROFILE_SURFACES if (root / rel).is_file()]
    if not present:
        return []

    violations: list[str] = []
    for rel, required_tokens in VERIFICATION_PROFILE_SURFACES.items():
        path = root / rel
        if not path.is_file():
            violations.append(f"verification profile surface missing: {rel.as_posix()}")
            continue
        text = path.read_text(encoding="utf-8")
        missing = [token for token in required_tokens if token not in text]
        if missing:
            violations.append(
                "verification profile surface "
                f"{rel.as_posix()} missing required markers: {', '.join(missing)}"
            )

    return violations
