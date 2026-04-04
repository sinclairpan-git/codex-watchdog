from __future__ import annotations

from pathlib import Path

from a_control_agent.observability.audit_aggregate import aggregate_audit_actions
from a_control_agent.observability.prometheus_render import render_gauge, render_labeled_counter
from a_control_agent.storage.tasks_store import TaskStore

PROM_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def build_a_metrics_text(
    store: TaskStore,
    audit_path: Path,
    *,
    approvals_audit_path: Path | None = None,
) -> str:
    """A 侧：任务数 + 审计按 action 计数 + PRD 对齐摘要 gauge。"""
    counts = aggregate_audit_actions(audit_path)
    if approvals_audit_path and approvals_audit_path.is_file():
        extra = aggregate_audit_actions(approvals_audit_path)
        for k, v in extra.items():
            counts[k] = counts.get(k, 0) + v
    parts: list[str] = [
        render_gauge(
            "aca_tasks_total",
            "Number of tasks persisted in A-Control-Agent.",
            float(store.count_projects()),
        )
    ]
    label_vals = {k: float(v) for k, v in sorted(counts.items())}
    parts.append(
        render_labeled_counter(
            "aca_audit_events_total",
            "Audit JSONL events on A side by action field.",
            label_vals if label_vals else {"none": 0.0},
        )
    )
    # PRD §14.3 对齐（从审计可推导的代理量）
    parts.append(
        render_gauge(
            "aca_stuck_loop_escalations_total",
            "Loop / repeat-error escalation signals (action loop_escalation).",
            float(counts.get("loop_escalation", 0)),
        )
    )
    parts.append(
        render_gauge(
            "aca_steer_injections_total",
            "Steer injections recorded on A (action steer_injected).",
            float(counts.get("steer_injected", 0)),
        )
    )
    parts.append(
        render_gauge(
            "aca_handoff_events_total",
            "Handoff actions (action handoff).",
            float(counts.get("handoff", 0)),
        )
    )
    parts.append(
        render_gauge(
            "aca_resume_events_total",
            "Resume actions (action resume).",
            float(counts.get("resume", 0)),
        )
    )
    ap_c = counts.get("approval_created", 0)
    ap_d = counts.get("decision", 0)
    parts.append(
        render_gauge(
            "aca_approval_events_total",
            "Approval lifecycle (approval_created + decision).",
            float(ap_c + ap_d),
        )
    )
    return "".join(parts)
