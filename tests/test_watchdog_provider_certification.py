from __future__ import annotations

import importlib


def test_provider_certification_module_exports_inference_and_memory_adapter_types() -> None:
    module = importlib.import_module("watchdog.services.brain.provider_certification")

    assert hasattr(module, "InferenceProviderCertification")
    assert hasattr(module, "MemoryProviderAdapterCertification")
    assert hasattr(module, "ProviderCompatibilityMatrix")


def test_provider_compatibility_matrix_covers_runtime_drift_fields() -> None:
    module = importlib.import_module("watchdog.services.brain.provider_certification")

    matrix = module.ProviderCompatibilityMatrix(
        provider="provider-a",
        model="model-a",
        prompt_schema_ref="prompt:v1",
        output_schema_ref="schema:v1",
        tool_schema_hash="tool:abc",
        risk_policy_version="risk:v1",
        decision_input_builder_version="dib:v1",
        policy_engine_version="policy:v1",
        memory_provider_adapter_hash="memory:abc",
    )

    assert matrix.decision_input_builder_version == "dib:v1"
    assert matrix.policy_engine_version == "policy:v1"
