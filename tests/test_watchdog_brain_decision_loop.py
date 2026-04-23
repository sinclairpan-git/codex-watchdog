from __future__ import annotations

import importlib
import importlib.util


def _find_spec(module_name: str):
    try:
        return importlib.util.find_spec(module_name)
    except ModuleNotFoundError:
        return None


def test_brain_contract_modules_exist_for_decision_loop() -> None:
    expected_modules = (
        "watchdog.services.brain.models",
        "watchdog.services.brain.decision_input_builder",
        "watchdog.services.brain.service",
        "watchdog.services.brain.validator",
        "watchdog.services.brain.provider_certification",
        "watchdog.services.brain.replay",
    )

    missing = [module_name for module_name in expected_modules if _find_spec(module_name) is None]

    assert missing == []


def test_brain_models_export_intent_trace_and_worker_guard_types() -> None:
    module_spec = _find_spec("watchdog.services.brain.models")
    assert module_spec is not None

    models = importlib.import_module("watchdog.services.brain.models")
    expected_symbols = (
        "DecisionIntent",
        "DecisionTrace",
        "DecisionPacketInput",
        "ApprovalReadSnapshot",
        "FutureWorkerTraceRef",
    )
    missing = [symbol for symbol in expected_symbols if not hasattr(models, symbol)]

    assert missing == []


def test_brain_service_replaces_legacy_action_first_entry() -> None:
    module_spec = _find_spec("watchdog.services.brain.service")
    assert module_spec is not None

    service = importlib.import_module("watchdog.services.brain.service")

    assert hasattr(service, "BrainDecisionService")
    assert hasattr(service.BrainDecisionService, "evaluate_session")
