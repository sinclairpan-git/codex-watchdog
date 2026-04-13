from __future__ import annotations

import importlib


def test_release_gate_module_exports_report_and_verdict_types() -> None:
    module = importlib.import_module("watchdog.services.brain.release_gate")

    assert hasattr(module, "ReleaseGateReport")
    assert hasattr(module, "ReleaseGateVerdict")
    assert hasattr(module, "ReleaseGateEvaluator")


def test_release_gate_report_carries_runtime_invalidation_fields() -> None:
    module = importlib.import_module("watchdog.services.brain.release_gate")

    report = module.ReleaseGateReport(
        report_id="report-1",
        report_hash="sha256:report",
        sample_window="2026-04-01..2026-04-07",
        shadow_window="2026-04-08..2026-04-09",
        label_manifest="tests/fixtures/release_gate_label_manifest.json",
        generated_by="codex",
        report_approved_by="operator-a",
        artifact_ref="tests/fixtures/release_gate_expected_report.json",
        expires_at="2026-05-01T00:00:00Z",
        provider="provider-a",
        model="model-a",
        prompt_schema_ref="prompt:v1",
        output_schema_ref="schema:v1",
        risk_policy_version="risk:v1",
        decision_input_builder_version="dib:v1",
        policy_engine_version="policy:v1",
        tool_schema_hash="tool:abc",
        memory_provider_adapter_hash="memory:abc",
        input_hash="sha256:input",
    )

    assert report.decision_input_builder_version == "dib:v1"
    assert report.policy_engine_version == "policy:v1"
    assert report.report_approved_by == "operator-a"


def test_release_gate_verdict_records_trace_and_approval_refs() -> None:
    module = importlib.import_module("watchdog.services.brain.release_gate")

    verdict = module.ReleaseGateVerdict(
        status="degraded",
        decision_trace_ref="trace:1",
        approval_read_ref="approval:event:1",
        degrade_reason="approval_stale",
        report_id="report-1",
        report_hash="sha256:report",
        input_hash="sha256:input",
    )

    assert verdict.decision_trace_ref == "trace:1"
    assert verdict.approval_read_ref == "approval:event:1"
