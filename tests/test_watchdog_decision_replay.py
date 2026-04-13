from __future__ import annotations

import importlib

from watchdog.settings import Settings


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


def test_packet_replay_marks_missing_packet_input_as_incomplete() -> None:
    module = importlib.import_module("watchdog.services.brain.replay")

    result = module.DecisionReplayService().packet_replay(
        packet_input=None,
        frozen_contract={"model": "model-a"},
        current_contract={"model": "model-a"},
    )

    assert result.replay_incomplete is True
    assert result.drift_detected is False
    assert result.missing_context == ["decision_packet_input"]
    assert "missing_packet_input" in result.failure_reasons


def test_packet_replay_detects_runtime_contract_drift() -> None:
    module = importlib.import_module("watchdog.services.brain.replay")

    result = module.DecisionReplayService().packet_replay(
        packet_input={"packet_id": "packet:1"},
        frozen_contract={
            "provider": "provider-a",
            "model": "model-a",
            "policy_engine_version": "policy:v1",
        },
        current_contract={
            "provider": "provider-a",
            "model": "model-b",
            "policy_engine_version": "policy:v2",
        },
    )

    assert result.replay_incomplete is False
    assert result.drift_detected is True
    assert "model_mismatch" in result.failure_reasons
    assert "policy_engine_version_mismatch" in result.failure_reasons


def test_session_semantic_replay_marks_missing_required_events_as_incomplete() -> None:
    module = importlib.import_module("watchdog.services.brain.replay")

    result = module.DecisionReplayService().session_semantic_replay(
        session_events=[{"event_id": "evt:1"}, {"event_id": "evt:3"}],
        required_event_ids=["evt:1", "evt:2", "evt:3"],
    )

    assert result.replay_incomplete is True
    assert result.drift_detected is False
    assert result.missing_context == ["evt:2"]
    assert "missing_required_events" in result.failure_reasons


def test_packet_replay_accepts_settings_built_runtime_contract() -> None:
    replay_module = importlib.import_module("watchdog.services.brain.replay")
    certification_module = importlib.import_module("watchdog.services.brain.provider_certification")

    settings = Settings(
        release_gate_risk_policy_version="risk:v2",
        release_gate_decision_input_builder_version="dib:v2",
        release_gate_policy_engine_version="policy:v2",
        release_gate_tool_schema_hash="tool:def",
        release_gate_memory_provider_adapter_hash="memory:def",
    )
    runtime_contract = certification_module.build_runtime_contract(
        settings=settings,
        provider="provider-a",
        model="model-a",
        prompt_schema_ref="prompt:v1",
        output_schema_ref="schema:v1",
    )

    result = replay_module.DecisionReplayService().packet_replay(
        packet_input={"packet_id": "packet:1"},
        frozen_contract=runtime_contract,
        current_contract=runtime_contract,
    )

    assert result.replay_incomplete is False
    assert result.drift_detected is False
    assert result.failure_reasons == []
