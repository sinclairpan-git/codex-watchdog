from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def summarize_workspace_activity(
    cwd: Path,
    *,
    max_files: int = 500,
    max_depth: int = 5,
    recent_minutes: int = 15,
) -> dict[str, Any]:
    """扫描工作区（仅文件 mtime，不执行 shell）。用于辅助「是否有有效变更」类判别。"""
    if not cwd.is_dir():
        return {
            "cwd_exists": False,
            "files_scanned": 0,
            "latest_mtime_iso": None,
            "recent_change_count": 0,
        }

    now = time.time()
    threshold = now - recent_minutes * 60
    latest_mtime = 0.0
    scanned = 0
    recent_count = 0
    root0 = cwd.resolve()

    for root, dirs, files in os.walk(root0, topdown=True):
        rel = Path(root).relative_to(root0)
        depth = len(rel.parts)
        if depth > max_depth:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            if scanned >= max_files:
                break
            if name.startswith("."):
                continue
            path = Path(root) / name
            try:
                st = path.stat()
            except OSError:
                continue
            scanned += 1
            if st.st_mtime > latest_mtime:
                latest_mtime = st.st_mtime
            if st.st_mtime >= threshold:
                recent_count += 1
        if scanned >= max_files:
            break

    latest_iso: str | None = None
    if latest_mtime > 0:
        latest_iso = datetime.fromtimestamp(latest_mtime, tz=timezone.utc).isoformat()

    return {
        "cwd_exists": True,
        "files_scanned": scanned,
        "latest_mtime_iso": latest_iso,
        "recent_change_count": recent_count,
        "recent_window_minutes": recent_minutes,
    }
