from __future__ import annotations

import importlib
import json
from pathlib import Path


def test_release_gate_evidence_module_exports_frozen_evidence_types() -> None:
    module = importlib.import_module("watchdog.services.brain.release_gate_evidence")

    assert hasattr(module, "CertificationPacketCorpus")
    assert hasattr(module, "ShadowDecisionLedger")
    assert hasattr(module, "ReleaseGateEvidenceBundle")


def test_release_gate_evidence_bundle_carries_formal_governance_metadata() -> None:
    module = importlib.import_module("watchdog.services.brain.release_gate_evidence")

    bundle = module.ReleaseGateEvidenceBundle(
        certification_packet_corpus=module.CertificationPacketCorpus(
            artifact_ref="artifacts/certification-packets.jsonl"
        ),
        shadow_decision_ledger=module.ShadowDecisionLedger(
            artifact_ref="artifacts/shadow-ledger.jsonl"
        ),
        release_gate_report_ref="artifacts/release-gate-report.json",
        label_manifest_ref="tests/fixtures/release_gate_label_manifest.json",
        generated_by="codex",
        report_approved_by="operator-a",
        report_id="report:2026-04-14",
        report_hash="sha256:report",
        input_hash="sha256:input",
    )

    dumped = bundle.model_dump(mode="json")

    assert dumped["label_manifest_ref"] == "tests/fixtures/release_gate_label_manifest.json"
    assert dumped["generated_by"] == "codex"
    assert dumped["report_approved_by"] == "operator-a"
    assert dumped["report_id"] == "report:2026-04-14"
    assert dumped["report_hash"] == "sha256:report"
    assert dumped["input_hash"] == "sha256:input"


def test_future_worker_trace_ref_is_declarative_only() -> None:
    models = importlib.import_module("watchdog.services.brain.models")

    ref = models.FutureWorkerTraceRef(
        parent_session_id="session:repo-a",
        worker_task_ref="worker:task-1",
        scope="read_only",
        allowed_hands=["codex"],
        input_packet_refs=["packet:1"],
        retrieval_handles=["handle:1"],
        distilled_summary_ref="summary:1",
        decision_trace_ref="trace:1",
    )

    dumped = ref.model_dump(mode="json")

    assert dumped["decision_trace_ref"] == "trace:1"
    assert "command_id" not in dumped
    assert "approval_mutation" not in dumped
    assert "goal_contract_patch" not in dumped


def test_release_gate_fixtures_are_checked_in() -> None:
    root = Path(__file__).resolve().parents[1]
    packets = root / "tests" / "fixtures" / "release_gate_packets.jsonl"
    shadow_runs = root / "tests" / "fixtures" / "release_gate_shadow_runs.jsonl"
    expected_report = root / "tests" / "fixtures" / "release_gate_expected_report.json"
    label_manifest = root / "tests" / "fixtures" / "release_gate_label_manifest.json"

    assert packets.exists()
    assert shadow_runs.exists()
    assert expected_report.exists()
    assert label_manifest.exists()

    expected = json.loads(expected_report.read_text(encoding="utf-8"))
    labels = json.loads(label_manifest.read_text(encoding="utf-8"))

    assert expected["label_manifest"] == "tests/fixtures/release_gate_label_manifest.json"
    assert expected["artifact_ref"] == "tests/fixtures/release_gate_expected_report.json"
    assert (
        expected["runtime_contract_surface_ref"]
        == "watchdog.settings.Settings.build_runtime_contract"
    )
    assert expected["runtime_gate_reason_taxonomy"]["validator_reasons"] == [
        "memory_conflict",
        "memory_unavailable",
        "goal_contract_not_ready",
        "validator_missing",
        "validator_blocked",
    ]
    assert expected["runtime_gate_reason_taxonomy"]["contract_mismatch_suffix"] == "_mismatch"
    assert expected["runtime_gate_reason_taxonomy"]["validator_bucket"] == "validator_degraded"
    assert expected["runtime_gate_reason_taxonomy"]["fallback_bucket"] == "unknown"
    assert labels["generated_by"] == "codex"
    assert labels["report_approved_by"] == "operator-a"


def test_release_gate_runbook_documents_scripted_artifacts_and_manual_splicing_ban() -> None:
    root = Path(__file__).resolve().parents[1]
    runbook = root / "docs" / "operations" / "release-gate-runbook.md"

    assert runbook.exists()
    contents = runbook.read_text(encoding="utf-8")

    assert "scripts/generate_release_gate_report.py" in contents
    assert "label_manifest" in contents
    assert "generated_by" in contents
    assert "report_approved_by" in contents
    assert "artifact_ref" in contents
    assert "禁止人工拼接" in contents


def test_release_gate_runbook_documents_runtime_contract_surface_and_reason_taxonomy() -> None:
    root = Path(__file__).resolve().parents[1]
    runbook = root / "docs" / "operations" / "release-gate-runbook.md"

    assert runbook.exists()
    contents = runbook.read_text(encoding="utf-8")

    assert "Settings.build_runtime_contract" in contents
    assert "provider / replay / resident runtime" in contents
    assert "禁止调用方手写 runtime contract" in contents

    assert "approval_stale" in contents
    assert "report_expired" in contents
    assert "report_load_failed" in contents
    assert "input_hash_mismatch" in contents
    assert "validator_degraded" in contents
    assert "memory_conflict" in contents
    assert "memory_unavailable" in contents
    assert "goal_contract_not_ready" in contents
    assert "validator_missing" in contents
    assert "validator_blocked" in contents
    assert "contract_mismatch" in contents
    assert "unknown" in contents
    assert "禁止直接把 raw degrade_reason" in contents


def test_release_gate_runbook_documents_runtime_load_time_validation() -> None:
    root = Path(__file__).resolve().parents[1]
    runbook = root / "docs" / "operations" / "release-gate-runbook.md"

    assert runbook.exists()
    contents = runbook.read_text(encoding="utf-8")

    assert "parse_release_gate_report" in contents
    assert "JSON object" in contents
    assert "canonical JSON contract" in contents
    assert "report_load_failed" in contents


def test_release_gate_runbook_documents_single_refresh_command_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    runbook = root / "docs" / "operations" / "release-gate-runbook.md"

    assert runbook.exists()
    contents = runbook.read_text(encoding="utf-8")

    assert "scripts/refresh_release_gate_artifacts.py" in contents
    assert "archive rebuild" in contents
    assert "fixture regeneration" in contents
    assert "唯一正式命令" in contents
    assert "禁止人工编辑 JSON" in contents
