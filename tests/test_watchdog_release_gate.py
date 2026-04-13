from __future__ import annotations

import importlib
import json
import subprocess
from pathlib import Path

from watchdog.services.brain.models import DecisionTrace
from watchdog.services.brain.validator import DecisionValidationVerdict


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


def test_generate_release_gate_report_script_produces_expected_fixture(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "generate_release_gate_report.py"
    packets = root / "tests" / "fixtures" / "release_gate_packets.jsonl"
    shadow_runs = root / "tests" / "fixtures" / "release_gate_shadow_runs.jsonl"
    label_manifest = root / "tests" / "fixtures" / "release_gate_label_manifest.json"
    expected_report = root / "tests" / "fixtures" / "release_gate_expected_report.json"
    output_path = tmp_path / "release_gate_report.json"

    subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(script),
            "--packets",
            str(packets),
            "--shadow-runs",
            str(shadow_runs),
            "--label-manifest",
            str(label_manifest),
            "--generated-by",
            "codex",
            "--report-approved-by",
            "operator-a",
            "--artifact-ref",
            "tests/fixtures/release_gate_expected_report.json",
            "--sample-window",
            "2026-04-01..2026-04-07",
            "--shadow-window",
            "2026-04-08..2026-04-09",
            "--output",
            str(output_path),
        ],
        check=True,
        cwd=root,
    )

    assert json.loads(output_path.read_text(encoding="utf-8")) == json.loads(
        expected_report.read_text(encoding="utf-8")
    )


def test_release_gate_evaluator_accepts_current_matching_report() -> None:
    module = importlib.import_module("watchdog.services.brain.release_gate")

    evaluator = module.ReleaseGateEvaluator()
    trace = DecisionTrace(
        trace_id="trace:1",
        session_event_cursor="log_seq:7",
        goal_contract_version="goal-v1",
        policy_ruleset_hash="sha256:policy",
        memory_packet_input_ids=[],
        memory_packet_input_hashes=[],
        provider="provider-a",
        model="model-a",
        prompt_schema_ref="prompt:v1",
        output_schema_ref="schema:v1",
    )
    validator_verdict = DecisionValidationVerdict(status="pass", reason="schema_and_risk_ok")
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
        input_hash=evaluator._input_hash_for_trace(trace),
    )

    verdict = evaluator.evaluate(
        brain_intent="propose_execute",
        trace=trace,
        validator_verdict=validator_verdict,
        report=report,
        runtime_contract={
            "risk_policy_version": "risk:v1",
            "decision_input_builder_version": "dib:v1",
            "policy_engine_version": "policy:v1",
            "tool_schema_hash": "tool:abc",
            "memory_provider_adapter_hash": "memory:abc",
        },
        now="2026-04-15T00:00:00Z",
    )

    assert verdict.status == "pass"
    assert verdict.report_id == "report-1"


def test_release_gate_evaluator_degrades_expired_report() -> None:
    module = importlib.import_module("watchdog.services.brain.release_gate")

    evaluator = module.ReleaseGateEvaluator()
    trace = DecisionTrace(
        trace_id="trace:1",
        session_event_cursor="log_seq:7",
        goal_contract_version="goal-v1",
        policy_ruleset_hash="sha256:policy",
        memory_packet_input_ids=[],
        memory_packet_input_hashes=[],
        provider="provider-a",
        model="model-a",
        prompt_schema_ref="prompt:v1",
        output_schema_ref="schema:v1",
    )
    validator_verdict = DecisionValidationVerdict(status="pass", reason="schema_and_risk_ok")
    report = module.ReleaseGateReport(
        report_id="report-1",
        report_hash="sha256:report",
        sample_window="2026-04-01..2026-04-07",
        shadow_window="2026-04-08..2026-04-09",
        label_manifest="tests/fixtures/release_gate_label_manifest.json",
        generated_by="codex",
        report_approved_by="operator-a",
        artifact_ref="tests/fixtures/release_gate_expected_report.json",
        expires_at="2026-04-10T00:00:00Z",
        provider="provider-a",
        model="model-a",
        prompt_schema_ref="prompt:v1",
        output_schema_ref="schema:v1",
        risk_policy_version="risk:v1",
        decision_input_builder_version="dib:v1",
        policy_engine_version="policy:v1",
        tool_schema_hash="tool:abc",
        memory_provider_adapter_hash="memory:abc",
        input_hash=evaluator._input_hash_for_trace(trace),
    )

    verdict = evaluator.evaluate(
        brain_intent="propose_execute",
        trace=trace,
        validator_verdict=validator_verdict,
        report=report,
        runtime_contract={
            "risk_policy_version": "risk:v1",
            "decision_input_builder_version": "dib:v1",
            "policy_engine_version": "policy:v1",
            "tool_schema_hash": "tool:abc",
            "memory_provider_adapter_hash": "memory:abc",
        },
        now="2026-04-15T00:00:00Z",
    )

    assert verdict.status == "degraded"
    assert verdict.degrade_reason == "report_expired"


def test_release_gate_evaluator_degrades_on_input_hash_drift() -> None:
    module = importlib.import_module("watchdog.services.brain.release_gate")

    evaluator = module.ReleaseGateEvaluator()
    trace = DecisionTrace(
        trace_id="trace:1",
        session_event_cursor="log_seq:7",
        goal_contract_version="goal-v1",
        policy_ruleset_hash="sha256:policy",
        memory_packet_input_ids=[],
        memory_packet_input_hashes=[],
        provider="provider-a",
        model="model-a",
        prompt_schema_ref="prompt:v1",
        output_schema_ref="schema:v1",
    )
    validator_verdict = DecisionValidationVerdict(status="pass", reason="schema_and_risk_ok")
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
        input_hash="sha256:drifted",
    )

    verdict = evaluator.evaluate(
        brain_intent="propose_execute",
        trace=trace,
        validator_verdict=validator_verdict,
        report=report,
        runtime_contract={
            "risk_policy_version": "risk:v1",
            "decision_input_builder_version": "dib:v1",
            "policy_engine_version": "policy:v1",
            "tool_schema_hash": "tool:abc",
            "memory_provider_adapter_hash": "memory:abc",
        },
        now="2026-04-15T00:00:00Z",
    )

    assert verdict.status == "degraded"
    assert verdict.degrade_reason == "input_hash_mismatch"
