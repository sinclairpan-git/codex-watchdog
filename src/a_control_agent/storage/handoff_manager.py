"""Handoff 文件写入（PRD §8.4.4 结构占位，可替换为完整模板）。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build_handoff_markdown(
    *,
    project_id: str,
    reason: str,
    task: dict[str, Any],
) -> str:
    lines = [
        "# Handoff summary",
        "",
        f"## 项目: `{project_id}`",
        "",
        "## 原因",
        reason,
        "",
        "## 当前目标",
        str(task.get("task_title", "")),
        "",
        "## 已完成 / 摘要",
        str(task.get("last_summary", "")),
        "",
        "## 已修改文件",
        ", ".join(task.get("files_touched") or []) or "(无)",
        "",
        "## 阻塞与待审批",
        f"pending_approval={task.get('pending_approval')}",
        "",
        "## 下一步建议",
        "由接收线程基于本摘要继续执行。",
        "",
    ]
    return "\n".join(lines)


def write_handoff_file(
    handoffs_dir: Path,
    project_id: str,
    reason: str,
    task: dict[str, Any],
) -> tuple[str, str]:
    handoffs_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"handoff_{project_id}_{ts}.md"
    path = handoffs_dir / name
    body = build_handoff_markdown(project_id=project_id, reason=reason, task=task)
    path.write_text(body, encoding="utf-8")
    return str(path.resolve()), body
