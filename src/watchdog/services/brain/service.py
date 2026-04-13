from __future__ import annotations

from typing import TYPE_CHECKING

from watchdog.services.brain.models import DecisionIntent, DecisionTrace

if TYPE_CHECKING:
    from watchdog.services.session_spine.store import PersistedSessionRecord


class BrainDecisionService:
    def evaluate_session(
        self,
        *,
        record: PersistedSessionRecord | None = None,
        suggested_action_ref: str | None = None,
        trace: DecisionTrace | None = None,
        intent: str | None = None,
        rationale: str | None = None,
    ) -> DecisionIntent:
        _ = (trace, suggested_action_ref)
        if intent is None:
            fact_codes = {fact.fact_code for fact in record.facts} if record is not None else set()
            if "task_completed" in fact_codes:
                intent = "candidate_closure"
                rationale = rationale or "session reached a terminal completed state"
            elif fact_codes.intersection({"approval_pending", "awaiting_human_direction"}):
                intent = "require_approval"
                rationale = rationale or "session requires explicit human guidance"
            elif "context_critical" in fact_codes:
                intent = "propose_recovery"
                rationale = rationale or "session requires recovery handoff"
            elif fact_codes.intersection({"stuck_no_progress", "repeat_failure"}):
                intent = "propose_execute"
                rationale = rationale or "session can continue autonomously"
            else:
                intent = "observe_only"
                rationale = rationale or "no executable action proposed"
        return DecisionIntent(intent=intent, rationale=rationale)
