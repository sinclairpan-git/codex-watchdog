from __future__ import annotations

from watchdog.services.brain.models import DecisionIntent, DecisionTrace


class BrainDecisionService:
    def evaluate_session(
        self,
        *,
        trace: DecisionTrace,
        intent: str,
        rationale: str | None = None,
    ) -> DecisionIntent:
        _ = trace
        return DecisionIntent(intent=intent, rationale=rationale)

