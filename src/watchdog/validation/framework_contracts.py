from __future__ import annotations

import re
from pathlib import Path

FRAMEWORK_DEFECT_BACKLOG = Path("docs/framework-defect-backlog.zh-CN.md")
INITIALIZED_PROJECT_STATE = Path(".ai-sdlc/project/config/project-state.yaml")
DEFECT_ID_PATTERN = re.compile(r"\bFD-\d{4}-\d{2}-\d{2}-\d{3}\b")
REQUIRED_BACKLOG_FIELDS = (
    "现象",
    "触发场景",
    "影响范围",
    "根因分类",
    "未来杜绝方案摘要",
    "建议改动层级",
    "风险等级",
    "可验证成功标准",
    "是否需要回归测试补充",
)
FORMAL_ARTIFACTS = frozenset({"spec", "plan", "tasks", "task-execution-log"})
BACKLOG_HEADER_PATTERN = re.compile(r"^##\s+(?P<title>FD-[^\n]+)$")
BACKLOG_FIELD_PATTERN = re.compile(r"^- (?P<key>[^:]+):\s*(?P<value>.*)$")


def classify_canonical_doc_path(
    artifact_kind: str,
    *,
    work_item_id: str | None = None,
    name: str | None = None,
) -> Path:
    if artifact_kind == "architecture":
        if not name:
            raise ValueError("architecture docs require name")
        return Path("docs/architecture") / f"{name}.md"

    if artifact_kind in FORMAL_ARTIFACTS:
        if not work_item_id:
            raise ValueError(f"{artifact_kind} docs require work_item_id")
        return Path("specs") / work_item_id / f"{artifact_kind}.md"

    raise ValueError(f"unsupported artifact kind: {artifact_kind}")


def validate_formal_doc_candidate(
    repo_root: Path | None,
    *,
    artifact_kind: str,
    candidate_path: str | Path,
    work_item_id: str | None = None,
    name: str | None = None,
) -> str | None:
    root = repo_root or Path(__file__).resolve().parents[3]
    normalized = Path(candidate_path).as_posix().lstrip("./")
    expected = classify_canonical_doc_path(
        artifact_kind,
        work_item_id=work_item_id,
        name=name,
    ).as_posix()
    if not _has_canonical_formal_dirs(root):
        return None
    if normalized == expected:
        return None
    return f"formal {artifact_kind} path must stay under {expected}, got {normalized}"


def validate_framework_contracts(repo_root: Path | None = None) -> list[str]:
    root = repo_root or Path(__file__).resolve().parents[3]
    violations: list[str] = []

    backlog_path = root / FRAMEWORK_DEFECT_BACKLOG
    initialized = (root / INITIALIZED_PROJECT_STATE).exists()

    if initialized and not backlog_path.exists():
        violations.append(
            "missing canonical framework backlog docs/framework-defect-backlog.zh-CN.md"
        )

    if backlog_path.exists():
        for title, fields in _parse_framework_defect_backlog(backlog_path.read_text(encoding="utf-8")):
            missing = [
                field
                for field in REQUIRED_BACKLOG_FIELDS
                if not fields.get(field, "").strip()
            ]
            if missing:
                violations.append(
                    "framework-defect-backlog entry "
                    f"'{title}' missing required fields: {', '.join(missing)}"
                )

    if _has_canonical_formal_dirs(root):
        for rel_path in _scan_misplaced_formal_artifacts(root):
            violations.append(
                "misplaced formal artifact detected under docs/superpowers/*: "
                f"{rel_path}"
            )

    return violations


def validate_backlog_reference_sync(repo_root: Path | None = None) -> list[str]:
    root = repo_root or Path(__file__).resolve().parents[3]
    backlog_ids = set(_load_backlog_entry_ids(root))
    if not backlog_ids:
        return []

    violations: list[str] = []
    specs_root = root / "specs"
    if not specs_root.exists():
        return []

    for path in sorted(specs_root.rglob("*.md")):
        referenced = sorted(set(DEFECT_ID_PATTERN.findall(path.read_text(encoding="utf-8"))))
        missing = [defect_id for defect_id in referenced if defect_id not in backlog_ids]
        if missing:
            violations.append(
                "breach_detected_but_not_logged: "
                f"{path.relative_to(root).as_posix()} references missing backlog ids: {', '.join(missing)}"
            )

    return violations


def _parse_framework_defect_backlog(text: str) -> list[tuple[str, dict[str, str]]]:
    entries: list[tuple[str, dict[str, str]]] = []
    current_title: str | None = None
    current_fields: dict[str, str] = {}

    for raw_line in text.splitlines():
        header_match = BACKLOG_HEADER_PATTERN.match(raw_line)
        if header_match:
            if current_title:
                entries.append((current_title, current_fields))
            current_title = header_match.group("title").strip()
            current_fields = {}
            continue

        if current_title is None:
            continue

        field_match = BACKLOG_FIELD_PATTERN.match(raw_line)
        if field_match:
            key = field_match.group("key").strip()
            current_fields[key] = field_match.group("value").strip()

    if current_title:
        entries.append((current_title, current_fields))

    return entries


def _has_canonical_formal_dirs(root: Path) -> bool:
    return (root / "docs/architecture").is_dir() and (root / "specs").is_dir()


def _scan_misplaced_formal_artifacts(root: Path) -> list[str]:
    superpowers_root = root / "docs/superpowers"
    if not superpowers_root.exists():
        return []

    misplaced: list[str] = []
    for path in superpowers_root.rglob("*.md"):
        if path.name[:-3] in FORMAL_ARTIFACTS:
            misplaced.append(path.relative_to(root).as_posix())
    return sorted(misplaced)


def _load_backlog_entry_ids(root: Path) -> tuple[str, ...]:
    path = root / FRAMEWORK_DEFECT_BACKLOG
    if not path.is_file():
        return ()

    entry_ids: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith("## FD-"):
            continue
        title = line[3:].strip()
        defect_id = title.split("|", 1)[0].strip()
        if defect_id:
            entry_ids.append(defect_id)
    return tuple(dict.fromkeys(entry_ids))
