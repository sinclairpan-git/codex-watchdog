"""Handoff 文件写入（PRD §8.4.4 结构占位，可替换为完整模板）。"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any


def build_handoff_markdown(
    *,
    project_id: str,
    reason: str,
    task: dict[str, Any],
    source_packet_id: str,
    goal_contract_version: str | None = None,
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
        "## Provenance",
        f"source_packet_id={source_packet_id}",
    ]
    if goal_contract_version:
        lines.extend(["", f"goal_contract_version={goal_contract_version}"])
    lines.extend(
        [
            "",
        "## 下一步建议",
        "由接收线程基于本摘要继续执行。",
        "",
        ]
    )
    return "\n".join(lines)


def build_source_packet_id(
    *,
    handoff_path: Path,
    project_id: str,
    reason: str,
    task: dict[str, Any],
) -> str:
    material = json.dumps(
        {
            "project_id": project_id,
            "reason": reason,
            "handoff_path": str(handoff_path.resolve()),
            "task": task,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return f"packet:handoff:{sha256(material.encode('utf-8')).hexdigest()[:16]}"


def write_handoff_file(
    handoffs_dir: Path,
    project_id: str,
    reason: str,
    task: dict[str, Any],
) -> tuple[str, str, str]:
    handoffs_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"handoff_{project_id}_{ts}.md"
    path = handoffs_dir / name
    source_packet_id = build_source_packet_id(
        handoff_path=path,
        project_id=project_id,
        reason=reason,
        task=task,
    )
    goal_contract_version = str(task.get("goal_contract_version") or "").strip() or None
    body = build_handoff_markdown(
        project_id=project_id,
        reason=reason,
        task=task,
        source_packet_id=source_packet_id,
        goal_contract_version=goal_contract_version,
    )
    path.write_text(body, encoding="utf-8")
    return str(path.resolve()), body, source_packet_id
