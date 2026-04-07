from __future__ import annotations

from pathlib import Path

from a_control_agent.observability.audit_aggregate import aggregate_watchdog_audit_actions
from a_control_agent.observability.prometheus_render import render_gauge, render_labeled_counter

PROM_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def build_watchdog_metrics_text(audit_path: Path) -> str:
    """B 侧：仅统计 audit 中 source=watchdog 的记录。"""
    counts = aggregate_watchdog_audit_actions(audit_path)
    label_vals = {k: float(v) for k, v in sorted(counts.items())}
    parts: list[str] = [
        render_labeled_counter(
            "watchdog_audit_events_total",
            "Watchdog-sourced audit events by action.",
            label_vals if label_vals else {"none": 0.0},
        ),
        render_gauge(
            "watchdog_auto_steer_total",
            "Automatic steer injections from Watchdog (action steer_injected).",
            float(counts.get("steer_injected", 0)),
        ),
    ]
    return "".join(parts)
