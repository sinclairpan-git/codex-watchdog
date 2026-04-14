from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

from watchdog.services.brain.models import DecisionTrace
from watchdog.services.brain.release_gate import (
    DEFAULT_RUNTIME_CONTRACT_SURFACE_REF,
    DEFAULT_RUNTIME_GATE_REASON_TAXONOMY,
)
from watchdog.services.brain.validator import DecisionValidationVerdict


def _runtime_governance_fields() -> dict[str, object]:
    return {
        "runtime_contract_surface_ref": DEFAULT_RUNTIME_CONTRACT_SURFACE_REF,
        "runtime_gate_reason_taxonomy": DEFAULT_RUNTIME_GATE_REASON_TAXONOMY,
    }


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
        **_runtime_governance_fields(),
    )

    assert report.decision_input_builder_version == "dib:v1"
    assert report.policy_engine_version == "policy:v1"
    assert report.report_approved_by == "operator-a"
    assert (
        report.runtime_contract_surface_ref
        == DEFAULT_RUNTIME_CONTRACT_SURFACE_REF
    )
    assert report.runtime_gate_reason_taxonomy.validator_bucket == "validator_degraded"


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


def test_generate_release_gate_report_script_embeds_runtime_governance_contract(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "generate_release_gate_report.py"
    packets = root / "tests" / "fixtures" / "release_gate_packets.jsonl"
    shadow_runs = root / "tests" / "fixtures" / "release_gate_shadow_runs.jsonl"
    label_manifest = root / "tests" / "fixtures" / "release_gate_label_manifest.json"
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

    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert (
        payload["runtime_contract_surface_ref"]
        == DEFAULT_RUNTIME_CONTRACT_SURFACE_REF
    )
    assert payload["runtime_gate_reason_taxonomy"] == DEFAULT_RUNTIME_GATE_REASON_TAXONOMY


def test_parse_release_gate_report_rejects_governance_contract_drift() -> None:
    module = importlib.import_module("watchdog.services.brain.release_gate")

    payload = {
        "report_id": "report-1",
        "report_hash": "sha256:report",
        "sample_window": "2026-04-01..2026-04-07",
        "shadow_window": "2026-04-08..2026-04-09",
        "label_manifest": "tests/fixtures/release_gate_label_manifest.json",
        "generated_by": "codex",
        "report_approved_by": "operator-a",
        "artifact_ref": "tests/fixtures/release_gate_expected_report.json",
        "expires_at": "2026-05-01T00:00:00Z",
        "provider": "provider-a",
        "model": "model-a",
        "prompt_schema_ref": "prompt:v1",
        "output_schema_ref": "schema:v1",
        "risk_policy_version": "risk:v1",
        "decision_input_builder_version": "dib:v1",
        "policy_engine_version": "policy:v1",
        "tool_schema_hash": "tool:abc",
        "memory_provider_adapter_hash": "memory:abc",
        "input_hash": "sha256:input",
        "runtime_contract_surface_ref": "custom.builder",
        "runtime_gate_reason_taxonomy": DEFAULT_RUNTIME_GATE_REASON_TAXONOMY,
    }

    with pytest.raises(ValueError, match="runtime_contract_surface_ref"):
        module.parse_release_gate_report(payload)

    payload["runtime_contract_surface_ref"] = DEFAULT_RUNTIME_CONTRACT_SURFACE_REF
    payload["runtime_gate_reason_taxonomy"] = {
        **DEFAULT_RUNTIME_GATE_REASON_TAXONOMY,
        "fallback_bucket": "unexpected",
    }

    with pytest.raises(ValueError, match="runtime_gate_reason_taxonomy"):
        module.parse_release_gate_report(payload)


def test_parse_release_gate_report_rejects_defaulted_governance_metadata() -> None:
    module = importlib.import_module("watchdog.services.brain.release_gate")

    payload = {
        "report_id": "report-1",
        "report_hash": "sha256:report",
        "sample_window": "2026-04-01..2026-04-07",
        "shadow_window": "2026-04-08..2026-04-09",
        "label_manifest": "tests/fixtures/release_gate_label_manifest.json",
        "generated_by": "codex",
        "report_approved_by": "operator-a",
        "artifact_ref": "tests/fixtures/release_gate_expected_report.json",
        "expires_at": "2026-05-01T00:00:00Z",
        "provider": "provider-a",
        "model": "model-a",
        "prompt_schema_ref": "prompt:v1",
        "output_schema_ref": "schema:v1",
        "risk_policy_version": "risk:v1",
        "decision_input_builder_version": "dib:v1",
        "policy_engine_version": "policy:v1",
        "tool_schema_hash": "tool:abc",
        "memory_provider_adapter_hash": "memory:abc",
        "input_hash": "sha256:input",
        "runtime_contract_surface_ref": DEFAULT_RUNTIME_CONTRACT_SURFACE_REF,
        "runtime_gate_reason_taxonomy": {
            key: value
            for key, value in DEFAULT_RUNTIME_GATE_REASON_TAXONOMY.items()
            if key != "raw_reason_labels_forbidden"
        },
    }

    with pytest.raises(ValueError, match="runtime_gate_reason_taxonomy"):
        module.parse_release_gate_report(payload)


def test_parse_release_gate_report_rejects_non_object_payload() -> None:
    module = importlib.import_module("watchdog.services.brain.release_gate")

    with pytest.raises(ValueError, match="JSON object"):
        module.parse_release_gate_report([])


def test_parse_release_gate_report_rejects_python_equal_but_json_drifted_taxonomy() -> None:
    module = importlib.import_module("watchdog.services.brain.release_gate")

    payload = {
        "report_id": "report-1",
        "report_hash": "sha256:report",
        "sample_window": "2026-04-01..2026-04-07",
        "shadow_window": "2026-04-08..2026-04-09",
        "label_manifest": "tests/fixtures/release_gate_label_manifest.json",
        "generated_by": "codex",
        "report_approved_by": "operator-a",
        "artifact_ref": "tests/fixtures/release_gate_expected_report.json",
        "expires_at": "2026-05-01T00:00:00Z",
        "provider": "provider-a",
        "model": "model-a",
        "prompt_schema_ref": "prompt:v1",
        "output_schema_ref": "schema:v1",
        "risk_policy_version": "risk:v1",
        "decision_input_builder_version": "dib:v1",
        "policy_engine_version": "policy:v1",
        "tool_schema_hash": "tool:abc",
        "memory_provider_adapter_hash": "memory:abc",
        "input_hash": "sha256:input",
        "runtime_contract_surface_ref": DEFAULT_RUNTIME_CONTRACT_SURFACE_REF,
        "runtime_gate_reason_taxonomy": {
            **DEFAULT_RUNTIME_GATE_REASON_TAXONOMY,
            "raw_reason_labels_forbidden": 1,
        },
    }

    with pytest.raises(ValueError, match="runtime_gate_reason_taxonomy"):
        module.parse_release_gate_report(payload)


def test_release_gate_loading_module_exports_shared_loader_surface() -> None:
    assert (
        importlib.util.find_spec("watchdog.services.brain.release_gate_loading")
        is not None
    )

    module = importlib.import_module("watchdog.services.brain.release_gate_loading")

    assert hasattr(module, "LoadedReleaseGateArtifacts")
    assert hasattr(module, "load_release_gate_artifacts")


def test_release_gate_shared_loader_rejects_report_hash_drift(tmp_path: Path) -> None:
    loading = importlib.import_module("watchdog.services.brain.release_gate_loading")
    report = {
        "report_id": "report-1",
        "report_hash": "sha256:seed",
        "sample_window": "2026-04-01..2026-04-07",
        "shadow_window": "2026-04-08..2026-04-09",
        "label_manifest": "tests/fixtures/release_gate_label_manifest.json",
        "generated_by": "codex",
        "report_approved_by": "operator-a",
        "artifact_ref": "tests/fixtures/release_gate_expected_report.json",
        "expires_at": "2026-05-01T00:00:00Z",
        "provider": "provider-a",
        "model": "model-a",
        "prompt_schema_ref": "prompt:v1",
        "output_schema_ref": "schema:v1",
        "risk_policy_version": "risk:v1",
        "decision_input_builder_version": "dib:v1",
        "policy_engine_version": "policy:v1",
        "tool_schema_hash": "tool:abc",
        "memory_provider_adapter_hash": "memory:abc",
        "input_hash": "sha256:input",
        **_runtime_governance_fields(),
    }
    canonical = json.dumps(report, sort_keys=True, separators=(",", ":"))
    report["report_hash"] = f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"
    report["generated_by"] = "tampered-codex"
    report_path = tmp_path / "release_gate_report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(ValueError, match="report_hash"):
        loading.load_release_gate_artifacts(
            report_path=str(report_path),
            runtime_contract={
                "risk_policy_version": "risk:v1",
                "decision_input_builder_version": "dib:v1",
                "policy_engine_version": "policy:v1",
                "tool_schema_hash": "tool:abc",
                "memory_provider_adapter_hash": "memory:abc",
            },
            certification_packet_corpus_ref="tests/fixtures/release_gate_packets.jsonl",
            shadow_decision_ledger_ref="tests/fixtures/release_gate_shadow_runs.jsonl",
        )


def test_release_gate_report_material_module_exports_shared_contract() -> None:
    assert (
        importlib.util.find_spec("watchdog.services.brain.release_gate_report_material")
        is not None
    )

    module = importlib.import_module("watchdog.services.brain.release_gate_report_material")

    assert hasattr(module, "canonicalize_release_gate_report_material")
    assert hasattr(module, "build_release_gate_report_id")
    assert hasattr(module, "stable_release_gate_report_hash")


def test_release_gate_report_material_helpers_rebuild_fixture_and_loader_hash() -> None:
    root = Path(__file__).resolve().parents[1]
    module = importlib.import_module("watchdog.services.brain.release_gate_report_material")
    loading = importlib.import_module("watchdog.services.brain.release_gate_loading")
    fixture_path = root / "tests" / "fixtures" / "release_gate_expected_report.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))

    material = module.canonicalize_release_gate_report_material(payload)

    assert "report_hash" not in material
    assert module.build_release_gate_report_id(payload) == payload["report_id"]
    assert module.stable_release_gate_report_hash(payload) == payload["report_hash"]

    loaded = loading.load_release_gate_artifacts(
        report_path=str(fixture_path),
        runtime_contract={
            "risk_policy_version": payload["risk_policy_version"],
            "decision_input_builder_version": payload["decision_input_builder_version"],
            "policy_engine_version": payload["policy_engine_version"],
            "tool_schema_hash": payload["tool_schema_hash"],
            "memory_provider_adapter_hash": payload["memory_provider_adapter_hash"],
        },
        certification_packet_corpus_ref="tests/fixtures/release_gate_packets.jsonl",
        shadow_decision_ledger_ref="tests/fixtures/release_gate_shadow_runs.jsonl",
    )

    assert loaded.raw_payload_hash == module.stable_release_gate_report_hash(payload)


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
        **_runtime_governance_fields(),
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
        **_runtime_governance_fields(),
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
        **_runtime_governance_fields(),
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
