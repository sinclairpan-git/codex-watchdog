from __future__ import annotations

import importlib


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
