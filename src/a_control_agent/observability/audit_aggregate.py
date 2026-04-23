from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


def aggregate_audit_actions(audit_path: Path) -> dict[str, int]:
    """扫描 audit.jsonl，按 `action` 字段计数（缺失或非字符串忽略）。"""
    if not audit_path.is_file():
        return {}
    counts: Counter[str] = Counter()
    with audit_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec: dict[str, Any] = json.loads(line)
            except json.JSONDecodeError:
                continue
            act = rec.get("action")
            if isinstance(act, str):
                counts[act] += 1
    return dict(counts)


def aggregate_watchdog_audit_actions(audit_path: Path) -> dict[str, int]:
    """仅统计 `source == watchdog` 的记录，避免与 runtime 侧同文件混写时重复（若分文件则等同全量）。"""
    if not audit_path.is_file():
        return {}
    counts: Counter[str] = Counter()
    with audit_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec: dict[str, Any] = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("source") != "watchdog":
                continue
            act = rec.get("action")
            if isinstance(act, str):
                counts[act] += 1
    return dict(counts)
