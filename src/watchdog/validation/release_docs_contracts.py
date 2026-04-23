from __future__ import annotations

from pathlib import Path

README_REL = Path("README.md")
RELEASE_NOTES_REL = Path("docs/releases/v0.6.0.md")
USER_GUIDE_REL = Path("USER_GUIDE.zh-CN.md")
OFFLINE_README_REL = Path("packaging/offline/README.md")
RELEASE_POLICY_REL = Path("docs/框架自迭代开发与发布约定.md")
PR_CHECKLIST_REL = Path("docs/pull-request-checklist.zh.md")

RELEASE_DOCS_CONSISTENCY_SURFACES: dict[Path, tuple[str, ...]] = {
    README_REL: (
        "v0.6.0",
        "docs/releases/v0.6.0.md",
        "ai-sdlc-offline-0.6.0.zip",
        "ai-sdlc-offline-0.6.0.tar.gz",
    ),
    RELEASE_NOTES_REL: (
        "v0.6.0",
        "Windows",
        ".zip",
        "macOS / Linux",
        ".tar.gz",
    ),
    USER_GUIDE_REL: (
        "v0.6.0",
        "Windows",
        "macOS",
        "Linux",
        ".zip",
        ".tar.gz",
    ),
    OFFLINE_README_REL: (
        "v0.6.0",
        "Windows",
        ".zip",
        "Linux/macOS",
        ".tar.gz",
    ),
    RELEASE_POLICY_REL: (
        "README.md",
        "docs/releases/v0.6.0.md",
        "USER_GUIDE.zh-CN.md",
        "packaging/offline/README.md",
        "docs/pull-request-checklist.zh.md",
        "Windows",
        ".zip",
        "macOS / Linux",
        ".tar.gz",
    ),
    PR_CHECKLIST_REL: (
        "README.md",
        "docs/releases/v0.6.0.md",
        "USER_GUIDE.zh-CN.md",
        "packaging/offline/README.md",
        "v0.6.0",
        "Windows",
        ".zip",
        "macOS / Linux",
        ".tar.gz",
    ),
}


def validate_release_docs_consistency(repo_root: Path | None = None) -> list[str]:
    root = repo_root or Path(__file__).resolve().parents[3]
    activation_surfaces = (
        README_REL,
        RELEASE_NOTES_REL,
        USER_GUIDE_REL,
        OFFLINE_README_REL,
        RELEASE_POLICY_REL,
    )
    if not any((root / rel).is_file() for rel in activation_surfaces):
        return []

    violations: list[str] = []
    for rel, required_tokens in RELEASE_DOCS_CONSISTENCY_SURFACES.items():
        path = root / rel
        if not path.is_file():
            violations.append(
                f"release docs consistency missing required entry doc: {rel.as_posix()}"
            )
            continue
        text = path.read_text(encoding="utf-8")
        missing = [token for token in required_tokens if token not in text]
        if missing:
            violations.append(
                "release docs consistency drift: "
                f"{rel.as_posix()} missing required markers: {', '.join(missing)}"
            )

    return violations
