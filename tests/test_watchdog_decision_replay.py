from __future__ import annotations

import importlib


def test_replay_module_exports_packet_and_session_semantic_replay() -> None:
    module = importlib.import_module("watchdog.services.brain.replay")

    assert hasattr(module, "DecisionReplayService")
    assert hasattr(module.DecisionReplayService, "packet_replay")
    assert hasattr(module.DecisionReplayService, "session_semantic_replay")


def test_replay_result_exposes_incomplete_and_drift_fields() -> None:
    models = importlib.import_module("watchdog.services.brain.models")

    result = models.ReplayResult(
        replay_mode="packet_replay",
        replay_incomplete=True,
        drift_detected=False,
        missing_context=["session:event:42"],
        failure_reasons=["missing_context"],
    )

    assert result.replay_incomplete is True
    assert result.missing_context == ["session:event:42"]
