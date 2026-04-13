from __future__ import annotations

import importlib
import json
from pathlib import Path


def test_release_gate_evidence_module_exports_frozen_evidence_types() -> None:
    module = importlib.import_module("watchdog.services.brain.release_gate_evidence")

    assert hasattr(module, "CertificationPacketCorpus")
    assert hasattr(module, "ShadowDecisionLedger")
    assert hasattr(module, "ReleaseGateEvidenceBundle")


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
