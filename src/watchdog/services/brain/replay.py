from __future__ import annotations

from watchdog.services.brain.models import ReplayResult


class DecisionReplayService:
    def packet_replay(self) -> ReplayResult:
        return ReplayResult(replay_mode="packet_replay")

    def session_semantic_replay(self) -> ReplayResult:
        return ReplayResult(replay_mode="session_semantic_replay")

