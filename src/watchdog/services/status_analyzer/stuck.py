from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    s = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class StuckThresholds:
    """默认与 PRD §8.1 对齐（分钟）。"""

    soft_steer_after_minutes: float = 8.0


def evaluate_stuck(
    task: dict[str, Any],
    *,
    now: datetime | None = None,
    thresholds: StuckThresholds | None = None,
) -> dict[str, Any]:
    """返回是否建议 soft steer 及目标 stuck_level。"""
    thresholds = thresholds or StuckThresholds()
    now = now or datetime.now(timezone.utc)
    lp = _parse_ts(task.get("last_progress_at"))
    if lp is None:
        return {
            "should_steer": False,
            "reason": "no_last_progress_at",
            "next_stuck_level": int(task.get("stuck_level", 0)),
            "detail": "missing timestamp",
        }
    if lp.tzinfo is None:
        lp = lp.replace(tzinfo=timezone.utc)
    delta_min = (now - lp.astimezone(timezone.utc)).total_seconds() / 60.0
    level = int(task.get("stuck_level", 0))
    if delta_min >= thresholds.soft_steer_after_minutes and level < 2:
        return {
            "should_steer": True,
            "reason": "stuck_soft",
            "next_stuck_level": 2,
            "detail": f"idle {delta_min:.1f} min",
        }
    return {
        "should_steer": False,
        "reason": "within_threshold",
        "next_stuck_level": level,
        "detail": f"idle {delta_min:.1f} min",
    }


def bump_failure_if_same_signature(
    previous_sig: str | None,
    new_sig: str,
    current_count: int,
) -> tuple[int, bool]:
    """同类错误重复时递增 failure_count。"""
    if previous_sig == new_sig:
        return current_count + 1, True
    return 1, False
