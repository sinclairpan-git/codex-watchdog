from __future__ import annotations

from typing import Any


def is_deferred_policy_auto_approval(approval: dict[str, Any]) -> bool:
    return (
        str(approval.get("status") or "").lower() == "approved"
        and str(approval.get("decided_by") or "") == "policy-auto"
        and str(approval.get("callback_status") or "") == "deferred"
    )


def is_actionable_approval(approval: dict[str, Any]) -> bool:
    status = str(approval.get("status") or "").lower()
    return status == "pending" or is_deferred_policy_auto_approval(approval)


def actionable_approval_count(approvals: list[dict[str, Any]]) -> int:
    return sum(1 for approval in approvals if is_actionable_approval(approval))


def approval_supports_reject(approval: dict[str, Any]) -> bool:
    return str(approval.get("status") or "").lower() == "pending"


def has_rejectable_approval(approvals: list[dict[str, Any]]) -> bool:
    return any(approval_supports_reject(approval) for approval in approvals)
