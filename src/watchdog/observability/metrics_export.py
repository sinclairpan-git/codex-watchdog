from __future__ import annotations

from pathlib import Path

from a_control_agent.observability.audit_aggregate import aggregate_watchdog_audit_actions
from a_control_agent.observability.prometheus_render import render_gauge, render_labeled_counter
from watchdog.api.ops import build_ops_summary
from watchdog.settings import Settings

PROM_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _render_labeled_gauge(name: str, help_text: str, *, label_key: str, values: dict[str, float]) -> str:
    lines = [
        f"# HELP {name} {help_text}",
        f"# TYPE {name} gauge",
    ]
    for label, value in sorted(values.items()):
        safe = label.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'{name}{{{label_key}="{safe}"}} {value}')
    return "\n".join(lines) + "\n"


def build_watchdog_metrics_text(
    audit_path: Path,
    *,
    data_dir: Path | None = None,
    settings: Settings | None = None,
) -> str:
    """B 侧：仅统计 audit 中 source=watchdog 的记录。"""
    counts = aggregate_watchdog_audit_actions(audit_path)
    label_vals = {k: float(v) for k, v in sorted(counts.items())}
    alert_vals: dict[str, float] = {}
    release_gate_blocker_vals: dict[str, float] = {}
    future_worker_status_vals: dict[str, float] = {}
    future_worker_blocked_vals: dict[str, float] = {}
    if data_dir is not None and settings is not None:
        summary = build_ops_summary(data_dir=data_dir, settings=settings)
        alert_vals = {item.alert_code: float(item.count) for item in summary.alerts}
        for blocker in summary.release_gate_blockers:
            release_gate_blocker_vals[blocker.reason] = (
                release_gate_blocker_vals.get(blocker.reason, 0.0) + 1.0
            )
        for worker in summary.future_workers:
            future_worker_status_vals[worker.status] = (
                future_worker_status_vals.get(worker.status, 0.0) + 1.0
            )
            if worker.blocking_reason:
                future_worker_blocked_vals[worker.blocking_reason] = (
                    future_worker_blocked_vals.get(worker.blocking_reason, 0.0) + 1.0
                )
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
        _render_labeled_gauge(
            "watchdog_ops_alert_active",
            "Active Watchdog ops alerts by alert code.",
            label_key="alert",
            values=alert_vals
            if alert_vals
            else {
                "approval_pending_too_long": 0.0,
                "blocked_too_long": 0.0,
                "delivery_failed": 0.0,
                "mapping_incomplete": 0.0,
                "recovery_failed": 0.0,
            },
        ),
        _render_labeled_gauge(
            "watchdog_release_gate_blocker_active",
            "Active release gate blockers by normalized reason.",
            label_key="reason",
            values=release_gate_blocker_vals if release_gate_blocker_vals else {"none": 0.0},
        ),
        _render_labeled_gauge(
            "watchdog_future_worker_status_active",
            "Active future worker states by canonical status.",
            label_key="status",
            values=future_worker_status_vals if future_worker_status_vals else {"none": 0.0},
        ),
        _render_labeled_gauge(
            "watchdog_future_worker_blocked_active",
            "Active future worker blocking reasons.",
            label_key="reason",
            values=future_worker_blocked_vals if future_worker_blocked_vals else {"none": 0.0},
        ),
    ]
    return "".join(parts)
