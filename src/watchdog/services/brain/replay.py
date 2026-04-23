from __future__ import annotations

from watchdog.services.brain.models import ReplayResult


class DecisionReplayService:
    def packet_replay(
        self,
        *,
        packet_input: dict[str, object] | None = None,
        frozen_contract: dict[str, str] | None = None,
        current_contract: dict[str, str] | None = None,
    ) -> ReplayResult:
        if packet_input is None:
            return ReplayResult(
                replay_mode="packet_replay",
                replay_incomplete=True,
                drift_detected=False,
                missing_context=["decision_packet_input"],
                failure_reasons=["missing_packet_input"],
            )
        mismatches = self._contract_mismatches(
            frozen_contract=frozen_contract or {},
            current_contract=current_contract or {},
        )
        return ReplayResult(
            replay_mode="packet_replay",
            replay_incomplete=False,
            drift_detected=bool(mismatches),
            missing_context=[],
            failure_reasons=mismatches,
        )

    def session_semantic_replay(
        self,
        *,
        session_events: list[dict[str, object]] | None = None,
        required_event_ids: list[str] | None = None,
    ) -> ReplayResult:
        events = session_events or []
        required = required_event_ids or []
        seen_event_ids = {
            str(event.get("event_id"))
            for event in events
            if isinstance(event, dict) and event.get("event_id") is not None
        }
        missing = [event_id for event_id in required if event_id not in seen_event_ids]
        return ReplayResult(
            replay_mode="session_semantic_replay",
            replay_incomplete=bool(missing),
            drift_detected=False,
            missing_context=missing,
            failure_reasons=(["missing_required_events"] if missing else []),
        )

    @staticmethod
    def _contract_mismatches(
        *,
        frozen_contract: dict[str, str],
        current_contract: dict[str, str],
    ) -> list[str]:
        mismatches: list[str] = []
        for field_name, expected in frozen_contract.items():
            actual = current_contract.get(field_name)
            if str(actual) != str(expected):
                mismatches.append(f"{field_name}_mismatch")
        return mismatches
