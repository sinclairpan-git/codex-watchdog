from __future__ import annotations

import re
from pathlib import Path

UNFINISHED_STATUS_MARKERS = ("进行中", "待开始", "未开始")
SUMMARY_STATUS_PATTERN = re.compile(r"(?m)^Status:\s*(?P<status>\w+)\s*$")
PLAN_TASK_STATUS_PATTERN = re.compile(r"(?m)^[ \t]*status:\s*(?P<status>[A-Za-z_]+)\s*$")


def validate_task_doc_status_contracts(repo_root: Path | None = None) -> list[str]:
    root = repo_root or Path(__file__).resolve().parents[3]
    violations: list[str] = []

    for tasks_doc in sorted((root / "specs").glob("*/tasks.md")):
        work_item_id = tasks_doc.parent.name
        wi_root = root / ".ai-sdlc/work-items" / work_item_id
        summary_path = wi_root / "latest-summary.md"
        plan_path = wi_root / "execution-plan.yaml"

        if not summary_path.exists() or not plan_path.exists():
            continue

        summary_text = summary_path.read_text(encoding="utf-8")
        plan_text = plan_path.read_text(encoding="utf-8")

        if _extract_summary_status(summary_text) != "completed":
            continue
        if not _all_plan_tasks_completed(plan_text):
            continue

        tasks_text = tasks_doc.read_text(encoding="utf-8")
        unfinished = [marker for marker in UNFINISHED_STATUS_MARKERS if marker in tasks_text]
        if unfinished:
            joined = ", ".join(unfinished)
            rel = tasks_doc.relative_to(root)
            violations.append(
                f"task doc status drift: {rel} still contains unfinished status markers {joined}"
            )

    return violations


def _extract_summary_status(text: str) -> str:
    match = SUMMARY_STATUS_PATTERN.search(text)
    return match.group("status") if match else ""


def _all_plan_tasks_completed(text: str) -> bool:
    statuses = PLAN_TASK_STATUS_PATTERN.findall(text)
    task_statuses = [status for status in statuses if status in {"completed", "pending", "in_progress"}]
    return bool(task_statuses) and all(status == "completed" for status in task_statuses)
