from __future__ import annotations

from pathlib import Path
from typing import Any

from a_control_agent.audit import append_jsonl


def append_watchdog_audit(data_dir: Path, record: dict[str, Any]) -> None:
    path = data_dir / "audit.jsonl"
    rec = dict(record)
    rec["source"] = "watchdog"
    append_jsonl(path, rec)


def __getattr__(name: str) -> Any:
    if name in {
        "ActionReceiptEntry",
        "CanonicalAuditQuery",
        "CanonicalAuditView",
        "query_canonical_audit",
    }:
        from .service import (
            ActionReceiptEntry,
            CanonicalAuditQuery,
            CanonicalAuditView,
            query_canonical_audit,
        )

        exports = {
            "ActionReceiptEntry": ActionReceiptEntry,
            "CanonicalAuditQuery": CanonicalAuditQuery,
            "CanonicalAuditView": CanonicalAuditView,
            "query_canonical_audit": query_canonical_audit,
        }
        return exports[name]
    if name in {
        "CanonicalReplayTrace",
        "ReplayTimelineEvent",
        "replay_canonical_audit",
    }:
        from .replay import CanonicalReplayTrace, ReplayTimelineEvent, replay_canonical_audit

        exports = {
            "CanonicalReplayTrace": CanonicalReplayTrace,
            "ReplayTimelineEvent": ReplayTimelineEvent,
            "replay_canonical_audit": replay_canonical_audit,
        }
        return exports[name]
    raise AttributeError(name)


__all__ = [
    "ActionReceiptEntry",
    "CanonicalAuditQuery",
    "CanonicalAuditView",
    "CanonicalReplayTrace",
    "ReplayTimelineEvent",
    "append_watchdog_audit",
    "query_canonical_audit",
    "replay_canonical_audit",
]
