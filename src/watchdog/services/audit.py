from __future__ import annotations

from pathlib import Path
from typing import Any

from a_control_agent.audit import append_jsonl


def append_watchdog_audit(data_dir: Path, record: dict[str, Any]) -> None:
    path = data_dir / "audit.jsonl"
    rec = dict(record)
    rec["source"] = "watchdog"
    append_jsonl(path, rec)
