from __future__ import annotations

import importlib
import importlib.util


def _find_spec(module_name: str):
    try:
        return importlib.util.find_spec(module_name)
    except ModuleNotFoundError:
        return None


def test_future_worker_contract_modules_exist() -> None:
    expected_modules = (
        "watchdog.services.future_worker.models",
        "watchdog.services.future_worker.service",
    )

    missing = [module_name for module_name in expected_modules if _find_spec(module_name) is None]

    assert missing == []


def test_future_worker_models_export_execution_request_and_result_envelope() -> None:
    module_spec = _find_spec("watchdog.services.future_worker.models")
    assert module_spec is not None

    models = importlib.import_module("watchdog.services.future_worker.models")
    expected_symbols = (
        "FutureWorkerExecutionRequest",
        "FutureWorkerResultEnvelope",
    )
    missing = [symbol for symbol in expected_symbols if not hasattr(models, symbol)]

    assert missing == []


def test_future_worker_result_envelope_is_declarative_and_cannot_patch_truth() -> None:
    models = importlib.import_module("watchdog.services.future_worker.models")

    envelope = models.FutureWorkerResultEnvelope(
        worker_task_ref="worker:task-1",
        parent_session_id="session:repo-a",
        decision_trace_ref="trace:1",
        result_summary_ref="summary:worker:1",
        artifact_refs=["artifact:patch:1"],
        input_contract_hash="sha256:input-contract",
        result_hash="sha256:result",
        produced_at="2026-04-14T03:00:00Z",
        status="completed",
    )

    dumped = envelope.model_dump(mode="json")

    assert dumped["worker_task_ref"] == "worker:task-1"
    assert dumped["status"] == "completed"
    assert "goal_contract_patch" not in dumped
    assert "approval_mutation" not in dumped
    assert "completion_truth_write" not in dumped
