from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import yaml

WORK_ITEM_PATTERN = re.compile(r"^(?P<number>\d{3})-(?P<slug>.+)$")
SUMMARY_LAST_TASK_PATTERN = re.compile(r"(?m)^Last Committed Task:\s*(?P<task>T\d+)\s*$")
SUMMARY_NEXT_TASK_PATTERN = re.compile(r"`(?P<task>T\d+)`")
REVIEW_REQUIRED_APPROVERS = (
    "Anthropic Manager Expert",
    "Hermes Agent Expert",
)
OWNER_ORDER = (
    "WI-047",
    "WI-048",
    "WI-049",
    "WI-050",
    "WI-051",
)
LIFECYCLE_SYNC_FIELDS = (
    "current_stage",
    "current_batch",
    "last_committed_task",
    "current_branch",
    "docs_baseline_ref",
    "docs_baseline_at",
    "review_approval_status",
)
RUNTIME_STAGE_ALLOWLIST = (
    "init",
    "refine",
    "design",
    "decompose",
    "execute",
    "verify",
    "completed",
    "close",
    "archived",
)
RUNTIME_ACTIVE_EXCLUDED_STAGES = {"archived", "close"}


@dataclass(frozen=True)
class WorkItemRef:
    number: int
    slug: str
    path: Path

    @property
    def work_item_id(self) -> str:
        return f"{self.number:03d}-{self.slug}"


@dataclass(frozen=True)
class ReconciliationInventory:
    spec_work_items: tuple[str, ...]
    mirrored_work_items: tuple[str, ...]
    missing_work_item_mirrors: tuple[str, ...]
    next_work_item_seq: int
    active_work_item_id: str | None
    stale_pointers: tuple[str, ...]


@dataclass(frozen=True)
class MatrixGapRow:
    stable_id: str
    summary: str
    gap_type: str
    source: str
    state_unstable: bool = False
    backlog_handoff: bool = False


@dataclass(frozen=True)
class OwnerLedgerEntry:
    stable_id: str
    summary: str
    gap_type: str
    owner: str
    non_owners: tuple[str, ...]
    dependency_artifacts: tuple[str, ...]
    source: str


@dataclass(frozen=True)
class _ExecutionPlanState:
    current_batch: str | None
    task_statuses: dict[str, str]
    batch_statuses: dict[str, str]


@dataclass(frozen=True)
class _RuntimeTruthState:
    current_stage: str | None
    violations: tuple[str, ...]


def collect_reconciliation_inventory(repo_root: Path | None = None) -> ReconciliationInventory:
    root = repo_root or Path(__file__).resolve().parents[3]
    spec_items = _list_work_items(root / "specs")
    mirrored_items = _list_work_items(root / ".ai-sdlc/work-items")
    spec_ids = tuple(item.work_item_id for item in spec_items)
    mirrored_ids = tuple(item.work_item_id for item in mirrored_items)
    max_number = _max_work_item_number(spec_items, mirrored_items)
    next_work_item_seq = max_number + 1 if max_number is not None else 1
    missing_mirrors = tuple(sorted(set(spec_ids) - set(mirrored_ids)))

    stale_pointers: list[str] = []
    checkpoint_path = root / ".ai-sdlc/state/checkpoint.yml"
    checkpoint_text = _read_text_if_exists(checkpoint_path)
    checkpoint_ids = tuple(
        value
        for value in (
            _extract_scalar(checkpoint_text, "linked_wi_id"),
            _extract_nested_feature_id(checkpoint_text),
        )
        if value
    )
    runtime_active_work_item_id = _detect_runtime_active_work_item(root / ".ai-sdlc/work-items")
    active_work_item_id = _select_highest_work_item_id(
        runtime_active_work_item_id,
        *checkpoint_ids,
    )
    if active_work_item_id:
        for checkpoint_id in checkpoint_ids:
            if checkpoint_id != active_work_item_id:
                stale_pointers.append(
                    f".ai-sdlc/state/checkpoint.yml points to {checkpoint_id}, expected {active_work_item_id}"
                )

    project_state_path = root / ".ai-sdlc/project/config/project-state.yaml"
    project_state_text = _read_text_if_exists(project_state_path)
    project_next_seq = _extract_scalar(project_state_text, "next_work_item_seq")
    if project_next_seq and project_next_seq.isdigit():
        if int(project_next_seq) != next_work_item_seq:
            stale_pointers.append(
                ".ai-sdlc/project/config/project-state.yaml "
                f"next_work_item_seq={project_next_seq}, expected {next_work_item_seq}"
            )

    state_resume_path = root / ".ai-sdlc/state/resume-pack.yaml"
    state_resume_text = _read_text_if_exists(state_resume_path)
    checkpoint_stage = _extract_scalar(checkpoint_text, "current_stage")
    checkpoint_branch = _extract_scalar(checkpoint_text, "current_branch")

    if checkpoint_stage:
        state_resume_stage = _extract_scalar(state_resume_text, "current_stage")
        if state_resume_stage and state_resume_stage != checkpoint_stage:
            stale_pointers.append(
                ".ai-sdlc/state/resume-pack.yaml: "
                f"current_stage={state_resume_stage} does not match checkpoint current_stage={checkpoint_stage}"
            )

    if checkpoint_branch:
        state_resume_branch = _extract_scalar(state_resume_text, "current_branch")
        if state_resume_branch and state_resume_branch != checkpoint_branch:
            stale_pointers.append(
                ".ai-sdlc/state/resume-pack.yaml: "
                "current_branch="
                f"{state_resume_branch} does not match checkpoint current_branch={checkpoint_branch}"
            )

    if active_work_item_id:
        for field, expected_value in (
            ("spec_path", f"specs/{active_work_item_id}/spec.md"),
            ("plan_path", f"specs/{active_work_item_id}/plan.md"),
            ("tasks_path", f"specs/{active_work_item_id}/tasks.md"),
        ):
            state_resume_value = _extract_scalar(state_resume_text, field)
            if state_resume_value and state_resume_value != expected_value:
                stale_pointers.append(
                    ".ai-sdlc/state/resume-pack.yaml: "
                    f"{field}={state_resume_value} does not match active truth {field}={expected_value}"
                )

    return ReconciliationInventory(
        spec_work_items=spec_ids,
        mirrored_work_items=mirrored_ids,
        missing_work_item_mirrors=missing_mirrors,
        next_work_item_seq=next_work_item_seq,
        active_work_item_id=active_work_item_id,
        stale_pointers=tuple(stale_pointers),
    )


def validate_work_item_lifecycle(work_item_root: Path) -> list[str]:
    violations: list[str] = []
    runtime_text = _read_text_if_exists(work_item_root / "runtime.yaml")
    execution_plan_text = _read_text_if_exists(work_item_root / "execution-plan.yaml")
    resume_text = _read_text_if_exists(work_item_root / "resume-pack.yaml")
    summary_text = _read_text_if_exists(work_item_root / "latest-summary.md")

    runtime = {field: _extract_scalar(runtime_text, field) for field in LIFECYCLE_SYNC_FIELDS}
    runtime["current_task"] = _extract_scalar(runtime_text, "current_task")
    runtime_reviewers = _extract_list(runtime_text, "review_approved_by")

    resume = {field: _extract_scalar(resume_text, field) for field in LIFECYCLE_SYNC_FIELDS}
    resume_reviewers = _extract_list(resume_text, "review_approved_by")

    if runtime.get("current_task") == "T472":
        for field in ("docs_baseline_ref", "docs_baseline_at", "review_approval_status"):
            if not runtime.get(field):
                violations.append(f"runtime.yaml: missing {field} before T472")
            if not resume.get(field):
                violations.append(f"resume-pack.yaml: missing {field} before T472")
        if not runtime_reviewers:
            violations.append("runtime.yaml: missing review_approved_by before T472")
        if not resume_reviewers:
            violations.append("resume-pack.yaml: missing review_approved_by before T472")

    for field in LIFECYCLE_SYNC_FIELDS:
        runtime_value = runtime.get(field)
        resume_value = resume.get(field)
        if runtime_value and resume_value and runtime_value != resume_value:
            violations.append(
                f"resume-pack.yaml: {field}={resume_value} does not match runtime.yaml={runtime_value}"
            )

    if runtime_reviewers and resume_reviewers and runtime_reviewers != resume_reviewers:
        violations.append("resume-pack.yaml: review_approved_by does not match runtime.yaml")

    if runtime.get("review_approval_status") and runtime["review_approval_status"] != "approved":
        violations.append("runtime.yaml: review_approval_status must be approved")
    if resume.get("review_approval_status") and resume["review_approval_status"] != "approved":
        violations.append("resume-pack.yaml: review_approval_status must be approved")

    for approver in REVIEW_REQUIRED_APPROVERS:
        if runtime_reviewers and approver not in runtime_reviewers:
            violations.append(f"runtime.yaml: missing required approver {approver}")
        if resume_reviewers and approver not in resume_reviewers:
            violations.append(f"resume-pack.yaml: missing required approver {approver}")

    if execution_plan_text:
        plan = _parse_execution_plan(execution_plan_text)
        if runtime.get("current_batch") and plan.current_batch and runtime["current_batch"] != plan.current_batch:
            violations.append(
                "execution-plan.yaml: current_batch="
                f"{plan.current_batch} does not match runtime.yaml={runtime['current_batch']}"
            )

        current_stage = runtime.get("current_stage")
        current_task = runtime.get("current_task")
        if current_task:
            task_status = plan.task_statuses.get(current_task)
            if task_status != "in_progress":
                violations.append(
                    f"execution-plan.yaml: {current_task} status must be in_progress, got {task_status or 'missing'}"
                )

        last_committed = runtime.get("last_committed_task")
        if last_committed:
            task_status = plan.task_statuses.get(last_committed)
            if task_status != "completed":
                violations.append(
                    "execution-plan.yaml: "
                    f"{last_committed} status must be completed, got {task_status or 'missing'}"
                )

        if runtime.get("current_batch"):
            batch_status = plan.batch_statuses.get(runtime["current_batch"])
            expected_batch_status = "completed" if current_stage == "completed" and not current_task else "in_progress"
            if batch_status != expected_batch_status:
                violations.append(
                    "execution-plan.yaml: batch "
                    f"{runtime['current_batch']} status must be {expected_batch_status}, got {batch_status or 'missing'}"
                )

    if summary_text:
        summary_last_task = _extract_summary_last_committed_task(summary_text)
        if runtime.get("last_committed_task") and summary_last_task != runtime["last_committed_task"]:
            violations.append(
                "latest-summary.md: Last Committed Task "
                f"{summary_last_task or 'missing'} does not match runtime.yaml={runtime['last_committed_task']}"
            )

        current_task = runtime.get("current_task")
        if current_task:
            summary_next_task = _extract_summary_next_task(summary_text)
            if summary_next_task and summary_next_task != current_task:
                violations.append(
                    "latest-summary.md: next task "
                    f"{summary_next_task} does not match runtime.yaml current_task={current_task}"
                )

    return violations


def validate_completed_review_gate_mirror_drift(repo_root: Path | None = None) -> list[str]:
    root = repo_root or Path(__file__).resolve().parents[3]
    violations: list[str] = []
    work_items_root = root / ".ai-sdlc/work-items"

    for item in _list_work_items(work_items_root):
        runtime_text = _read_text_if_exists(item.path / "runtime.yaml")
        resume_text = _read_text_if_exists(item.path / "resume-pack.yaml")
        runtime_stage = _extract_scalar(runtime_text, "current_stage")
        resume_stage = _extract_scalar(resume_text, "current_stage")

        if runtime_stage == "completed" and _extract_scalar(runtime_text, "review_approval_status") == "pending":
            violations.append(
                "completed work-item review gate mirror "
                f"({item.work_item_id}): "
                "runtime.yaml: review_approval_status must be removed once current_stage=completed"
            )
        if resume_stage == "completed" and _extract_scalar(resume_text, "review_approval_status") == "pending":
            violations.append(
                "completed work-item review gate mirror "
                f"({item.work_item_id}): "
                "resume-pack.yaml: review_approval_status must be removed once current_stage=completed"
            )

    return violations


def validate_runtime_truth_integrity(repo_root: Path | None = None) -> list[str]:
    root = repo_root or Path(__file__).resolve().parents[3]
    violations: list[str] = []

    for item in _list_work_items(root / ".ai-sdlc/work-items"):
        runtime_state = _inspect_runtime_truth(item)
        violations.extend(
            f"runtime truth integrity ({item.work_item_id}): {violation}"
            for violation in runtime_state.violations
        )

    return violations


def build_owner_ledger(rows: Sequence[MatrixGapRow]) -> list[OwnerLedgerEntry]:
    seen_ids: set[str] = set()
    ledger: list[OwnerLedgerEntry] = []

    for row in rows:
        if row.stable_id in seen_ids:
            raise ValueError(f"duplicate matrix stable_id: {row.stable_id}")
        seen_ids.add(row.stable_id)

        owner = _assign_owner(row)
        ledger.append(
            OwnerLedgerEntry(
                stable_id=row.stable_id,
                summary=row.summary,
                gap_type=row.gap_type,
                owner=owner,
                non_owners=tuple(candidate for candidate in OWNER_ORDER if candidate != owner),
                dependency_artifacts=_dependency_artifacts_for_owner(owner),
                source=row.source,
            )
        )

    return ledger


def parse_unlanded_matrix_rows(markdown: str) -> list[MatrixGapRow]:
    rows: list[MatrixGapRow] = []

    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue

        columns = [column.strip() for column in stripped.strip("|").split("|")]
        if len(columns) != 7:
            continue
        if columns[0] == "来源" or all(set(column) <= {"-"} for column in columns):
            continue

        source, summary, _implementation, _verification, _entry, gap_type, conclusion = columns
        if conclusion != "未落地":
            continue

        rows.append(
            MatrixGapRow(
                stable_id=f"matrix-row-{len(rows) + 1:04d}",
                summary=summary,
                gap_type=gap_type,
                source=source,
                state_unstable=_contains_any(gap_type, ("状态真值", "镜像", "owner ledger", "framework gate")),
            )
        )

    return rows


def _assign_owner(row: MatrixGapRow) -> str:
    gap = row.gap_type

    if row.state_unstable or _contains_any(gap, ("状态真值", "镜像", "owner ledger", "framework gate")):
        return "WI-047"
    if _contains_any(gap, ("无实现", "实现缺口", "实现不足", "边界校验缺失", "枚举不一致")):
        return "WI-048"
    if _contains_any(gap, ("无入口", "缺飞书入口", "缺运行时入口", "自然语言映射", "渠道")):
        return "WI-049"
    if _contains_any(gap, ("无验证", "性能", "重启", "安全", "可靠性", "测试报告", "交付物")):
        return "WI-050"
    if row.backlog_handoff:
        return "WI-051"
    return "WI-047"


def _dependency_artifacts_for_owner(owner: str) -> tuple[str, ...]:
    if owner == "WI-047":
        return ("reconciliation-inventory.yaml", "matrix-owner-ledger.yaml")
    if owner == "WI-048":
        return ("WI-047 owner ledger", "runtime semantics baseline")
    if owner == "WI-049":
        return ("WI-048 runtime semantics baseline", "canonical route contract")
    if owner == "WI-050":
        return ("WI-048 runtime semantics baseline", "WI-049 entry surface")
    return ("WI-050 latest-summary explicit handoff",)


def _list_work_items(base_dir: Path) -> tuple[WorkItemRef, ...]:
    if not base_dir.exists():
        return ()

    items: list[WorkItemRef] = []
    for path in sorted(base_dir.iterdir()):
        if not path.is_dir():
            continue
        match = WORK_ITEM_PATTERN.match(path.name)
        if match is None:
            continue
        items.append(
            WorkItemRef(
                number=int(match.group("number")),
                slug=match.group("slug"),
                path=path,
            )
        )
    return tuple(items)


def _max_work_item_number(*groups: Iterable[WorkItemRef]) -> int | None:
    numbers = [item.number for group in groups for item in group]
    return max(numbers) if numbers else None


def _detect_runtime_active_work_item(work_items_root: Path) -> str | None:
    candidates: list[tuple[int, str]] = []
    completed_candidates: list[tuple[int, str]] = []
    for item in _list_work_items(work_items_root):
        runtime_state = _inspect_runtime_truth(item)
        current_stage = runtime_state.current_stage
        if runtime_state.violations or not current_stage:
            continue
        if current_stage in RUNTIME_ACTIVE_EXCLUDED_STAGES:
            continue
        if current_stage == "completed":
            completed_candidates.append((item.number, item.work_item_id))
            continue
        candidates.append((item.number, item.work_item_id))

    if candidates:
        return max(candidates, key=lambda item: item[0])[1]
    if completed_candidates:
        return max(completed_candidates, key=lambda item: item[0])[1]
    return None


def _select_highest_work_item_id(*work_item_ids: str | None) -> str | None:
    candidates: list[tuple[int, str]] = []
    for work_item_id in work_item_ids:
        if not work_item_id:
            continue
        match = WORK_ITEM_PATTERN.match(work_item_id)
        if match is None:
            continue
        candidates.append((int(match.group("number")), work_item_id))

    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _inspect_runtime_truth(item: WorkItemRef) -> _RuntimeTruthState:
    runtime_path = item.path / "runtime.yaml"
    violations: list[str] = []

    for temp_path in sorted(_iter_runtime_atomic_temp_files(item.path)):
        violations.append(f"runtime.yaml: leftover atomic temp file {temp_path.name}")

    if not runtime_path.exists():
        return _RuntimeTruthState(current_stage=None, violations=tuple(violations))

    try:
        payload = yaml.safe_load(runtime_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return _RuntimeTruthState(current_stage=None, violations=tuple([*violations, "runtime.yaml: invalid YAML"]))

    if not isinstance(payload, dict):
        return _RuntimeTruthState(
            current_stage=None,
            violations=tuple([*violations, "runtime.yaml: top-level YAML must be a mapping"]),
        )

    current_stage = payload.get("current_stage")
    if current_stage is None:
        violations.append("runtime.yaml: missing current_stage")
    elif not isinstance(current_stage, str) or not current_stage.strip():
        violations.append("runtime.yaml: current_stage must be a non-empty string")
    else:
        current_stage = current_stage.strip()
        if current_stage not in RUNTIME_STAGE_ALLOWLIST:
            violations.append(f"runtime.yaml: current_stage={current_stage} is not allowed")

    work_item_id = payload.get("work_item_id")
    if work_item_id is not None:
        if not isinstance(work_item_id, str) or not work_item_id.strip():
            violations.append("runtime.yaml: work_item_id must be a non-empty string when present")
        elif work_item_id.strip() != item.work_item_id:
            violations.append(
                "runtime.yaml: "
                f"work_item_id={work_item_id.strip()} does not match directory={item.work_item_id}"
            )

    if violations:
        return _RuntimeTruthState(current_stage=None, violations=tuple(violations))

    return _RuntimeTruthState(current_stage=current_stage, violations=())


def _iter_runtime_atomic_temp_files(work_item_root: Path) -> tuple[Path, ...]:
    return tuple(
        path
        for path in work_item_root.iterdir()
        if path.is_file()
        and (
            path.name == "runtime.yaml.tmp"
            or (path.name.startswith(".runtime.yaml.") and path.name.endswith(".tmp"))
        )
    )


def _extract_scalar(text: str, key: str) -> str | None:
    if not text:
        return None

    match = re.search(rf"(?m)^[ \t]*{re.escape(key)}:\s*(?P<value>.*)$", text)
    if match is None:
        return None

    value = match.group("value").strip()
    if value in {"", "null", "~"}:
        return None
    if value in {"''", '""'}:
        return ""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _extract_list(text: str, key: str) -> tuple[str, ...]:
    if not text:
        return ()

    lines = text.splitlines()
    for index, line in enumerate(lines):
        if re.match(rf"^[ \t]*{re.escape(key)}:\s*$", line) is None:
            continue

        base_indent = len(line) - len(line.lstrip(" "))
        values: list[str] = []
        cursor = index + 1
        while cursor < len(lines):
            candidate = lines[cursor]
            if not candidate.strip():
                cursor += 1
                continue

            indent = len(candidate) - len(candidate.lstrip(" "))
            stripped = candidate.strip()
            if indent < base_indent:
                break
            if indent == base_indent and not stripped.startswith("- "):
                break
            if stripped.startswith("- "):
                values.append(_clean_value(stripped[2:]))
            cursor += 1
        return tuple(values)

    return ()


def _extract_nested_feature_id(text: str) -> str | None:
    if not text:
        return None

    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != "feature:":
            continue

        base_indent = len(line) - len(line.lstrip(" "))
        cursor = index + 1
        while cursor < len(lines):
            candidate = lines[cursor]
            if not candidate.strip():
                cursor += 1
                continue

            indent = len(candidate) - len(candidate.lstrip(" "))
            stripped = candidate.strip()
            if indent <= base_indent:
                break
            if stripped.startswith("id:"):
                return _clean_value(stripped.split(":", 1)[1].strip())
            cursor += 1

    return None


def _parse_execution_plan(text: str) -> _ExecutionPlanState:
    current_batch = _extract_scalar(text, "current_batch")
    task_statuses: dict[str, str] = {}
    batch_statuses: dict[str, str] = {}

    in_batches = False
    current_task_id: str | None = None
    current_batch_id: str | None = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        if stripped == "tasks:" and not in_batches:
            current_task_id = None
            continue
        if stripped == "batches:":
            in_batches = True
            current_task_id = None
            current_batch_id = None
            continue

        if not in_batches:
            if stripped.startswith("- task_id:"):
                current_task_id = _clean_value(stripped.split(":", 1)[1].strip())
                task_statuses.setdefault(current_task_id, "")
                continue
            if stripped.startswith("task_id:"):
                current_task_id = _clean_value(stripped.split(":", 1)[1].strip())
                task_statuses.setdefault(current_task_id, "")
                continue
            if stripped.startswith("status:") and current_task_id:
                task_statuses[current_task_id] = _clean_value(stripped.split(":", 1)[1].strip())
                continue
        else:
            if stripped.startswith("- batch_id:"):
                current_batch_id = _clean_value(stripped.split(":", 1)[1].strip())
                batch_statuses.setdefault(current_batch_id, "")
                continue
            if stripped.startswith("batch_id:"):
                current_batch_id = _clean_value(stripped.split(":", 1)[1].strip())
                batch_statuses.setdefault(current_batch_id, "")
                continue
            if stripped.startswith("status:") and current_batch_id:
                batch_statuses[current_batch_id] = _clean_value(stripped.split(":", 1)[1].strip())
                continue

    return _ExecutionPlanState(
        current_batch=current_batch,
        task_statuses=task_statuses,
        batch_statuses=batch_statuses,
    )


def _extract_summary_last_committed_task(text: str) -> str | None:
    match = SUMMARY_LAST_TASK_PATTERN.search(text)
    return match.group("task") if match else None


def _extract_summary_next_task(text: str) -> str | None:
    for line in text.splitlines():
        if "下一执行入口" not in line:
            continue
        match = SUMMARY_NEXT_TASK_PATTERN.search(line)
        if match:
            return match.group("task")
    return None


def _read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _clean_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _contains_any(value: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in value for keyword in keywords)
