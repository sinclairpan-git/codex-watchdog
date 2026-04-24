from __future__ import annotations

import asyncio
import hashlib
import importlib
import inspect
import json
import threading
import time
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from _polling import wait_until, wait_until_async
from watchdog.main import _run_delivery_loop, _run_session_spine_refresh_loop, create_app
from watchdog.contracts.session_spine.enums import ActionStatus, Effect, ReplyCode
from watchdog.contracts.session_spine.models import ApprovalProjection, WatchdogActionResult
from watchdog.services.brain.models import DecisionIntent, DecisionTrace
from watchdog.services.brain.release_gate import (
    DEFAULT_RUNTIME_CONTRACT_SURFACE_REF,
    DEFAULT_RUNTIME_GATE_REASON_TAXONOMY,
    ReleaseGateEvaluator,
    ReleaseGateVerdict,
)
from watchdog.services.brain.release_gate_loading import load_release_gate_artifacts
from watchdog.services.approvals.service import materialize_canonical_approval
from watchdog.services.delivery.models import DeliveryAttemptResult
from watchdog.services.future_worker.models import FutureWorkerExecutionRequest
from watchdog.services.goal_contract.service import GoalContractService
from watchdog.services.policy.decisions import (
    CanonicalDecisionRecord,
    build_canonical_decision_record,
)
from watchdog.services.resident_experts.models import ResidentExpertRuntimeBinding
from watchdog.services.policy.engine import evaluate_persisted_session_policy
from watchdog.services.session_spine.orchestrator import (
    ResidentOrchestrationOutcome,
    ResidentOrchestrator,
    _parse_iso,
)
from watchdog.services.session_spine.runtime import SessionSpineRuntime
from watchdog.services.session_spine.service import (
    SessionReadBundle,
    _directory_bundle_is_active,
    _directory_task_with_projected_active_state,
    build_approval_inbox_bundle,
    build_session_read_bundle,
)
from watchdog.services.session_spine.store import SessionSpineStore
from watchdog.settings import Settings


SESSION_SPINE_STORE_FILENAME = "session_spine.json"


class FakeResidentAClient:
    def __init__(
        self,
        *,
        task: dict[str, object],
        approvals: list[dict[str, object]] | None = None,
        workspace_activity: dict[str, object] | None = None,
    ) -> None:
        self._task = dict(task)
        self._approvals = [dict(approval) for approval in approvals or []]
        self._workspace_activity = dict(workspace_activity or {})

    def list_tasks(self) -> list[dict[str, object]]:
        return [dict(self._task)]

    def get_envelope(self, project_id: str) -> dict[str, object]:
        assert project_id == self._task["project_id"]
        return {"success": True, "data": dict(self._task)}

    def list_approvals(
        self,
        *,
        status: str | None = None,
        project_id: str | None = None,
        decided_by: str | None = None,
        callback_status: str | None = None,
    ) -> list[dict[str, object]]:
        _ = (decided_by, callback_status)
        rows = [dict(approval) for approval in self._approvals]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if project_id:
            rows = [row for row in rows if row.get("project_id") == project_id]
        return rows

    def get_workspace_activity_envelope(
        self,
        project_id: str,
        *,
        recent_minutes: int = 15,
    ) -> dict[str, object]:
        assert project_id == self._task["project_id"]
        activity = {
            "cwd_exists": True,
            "files_scanned": 0,
            "latest_mtime_iso": None,
            "recent_change_count": 0,
            "recent_window_minutes": recent_minutes,
        }
        activity.update(self._workspace_activity)
        return {
            "success": True,
            "data": {
                "project_id": project_id,
                "activity": activity,
            },
        }


class CyclingResidentAClient(FakeResidentAClient):
    def __init__(self, *, tasks: list[dict[str, object]]) -> None:
        super().__init__(task=tasks[0])
        self._tasks = [dict(task) for task in tasks]
        self._calls = 0

    def list_tasks(self) -> list[dict[str, object]]:
        idx = min(self._calls, len(self._tasks) - 1)
        self._calls += 1
        return [dict(self._tasks[idx])]

    def get_envelope(self, project_id: str) -> dict[str, object]:
        tasks = self.list_tasks()
        assert len(tasks) == 1
        task = tasks[0]
        assert project_id == task["project_id"]
        return {"success": True, "data": dict(task)}

    def trigger_handoff(
        self,
        project_id: str,
        *,
        reason: str,
        continuation_packet: dict[str, object] | None = None,
    ) -> dict[str, object]:
        _ = continuation_packet
        raise AssertionError("trigger_handoff should not be called in this fixture")

    def trigger_resume(
        self,
        project_id: str,
        *,
        mode: str,
        handoff_summary: str,
        continuation_packet: dict[str, object] | None = None,
    ) -> dict[str, object]:
        _ = continuation_packet
        raise AssertionError("trigger_resume should not be called in this fixture")


class RecoveringResidentAClient(FakeResidentAClient):
    def __init__(self, *, task: dict[str, object]) -> None:
        super().__init__(task=task)
        self.handoff_calls: list[tuple[str, str]] = []
        self.resume_calls: list[tuple[str, str, str]] = []

    def trigger_handoff(
        self,
        project_id: str,
        *,
        reason: str,
        continuation_packet: dict[str, object] | None = None,
    ) -> dict[str, object]:
        _ = continuation_packet
        self.handoff_calls.append((project_id, reason))
        return {
            "success": True,
            "data": {"handoff_file": f"/tmp/{project_id}.handoff.md", "summary": "handoff"},
        }

    def trigger_resume(
        self,
        project_id: str,
        *,
        mode: str,
        handoff_summary: str,
        continuation_packet: dict[str, object] | None = None,
    ) -> dict[str, object]:
        _ = continuation_packet
        self.resume_calls.append((project_id, mode, handoff_summary))
        return {
            "success": True,
            "data": {"project_id": project_id, "status": "running", "mode": mode},
        }


def _bind_dual_resident_experts(app, *, observed_at: str) -> None:
    app.state.resident_expert_runtime_service.bind_runtime_handle(
        expert_id="managed-agent-expert",
        runtime_handle="agent:managed:1",
        observed_at=observed_at,
    )
    app.state.resident_expert_runtime_service.bind_runtime_handle(
        expert_id="hermes-agent-expert",
        runtime_handle="agent:hermes:1",
        observed_at=observed_at,
    )


class UniqueRecoveryResidentAClient(RecoveringResidentAClient):
    def __init__(self, *, task: dict[str, object]) -> None:
        super().__init__(task=task)
        self._handoff_seq = 0

    def trigger_handoff(
        self,
        project_id: str,
        *,
        reason: str,
        continuation_packet: dict[str, object] | None = None,
    ) -> dict[str, object]:
        _ = continuation_packet
        self._handoff_seq += 1
        self.handoff_calls.append((project_id, reason))
        return {
            "success": True,
            "data": {
                "handoff_file": f"/tmp/{project_id}.{self._handoff_seq}.handoff.md",
                "summary": "handoff",
            },
        }


class HandoffLoopResidentAClient(FakeResidentAClient):
    def __init__(self, *, task: dict[str, object]) -> None:
        super().__init__(task=task)
        self.handoff_calls: list[tuple[str, str]] = []

    def trigger_handoff(
        self,
        project_id: str,
        *,
        reason: str,
        continuation_packet: dict[str, object] | None = None,
    ) -> dict[str, object]:
        _ = continuation_packet
        self.handoff_calls.append((project_id, reason))
        self._task.update(
            {
                "status": "handoff_in_progress",
                "phase": "handoff",
                "last_summary": "handoff drafted",
                "context_pressure": "critical",
                "stuck_level": 4,
                "failure_count": 3,
            }
        )
        return {
            "success": True,
            "data": {
                "handoff_file": f"/tmp/{project_id}.handoff.md",
                "summary": "handoff",
            },
        }

    def trigger_resume(
        self,
        project_id: str,
        *,
        mode: str,
        handoff_summary: str,
        continuation_packet: dict[str, object] | None = None,
    ) -> dict[str, object]:
        _ = continuation_packet
        raise AssertionError("trigger_resume should not be called when auto resume is disabled")


class MultiProjectResidentAClient:
    def __init__(
        self,
        *,
        tasks: list[dict[str, object]],
        approvals: list[dict[str, object]],
    ) -> None:
        self._tasks = [dict(task) for task in tasks]
        self._approvals = [dict(approval) for approval in approvals]
        self.list_approvals_calls: list[tuple[str | None, str | None, str | None]] = []

    def list_tasks(self) -> list[dict[str, object]]:
        return [dict(task) for task in self._tasks]

    def get_envelope(self, project_id: str) -> dict[str, object]:
        for task in self._tasks:
            if task.get("project_id") == project_id:
                return {"success": True, "data": dict(task)}
        raise AssertionError(f"unexpected project_id: {project_id}")

    def list_approvals(
        self,
        *,
        status: str | None = None,
        project_id: str | None = None,
        decided_by: str | None = None,
        callback_status: str | None = None,
    ) -> list[dict[str, object]]:
        self.list_approvals_calls.append((status, project_id, callback_status))
        rows = [dict(approval) for approval in self._approvals]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if project_id:
            rows = [row for row in rows if row.get("project_id") == project_id]
        if decided_by:
            rows = [row for row in rows if row.get("decided_by") == decided_by]
        if callback_status:
            rows = [row for row in rows if row.get("callback_status") == callback_status]
        return rows


def test_session_spine_runtime_refresh_all_uses_authoritative_current_task_for_duplicate_project_entries(
    tmp_path: Path,
) -> None:
    class DuplicateProjectClient:
        def __init__(self) -> None:
            self.get_envelope_calls: list[str] = []

        def list_tasks(self) -> list[dict[str, object]]:
            return [
                {
                    "project_id": "Ai_AutoSDLC",
                    "thread_id": "thr_old",
                    "status": "running",
                    "phase": "planning",
                    "context_pressure": "critical",
                    "stuck_level": 4,
                    "failure_count": 0,
                    "last_summary": "stale task snapshot",
                    "files_touched": [],
                    "pending_approval": False,
                    "last_progress_at": "2026-04-22T08:23:07Z",
                },
                {
                    "project_id": "Ai_AutoSDLC",
                    "thread_id": "thr_new",
                    "status": "running",
                    "phase": "editing_source",
                    "context_pressure": "medium",
                    "stuck_level": 0,
                    "failure_count": 0,
                    "last_summary": "authoritative current task",
                    "files_touched": [],
                    "pending_approval": False,
                    "last_progress_at": "2026-04-22T10:45:37Z",
                },
            ]

        def get_envelope(self, project_id: str) -> dict[str, object]:
            self.get_envelope_calls.append(project_id)
            assert project_id == "Ai_AutoSDLC"
            return {
                "success": True,
                "data": {
                    "project_id": "Ai_AutoSDLC",
                    "thread_id": "thr_new",
                    "status": "running",
                    "phase": "editing_source",
                    "context_pressure": "medium",
                    "stuck_level": 0,
                    "failure_count": 0,
                    "last_summary": "authoritative current task",
                    "files_touched": [],
                    "pending_approval": False,
                    "last_progress_at": "2026-04-22T10:45:37Z",
                },
            }

        def list_approvals(
            self,
            *,
            status: str | None = None,
            project_id: str | None = None,
            decided_by: str | None = None,
            callback_status: str | None = None,
        ) -> list[dict[str, object]]:
            _ = (status, project_id, decided_by, callback_status)
            return []

    store = SessionSpineStore(tmp_path / SESSION_SPINE_STORE_FILENAME)
    client = DuplicateProjectClient()
    runtime = SessionSpineRuntime(client=client, store=store)

    runtime.refresh_all()

    record = store.get("Ai_AutoSDLC")
    assert record is not None
    assert record.effective_native_thread_id == "thr_new"
    assert record.progress.activity_phase == "editing_source"
    assert record.progress.context_pressure == "medium"
    assert record.progress.summary == "authoritative current task"
    assert client.get_envelope_calls == ["Ai_AutoSDLC"]


def _runtime_gate_pass_kwargs() -> dict[str, dict[str, object]]:
    return {
        "validator_verdict": {
            "status": "pass",
            "reason": "schema_and_risk_ok",
        },
        "release_gate_verdict": {
            "release_gate_verdict": {
                "status": "pass",
                "decision_trace_ref": "trace:seed",
                "approval_read_ref": "approval:none",
                "report_id": "report-seed",
                "report_hash": "sha256:report-seed",
                "input_hash": "sha256:input-seed",
            },
            "release_gate_evidence_bundle": _formal_release_gate_bundle(
                report_id="report-seed",
                report_hash="sha256:report-seed",
                input_hash="sha256:input-seed",
            ),
        },
    }


def _release_gate_trace() -> DecisionTrace:
    return DecisionTrace(
        trace_id="trace:runtime-report",
        session_event_cursor="cursor:42",
        goal_contract_version="goal:v1",
        policy_ruleset_hash="sha256:policy-rules",
        memory_packet_input_ids=["packet:1"],
        memory_packet_input_hashes=["sha256:packet-1"],
        provider="provider-a",
        model="model-a",
        prompt_schema_ref="prompt:v1",
        output_schema_ref="schema:v1",
    )


def _write_release_gate_report(
    path: Path,
    *,
    trace: DecisionTrace,
    expires_at: str,
) -> dict[str, object]:
    evaluator = ReleaseGateEvaluator()
    report = {
        "report_id": "report:runtime-qualified",
        "sample_window": "2026-04-01/2026-04-05",
        "shadow_window": "2026-04-06/2026-04-07",
        "label_manifest": "manifest:runtime-qualified",
        "generated_by": "tests/runtime",
        "report_approved_by": "qa/runtime",
        "artifact_ref": "artifact://release-gate/runtime-qualified.json",
        "expires_at": expires_at,
        "provider": trace.provider,
        "model": trace.model,
        "prompt_schema_ref": trace.prompt_schema_ref,
        "output_schema_ref": trace.output_schema_ref,
        "risk_policy_version": "risk:v1",
        "decision_input_builder_version": "dib:v1",
        "policy_engine_version": "policy:v1",
        "tool_schema_hash": "tool:abc",
        "memory_provider_adapter_hash": "memory:abc",
        "input_hash": evaluator._input_hash_for_trace(trace),
        "runtime_contract_surface_ref": DEFAULT_RUNTIME_CONTRACT_SURFACE_REF,
        "runtime_gate_reason_taxonomy": DEFAULT_RUNTIME_GATE_REASON_TAXONOMY,
    }
    material = dict(report)
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"))
    report["report_hash"] = f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _runtime_gate_decision(
    *,
    release_gate_verdict: dict[str, object],
    validator_verdict: dict[str, object] | None = None,
) -> CanonicalDecisionRecord:
    return CanonicalDecisionRecord(
        decision_id="decision:runtime-gate",
        decision_key=(
            "session:repo-a|fact-v7|policy-v1|auto_execute_and_notify|"
            "propose_execute|continue_session|"
        ),
        session_id="session:repo-a",
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="thr_native_1",
        approval_id=None,
        action_ref="continue_session",
        trigger="resident_orchestrator",
        brain_intent="propose_execute",
        runtime_disposition="auto_execute_and_notify",
        decision_result="auto_execute_and_notify",
        risk_class="none",
        decision_reason="registered action and complete evidence",
        matched_policy_rules=["registered_action"],
        why_not_escalated="policy_allows_auto_execution",
        why_escalated=None,
        uncertainty_reasons=[],
        policy_version="policy-v1",
        fact_snapshot_version="fact-v7",
        idempotency_key=(
            "session:repo-a|fact-v7|policy-v1|auto_execute_and_notify|"
            "propose_execute|continue_session|"
        ),
        created_at="2099-01-01T00:00:00Z",
        operator_notes=[],
        evidence={
            "validator_verdict": validator_verdict
            or {"status": "pass", "reason": "schema_and_risk_ok"},
            "release_gate_verdict": release_gate_verdict,
        },
    )


def _with_formal_release_gate_bundle(
    decision: CanonicalDecisionRecord,
) -> CanonicalDecisionRecord:
    return decision.model_copy(
        update={
            "evidence": {
                **decision.evidence,
                "release_gate_evidence_bundle": _formal_release_gate_bundle(
                    report_id="report-seed",
                    report_hash="sha256:report-seed",
                    input_hash="sha256:input-seed",
                ),
            }
        }
    )


def _formal_release_gate_bundle(
    *,
    report_id: str,
    report_hash: str,
    input_hash: str,
) -> dict[str, object]:
    return {
        "certification_packet_corpus": {
            "artifact_ref": "artifacts/certification-packets.jsonl"
        },
        "shadow_decision_ledger": {
            "artifact_ref": "artifacts/shadow-ledger.jsonl"
        },
        "release_gate_report_ref": "artifacts/release-gate-report.json",
        "label_manifest_ref": "tests/fixtures/release_gate_label_manifest.json",
        "generated_by": "codex",
        "report_approved_by": "operator-a",
        "report_id": report_id,
        "report_hash": report_hash,
        "input_hash": input_hash,
    }


def test_release_gate_read_contract_runtime_module_exports_typed_surface() -> None:
    module = importlib.import_module("watchdog.services.brain.release_gate_read_contract")

    assert hasattr(module, "ReleaseGateDecisionReadSnapshot")
    assert hasattr(module, "read_release_gate_decision_evidence")


def test_validator_read_contract_runtime_module_exports_typed_surface() -> None:
    module = importlib.import_module("watchdog.services.brain.validator_read_contract")

    assert hasattr(module, "ValidatorDecisionReadSnapshot")
    assert hasattr(module, "read_validator_decision_evidence")


def test_release_gate_write_contract_runtime_module_exports_typed_surface() -> None:
    module = importlib.import_module("watchdog.services.brain.release_gate_write_contract")

    assert hasattr(module, "ReleaseGateRuntimeEvidenceWriteBundle")
    assert hasattr(module, "build_release_gate_runtime_evidence")


def test_session_event_gate_payload_contract_module_exports_surface() -> None:
    module = importlib.import_module(
        "watchdog.services.session_spine.event_gate_payload_contract"
    )

    assert hasattr(module, "build_session_event_gate_payload")


def test_release_gate_write_contract_preserves_loaded_artifact_bundle(
    tmp_path: Path,
) -> None:
    module = importlib.import_module("watchdog.services.brain.release_gate_write_contract")
    report_path = tmp_path / "runtime-release-gate-report.json"
    trace = _release_gate_trace()
    report = _write_release_gate_report(
        report_path,
        trace=trace,
        expires_at="2026-04-20T00:00:00Z",
    )
    loaded_artifacts = load_release_gate_artifacts(
        report_path=str(report_path),
        runtime_contract={
            "runtime_contract_surface_ref": DEFAULT_RUNTIME_CONTRACT_SURFACE_REF,
        },
        certification_packet_corpus_ref="artifacts/certification-packets.jsonl",
        shadow_decision_ledger_ref="artifacts/shadow-ledger.jsonl",
    )
    verdict = ReleaseGateVerdict(
        status="pass",
        decision_trace_ref="trace:seed",
        approval_read_ref="approval:none",
        report_id=report["report_id"],
        report_hash=report["report_hash"],
        input_hash=report["input_hash"],
    )

    payload = module.build_release_gate_runtime_evidence(
        verdict=verdict,
        loaded_artifacts=loaded_artifacts,
        report_path=str(report_path),
        certification_packet_corpus_ref="artifacts/certification-packets.jsonl",
        shadow_decision_ledger_ref="artifacts/shadow-ledger.jsonl",
    )

    assert payload.verdict == verdict
    assert payload.evidence_bundle is not None
    assert payload.evidence_bundle.model_dump(mode="json", exclude_none=True) == (
        loaded_artifacts.evidence_bundle.model_dump(mode="json", exclude_none=True)
    )


def test_release_gate_write_contract_builds_fallback_bundle_without_extra_intent_fields() -> None:
    module = importlib.import_module("watchdog.services.brain.release_gate_write_contract")
    verdict = ReleaseGateVerdict(
        status="degraded",
        decision_trace_ref="trace:seed",
        approval_read_ref="approval:none",
        degrade_reason="report_load_failed",
        report_id="report:load_failed",
        report_hash="sha256:report_load_failed",
        input_hash="sha256:input-seed",
    )

    payload = module.build_release_gate_runtime_evidence(
        verdict=verdict,
        loaded_artifacts=None,
        report_path="artifacts/release-gate-report.json",
        certification_packet_corpus_ref="artifacts/certification-packets.jsonl",
        shadow_decision_ledger_ref="artifacts/shadow-ledger.jsonl",
    )

    assert payload.verdict == verdict
    assert payload.evidence_bundle is not None
    assert payload.evidence_bundle.model_dump(mode="json", exclude_none=True) == {
        "certification_packet_corpus": {
            "artifact_ref": "artifacts/certification-packets.jsonl"
        },
        "shadow_decision_ledger": {
            "artifact_ref": "artifacts/shadow-ledger.jsonl"
        },
        "release_gate_report_ref": "artifacts/release-gate-report.json",
        "report_id": "report:load_failed",
        "report_hash": "sha256:report_load_failed",
        "input_hash": "sha256:input-seed",
    }


def test_resident_orchestrator_rejects_incomplete_pass_release_gate_verdict() -> None:
    decision = _runtime_gate_decision(
        release_gate_verdict={
            "status": "pass",
            "decision_trace_ref": "trace:seed",
            "approval_read_ref": "approval:none",
            "report_id": "report-seed",
            "input_hash": "sha256:input-seed",
        }
    )

    assert ResidentOrchestrator._decision_has_runtime_gate(decision) is False
    assert ResidentOrchestrator._decision_allows_auto_execute(decision) is False


def test_resident_orchestrator_rejects_pass_verdict_without_bundle() -> None:
    decision = _runtime_gate_decision(
        release_gate_verdict={
            "status": "pass",
            "decision_trace_ref": "trace:seed",
            "approval_read_ref": "approval:none",
            "report_id": "report-seed",
            "report_hash": "sha256:report-seed",
            "input_hash": "sha256:input-seed",
        }
    )

    assert ResidentOrchestrator._decision_has_runtime_gate(decision) is False
    assert ResidentOrchestrator._decision_allows_auto_execute(decision) is False


def test_resident_orchestrator_rejects_pass_verdict_with_partial_bundle() -> None:
    decision = _runtime_gate_decision(
        release_gate_verdict={
            "status": "pass",
            "decision_trace_ref": "trace:seed",
            "approval_read_ref": "approval:none",
            "report_id": "report-seed",
            "report_hash": "sha256:report-seed",
            "input_hash": "sha256:input-seed",
        }
    ).model_copy(
        update={
            "evidence": {
                "validator_verdict": {"status": "pass", "reason": "schema_and_risk_ok"},
                "release_gate_verdict": {
                    "status": "pass",
                    "decision_trace_ref": "trace:seed",
                    "approval_read_ref": "approval:none",
                    "report_id": "report-seed",
                    "report_hash": "sha256:report-seed",
                    "input_hash": "sha256:input-seed",
                },
                "release_gate_evidence_bundle": {
                    "release_gate_report_ref": "artifacts/release-gate-report.json",
                    "generated_by": "codex",
                },
            }
        }
    )

    assert ResidentOrchestrator._decision_has_runtime_gate(decision) is False
    assert ResidentOrchestrator._decision_allows_auto_execute(decision) is False


def test_resident_orchestrator_rejects_malformed_pass_validator_verdict() -> None:
    decision = _with_formal_release_gate_bundle(
        _runtime_gate_decision(
            release_gate_verdict={
                "status": "pass",
                "decision_trace_ref": "trace:seed",
                "approval_read_ref": "approval:none",
                "report_id": "report-seed",
                "report_hash": "sha256:report-seed",
                "input_hash": "sha256:input-seed",
            },
            validator_verdict={
                "status": "pass",
                "reason": "schema_and_risk_ok",
                "unexpected": "raw-dict-leak",
            },
        )
    )

    assert ResidentOrchestrator._decision_has_runtime_gate(decision) is False
    assert ResidentOrchestrator._decision_allows_auto_execute(decision) is False


class RecordingDeliveryClient:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def deliver_record(self, record) -> DeliveryAttemptResult:
        self.records.append(dict(record.envelope_payload))
        return DeliveryAttemptResult(
            envelope_id=record.envelope_id,
            delivery_status="delivered",
            accepted=True,
            receipt_id=f"rcpt:{record.envelope_id}",
        )


class FlakyRuntime:
    def __init__(self, delegate) -> None:
        self._delegate = delegate
        self.calls = 0

    def refresh_all(self) -> None:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transient runtime failure")
        self._delegate.refresh_all()


class FlakyOrchestrator:
    def __init__(self, delegate) -> None:
        self._delegate = delegate
        self.calls = 0

    def orchestrate_all(self, *, now):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transient orchestrator failure")
        return self._delegate.orchestrate_all(now=now)


class FlakyDeliveryWorker:
    def __init__(self, delegate) -> None:
        self._delegate = delegate
        self.calls = 0

    def process_next_ready(self, *, now, session_id=None):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transient delivery failure")
        return self._delegate.process_next_ready(now=now, session_id=session_id)


class StaticBrainService:
    def __init__(self, *, intent: str, rationale: str = "test override") -> None:
        self.intent = intent
        self.rationale = rationale

    def evaluate_session(self, **kwargs) -> DecisionIntent:
        _ = kwargs
        return DecisionIntent(intent=self.intent, rationale=self.rationale)


class SpyResidentExpertRuntimeService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def consult_or_restore(
        self,
        *,
        expert_ids: list[str] | None = None,
        consultation_ref: str | None = None,
        observed_runtime_handles: dict[str, str] | None = None,
        consulted_at: str | None = None,
    ) -> list[ResidentExpertRuntimeBinding]:
        self.calls.append(
            {
                "expert_ids": expert_ids,
                "consultation_ref": consultation_ref,
                "observed_runtime_handles": observed_runtime_handles,
                "consulted_at": consulted_at,
            }
        )
        return [
            ResidentExpertRuntimeBinding(
                expert_id="managed-agent-expert",
                charter_source_ref="docs/operations/resident-expert-agents.yaml",
                charter_version_hash="sha256:test",
                status="unavailable",
                last_consulted_at=consulted_at,
                last_consultation_ref=consultation_ref,
            ),
            ResidentExpertRuntimeBinding(
                expert_id="hermes-agent-expert",
                charter_source_ref="docs/operations/resident-expert-agents.yaml",
                charter_version_hash="sha256:test",
                status="unavailable",
                last_consulted_at=consulted_at,
                last_consultation_ref=consultation_ref,
            ),
        ]


def _store_path(root: Path) -> Path:
    return root / SESSION_SPINE_STORE_FILENAME


def _read_store(root: Path) -> dict[str, object]:
    return json.loads(_store_path(root).read_text(encoding="utf-8"))


def test_background_runtime_persists_session_spine_and_keeps_fact_snapshot_version_stable(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "editing files",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2099-01-01T00:00:00Z",
        }
    )

    with TestClient(create_app(settings, runtime_client=a_client, start_background_workers=True)):
        pass

    first_store_path = _store_path(tmp_path)
    assert first_store_path.exists()
    first_snapshot = _read_store(tmp_path)
    first_version = first_snapshot["sessions"]["repo-a"]["fact_snapshot_version"]
    assert first_version
    assert first_snapshot["sessions"]["repo-a"]["session"]["thread_id"] == "session:repo-a"

    with TestClient(create_app(settings, runtime_client=a_client, start_background_workers=True)):
        pass

    second_snapshot = _read_store(tmp_path)
    assert second_snapshot["sessions"]["repo-a"]["fact_snapshot_version"] == first_version


def test_background_runtime_refreshes_session_spine_periodically_and_advances_session_seq(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        session_spine_refresh_interval_seconds=0.01,
    )
    a_client = CyclingResidentAClient(
        tasks=[
            {
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "editing files",
                "files_touched": ["src/example.py"],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2099-01-01T00:00:00Z",
            },
            {
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "waiting_human",
                "phase": "approval",
                "pending_approval": True,
                "approval_risk": "L2",
                "last_summary": "waiting for approval",
                "files_touched": ["src/example.py"],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2099-01-01T00:01:00Z",
            },
        ]
    )
    a_client._approvals = [
        {
            "approval_id": "appr_001",
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "risk_level": "L2",
            "command": "uv run pytest",
            "reason": "verify tests",
            "alternative": "",
            "status": "pending",
            "requested_at": "2099-01-01T00:01:30Z",
        }
    ]

    with TestClient(create_app(settings, runtime_client=a_client, start_background_workers=True)):
        first_snapshot = _read_store(tmp_path)
        first_seq = int(first_snapshot["sessions"]["repo-a"]["session_seq"])
        assert first_seq >= 1

        refreshed_snapshot_holder = {"value": first_snapshot}
        wait_until(
            lambda: (
                refreshed_snapshot_holder.__setitem__("value", _read_store(tmp_path)) is None
                and int(refreshed_snapshot_holder["value"]["sessions"]["repo-a"]["session_seq"])
                > first_seq
            ),
            timeout_s=0.5,
        )
        refreshed_snapshot = refreshed_snapshot_holder["value"]

    if first_snapshot["sessions"]["repo-a"]["session"]["session_state"] != "awaiting_approval":
        assert int(refreshed_snapshot["sessions"]["repo-a"]["session_seq"]) > first_seq
    assert refreshed_snapshot["sessions"]["repo-a"]["session"]["session_state"] == "awaiting_approval"
    assert refreshed_snapshot["sessions"]["repo-a"]["progress"]["activity_phase"] == "approval"


def test_resident_orchestrator_skips_phantom_approval_when_only_pending_flag_is_set(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        progress_summary_max_age_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "waiting_human",
            "phase": "approval",
            "pending_approval": True,
            "last_summary": "waiting for approval",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)

    app.state.session_spine_runtime.refresh_all()
    outcomes = app.state.resident_orchestrator.orchestrate_all(
        now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
    )
    snapshot = _read_store(tmp_path)

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == [None]
    assert snapshot["sessions"]["repo-a"]["session"]["session_state"] == "active"
    assert snapshot["sessions"]["repo-a"]["session"]["pending_approval_count"] == 0
    assert snapshot["sessions"]["repo-a"]["facts"] == []
    assert app.state.delivery_outbox_store.list_records() == []


def test_approval_read_snapshot_uses_session_projection_instead_of_full_approval_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "waiting_human",
            "phase": "approval",
            "pending_approval": True,
            "approval_risk": "L2",
            "last_summary": "waiting for approval",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        approvals=[
            {
                "approval_id": "appr_001",
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "risk_level": "L2",
                "command": "uv run pytest",
                "reason": "verify tests",
                "alternative": "",
                "status": "pending",
                "requested_at": "2026-04-05T05:21:00Z",
            }
        ],
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="require_approval")
    app.state.session_spine_runtime.refresh_all()
    app.state.session_service.record_event_once(
        event_type="approval_requested",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:test:approval:appr_001",
        related_ids={"approval_id": "appr_001"},
        payload={
            "requested_action": "uv run pytest",
            "fact_snapshot_version": "fact-v99",
            "goal_contract_version": "goal-contract:v2",
            "expires_at": "2026-04-05T06:21:00Z",
        },
        occurred_at="2026-04-05T05:21:00Z",
    )
    record = app.state.session_spine_store.get("repo-a")
    assert record is not None

    def _fail_if_full_store_scanned():
        raise AssertionError("approval store list_records should not be used")

    monkeypatch.setattr(app.state.canonical_approval_store, "list_records", _fail_if_full_store_scanned)

    snapshot = app.state.resident_orchestrator._approval_read_snapshot_for_session(record)

    assert snapshot is not None
    assert snapshot.approval_id == "appr_001"
    assert snapshot.approval_event_id.startswith("event:")
    assert snapshot.requested_action == "uv run pytest"
    assert snapshot.fact_snapshot_version == "fact-v99"
    assert snapshot.goal_contract_version == "goal-contract:v2"
    assert snapshot.expires_at == "2026-04-05T06:21:00Z"
    assert snapshot.log_seq is not None


def test_approval_read_snapshot_ignores_locally_superseded_projected_approval(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "waiting_human",
            "phase": "approval",
            "pending_approval": True,
            "approval_risk": "L2",
            "last_summary": "waiting for approval",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        approvals=[
            {
                "approval_id": "appr_001",
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "risk_level": "L2",
                "command": "uv run pytest",
                "reason": "verify tests",
                "alternative": "",
                "status": "pending",
                "requested_at": "2026-04-05T05:21:00Z",
            }
        ],
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()
    app.state.session_service.record_event_once(
        event_type="approval_requested",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:test:approval:appr_001",
        related_ids={"approval_id": "appr_001"},
        payload={
            "requested_action": "uv run pytest",
            "fact_snapshot_version": "fact-v99",
            "goal_contract_version": "goal-contract:v2",
            "expires_at": "2026-04-05T06:21:00Z",
        },
        occurred_at="2026-04-05T05:21:00Z",
    )
    stale_decision = CanonicalDecisionRecord(
        decision_id="decision:repo-a:fact-v99:require_user_decision",
        decision_key="session:repo-a|fact-v99|policy-v1|require_user_decision|continue_session|appr_001",
        session_id="session:repo-a",
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="native:repo-a",
        approval_id="appr_001",
        action_ref="continue_session",
        trigger="resident_orchestrator",
        decision_result="require_user_decision",
        risk_class="human_gate",
        decision_reason="stale approval should be ignored locally",
        matched_policy_rules=["brain_requires_approval"],
        why_not_escalated=None,
        why_escalated="brain intent requires explicit human approval",
        uncertainty_reasons=[],
        policy_version="policy-v1",
        fact_snapshot_version="fact-v99",
        idempotency_key="session:repo-a|fact-v99|policy-v1|require_user_decision|continue_session|appr_001",
        created_at="2026-04-05T05:21:30Z",
        operator_notes=[],
        evidence={
            "decision": {
                "decision_result": "require_user_decision",
                "action_ref": "continue_session",
                "approval_id": "appr_001",
            }
        },
    )
    stale_approval = materialize_canonical_approval(
        stale_decision,
        approval_store=app.state.canonical_approval_store,
    )
    app.state.canonical_approval_store.update(
        stale_approval.model_copy(
            update={
                "status": "superseded",
                "decided_at": "2026-04-05T05:22:00Z",
                "decided_by": "policy-test",
            }
        )
    )
    record = app.state.session_spine_store.get("repo-a")
    assert record is not None

    snapshot = app.state.resident_orchestrator._approval_read_snapshot_for_session(record)

    assert snapshot is None


def test_approval_read_snapshot_uses_locally_pending_canonical_approval_when_projection_empty(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "waiting for local canonical approval",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()
    stale_decision = CanonicalDecisionRecord(
        decision_id="decision:repo-a:fact-v1:require_user_decision:local-only",
        decision_key="session:repo-a|fact-v1|policy-v1|require_user_decision|execute_recovery|appr_001",
        session_id="session:repo-a",
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="native:repo-a",
        approval_id="appr_001",
        action_ref="execute_recovery",
        trigger="resident_orchestrator",
        decision_result="require_user_decision",
        risk_class="human_gate",
        decision_reason="local canonical approval should remain visible",
        matched_policy_rules=["recovery_human_gate"],
        why_not_escalated=None,
        why_escalated="recovery execution requires explicit human decision",
        uncertainty_reasons=[],
        policy_version="policy-v1",
        fact_snapshot_version="fact-v1",
        idempotency_key="session:repo-a|fact-v1|policy-v1|require_user_decision|execute_recovery|appr_001",
        created_at="2026-04-05T05:21:30Z",
        operator_notes=[],
        evidence={
            "decision": {
                "decision_result": "require_user_decision",
                "action_ref": "execute_recovery",
                "approval_id": "appr_001",
            },
            "goal_contract_version": "goal-contract:unknown",
        },
    )
    approval = materialize_canonical_approval(
        stale_decision,
        approval_store=app.state.canonical_approval_store,
        session_service=app.state.session_service,
    )
    record = app.state.session_spine_store.get("repo-a")
    assert record is not None
    assert record.approval_queue == []

    snapshot = app.state.resident_orchestrator._approval_read_snapshot_for_session(record)

    assert snapshot is not None
    assert snapshot.approval_id == approval.approval_id
    assert snapshot.requested_action == "execute_recovery"
    assert snapshot.fact_snapshot_version == "fact-v1"


def test_resident_orchestrator_filters_locally_superseded_projection_before_policy_decision(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": True,
            "approval_risk": "L2",
            "last_summary": "waiting for approval",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        approvals=[
            {
                "approval_id": "appr_001",
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "risk_level": "L2",
                "command": "uv run pytest",
                "reason": "verify tests",
                "alternative": "",
                "status": "pending",
                "requested_at": "2026-04-05T05:21:00Z",
            }
        ],
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="observe_only")
    app.state.session_spine_runtime.refresh_all()
    stale_decision = CanonicalDecisionRecord(
        decision_id="decision:repo-a:fact-v1:require_user_decision",
        decision_key="session:repo-a|fact-v1|policy-v1|require_user_decision|continue_session|appr_001",
        session_id="session:repo-a",
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="native:repo-a",
        approval_id="appr_001",
        action_ref="continue_session",
        trigger="resident_orchestrator",
        decision_result="require_user_decision",
        risk_class="human_gate",
        decision_reason="stale approval should be ignored locally",
        matched_policy_rules=["brain_requires_approval"],
        why_not_escalated=None,
        why_escalated="brain intent requires explicit human approval",
        uncertainty_reasons=[],
        policy_version="policy-v1",
        fact_snapshot_version="fact-v1",
        idempotency_key="session:repo-a|fact-v1|policy-v1|require_user_decision|continue_session|appr_001",
        created_at="2026-04-05T05:21:30Z",
        operator_notes=[],
        evidence={
            "decision": {
                "decision_result": "require_user_decision",
                "action_ref": "continue_session",
                "approval_id": "appr_001",
            }
        },
    )
    stale_approval = materialize_canonical_approval(
        stale_decision,
        approval_store=app.state.canonical_approval_store,
    )
    app.state.canonical_approval_store.update(
        stale_approval.model_copy(
            update={
                "status": "superseded",
                "decided_at": "2026-04-05T05:22:00Z",
                "decided_by": "policy-test",
            }
        )
    )

    outcomes = app.state.resident_orchestrator.orchestrate_all(
        now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
    )

    decisions = app.state.policy_decision_store.list_records()
    approvals = app.state.canonical_approval_store.list_records()

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["block_and_alert"]
    assert len(decisions) == 1
    assert decisions[0].decision_result == "block_and_alert"
    assert decisions[0].approval_id is None
    assert len(approvals) == 1
    assert approvals[0].approval_id == "appr_001"
    assert approvals[0].status == "superseded"


def test_resident_orchestrator_reuses_locally_pending_canonical_approval_when_projection_missing(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "needs explicit recovery approval",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="require_approval")
    app.state.session_spine_runtime.refresh_all()
    prior_decision = CanonicalDecisionRecord(
        decision_id="decision:repo-a:fact-v1:require_user_decision:local-only",
        decision_key="session:repo-a|fact-v1|policy-v1|require_user_decision|continue_session|appr_001",
        session_id="session:repo-a",
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="native:repo-a",
        approval_id="appr_001",
        action_ref="continue_session",
        trigger="resident_orchestrator",
        decision_result="require_user_decision",
        risk_class="human_gate",
        decision_reason="existing local approval should be refreshed in place",
        matched_policy_rules=["brain_requires_approval"],
        why_not_escalated=None,
        why_escalated="brain intent requires explicit human approval",
        uncertainty_reasons=[],
        policy_version="policy-v1",
        fact_snapshot_version="fact-v1",
        idempotency_key="session:repo-a|fact-v1|policy-v1|require_user_decision|continue_session|appr_001",
        created_at="2026-04-05T05:21:30Z",
        operator_notes=[],
        evidence={
            "decision": {
                "decision_result": "require_user_decision",
                "action_ref": "continue_session",
                "approval_id": "appr_001",
            },
            "goal_contract_version": "goal-contract:unknown",
        },
    )
    prior_approval = materialize_canonical_approval(
        prior_decision,
        approval_store=app.state.canonical_approval_store,
        session_service=app.state.session_service,
    )

    outcomes = app.state.resident_orchestrator.orchestrate_all(
        now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
    )

    approvals = app.state.canonical_approval_store.list_records()
    decisions = app.state.policy_decision_store.list_records()

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["require_user_decision"]
    assert len(decisions) == 1
    assert decisions[0].approval_id == prior_approval.approval_id
    assert len(approvals) == 1
    assert approvals[0].approval_id == prior_approval.approval_id
    assert approvals[0].status == "pending"
    assert approvals[0].fact_snapshot_version == decisions[0].fact_snapshot_version
    assert decisions[0].decision_id != prior_decision.decision_id
    approval_events = app.state.session_service.list_events(
        session_id=prior_approval.session_id,
        event_type="approval_requested",
    )
    assert len(approval_events) == 1


def test_resident_orchestrator_remints_approval_when_projected_command_conflicts(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": True,
            "approval_risk": "L2",
            "last_summary": "old recovery approval is still projected",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        approvals=[
            {
                "approval_id": "appr_001",
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "risk_level": "L2",
                "command": "continue_session",
                "reason": "continue with explicit approval",
                "alternative": "",
                "status": "pending",
                "requested_at": "2026-04-05T05:21:00Z",
            }
        ],
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="require_approval")
    app.state.session_spine_runtime.refresh_all()
    prior_decision = CanonicalDecisionRecord(
        decision_id="decision:repo-a:fact-v1:require_user_decision:stale-recovery",
        decision_key="session:repo-a|fact-v1|policy-v1|require_user_decision|execute_recovery|appr_001",
        session_id="session:repo-a",
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="native:repo-a",
        approval_id="appr_001",
        action_ref="execute_recovery",
        trigger="resident_orchestrator",
        decision_result="require_user_decision",
        risk_class="human_gate",
        decision_reason="old recovery approval should not leak into continue-session gate",
        matched_policy_rules=["recovery_human_gate"],
        why_not_escalated=None,
        why_escalated="recovery execution requires explicit human decision",
        uncertainty_reasons=[],
        policy_version="policy-v1",
        fact_snapshot_version="fact-v1",
        idempotency_key="session:repo-a|fact-v1|policy-v1|require_user_decision|execute_recovery|appr_001",
        created_at="2026-04-05T05:21:30Z",
        operator_notes=[],
        evidence={
            "decision": {
                "decision_result": "require_user_decision",
                "action_ref": "execute_recovery",
                "approval_id": "appr_001",
            },
            "goal_contract_version": "goal-contract:unknown",
        },
    )
    materialize_canonical_approval(
        prior_decision,
        approval_store=app.state.canonical_approval_store,
        delivery_outbox_store=app.state.delivery_outbox_store,
        session_service=app.state.session_service,
    )

    outcomes = app.state.resident_orchestrator.orchestrate_all(
        now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
    )

    decisions = app.state.policy_decision_store.list_records()
    approvals = sorted(
        app.state.canonical_approval_store.list_records(),
        key=lambda approval: approval.created_at,
    )
    outbox = sorted(
        app.state.delivery_outbox_store.list_records(),
        key=lambda record: record.outbox_seq,
    )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["require_user_decision"]
    assert len(decisions) == 1
    assert decisions[0].approval_id is None
    assert decisions[0].action_ref == "continue_session"
    assert decisions[0].evidence["decision_trace"]["approval_read"] is None
    assert len(approvals) == 2
    assert approvals[0].approval_id == "appr_001"
    assert approvals[0].requested_action == "execute_recovery"
    assert approvals[0].status == "superseded"
    assert approvals[1].approval_id != "appr_001"
    assert approvals[1].requested_action == "continue_session"
    assert approvals[1].status == "pending"
    assert len(outbox) == 2
    assert outbox[0].envelope_id == approvals[0].envelope_id
    assert outbox[0].delivery_status == "superseded"
    assert outbox[1].envelope_id == approvals[1].envelope_id
    assert outbox[1].delivery_status == "pending"
    approval_events = app.state.session_service.list_events(
        session_id="session:repo-a",
        event_type="approval_requested",
    )
    assert len(approval_events) == 2


def test_resident_orchestrator_ignores_orphaned_stale_canonical_approval_when_runtime_has_none(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
        feishu_interaction_window_seconds=900.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "stale local approval should not block",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        approvals=[],
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    stale_decision = CanonicalDecisionRecord(
        decision_id="decision:repo-a:fact-v1:require_user_decision:stale-approval",
        decision_key="session:repo-a|fact-v1|policy-v1|require_user_decision|continue_session|appr_001",
        session_id="session:repo-a",
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="native:repo-a",
        approval_id="appr_001",
        action_ref="continue_session",
        trigger="resident_orchestrator",
        decision_result="require_user_decision",
        risk_class="human_gate",
        decision_reason="stale continue approval",
        matched_policy_rules=["brain_requires_approval"],
        why_not_escalated=None,
        why_escalated="brain intent requires explicit human approval",
        uncertainty_reasons=[],
        policy_version="policy-v1",
        fact_snapshot_version="fact-v1",
        idempotency_key="session:repo-a|fact-v1|policy-v1|require_user_decision|continue_session|appr_001",
        created_at="2026-04-05T05:21:30Z",
        operator_notes=[],
        evidence={
            "decision": {
                "decision_result": "require_user_decision",
                "action_ref": "continue_session",
                "approval_id": "appr_001",
            }
        },
    )
    approval = materialize_canonical_approval(
        stale_decision,
        approval_store=app.state.canonical_approval_store,
        delivery_outbox_store=app.state.delivery_outbox_store,
        session_service=app.state.session_service,
    )
    app.state.canonical_approval_store.update(
        approval.model_copy(
            update={
                "created_at": "2026-04-05T05:21:30Z",
            }
        )
    )

    record = app.state.session_spine_store.get("repo-a")
    assert record is not None

    assert app.state.resident_orchestrator._canonical_pending_approval_projections(record) == []
    assert app.state.resident_orchestrator._active_approvals(record) == []


def test_resident_orchestrator_blocks_orphaned_runtime_pending_flag_without_reminting_approval(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
        feishu_interaction_window_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "waiting_for_approval",
            "phase": "planning",
            "pending_approval": True,
            "approval_risk": "L2",
            "last_summary": "runtime claims approval is pending but approval list is empty",
            "files_touched": ["src/example.py"],
            "context_pressure": "medium",
            "stuck_level": 4,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        approvals=[],
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    stale_decision = CanonicalDecisionRecord(
        decision_id="decision:repo-a:fact-v1:require_user_decision:orphaned-runtime-pending",
        decision_key="session:repo-a|fact-v1|policy-v1|require_user_decision|continue_session|appr_001",
        session_id="session:repo-a",
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="native:repo-a",
        approval_id="appr_001",
        action_ref="continue_session",
        trigger="resident_orchestrator",
        decision_result="require_user_decision",
        risk_class="human_gate",
        decision_reason="orphaned pending approval should not be reminted",
        matched_policy_rules=["brain_requires_approval"],
        why_not_escalated=None,
        why_escalated="brain intent requires explicit human approval",
        uncertainty_reasons=[],
        policy_version="policy-v1",
        fact_snapshot_version="fact-v1",
        idempotency_key="session:repo-a|fact-v1|policy-v1|require_user_decision|continue_session|appr_001",
        created_at="2026-04-05T05:21:30Z",
        operator_notes=[],
        evidence={
            "decision": {
                "decision_result": "require_user_decision",
                "action_ref": "continue_session",
                "approval_id": "appr_001",
            }
        },
    )
    materialize_canonical_approval(
        stale_decision,
        approval_store=app.state.canonical_approval_store,
        delivery_outbox_store=app.state.delivery_outbox_store,
        session_service=app.state.session_service,
    )
    app.state.session_spine_runtime.refresh_all()

    record = app.state.session_spine_store.get("repo-a")
    assert record is not None
    assert record.approval_queue == []
    assert [fact.fact_code for fact in record.facts] == ["approval_state_unavailable"]

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["block_and_alert"]
    decisions = app.state.policy_decision_store.list_records()
    assert len(decisions) == 1
    assert decisions[0].brain_intent == "observe_only"
    approvals = app.state.canonical_approval_store.list_records()
    assert len(approvals) == 1
    assert approvals[0].approval_id == "appr_001"
    assert approvals[0].status == "superseded"
    steer_mock.assert_not_called()


def test_resident_orchestrator_remints_approval_when_projected_goal_contract_drifts(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": True,
            "approval_risk": "L2",
            "last_summary": "old recovery approval has stale goal truth",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        approvals=[
            {
                "approval_id": "appr_001",
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "risk_level": "L2",
                "command": "execute_recovery",
                "reason": "recover manually",
                "alternative": "",
                "status": "pending",
                "requested_at": "2026-04-05T05:21:00Z",
            }
        ],
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="require_approval")
    app.state.session_spine_runtime.refresh_all()
    prior_decision = CanonicalDecisionRecord(
        decision_id="decision:repo-a:fact-v1:require_user_decision:stale-goal-contract",
        decision_key="session:repo-a|fact-v1|policy-v1|require_user_decision|continue_session|appr_001",
        session_id="session:repo-a",
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="native:repo-a",
        approval_id="appr_001",
        action_ref="continue_session",
        trigger="resident_orchestrator",
        decision_result="require_user_decision",
        risk_class="human_gate",
        decision_reason="old continue-session approval predates current goal contract truth",
        matched_policy_rules=["brain_requires_approval"],
        why_not_escalated=None,
        why_escalated="brain intent requires explicit human approval",
        uncertainty_reasons=[],
        policy_version="policy-v1",
        fact_snapshot_version="fact-v1",
        idempotency_key="session:repo-a|fact-v1|policy-v1|require_user_decision|continue_session|appr_001",
        created_at="2026-04-05T05:21:30Z",
        operator_notes=[],
        evidence={
            "decision": {
                "decision_result": "require_user_decision",
                "action_ref": "continue_session",
                "approval_id": "appr_001",
            }
        },
    )
    materialize_canonical_approval(
        prior_decision,
        approval_store=app.state.canonical_approval_store,
        delivery_outbox_store=app.state.delivery_outbox_store,
        session_service=app.state.session_service,
    )

    outcomes = app.state.resident_orchestrator.orchestrate_all(
        now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
    )

    decisions = app.state.policy_decision_store.list_records()
    approvals = sorted(
        app.state.canonical_approval_store.list_records(),
        key=lambda approval: approval.created_at,
    )
    outbox = sorted(
        app.state.delivery_outbox_store.list_records(),
        key=lambda record: record.outbox_seq,
    )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["require_user_decision"]
    assert len(decisions) == 1
    assert decisions[0].approval_id is None
    assert decisions[0].action_ref == "continue_session"
    assert decisions[0].evidence["decision_trace"]["approval_read"] is None
    assert len(approvals) == 2
    assert approvals[0].approval_id == "appr_001"
    assert approvals[0].goal_contract_version is None
    assert approvals[0].status == "superseded"
    assert approvals[1].approval_id != "appr_001"
    assert approvals[1].requested_action == "continue_session"
    assert approvals[1].goal_contract_version == "goal-contract:unknown"
    assert approvals[1].status == "pending"
    assert len(outbox) == 2
    assert outbox[0].envelope_id == approvals[0].envelope_id
    assert outbox[0].delivery_status == "superseded"
    assert outbox[1].envelope_id == approvals[1].envelope_id
    assert outbox[1].delivery_status == "pending"
    approval_events = app.state.session_service.list_events(
        session_id="session:repo-a",
        event_type="approval_requested",
    )
    assert len(approval_events) == 2


def test_session_spine_runtime_refresh_all_reuses_shared_approval_snapshot(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    a_client = MultiProjectResidentAClient(
        tasks=[
            {
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "waiting_human",
                "phase": "approval",
                "pending_approval": True,
                "approval_risk": "L2",
                "last_summary": "waiting for approval a",
                "files_touched": ["src/a.py"],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2099-01-01T00:00:00Z",
            },
            {
                "project_id": "repo-b",
                "thread_id": "thr_native_2",
                "status": "waiting_human",
                "phase": "approval",
                "pending_approval": True,
                "approval_risk": "L2",
                "last_summary": "waiting for approval b",
                "files_touched": ["src/b.py"],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2099-01-01T00:01:00Z",
            },
        ],
        approvals=[
            {
                "approval_id": "appr_001",
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "risk_level": "L2",
                "command": "uv run pytest repo-a",
                "reason": "verify repo-a",
                "alternative": "",
                "status": "pending",
                "requested_at": "2099-01-01T00:00:30Z",
            },
            {
                "approval_id": "appr_002",
                "project_id": "repo-b",
                "thread_id": "thr_native_2",
                "risk_level": "L2",
                "command": "uv run pytest repo-b",
                "reason": "verify repo-b",
                "alternative": "",
                "status": "pending",
                "requested_at": "2099-01-01T00:01:30Z",
            },
        ],
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)

    app.state.session_spine_runtime.refresh_all()

    records = {
        record.project_id: record for record in app.state.session_spine_store.list_records()
    }

    assert sorted(a_client.list_approvals_calls) == [
        ("approved", None, "deferred"),
        ("pending", None, None),
    ]
    assert sorted(records) == ["repo-a", "repo-b"]
    assert [approval.approval_id for approval in records["repo-a"].approval_queue] == ["appr_001"]
    assert [approval.approval_id for approval in records["repo-b"].approval_queue] == ["appr_002"]


def test_session_spine_runtime_refresh_all_preserves_existing_approval_state_when_project_fetch_fails(
    tmp_path: Path,
) -> None:
    class SharedApprovalFailureClient(MultiProjectResidentAClient):
        def __init__(
            self,
            *,
            tasks: list[dict[str, object]],
            approvals: list[dict[str, object]],
        ) -> None:
            super().__init__(tasks=tasks, approvals=approvals)
            self.fail_shared_approvals = False
            self.fail_project_approvals: set[str] = set()

        def list_approvals(
            self,
            *,
            status: str | None = None,
            project_id: str | None = None,
            decided_by: str | None = None,
            callback_status: str | None = None,
        ) -> list[dict[str, object]]:
            if self.fail_shared_approvals and project_id is None:
                self.list_approvals_calls.append((status, project_id, callback_status))
                raise RuntimeError("shared approvals unavailable")
            if project_id in self.fail_project_approvals:
                self.list_approvals_calls.append((status, project_id, callback_status))
                raise RuntimeError(f"{project_id} approvals unavailable")
            return super().list_approvals(
                status=status,
                project_id=project_id,
                decided_by=decided_by,
                callback_status=callback_status,
            )

    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    a_client = SharedApprovalFailureClient(
        tasks=[
            {
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "waiting_human",
                "phase": "approval",
                "pending_approval": True,
                "approval_risk": "L2",
                "last_summary": "waiting for approval a",
                "files_touched": ["src/a.py"],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2099-01-01T00:00:00Z",
            },
            {
                "project_id": "repo-b",
                "thread_id": "thr_native_2",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "keep coding repo-b",
                "files_touched": ["src/b.py"],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2099-01-01T00:01:00Z",
            },
        ],
        approvals=[
            {
                "approval_id": "appr_001",
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "risk_level": "L2",
                "command": "uv run pytest repo-a",
                "reason": "verify repo-a",
                "alternative": "",
                "status": "pending",
                "requested_at": "2099-01-01T00:00:30Z",
            }
        ],
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)

    app.state.session_spine_runtime.refresh_all()
    initial_records = {
        record.project_id: record for record in app.state.session_spine_store.list_records()
    }
    assert sorted(initial_records) == ["repo-a", "repo-b"]
    assert [approval.approval_id for approval in initial_records["repo-a"].approval_queue] == [
        "appr_001"
    ]
    assert initial_records["repo-b"].approval_queue == []

    a_client._tasks = [
        {
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "waiting_human",
            "phase": "approval",
            "pending_approval": True,
            "approval_risk": "L2",
            "last_summary": "waiting for approval a updated",
            "files_touched": ["src/a.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2099-01-01T00:02:00Z",
        },
        {
            "project_id": "repo-b",
            "thread_id": "thr_native_2",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "keep coding repo-b updated",
            "files_touched": ["src/b.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2099-01-01T00:02:00Z",
        },
    ]
    a_client.fail_shared_approvals = True
    a_client.fail_project_approvals = {"repo-b"}

    records = {
        record.project_id: record for record in app.state.session_spine_store.list_records()
    }

    app.state.session_spine_runtime.refresh_all()

    records = {
        record.project_id: record for record in app.state.session_spine_store.list_records()
    }

    assert sorted(records) == ["repo-a", "repo-b"]
    assert [approval.approval_id for approval in records["repo-a"].approval_queue] == ["appr_001"]
    assert records["repo-a"].session.headline == "waiting for approval a updated"
    assert records["repo-b"].approval_queue == initial_records["repo-b"].approval_queue
    assert records["repo-b"].session.headline == initial_records["repo-b"].session.headline
    assert a_client.list_approvals_calls == [
        ("pending", None, None),
        ("approved", None, "deferred"),
        ("pending", None, None),
        ("pending", "repo-a", None),
        ("approved", "repo-a", "deferred"),
        ("pending", "repo-b", None),
    ]


def test_background_runtime_approval_queue_uses_effective_native_thread_from_legacy_approval_record(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_root_1",
            "status": "waiting_human",
            "phase": "approval",
            "pending_approval": True,
            "last_summary": "waiting for approval",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2099-01-01T00:00:00Z",
        },
        approvals=[],
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    approval = materialize_canonical_approval(
        CanonicalDecisionRecord(
            decision_id="decision:runtime-legacy-approval-queue",
            decision_key=(
                "session:repo-a|fact-v7|policy-v1|require_user_decision|continue_session|appr_legacy"
            ),
            session_id="session:repo-a",
            project_id="repo-a",
            thread_id="session:repo-a",
            native_thread_id="thr_child_1",
            approval_id="appr_legacy",
            action_ref="continue_session",
            trigger="resident_supervision",
            decision_result="require_user_decision",
            risk_class="human_gate",
            decision_reason="explicit human confirmation required",
            matched_policy_rules=["human_gate"],
            why_not_escalated=None,
            why_escalated="manual decision required",
            uncertainty_reasons=[],
            policy_version="policy-v1",
            fact_snapshot_version="fact-v7",
            idempotency_key=(
                "session:repo-a|fact-v7|policy-v1|require_user_decision|continue_session|appr_legacy"
            ),
            created_at="2099-01-01T00:00:10Z",
            operator_notes=[],
            evidence={},
        ),
        approval_store=app.state.canonical_approval_store,
    )
    path = tmp_path / "canonical_approvals.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload[approval.envelope_id]["native_thread_id"] = None
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    app.state.session_spine_runtime.refresh_all()

    record = app.state.session_spine_store.get("repo-a")
    assert record is not None
    snapshot = app.state.resident_orchestrator._approval_read_snapshot_for_session(record)
    assert snapshot is not None
    assert snapshot.approval_id == approval.approval_id
    assert snapshot.effective_native_thread_id == "thr_child_1"


def test_background_runtime_overlays_canonical_pending_approvals_onto_persisted_record(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "runtime task has no visible approvals",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 4,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
        approvals=[],
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    approval = materialize_canonical_approval(
        CanonicalDecisionRecord(
            decision_id="decision:runtime-overlay-approval",
            decision_key=(
                "session:repo-a|fact-v1|policy-v1|require_user_decision|continue_session|"
                "approval:runtime-overlay"
            ),
            session_id="session:repo-a",
            project_id="repo-a",
            thread_id="session:repo-a",
            native_thread_id="thr_native_1",
            approval_id="approval:runtime-overlay",
            action_ref="continue_session",
            trigger="resident_orchestrator",
            decision_result="require_user_decision",
            risk_class="human_gate",
            decision_reason="explicit human confirmation required",
            matched_policy_rules=["brain_requires_approval"],
            why_not_escalated=None,
            why_escalated="manual decision required",
            uncertainty_reasons=[],
            policy_version="policy-v1",
            fact_snapshot_version="fact-v1",
            idempotency_key=(
                "session:repo-a|fact-v1|policy-v1|require_user_decision|continue_session|"
                "approval:runtime-overlay"
            ),
            created_at="2026-04-05T05:21:00Z",
            operator_notes=[],
            evidence={},
        ),
        approval_store=app.state.canonical_approval_store,
        session_service=app.state.session_service,
    )

    app.state.session_spine_runtime.refresh_all()

    record = app.state.session_spine_store.get("repo-a")
    assert record is not None
    assert record.session.pending_approval_count == 1
    assert [approval_row.approval_id for approval_row in record.approval_queue] == [
        approval.approval_id
    ]
    assert {fact.fact_code for fact in record.facts} >= {
        "approval_pending",
        "awaiting_human_direction",
    }


def test_resident_orchestrator_does_not_execute_when_brain_observes_only(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "still stuck",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="observe_only")
    app.state.session_spine_runtime.refresh_all()

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["block_and_alert"]
    decisions = app.state.policy_decision_store.list_records()
    assert len(decisions) == 1
    assert decisions[0].brain_intent == "observe_only"
    outbox = app.state.delivery_outbox_store.list_records()
    assert len(outbox) == 1
    assert outbox[0].envelope_type == "notification"
    assert app.state.canonical_approval_store.list_records() == []
    assert app.state.command_lease_store.list_events() == []
    steer_mock.assert_not_called()


def test_resident_orchestrator_routes_brain_require_approval_to_human_gate(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "still stuck",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="require_approval")
    app.state.session_spine_runtime.refresh_all()

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["require_user_decision"]
    decisions = app.state.policy_decision_store.list_records()
    assert len(decisions) == 1
    assert decisions[0].brain_intent == "require_approval"
    approvals = app.state.canonical_approval_store.list_records()
    assert len(approvals) == 1
    assert approvals[0].requested_action == "continue_session"
    assert app.state.command_lease_store.list_events() == []
    steer_mock.assert_not_called()


def test_resident_orchestrator_auto_executes_brain_proposed_recovery(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "context exhausted",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="propose_recovery")
    app.state.session_spine_runtime.refresh_all()
    recovery_result = WatchdogActionResult(
        action_code="execute_recovery",
        project_id="repo-a",
        approval_id=None,
        idempotency_key="decision:recovery",
        action_status=ActionStatus.COMPLETED,
        effect=Effect.HANDOFF_AND_RESUME,
        reply_code=ReplyCode.RECOVERY_EXECUTION_RESULT,
        message="recovery handoff triggered and resume requested",
        facts=[],
    )

    with patch(
        "watchdog.services.session_spine.orchestrator.execute_canonical_decision",
        return_value=recovery_result,
    ) as execute_mock:
        with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
            outcomes = app.state.resident_orchestrator.orchestrate_all(
                now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
            )

    assert [outcome.action_ref for outcome in outcomes] == ["execute_recovery"]
    assert [outcome.decision_result for outcome in outcomes] == ["auto_execute_and_notify"]
    decisions = app.state.policy_decision_store.list_records()
    assert len(decisions) == 1
    assert decisions[0].brain_intent == "propose_recovery"
    assert decisions[0].runtime_disposition == "auto_execute_and_notify"
    assert app.state.canonical_approval_store.list_records() == []
    execute_mock.assert_called_once()
    assert any(
        record.envelope_type == "notification"
        and record.envelope_payload.get("notification_kind") == "decision_result"
        and record.envelope_payload.get("action_name") == "execute_recovery"
        for record in app.state.delivery_outbox_store.list_records()
    )
    steer_mock.assert_not_called()


def test_resident_orchestrator_routes_brain_suggest_only_to_notification(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "still stuck",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="suggest_only")
    app.state.session_spine_runtime.refresh_all()

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["block_and_alert"]
    decisions = app.state.policy_decision_store.list_records()
    assert len(decisions) == 1
    assert decisions[0].brain_intent == "suggest_only"
    outbox = app.state.delivery_outbox_store.list_records()
    assert len(outbox) == 1
    assert outbox[0].envelope_type == "notification"
    assert app.state.canonical_approval_store.list_records() == []
    assert app.state.command_lease_store.list_events() == []
    steer_mock.assert_not_called()


def test_resident_orchestrator_cooldown_only_suppresses_propose_execute(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=600.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "still stuck",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()
    app.state.resident_orchestration_state_store.put_auto_continue_checkpoint(
        project_id="repo-a",
        last_auto_continue_at="2026-04-07T00:00:00Z",
    )

    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="suggest_only")
    suggest_outcomes = app.state.resident_orchestrator.orchestrate_all(
        now=datetime(2026, 4, 7, 0, 5, 0, tzinfo=UTC)
    )

    app.state.policy_decision_store = type(app.state.policy_decision_store)(
        tmp_path / "policy_decisions_2.json"
    )
    app.state.delivery_outbox_store = type(app.state.delivery_outbox_store)(
        tmp_path / "delivery_outbox_2.json"
    )
    app.state.resident_orchestrator._decision_store = app.state.policy_decision_store
    app.state.resident_orchestrator._delivery_outbox_store = app.state.delivery_outbox_store
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="require_approval")
    require_outcomes = app.state.resident_orchestrator.orchestrate_all(
        now=datetime(2026, 4, 7, 0, 5, 0, tzinfo=UTC)
    )

    assert [outcome.action_ref for outcome in suggest_outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in suggest_outcomes] == ["block_and_alert"]
    assert [outcome.action_ref for outcome in require_outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in require_outcomes] == ["require_user_decision"]


def test_resident_orchestrator_routes_done_session_to_candidate_closure_review(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_done",
            "status": "waiting_human",
            "phase": "done",
            "pending_approval": False,
            "last_summary": "task complete",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)

    app.state.session_spine_runtime.refresh_all()
    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    snapshot = _read_store(tmp_path)
    assert [outcome.action_ref for outcome in outcomes] == ["post_operator_guidance"]
    assert [outcome.decision_result for outcome in outcomes] == ["require_user_decision"]
    assert len(snapshot["sessions"]["repo-a"]["facts"]) == 1
    assert snapshot["sessions"]["repo-a"]["facts"][0]["fact_id"] == "repo-a:task_completed"
    assert snapshot["sessions"]["repo-a"]["facts"][0]["fact_code"] == "task_completed"
    assert snapshot["sessions"]["repo-a"]["facts"][0]["detail"] == (
        "session reached a terminal completed state"
    )
    decisions = app.state.policy_decision_store.list_records()
    assert len(decisions) == 1
    assert decisions[0].brain_intent == "candidate_closure"
    assert decisions[0].runtime_disposition == "require_user_decision"
    assert decisions[0].action_ref == "post_operator_guidance"
    assert "task_completion_candidate" in decisions[0].matched_policy_rules
    approvals = app.state.canonical_approval_store.list_records()
    assert len(approvals) == 1
    assert approvals[0].requested_action == "post_operator_guidance"
    assert steer_mock.call_count == 0


def test_resident_orchestrator_auto_executes_branch_complete_switch_as_operator_guidance(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "completed continuation governance on current branch",
            "files_touched": ["src/watchdog/services/session_spine/orchestrator.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    GoalContractService(app.state.session_service).bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="Model-first continuation governance",
        task_prompt="Build model-first continuation governance for the watchdog.",
        last_user_instruction="Continue landing the next branch routing path.",
        phase="editing_source",
        last_summary="completed continuation governance on current branch",
        current_phase_goal="Land branch-complete routing for the current work item",
        explicit_deliverables=["branch switch governance", "runtime coverage"],
        completion_signals=["branch switch guidance emitted", "targeted tests green"],
        active_goal="Land branch-complete routing for the current work item",
    )

    class StructuredBrainService:
        def evaluate_session(self, **_: object) -> DecisionIntent:
            return DecisionIntent(
                intent="branch_complete_switch",
                rationale="current branch goal is complete",
                continuation_decision="branch_complete_switch",
                routing_preference="next_branch_session",
                next_branch_hypothesis="086-next-branch-routing",
                target_work_item_seq=86,
                branch_switch_token="branch-switch:repo-a:86:fact-v1",
                goal_coverage="complete",
                remaining_work_hypothesis=[],
                provider="openai-compatible",
                model="gpt-5.4",
                prompt_schema_ref="prompt:brain-continuation-decision-v3",
                output_schema_ref="schema:provider-continuation-decision-v3",
                provider_output_schema_ref="schema:provider-continuation-decision-v3",
            )

        def progress_summary_for_decision_context(self, _record: object) -> str:
            return (
                "当前分支目标：Land branch-complete routing for the current work item；"
                "当前阶段：editing_source；当前信号：branch_goal_complete"
            )

    app.state.resident_orchestrator._brain_service = StructuredBrainService()
    _bind_dual_resident_experts(
        app,
        observed_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in outcomes] == ["post_operator_guidance"]
    assert [outcome.decision_result for outcome in outcomes] == ["auto_execute_and_notify"]
    steer_mock.assert_called_once()
    message = steer_mock.call_args.kwargs["message"]
    assert "项目总目标" in message
    assert "Build model-first continuation governance for the watchdog." in message
    assert "当前分支目标" in message
    assert "Land branch-complete routing for the current work item" in message
    assert "当前进度" in message
    assert "当前阶段：editing_source" in message
    assert "当前信号：branch_goal_complete" in message
    assert "后续任务" in message
    assert "086" in message
    assert "086-next-branch-routing" in message
    assert steer_mock.call_args.kwargs["reason"] == "branch_complete_switch"

    approvals = app.state.canonical_approval_store.list_records()
    assert approvals == []
    decisions = app.state.policy_decision_store.list_records()
    assert len(decisions) == 1
    assert decisions[0].brain_intent == "branch_complete_switch"
    assert decisions[0].action_ref == "post_operator_guidance"

    token_issued_events = app.state.session_service.list_events(
        session_id="session:repo-a",
        event_type="branch_switch_token_issued",
    )
    token_consumed_events = app.state.session_service.list_events(
        session_id="session:repo-a",
        event_type="branch_switch_token_consumed",
    )
    assert len(token_issued_events) == 1
    assert len(token_consumed_events) == 1
    assert token_consumed_events[0].related_ids == {
        "branch_switch_token": "branch-switch:repo-a:86:fact-v1",
        "continuation_identity": (
            "repo-a:session:repo-a:thr_native_1:branch_complete_switch"
        ),
        "route_key": (
            "repo-a:session:repo-a:thr_native_1:branch_complete_switch:fact-v1"
        ),
    }
    checkpoint = app.state.resident_orchestration_state_store.get_auto_dispatch_checkpoint(
        project_id="repo-a",
        continuation_identity="repo-a:session:repo-a:thr_native_1:branch_complete_switch",
        route_key="repo-a:session:repo-a:thr_native_1:branch_complete_switch:fact-v1",
    )
    assert checkpoint is not None
    assert checkpoint.status == "completed"


def test_resident_orchestrator_blocks_branch_complete_switch_without_authoritative_target(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "completed continuation governance on current branch",
            "files_touched": ["src/watchdog/services/session_spine/orchestrator.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    GoalContractService(app.state.session_service).bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="Model-first continuation governance",
        task_prompt="Build model-first continuation governance for the watchdog.",
        last_user_instruction="Continue landing the next branch routing path.",
        phase="editing_source",
        last_summary="completed continuation governance on current branch",
        current_phase_goal="Land branch-complete routing for the current work item",
        explicit_deliverables=["branch switch governance", "runtime coverage"],
        completion_signals=["branch switch guidance emitted", "targeted tests green"],
        active_goal="Land branch-complete routing for the current work item",
    )

    class StructuredBrainService:
        def evaluate_session(self, **_: object) -> DecisionIntent:
            return DecisionIntent(
                intent="branch_complete_switch",
                rationale="current branch goal is complete",
                continuation_decision="branch_complete_switch",
                routing_preference="next_branch_session",
                next_branch_hypothesis="",
                goal_coverage="complete",
                remaining_work_hypothesis=[],
                provider="openai-compatible",
                model="gpt-5.4",
                prompt_schema_ref="prompt:brain-continuation-decision-v3",
                output_schema_ref="schema:provider-continuation-decision-v3",
                provider_output_schema_ref="schema:provider-continuation-decision-v3",
            )

    app.state.resident_orchestrator._brain_service = StructuredBrainService()

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in outcomes] == ["post_operator_guidance"]
    assert [outcome.decision_result for outcome in outcomes] == ["block_and_alert"]
    steer_mock.assert_not_called()
    decision = app.state.policy_decision_store.list_records()[0]
    assert "validator_gate_degraded" in decision.matched_policy_rules
    assert decision.uncertainty_reasons == ["action_args_invalid"]


def test_resident_orchestrator_applies_shared_dispatch_cooldown_to_branch_guidance(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=300.0,
    )
    a_client = CyclingResidentAClient(
        tasks=[
            {
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "completed current branch milestone",
                "files_touched": ["src/watchdog/services/session_spine/orchestrator.py"],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T05:20:00Z",
            },
            {
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "completed current branch milestone and refreshed notes",
                "files_touched": ["src/watchdog/services/session_spine/orchestrator.py"],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T05:21:00Z",
            },
            {
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "completed current branch milestone and refreshed notes again",
                "files_touched": ["src/watchdog/services/session_spine/orchestrator.py"],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T05:22:00Z",
            },
        ]
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    GoalContractService(app.state.session_service).bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="Model-first continuation governance",
        task_prompt="Build model-first continuation governance for the watchdog.",
        last_user_instruction="Continue landing the next branch routing path.",
        phase="editing_source",
        last_summary="completed current branch milestone",
        current_phase_goal="Land branch-complete routing for the current work item",
        explicit_deliverables=["branch switch governance", "runtime coverage"],
        completion_signals=["branch switch guidance emitted", "targeted tests green"],
        active_goal="Land branch-complete routing for the current work item",
    )

    class StructuredBrainService:
        def evaluate_session(self, **_: object) -> DecisionIntent:
            return DecisionIntent(
                intent="branch_complete_switch",
                rationale="current branch goal is complete",
                continuation_decision="branch_complete_switch",
                routing_preference="next_branch_session",
                next_branch_hypothesis="086-next-branch-routing",
                target_work_item_seq=86,
                branch_switch_token="branch-switch:repo-a:86:fact-v1",
                goal_coverage="complete",
                remaining_work_hypothesis=[],
                provider="openai-compatible",
                model="gpt-5.4",
                prompt_schema_ref="prompt:brain-continuation-decision-v3",
                output_schema_ref="schema:provider-continuation-decision-v3",
                provider_output_schema_ref="schema:provider-continuation-decision-v3",
            )

    app.state.resident_orchestrator._brain_service = StructuredBrainService()
    _bind_dual_resident_experts(
        app,
        observed_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}

        first = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

        app.state.session_spine_runtime.refresh_all()
        second = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 2, 0, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in first] == ["post_operator_guidance"]
    assert [outcome.decision_result for outcome in first] == ["auto_execute_and_notify"]
    assert [outcome.action_ref for outcome in second] == [None]
    assert [outcome.decision_result for outcome in second] == [None]
    assert steer_mock.call_count == 1


def test_background_runtime_persists_last_local_manual_activity_from_a_side_task(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    app = create_app(
        settings,
        runtime_client=FakeResidentAClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "editing files",
                "files_touched": ["src/example.py"],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2099-01-01T00:00:00Z",
                "last_local_manual_activity_at": "2026-04-07T00:05:00Z",
            }
        ),
        start_background_workers=False,
    )

    app.state.session_spine_runtime.refresh_all()
    snapshot = _read_store(tmp_path)

    assert snapshot["sessions"]["repo-a"]["last_local_manual_activity_at"] == (
        "2026-04-07T00:05:00Z"
    )


def test_resident_orchestrator_suppresses_auto_continue_during_recent_local_manual_activity(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
        local_manual_activity_auto_execute_quiet_window_seconds=600.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "editing files locally",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
            "last_local_manual_activity_at": "2026-04-06T23:55:30Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="propose_execute")
    app.state.session_spine_runtime.refresh_all()

    with patch("watchdog.services.session_spine.orchestrator.execute_canonical_decision") as execute_mock:
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in outcomes] == [None]
    assert [outcome.decision_result for outcome in outcomes] == [None]
    assert app.state.policy_decision_store.list_records() == []
    execute_mock.assert_not_called()
    gate_events = app.state.session_service.list_events(
        session_id="session:repo-a",
        event_type="continuation_gate_evaluated",
    )
    assert gate_events == []


def test_session_spine_runtime_uses_recent_workspace_activity_as_manual_activity_fallback(
    tmp_path: Path,
) -> None:
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        runtime_client=FakeResidentAClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "editing locally without new chat input",
                "files_touched": ["src/example.py"],
                "context_pressure": "low",
                "stuck_level": 2,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T05:20:00Z",
                "last_local_manual_activity_at": None,
            },
            workspace_activity={
                "cwd_exists": True,
                "files_scanned": 12,
                "latest_mtime_iso": "2026-04-06T23:55:30Z",
                "recent_change_count": 3,
            },
        ),
        start_background_workers=False,
    )

    app.state.session_spine_runtime.refresh_all()
    record = app.state.session_spine_store.get("repo-a")

    assert record is not None
    assert record.last_local_manual_activity_at == "2026-04-06T23:55:30Z"


def test_session_spine_runtime_uses_newer_workspace_mtime_even_without_recent_change_count(
    tmp_path: Path,
) -> None:
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        runtime_client=FakeResidentAClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "workspace moved ahead of runtime progress",
                "files_touched": [],
                "context_pressure": "low",
                "stuck_level": 2,
                "failure_count": 0,
                "last_progress_at": "2026-04-22T14:25:26.841551+00:00",
                "last_local_manual_activity_at": None,
            },
            workspace_activity={
                "cwd_exists": True,
                "files_scanned": 500,
                "latest_mtime_iso": "2026-04-23T03:59:16.049808+00:00",
                "recent_change_count": 0,
            },
        ),
        start_background_workers=False,
    )

    app.state.session_spine_runtime.refresh_all()
    record = app.state.session_spine_store.get("repo-a")

    assert record is not None
    assert record.last_local_manual_activity_at == "2026-04-23T03:59:16.049808+00:00"


def test_resident_orchestrator_suppresses_auto_continue_when_recent_workspace_activity_indicates_manual_work(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
        local_manual_activity_auto_execute_quiet_window_seconds=600.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "editing files locally",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
            "last_local_manual_activity_at": None,
        },
        workspace_activity={
            "cwd_exists": True,
            "files_scanned": 12,
            "latest_mtime_iso": "2026-04-06T23:55:30Z",
            "recent_change_count": 3,
        },
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="propose_execute")
    app.state.session_spine_runtime.refresh_all()

    with patch("watchdog.services.session_spine.orchestrator.execute_canonical_decision") as execute_mock:
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in outcomes] == [None]
    assert [outcome.decision_result for outcome in outcomes] == [None]
    assert app.state.policy_decision_store.list_records() == []
    execute_mock.assert_not_called()


def test_session_spine_runtime_pauses_project_when_workspace_cwd_is_missing(
    tmp_path: Path,
) -> None:
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        runtime_client=FakeResidentAClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "workspace missing",
                "files_touched": [],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-23T02:20:49Z",
                "last_local_manual_activity_at": None,
            },
            workspace_activity={
                "cwd_exists": False,
                "files_scanned": 0,
                "latest_mtime_iso": None,
                "recent_change_count": 0,
            },
        ),
        start_background_workers=False,
    )

    app.state.session_spine_runtime.refresh_all()
    record = app.state.session_spine_store.get("repo-a")

    assert record is not None
    assert record.session.session_state == "blocked"
    assert {fact.fact_code for fact in record.facts} == {"project_not_active"}


def test_session_spine_runtime_pauses_project_when_workspace_mtime_is_stale_relative_to_runtime_progress(
    tmp_path: Path,
) -> None:
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        runtime_client=FakeResidentAClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "handoff",
                "pending_approval": False,
                "last_summary": "runtime progress is newer than any real workspace activity",
                "files_touched": [],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-22T13:01:11.938008+00:00",
                "last_local_manual_activity_at": "2026-03-26T08:54:44.400Z",
            },
            workspace_activity={
                "cwd_exists": True,
                "files_scanned": 189,
                "latest_mtime_iso": "2026-03-26T08:57:16.598350+00:00",
                "recent_change_count": 0,
            },
        ),
        start_background_workers=False,
    )

    app.state.session_spine_runtime.refresh_all()
    record = app.state.session_spine_store.get("repo-a")

    assert record is not None
    assert record.session.session_state == "blocked"
    assert {fact.fact_code for fact in record.facts} == {"project_not_active"}


def test_directory_active_filter_uses_task_execution_state_when_facts_are_event_only() -> None:
    bundle = SessionReadBundle(
        project_id="repo-a",
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "project_execution_state": "paused",
        },
        approvals=[],
        facts=[],
        session=None,  # type: ignore[arg-type]
        progress=None,  # type: ignore[arg-type]
        approval_queue=[],
    )

    assert _directory_bundle_is_active(bundle) is False


def test_projected_directory_active_state_ignores_watchdog_generated_handoff_progress() -> None:
    task = {
        "project_id": "repo-a",
        "thread_id": "session:repo-a",
        "status": "running",
        "phase": "handoff",
        "last_progress_at": "2026-04-22T13:00:00Z",
        "last_local_manual_activity_at": "2026-04-09T12:00:00Z",
        "last_substantive_user_input_at": "2026-04-09T12:30:00Z",
    }

    updated = _directory_task_with_projected_active_state(task)

    assert updated is not None
    assert updated["project_execution_state"] == "active"
    assert updated["last_progress_at"] == "2026-04-09T12:30:00Z"


def test_session_spine_runtime_reconciles_missing_persisted_project_via_workspace_liveness(
    tmp_path: Path,
) -> None:
    seed_store = SessionSpineStore(tmp_path / SESSION_SPINE_STORE_FILENAME)
    seed_runtime = SessionSpineRuntime(
        client=FakeResidentAClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "handoff",
                "pending_approval": False,
                "last_summary": "runtime still thinks the task is alive",
                "files_touched": [],
                "context_pressure": "medium",
                "stuck_level": 4,
                "failure_count": 0,
                "last_progress_at": "2026-04-22T13:01:11.938008+00:00",
                "last_local_manual_activity_at": "2026-03-26T08:54:44.400Z",
            }
        ),
        store=seed_store,
    )
    seed_runtime.refresh_all()

    seeded_record = seed_store.get("repo-a")
    assert seeded_record is not None
    assert {fact.fact_code for fact in seeded_record.facts} == {
        "stuck_no_progress",
        "recovery_available",
    }

    class MissingRuntimeTaskClient:
        def list_tasks(self) -> list[dict[str, object]]:
            return []

        def list_approvals(
            self,
            *,
            status: str | None = None,
            project_id: str | None = None,
            decided_by: str | None = None,
            callback_status: str | None = None,
        ) -> list[dict[str, object]]:
            _ = (status, project_id, decided_by, callback_status)
            return []

        def get_workspace_activity_envelope(
            self,
            project_id: str,
            *,
            recent_minutes: int = 15,
        ) -> dict[str, object]:
            assert project_id == "repo-a"
            return {
                "success": True,
                "data": {
                    "project_id": project_id,
                    "activity": {
                        "cwd_exists": True,
                        "files_scanned": 189,
                        "latest_mtime_iso": "2026-03-26T08:57:16.598350+00:00",
                        "recent_change_count": 0,
                        "recent_window_minutes": recent_minutes,
                    },
                },
            }

    reconcile_runtime = SessionSpineRuntime(client=MissingRuntimeTaskClient(), store=seed_store)
    reconcile_runtime.refresh_all()

    reconciled_record = seed_store.get("repo-a")
    assert reconciled_record is not None
    assert reconciled_record.session.session_state == "blocked"
    assert {fact.fact_code for fact in reconciled_record.facts} == {"project_not_active"}


def test_session_spine_runtime_refresh_all_uses_direct_project_fetch_when_task_list_omits_project(
    tmp_path: Path,
) -> None:
    store = SessionSpineStore(tmp_path / SESSION_SPINE_STORE_FILENAME)
    seed_runtime = SessionSpineRuntime(
        client=FakeResidentAClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "stale persisted summary",
                "files_touched": ["src/example.py"],
                "context_pressure": "critical",
                "stuck_level": 4,
                "failure_count": 3,
                "last_progress_at": "2026-04-22T13:01:11.938008+00:00",
            }
        ),
        store=store,
    )
    seed_runtime.refresh_all()

    class MissingFromTaskListClient:
        def list_tasks(self) -> list[dict[str, object]]:
            return [
                {
                    "project_id": "repo-b",
                    "thread_id": "thr_native_2",
                    "status": "running",
                    "phase": "planning",
                    "pending_approval": False,
                    "last_summary": "other task",
                    "files_touched": [],
                    "context_pressure": "low",
                    "stuck_level": 0,
                    "failure_count": 0,
                    "last_progress_at": "2026-04-24T03:00:00Z",
                }
            ]

        def get_envelope(self, project_id: str) -> dict[str, object]:
            assert project_id == "repo-a"
            return {
                "success": True,
                "data": {
                    "project_id": "repo-a",
                    "thread_id": "thr_native_1",
                    "status": "resuming",
                    "phase": "handoff",
                    "pending_approval": False,
                    "last_summary": "live recovery is still in progress",
                    "files_touched": [],
                    "context_pressure": "critical",
                    "stuck_level": 4,
                    "failure_count": 0,
                    "last_progress_at": "2026-04-24T03:00:00Z",
                },
            }

        def list_approvals(
            self,
            *,
            status: str | None = None,
            project_id: str | None = None,
            decided_by: str | None = None,
            callback_status: str | None = None,
        ) -> list[dict[str, object]]:
            _ = (status, project_id, decided_by, callback_status)
            return []

        def get_workspace_activity_envelope(
            self,
            project_id: str,
            *,
            recent_minutes: int = 15,
        ) -> dict[str, object]:
            return {
                "success": True,
                "data": {
                    "project_id": project_id,
                    "activity": {
                        "cwd_exists": True,
                        "files_scanned": 0,
                        "latest_mtime_iso": None,
                        "recent_change_count": 0,
                        "recent_window_minutes": recent_minutes,
                    },
                },
            }

    reconcile_runtime = SessionSpineRuntime(client=MissingFromTaskListClient(), store=store)
    reconcile_runtime.refresh_all()

    reconciled_record = store.get("repo-a")
    assert reconciled_record is not None
    assert reconciled_record.session.session_state == "active"
    assert reconciled_record.progress.summary == "live recovery is still in progress"
    assert reconciled_record.progress.last_progress_at == "2026-04-24T03:00:00Z"
    assert reconciled_record.facts == []


def test_session_spine_runtime_pauses_project_when_only_stale_substantive_input_remains(
    tmp_path: Path,
) -> None:
    app = create_app(
        Settings(
            api_token="wt",
            codex_runtime_token="at",
            codex_runtime_base_url="http://a.test",
            data_dir=str(tmp_path),
        ),
        runtime_client=FakeResidentAClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "handoff",
                "pending_approval": False,
                "last_summary": "stale runtime progress is masking a dead workspace",
                "files_touched": [],
                "context_pressure": "medium",
                "stuck_level": 4,
                "failure_count": 0,
                "last_progress_at": "2026-04-22T13:01:11.938008+00:00",
                "last_local_manual_activity_at": "2026-03-26T08:54:44.400Z",
                "last_substantive_user_input_at": "2026-04-09T12:40:42.376Z",
            },
            workspace_activity={
                "cwd_exists": True,
                "files_scanned": 189,
                "latest_mtime_iso": "2026-03-26T08:57:16.598350+00:00",
                "recent_change_count": 0,
            },
        ),
        start_background_workers=False,
    )

    app.state.session_spine_runtime.refresh_all()
    record = app.state.session_spine_store.get("repo-a")

    assert record is not None
    assert record.session.session_state == "blocked"
    assert {fact.fact_code for fact in record.facts} == {"project_not_active"}


def test_resident_orchestrator_suppresses_auto_recovery_during_recent_local_manual_activity(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
        local_manual_activity_auto_execute_quiet_window_seconds=600.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "context exhausted but user is still actively editing",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
            "last_local_manual_activity_at": "2026-04-06T23:55:30Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="propose_recovery")
    app.state.session_spine_runtime.refresh_all()

    with patch("watchdog.services.session_spine.orchestrator.execute_canonical_decision") as execute_mock:
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in outcomes] == [None]
    assert [outcome.decision_result for outcome in outcomes] == [None]
    assert app.state.policy_decision_store.list_records() == []
    execute_mock.assert_not_called()
    gate_events = app.state.session_service.list_events(
        session_id="session:repo-a",
        event_type="continuation_gate_evaluated",
    )
    assert gate_events == []


def test_resident_orchestrator_marks_recently_idle_presence_without_suppressing_auto_continue(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
        local_manual_activity_auto_execute_quiet_window_seconds=600.0,
        local_manual_activity_recently_idle_window_seconds=1800.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "local work paused a little while ago",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 1,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
            "last_local_manual_activity_at": "2026-04-06T23:45:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="propose_execute")
    app.state.session_spine_runtime.refresh_all()
    record = app.state.session_spine_store.get("repo-a")
    assert record is not None

    orchestrator = app.state.resident_orchestrator
    brain_intent = orchestrator._evaluate_brain_intent(record)
    action_ref = orchestrator._action_ref_for_brain_intent(record, brain_intent.intent)
    assert action_ref == "continue_session"
    assert (
        orchestrator._local_manual_activity_suppression_details(
            record,
            brain_intent=brain_intent,
            action_ref=action_ref,
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC),
        )
        is None
    )
    requested_action_args = orchestrator._requested_action_args_for_intent(
        record,
        brain_intent=brain_intent,
    )
    trusted_record = orchestrator._record_with_trustworthy_approval_identity(
        record,
        action_ref=action_ref,
        requested_action_args=requested_action_args,
        goal_contract_version=orchestrator._goal_contract_version_for_record(record),
        policy_version="policy-v1",
    )
    intent_evidence = orchestrator._decision_evidence_for_intent(
        trusted_record,
        brain_intent=brain_intent,
        action_ref=action_ref,
        requested_action_args=requested_action_args,
        goal_contract_readiness=orchestrator._goal_contract_readiness_for_record(record),
        now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC),
    )

    assert intent_evidence["human_presence"] == {
        "state": "human_recently_idle",
        "last_local_manual_activity_at": "2026-04-06T23:45:00Z",
        "idle_seconds": 900,
        "active_window_seconds": 600,
        "recently_idle_window_seconds": 1800,
    }
    assert (
        intent_evidence["continuation_governance"]["human_presence_state"]
        == "human_recently_idle"
    )


def test_resident_orchestrator_maps_propose_recovery_to_request_recovery_when_execute_recovery_unavailable(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "session looks stuck and may need recovery",
            "files_touched": ["src/example.py"],
            "context_pressure": "medium",
            "stuck_level": 3,
            "failure_count": 1,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()
    record = app.state.session_spine_store.get("repo-a")
    assert record is not None

    record = record.model_copy(
        update={
            "session": record.session.model_copy(
                update={
                    "available_intents": [
                        "get_session",
                        "continue_session",
                        "request_recovery",
                    ]
                }
            )
        }
    )

    action_ref = app.state.resident_orchestrator._action_ref_for_brain_intent(
        record,
        "propose_recovery",
    )

    assert action_ref == "request_recovery"


def test_resident_orchestrator_keeps_pending_approval_requested_action_for_require_approval(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "session is waiting on a recovery approval",
            "files_touched": ["src/example.py"],
            "context_pressure": "medium",
            "stuck_level": 3,
            "failure_count": 1,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()
    record = app.state.session_spine_store.get("repo-a")
    assert record is not None

    record = record.model_copy(
        update={
            "approval_queue": [
                ApprovalProjection(
                    approval_id="appr_recovery",
                    project_id="repo-a",
                    thread_id="session:repo-a",
                    native_thread_id="thr_native_1",
                    risk_level="L1",
                    command="request_recovery",
                    reason="need explicit approval before recovery guidance",
                    alternative="",
                    status="pending",
                    requested_at="2026-04-07T00:00:00Z",
                )
            ],
            "session": record.session.model_copy(update={"pending_approval_count": 1}),
        }
    )

    action_ref = app.state.resident_orchestrator._action_ref_for_brain_intent(
        record,
        "require_approval",
    )

    assert action_ref == "request_recovery"


def test_background_runtime_auto_executes_context_critical_recovery(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        recover_auto_resume=True,
        session_spine_refresh_interval_seconds=0.01,
        resident_orchestrator_interval_seconds=0.01,
        progress_summary_interval_seconds=0.0,
    )
    a_client = UniqueRecoveryResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "context exhausted",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2099-01-01T00:00:00Z",
        }
    )
    delivery_client = RecordingDeliveryClient()
    app = create_app(settings, runtime_client=a_client, start_background_workers=True)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="propose_recovery")
    app.state.delivery_worker._delivery_client = delivery_client

    with TestClient(app):
        assert wait_until(
            lambda: any(
                record.get("envelope_type") == "notification"
                and record.get("notification_kind") == "decision_result"
                and record.get("action_name") == "execute_recovery"
                and record.get("decision_result") == "auto_execute_and_notify"
                for record in delivery_client.records
            ),
            timeout_s=0.5,
        )

    assert a_client.handoff_calls == [("repo-a", "context_critical")]
    assert a_client.resume_calls == [("repo-a", "resume_or_new_thread", "")]
    assert any(
        record.get("envelope_type") == "notification"
        and record.get("notification_kind") == "decision_result"
        and record.get("action_name") == "execute_recovery"
        and record.get("decision_result") == "auto_execute_and_notify"
        for record in delivery_client.records
    )
    assert not any(
        record.get("envelope_type") == "approval"
        and record.get("requested_action") == "execute_recovery"
        for record in delivery_client.records
    )


def test_background_runtime_does_not_repeat_recovery_while_handoff_is_in_progress(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        recover_auto_resume=False,
        session_spine_refresh_interval_seconds=0.01,
        resident_orchestrator_interval_seconds=0.01,
        progress_summary_interval_seconds=0.0,
    )
    a_client = HandoffLoopResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "context exhausted",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2099-01-01T00:00:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=True)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="propose_recovery")

    with TestClient(app):
        assert wait_until(
            lambda: a_client.handoff_calls == [("repo-a", "context_critical")],
            timeout_s=0.5,
        )

    assert a_client.handoff_calls == [("repo-a", "context_critical")]


def test_resident_orchestrator_does_not_rearm_recovery_without_newer_progress_after_completed_recovery(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        recover_auto_resume=False,
        auto_continue_cooldown_seconds=0.0,
        auto_recovery_cooldown_seconds=0.0,
    )
    a_client = UniqueRecoveryResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "context exhausted again",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_service.record_recovery_execution(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        parent_native_thread_id="thr_native_1",
        recovery_reason="context_critical",
        failure_family="context_pressure",
        failure_signature="critical",
        handoff={
            "handoff_file": "/tmp/repo-a.handoff.md",
            "summary": "handoff",
        },
        resume={
            "project_id": "repo-a",
            "status": "running",
            "mode": "resume_or_new_thread",
            "thread_id": "thr_native_1",
        },
        resume_outcome="same_thread_resume",
    )
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="propose_recovery")
    app.state.session_spine_runtime.refresh_all()

    first = app.state.resident_orchestrator.orchestrate_all(
        now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
    )
    second = app.state.resident_orchestrator.orchestrate_all(
        now=datetime(2026, 4, 7, 0, 5, 0, tzinfo=UTC)
    )

    assert a_client.handoff_calls == []
    assert [outcome.decision_result for outcome in first] == [None]
    assert [outcome.decision_result for outcome in second] == [None]
    suppressed_events = app.state.session_service.list_events(
        session_id="session:repo-a",
        event_type="recovery_execution_suppressed",
    )
    assert len(suppressed_events) == 1
    assert suppressed_events[0].payload["suppression_reason"] == "reentry_without_newer_progress"
    assert suppressed_events[0].payload["suppression_source"] == "resident_orchestrator"
    assert suppressed_events[0].related_ids["recovery_transaction_id"].startswith("recovery-tx:")


def test_resident_orchestrator_can_rearm_recovery_after_newer_progress_than_last_recovery(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        recover_auto_resume=False,
        auto_continue_cooldown_seconds=0.0,
        auto_recovery_cooldown_seconds=0.0,
    )
    a_client = UniqueRecoveryResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "context exhausted again",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2099-01-01T00:00:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_service.record_recovery_execution(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        parent_native_thread_id="thr_native_1",
        recovery_reason="context_critical",
        failure_family="context_pressure",
        failure_signature="critical",
        handoff={
            "handoff_file": "/tmp/repo-a.handoff.md",
            "summary": "handoff",
        },
        resume={
            "project_id": "repo-a",
            "status": "running",
            "mode": "resume_or_new_thread",
            "thread_id": "thr_native_1",
        },
        resume_outcome="same_thread_resume",
    )
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="propose_recovery")
    app.state.session_spine_runtime.refresh_all()

    app.state.resident_orchestrator.orchestrate_all(
        now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
    )

    assert a_client.handoff_calls == [("repo-a", "context_critical")]


def test_resident_orchestrator_treats_preflight_recovery_dispatch_as_in_flight(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        recover_auto_resume=False,
        auto_continue_cooldown_seconds=0.0,
        auto_recovery_cooldown_seconds=0.0,
    )
    a_client = UniqueRecoveryResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "context exhausted again",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_service.record_event_once(
        event_type="recovery_dispatch_started",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:recovery-dispatch:repo-a:fact-v1",
        occurred_at="2026-04-07T00:00:00Z",
        related_ids={"native_thread_id": "thr_native_1"},
        payload={
            "decision_source": "recovery_guard",
            "decision_class": "recover_current_branch",
            "context_pressure": "critical",
            "authoritative_snapshot_version": "fact-v1",
            "snapshot_epoch": "session-seq:1",
            "recovery_reason": "context_critical",
            "failure_signature": "critical",
            "last_progress_at": "2026-04-05T05:20:00Z",
        },
    )
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="propose_recovery")
    app.state.session_spine_runtime.refresh_all()

    outcomes = app.state.resident_orchestrator.orchestrate_all(
        now=datetime(2026, 4, 7, 0, 5, 0, tzinfo=UTC)
    )

    assert a_client.handoff_calls == []
    assert [outcome.decision_result for outcome in outcomes] == [None]
    suppressed_events = app.state.session_service.list_events(
        session_id="session:repo-a",
        event_type="recovery_execution_suppressed",
    )
    assert len(suppressed_events) == 1
    assert suppressed_events[0].payload["suppression_reason"] == "recovery_in_flight"


def test_resident_orchestrator_applies_cooldown_to_repeated_auto_recovery(
    tmp_path: Path,
) -> None:
    base_now = datetime.now(UTC).replace(microsecond=0)
    first_progress_at = base_now.isoformat().replace("+00:00", "Z")
    second_progress_at = (base_now + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        recover_auto_resume=False,
        auto_continue_cooldown_seconds=0.0,
        auto_recovery_cooldown_seconds=300.0,
    )
    a_client = CyclingResidentAClient(
        tasks=[
            {
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "context exhausted",
                "files_touched": ["src/example.py"],
                "context_pressure": "critical",
                "stuck_level": 2,
                "failure_count": 3,
                "last_progress_at": first_progress_at,
            },
            {
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "context exhausted again shortly after resume",
                "files_touched": ["src/example.py"],
                "context_pressure": "critical",
                "stuck_level": 2,
                "failure_count": 3,
                "last_progress_at": second_progress_at,
            },
        ]
    )
    handoff_calls: list[tuple[str, str]] = []

    def _trigger_handoff(
        project_id: str,
        *,
        reason: str,
        continuation_packet: dict[str, object] | None = None,
    ) -> dict[str, object]:
        _ = continuation_packet
        handoff_calls.append((project_id, reason))
        return {
            "success": True,
            "data": {"handoff_file": f"/tmp/{project_id}.handoff.md", "summary": "handoff"},
        }

    a_client.trigger_handoff = _trigger_handoff  # type: ignore[attr-defined]
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="propose_recovery")

    app.state.session_spine_runtime.refresh_all()
    first = app.state.resident_orchestrator.orchestrate_all(
        now=base_now
    )

    app.state.session_spine_runtime.refresh_all()
    second = app.state.resident_orchestrator.orchestrate_all(
        now=base_now + timedelta(minutes=2)
    )

    assert handoff_calls == [("repo-a", "context_critical")]
    assert [outcome.action_ref for outcome in first] == ["execute_recovery"]
    assert [outcome.action_ref for outcome in second] == [None]
    suppressed_events = app.state.session_service.list_events(
        session_id="session:repo-a",
        event_type="recovery_execution_suppressed",
    )
    assert len(suppressed_events) == 1
    assert suppressed_events[0].payload["suppression_reason"] == "cooldown_window_active"
    assert suppressed_events[0].payload["suppression_source"] == "resident_orchestrator"
    assert suppressed_events[0].payload["cooldown_seconds"] == "300"
    gate_events = app.state.session_service.list_events(
        session_id="session:repo-a",
        event_type="continuation_gate_evaluated",
    )
    suppressed_gate_events = [
        event
        for event in gate_events
        if event.payload.get("suppression_reason") == "cooldown_window_active"
    ]
    assert len(suppressed_gate_events) == 1
    assert suppressed_gate_events[0].payload["gate_status"] == "suppressed"
    assert app.state.session_service.list_events(
        session_id="session:repo-a",
        event_type="continuation_replay_invalidated",
    ) == []


def test_resident_orchestrator_applies_cooldown_after_recent_recovery_inflight_suppression(
    tmp_path: Path,
) -> None:
    base_now = datetime.now(UTC).replace(microsecond=0)
    progress_at = base_now.isoformat().replace("+00:00", "Z")
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        recover_auto_resume=False,
        auto_continue_cooldown_seconds=0.0,
        auto_recovery_cooldown_seconds=300.0,
    )
    a_client = UniqueRecoveryResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "context exhausted",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": progress_at,
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="propose_recovery")
    app.state.session_spine_runtime.refresh_all()
    app.state.session_service.record_event_once(
        event_type="recovery_execution_suppressed",
        project_id="repo-a",
        session_id="session:repo-a",
        correlation_id="corr:recent-recovery-suppression",
        payload={
            "suppression_reason": "recovery_in_flight",
            "suppression_source": "resident_orchestrator",
        },
        occurred_at=base_now.isoformat().replace("+00:00", "Z"),
    )

    outcomes = app.state.resident_orchestrator.orchestrate_all(
        now=base_now + timedelta(minutes=2)
    )

    assert a_client.handoff_calls == []
    assert [outcome.action_ref for outcome in outcomes] == [None]
    suppressed_events = app.state.session_service.list_events(
        session_id="session:repo-a",
        event_type="recovery_execution_suppressed",
    )
    assert suppressed_events[-1].payload["suppression_reason"] == "cooldown_window_active"


def test_resident_orchestrator_records_new_recovery_suppression_event_when_state_version_changes(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    a_client = UniqueRecoveryResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "context exhausted",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()
    record = app.state.session_spine_store.get("repo-a")
    assert record is not None

    app.state.resident_orchestrator._record_recovery_reentry_suppressed(
        record,
        details={
            "recovery_transaction_id": "txn-1",
            "recovery_status": "running",
            "recovery_updated_at": "2026-04-07T00:00:00Z",
            "last_progress_at": "2026-04-05T05:20:00Z",
            "suppression_reason": "recovery_in_flight",
        },
    )
    app.state.resident_orchestrator._record_recovery_reentry_suppressed(
        record,
        details={
            "recovery_transaction_id": "txn-1",
            "recovery_status": "running",
            "recovery_updated_at": "2026-04-07T00:00:05Z",
            "last_progress_at": "2026-04-05T05:20:00Z",
            "suppression_reason": "recovery_in_flight",
        },
    )

    suppressed_events = app.state.session_service.list_events(
        session_id="session:repo-a",
        event_type="recovery_execution_suppressed",
    )
    gate_events = app.state.session_service.list_events(
        session_id="session:repo-a",
        event_type="continuation_gate_evaluated",
    )
    assert len(suppressed_events) == 2
    assert [event.payload["recovery_updated_at"] for event in suppressed_events] == [
        "2026-04-07T00:00:00Z",
        "2026-04-07T00:00:05Z",
    ]
    suppressed_gate_events = [
        event for event in gate_events if event.payload.get("gate_kind") == "recovery_execution"
    ]
    assert len(suppressed_gate_events) == 2


def test_resident_orchestrator_allows_recovery_suppression_gate_replay_after_fact_version_changes(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    a_client = UniqueRecoveryResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "context exhausted",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()
    record = app.state.session_spine_store.get("repo-a")
    assert record is not None

    details = {
        "recovery_transaction_id": "txn-1",
        "recovery_status": "running",
        "recovery_updated_at": "2026-04-07T00:00:00Z",
        "last_progress_at": "2026-04-05T05:20:00Z",
        "suppression_reason": "recovery_in_flight",
        "source_packet_id": "packet:handoff-v9",
    }
    app.state.resident_orchestrator._record_recovery_reentry_suppressed(record, details=details)

    mutated_facts = list(record.facts)
    mutated_facts[0] = mutated_facts[0].model_copy(
        update={"detail": f"{mutated_facts[0].detail} (new evidence)"}
    )
    app.state.session_spine_store.put(
        project_id="repo-a",
        session=record.session,
        progress=record.progress,
        facts=mutated_facts,
        approval_queue=record.approval_queue,
        last_refreshed_at="2026-04-07T00:00:05Z",
        last_local_manual_activity_at=record.last_local_manual_activity_at,
    )
    updated_record = app.state.session_spine_store.get("repo-a")
    assert updated_record is not None
    assert updated_record.fact_snapshot_version == "fact-v2"

    app.state.resident_orchestrator._record_recovery_reentry_suppressed(
        updated_record,
        details=details,
    )

    suppressed_events = app.state.session_service.list_events(
        session_id="session:repo-a",
        event_type="recovery_execution_suppressed",
    )
    gate_events = app.state.session_service.list_events(
        session_id="session:repo-a",
        event_type="continuation_gate_evaluated",
    )

    assert len(suppressed_events) == 1
    assert [event.payload["authoritative_snapshot_version"] for event in gate_events] == [
        "fact-v1",
        "fact-v2",
    ]
    assert [
        event.related_ids["route_key"]
        for event in gate_events
        if event.payload.get("gate_kind") == "recovery_execution"
    ] == [
        "repo-a:session:repo-a:thr_native_1:recover_current_branch:fact-v1",
        "repo-a:session:repo-a:thr_native_1:recover_current_branch:fact-v2",
    ]


def test_resident_orchestrator_does_not_auto_recover_stale_unrefreshed_session_record(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        recover_auto_resume=False,
        auto_continue_cooldown_seconds=0.0,
        auto_recovery_cooldown_seconds=0.0,
        session_spine_freshness_window_seconds=60.0,
    )
    a_client = UniqueRecoveryResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "context exhausted",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="propose_recovery")

    app.state.session_spine_runtime.refresh_all()
    record = app.state.session_spine_store.get("repo-a")
    assert record is not None
    app.state.session_spine_store.put(
        project_id="repo-a",
        session=record.session,
        progress=record.progress,
        facts=record.facts,
        approval_queue=record.approval_queue,
        last_refreshed_at="2026-04-07T00:00:00Z",
        last_local_manual_activity_at=record.last_local_manual_activity_at,
    )
    outcomes = app.state.resident_orchestrator.orchestrate_all(
        now=datetime(2026, 4, 7, 0, 2, 0, tzinfo=UTC)
    )

    assert a_client.handoff_calls == []
    assert [outcome.action_ref for outcome in outcomes] == [None]
    assert [outcome.decision_result for outcome in outcomes] == [None]


def test_resident_orchestrator_does_not_auto_recover_paused_session_without_new_human_resume(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        recover_auto_resume=False,
        auto_continue_cooldown_seconds=0.0,
        auto_recovery_cooldown_seconds=0.0,
    )
    a_client = UniqueRecoveryResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "paused",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "paused by operator",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="propose_recovery")

    app.state.session_spine_runtime.refresh_all()
    outcomes = app.state.resident_orchestrator.orchestrate_all(
        now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
    )

    assert a_client.handoff_calls == []
    assert [outcome.action_ref for outcome in outcomes] == [None]
    assert [outcome.decision_result for outcome in outcomes] == [None]


def test_resident_orchestrator_does_not_auto_recover_non_active_project_execution_state(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        recover_auto_resume=False,
        auto_continue_cooldown_seconds=0.0,
        auto_recovery_cooldown_seconds=0.0,
    )
    a_client = UniqueRecoveryResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "project_execution_state": "completed",
            "pending_approval": False,
            "last_summary": "branch already delivered",
            "files_touched": ["src/example.py"],
            "context_pressure": "critical",
            "stuck_level": 2,
            "failure_count": 3,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="propose_recovery")

    app.state.session_spine_runtime.refresh_all()
    outcomes = app.state.resident_orchestrator.orchestrate_all(
        now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
    )

    assert a_client.handoff_calls == []
    assert [outcome.action_ref for outcome in outcomes] == [None]
    assert [outcome.decision_result for outcome in outcomes] == [None]


def test_resident_orchestrator_does_not_auto_continue_non_active_project_execution_state(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        recover_auto_resume=False,
        auto_continue_cooldown_seconds=0.0,
        auto_recovery_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "project_execution_state": "completed",
            "pending_approval": False,
            "last_summary": "branch already delivered",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="propose_execute")

    app.state.session_spine_runtime.refresh_all()
    outcomes = app.state.resident_orchestrator.orchestrate_all(
        now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
    )

    assert [outcome.action_ref for outcome in outcomes] == [None]
    assert [outcome.decision_result for outcome in outcomes] == [None]


def test_background_runtime_pauses_disconnected_stale_session_before_orchestration(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "meeting",
            "thread_id": "019d757d-d272-7913-b4a2-a8adafe62bc5",
            "status": "running",
            "phase": "planning",
            "project_execution_state": "active",
            "pending_approval": False,
            "last_summary": "stale zombie task",
            "files_touched": ["docs/spec.md"],
            "context_pressure": "low",
            "stuck_level": 1,
            "failure_count": 0,
            "last_progress_at": "2026-04-23T02:20:49Z",
            "last_local_manual_activity_at": "2026-04-10T03:44:44Z",
            "last_error_signature": "[Errno 32] Broken pipe",
        },
        approvals=[
            {
                "approval_id": "approval:meeting-stale",
                "project_id": "meeting",
                "thread_id": "session:meeting",
                "native_thread_id": "019d757d-d272-7913-b4a2-a8adafe62bc5",
                "requested_action": "post_operator_guidance",
                "status": "pending",
                "created_at": "2026-04-23T03:59:37Z",
            }
        ],
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="propose_execute")

    app.state.session_spine_runtime.refresh_all()
    record = app.state.session_spine_store.get("meeting")
    session_bundle = build_session_read_bundle(
        a_client,
        "meeting",
        store=app.state.session_spine_store,
        approval_store=app.state.canonical_approval_store,
    )
    app.state.session_service.record_event_once(
        event_type="approval_requested",
        project_id="meeting",
        session_id="session:meeting",
        correlation_id="corr:test:approval:meeting-stale",
        related_ids={"approval_id": "approval:meeting-stale"},
        payload={
            "requested_action": "post_operator_guidance",
            "fact_snapshot_version": "fact-v99",
            "goal_contract_version": "goal-contract:v2",
            "expires_at": "2026-04-23T06:59:37Z",
        },
        occurred_at="2026-04-23T03:59:37Z",
    )
    event_bundle = build_approval_inbox_bundle(
        a_client,
        project_id="meeting",
        session_service=app.state.session_service,
        store=app.state.session_spine_store,
        approval_store=app.state.canonical_approval_store,
    )
    outcomes = app.state.resident_orchestrator.orchestrate_all(
        now=datetime(2026, 4, 23, 3, 0, 0, tzinfo=UTC)
    )

    assert record is not None
    assert "project_not_active" in [fact.fact_code for fact in record.facts]
    assert record.progress.activity_phase == "planning"
    assert session_bundle.approvals == []
    assert session_bundle.session.pending_approval_count == 0
    assert event_bundle.approvals == []
    assert [outcome.action_ref for outcome in outcomes] == [None]
    assert [outcome.decision_result for outcome in outcomes] == [None]


def test_resident_orchestrator_does_not_request_branch_switch_guidance_for_non_active_project(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "meeting",
            "thread_id": "019d757d-d272-7913-b4a2-a8adafe62bc5",
            "status": "running",
            "phase": "planning",
            "project_execution_state": "active",
            "pending_approval": False,
            "last_summary": "stale zombie task",
            "files_touched": [],
            "context_pressure": "low",
            "stuck_level": 1,
            "failure_count": 0,
            "last_progress_at": "2026-04-23T02:20:49Z",
            "last_local_manual_activity_at": "2026-04-10T03:44:44Z",
            "last_error_signature": "[Errno 32] Broken pipe",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="branch_complete_switch")

    app.state.session_spine_runtime.refresh_all()
    outcomes = app.state.resident_orchestrator.orchestrate_all(
        now=datetime(2026, 4, 23, 3, 0, 0, tzinfo=UTC)
    )
    pending = [
        approval
        for approval in app.state.canonical_approval_store.list_records()
        if approval.project_id == "meeting" and approval.status == "pending"
    ]

    assert [outcome.action_ref for outcome in outcomes] == [None]
    assert [outcome.decision_result for outcome in outcomes] == [None]
    assert pending == []


def test_resident_orchestrator_supersedes_stale_pending_approval_after_newer_auto_continue(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
        progress_summary_max_age_seconds=0.0,
    )
    a_client = CyclingResidentAClient(
        tasks=[
            {
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "context exhausted",
                "files_touched": ["src/example.py"],
                "context_pressure": "critical",
                "stuck_level": 2,
                "failure_count": 3,
                "last_progress_at": "2026-04-05T05:20:00Z",
            },
            {
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "progress resumed after recovery window",
                "files_touched": ["src/example.py"],
                "context_pressure": "low",
                "stuck_level": 2,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T05:25:00Z",
            },
        ]
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="require_approval")

    app.state.session_spine_runtime.refresh_all()
    first = app.state.resident_orchestrator.orchestrate_all(
        now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
    )
    first_approvals = app.state.canonical_approval_store.list_records()

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}
        app.state.resident_orchestrator._brain_service = StaticBrainService(intent="propose_execute")
        app.state.session_spine_runtime.refresh_all()
        second = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 1, 0, tzinfo=UTC)
        )

    approvals = app.state.canonical_approval_store.list_records()
    session_bundle = build_session_read_bundle(
        a_client,
        "repo-a",
        store=app.state.session_spine_store,
        approval_store=app.state.canonical_approval_store,
    )
    inbox_bundle = build_approval_inbox_bundle(
        a_client,
        project_id="repo-a",
        store=app.state.session_spine_store,
        approval_store=app.state.canonical_approval_store,
    )
    event_inbox_bundle = build_approval_inbox_bundle(
        a_client,
        project_id="repo-a",
        session_service=app.state.session_service,
        store=app.state.session_spine_store,
        approval_store=app.state.canonical_approval_store,
    )

    assert [outcome.action_ref for outcome in first] == ["continue_session"]
    assert [outcome.decision_result for outcome in first] == ["require_user_decision"]
    assert len(first_approvals) == 1
    assert first_approvals[0].status == "pending"
    assert first_approvals[0].requested_action == "continue_session"
    assert [outcome.action_ref for outcome in second] == ["continue_session"]
    assert [outcome.decision_result for outcome in second] == ["auto_execute_and_notify"]
    assert steer_mock.call_count == 1
    assert len(approvals) == 1
    assert approvals[0].requested_action == "continue_session"
    assert approvals[0].status == "superseded"
    assert approvals[0].decided_by == "policy-supersede"
    assert any(
        note.startswith("approval_superseded_by_decision ")
        for note in approvals[0].operator_notes
    )
    assert session_bundle.session.session_state == "blocked"
    assert session_bundle.session.pending_approval_count == 0
    assert session_bundle.approvals == []
    assert inbox_bundle.approvals == []
    assert event_inbox_bundle.approvals == []
    approval_delivery = app.state.delivery_outbox_store.get_delivery_record(first_approvals[0].envelope_id)
    assert approval_delivery is not None
    assert approval_delivery.delivery_status == "superseded"
    assert any(
        note.startswith("delivery_superseded reason=approval_superseded_by_decision ")
        for note in approval_delivery.operator_notes
    )
    assert [fact.fact_code for fact in session_bundle.facts] == [
        "stuck_no_progress",
        "recovery_available",
    ]


def test_resident_orchestrator_records_command_lease_for_auto_continue(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "still stuck",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["auto_execute_and_notify"]

    decision = app.state.policy_decision_store.list_records()[0]
    command_id = f"command:{decision.decision_id}"
    events = app.state.command_lease_store.list_events(command_id=command_id)
    assert [event.event_type for event in events] == [
        "command_claimed",
        "command_executed",
    ]
    state = app.state.command_lease_store.get_command(command_id)
    assert state is not None
    assert state.status == "executed"
    assert state.claim_seq == 1
    assert state.worker_id == "resident_orchestrator"
    session_events = app.state.session_service.list_events(
        session_id="session:repo-a",
        correlation_id=f"corr:decision:{decision.decision_id}",
    )
    assert [event.event_type for event in session_events] == [
        "decision_proposed",
        "decision_validated",
        "command_created",
    ]
    assert session_events[0].related_ids["decision_id"] == decision.decision_id
    assert session_events[0].payload["brain_intent"] == "propose_execute"
    assert session_events[1].payload["decision_result"] == "auto_execute_and_notify"
    assert session_events[1].payload["brain_intent"] == "propose_execute"
    assert session_events[1].payload["decision_trace"]["trace_id"].startswith("trace:")
    assert session_events[1].payload["validator_verdict"]["status"] == "pass"
    assert session_events[1].payload["release_gate_verdict"]["status"] == "pass"
    assert session_events[1].payload["release_gate_verdict"]["decision_trace_ref"] == (
        session_events[1].payload["decision_trace"]["trace_id"]
    )
    assert session_events[2].related_ids["command_id"] == command_id


def test_resident_orchestrator_records_resident_expert_consultation_evidence(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "still stuck",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="observe_only")
    app.state.session_spine_runtime.refresh_all()

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    steer_mock.assert_not_called()
    decision = app.state.policy_decision_store.list_records()[0]
    consultation = decision.evidence["resident_expert_consultation"]
    assert consultation["consultation_ref"] == decision.decision_id
    assert consultation["consulted_at"] == decision.created_at
    assert [item["expert_id"] for item in consultation["experts"]] == [
        "managed-agent-expert",
        "hermes-agent-expert",
    ]
    assert [item["status"] for item in consultation["experts"]] == [
        "unavailable",
        "unavailable",
    ]

    runtime_views = app.state.resident_expert_runtime_service.list_runtime_views()
    assert [view.last_consultation_ref for view in runtime_views] == [
        decision.decision_id,
        decision.decision_id,
    ]
    assert [view.last_consulted_at for view in runtime_views] == [
        decision.created_at,
        decision.created_at,
    ]


def test_resident_orchestrator_marks_resident_expert_coverage_degraded_when_stale(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
        resident_expert_stale_after_seconds=60.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "still stuck",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="observe_only")
    app.state.resident_expert_runtime_service.bind_runtime_handle(
        expert_id="managed-agent-expert",
        runtime_handle="agent:managed:1",
        observed_at="2026-04-07T00:00:00Z",
    )
    app.state.resident_expert_runtime_service.bind_runtime_handle(
        expert_id="hermes-agent-expert",
        runtime_handle="agent:hermes:1",
        observed_at="2026-04-07T00:00:00Z",
    )
    app.state.session_spine_runtime.refresh_all()

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 2, 0, tzinfo=UTC)
        )

    steer_mock.assert_not_called()
    decision = app.state.policy_decision_store.list_records()[0]
    consultation = decision.evidence["resident_expert_consultation"]
    assert consultation["coverage_status"] == "degraded"
    assert consultation["degraded_expert_ids"] == [
        "managed-agent-expert",
        "hermes-agent-expert",
    ]
    assert [item["status"] for item in consultation["experts"]] == [
        "stale",
        "stale",
    ]


def test_resident_orchestrator_does_not_reconsult_resident_experts_for_identical_replay(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "completed",
            "phase": "done",
            "pending_approval": False,
            "last_summary": "finished",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="observe_only")
    app.state.session_spine_runtime.refresh_all()
    spy_runtime_service = SpyResidentExpertRuntimeService()
    app.state.resident_orchestrator._resident_expert_runtime_service = spy_runtime_service

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        steer_mock.assert_not_called()
        app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    decision = app.state.policy_decision_store.list_records()[0]
    assert len(spy_runtime_service.calls) == 1

    regenerated = decision.model_copy(
        update={
            "evidence": {
                **decision.evidence,
                "goal_contract_version": "goal-contract:test-replay",
            }
        }
    )

    stored = app.state.resident_orchestrator._record_and_store_decision(regenerated)

    assert stored.evidence["resident_expert_consultation"]["consultation_ref"] == decision.decision_id
    assert len(spy_runtime_service.calls) == 1


def test_resident_orchestrator_requires_dual_resident_expert_gate_for_external_auto_execute(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "continue implementation",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)

    class StructuredBrainService:
        def evaluate_session(self, **_: object) -> DecisionIntent:
            return DecisionIntent(
                intent="propose_execute",
                rationale="model recommends continue",
                action_arguments={
                    "message": "继续推进并验证 watchdog 修复。",
                    "reason_code": "brain_auto_continue",
                    "stuck_level": 2,
                },
                provider="openai-compatible",
                model="gpt-5.4",
                prompt_schema_ref="prompt:brain-continuation-decision-v3",
                output_schema_ref="schema:provider-continuation-decision-v3",
                provider_output_schema_ref="schema:provider-continuation-decision-v3",
            )

    app.state.resident_orchestrator._brain_service = StructuredBrainService()
    app.state.session_spine_runtime.refresh_all()

    with patch(
        "watchdog.services.session_spine.orchestrator.execute_canonical_decision"
    ) as execute_mock, patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["require_user_decision"]
    execute_mock.assert_not_called()
    steer_mock.assert_not_called()

    decisions = app.state.policy_decision_store.list_records()
    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.runtime_disposition == "require_user_decision"
    assert "resident_expert_dual_gate" in decision.matched_policy_rules
    assert decision.evidence["resident_expert_gate"]["gate_status"] == "suppressed"
    assert decision.evidence["resident_expert_gate"]["missing_expert_ids"] == []
    assert decision.evidence["resident_expert_gate"]["unhealthy_expert_ids"] == [
        "hermes-agent-expert",
        "managed-agent-expert",
    ]

    consultation = decision.evidence["resident_expert_consultation"]
    assert consultation["coverage_status"] == "degraded"
    assert [item["status"] for item in consultation["experts"]] == [
        "unavailable",
        "unavailable",
    ]
    assert len(app.state.canonical_approval_store.list_records()) == 1


def test_resident_orchestrator_allows_external_auto_execute_with_healthy_dual_resident_experts(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "continue implementation",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)

    class StructuredBrainService:
        def evaluate_session(self, **_: object) -> DecisionIntent:
            return DecisionIntent(
                intent="propose_execute",
                rationale="model recommends continue",
                action_arguments={
                    "message": "继续推进并验证 watchdog 修复。",
                    "reason_code": "brain_auto_continue",
                    "stuck_level": 2,
                },
                provider="openai-compatible",
                model="gpt-5.4",
                prompt_schema_ref="prompt:brain-continuation-decision-v3",
                output_schema_ref="schema:provider-continuation-decision-v3",
                provider_output_schema_ref="schema:provider-continuation-decision-v3",
            )

    app.state.resident_orchestrator._brain_service = StructuredBrainService()
    _bind_dual_resident_experts(
        app,
        observed_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )
    app.state.session_spine_runtime.refresh_all()
    continue_result = WatchdogActionResult(
        action_code="continue_session",
        project_id="repo-a",
        approval_id=None,
        idempotency_key="decision:auto-continue",
        action_status=ActionStatus.COMPLETED,
        effect=Effect.STEER_POSTED,
        reply_code=ReplyCode.ACTION_RESULT,
        message="continued",
        facts=[],
    )

    with patch(
        "watchdog.services.session_spine.orchestrator.execute_canonical_decision",
        return_value=continue_result,
    ) as execute_mock, patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["auto_execute_and_notify"]
    execute_mock.assert_called_once()
    steer_mock.assert_not_called()

    decisions = app.state.policy_decision_store.list_records()
    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.runtime_disposition == "auto_execute_and_notify"
    assert decision.evidence["resident_expert_gate"]["gate_status"] == "eligible"
    assert decision.evidence["resident_expert_gate"]["unhealthy_expert_ids"] == []
    assert [
        item["status"] for item in decision.evidence["resident_expert_consultation"]["experts"]
    ] == ["restoring", "restoring"]
    assert app.state.canonical_approval_store.list_records() == []


def test_resident_orchestrator_embeds_recorded_resident_expert_opinions_for_external_model_decision(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "continue implementation",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)

    class StructuredBrainService:
        def evaluate_session(self, **_: object) -> DecisionIntent:
            return DecisionIntent(
                intent="propose_execute",
                rationale="model recommends continue",
                action_arguments={
                    "message": "继续推进并验证 watchdog 修复。",
                    "reason_code": "brain_auto_continue",
                    "stuck_level": 2,
                },
                provider="openai-compatible",
                model="gpt-5.4",
                prompt_schema_ref="prompt:brain-continuation-decision-v3",
                output_schema_ref="schema:provider-continuation-decision-v3",
                provider_output_schema_ref="schema:provider-continuation-decision-v3",
            )

    app.state.resident_orchestrator._brain_service = StructuredBrainService()
    _bind_dual_resident_experts(
        app,
        observed_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )
    app.state.session_spine_runtime.refresh_all()
    record = app.state.session_spine_store.get("repo-a")
    assert record is not None

    orchestrator = app.state.resident_orchestrator
    brain_intent = orchestrator._evaluate_brain_intent(record)
    action_ref = orchestrator._action_ref_for_brain_intent(record, brain_intent.intent)
    assert action_ref == "continue_session"
    requested_action_args = orchestrator._requested_action_args_for_intent(
        record,
        brain_intent=brain_intent,
    )
    trusted_record = orchestrator._record_with_trustworthy_approval_identity(
        record,
        action_ref=action_ref,
        requested_action_args=requested_action_args,
        goal_contract_version=orchestrator._goal_contract_version_for_record(record),
        policy_version="policy-v1",
    )
    intent_evidence = orchestrator._decision_evidence_for_intent(
        trusted_record,
        brain_intent=brain_intent,
        action_ref=action_ref,
        requested_action_args=requested_action_args,
        goal_contract_readiness=orchestrator._goal_contract_readiness_for_record(record),
        now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC),
    )
    seed_decision = evaluate_persisted_session_policy(
        trusted_record,
        action_ref=action_ref,
        trigger="resident_orchestrator",
        brain_intent=brain_intent.intent,
        validator_verdict=intent_evidence,
        release_gate_verdict=intent_evidence,
        goal_contract_readiness=orchestrator._goal_contract_readiness_for_record(record),
    ).model_copy(update={"evidence": {**intent_evidence}})

    app.state.resident_expert_runtime_service.record_consultation_payload(
        consultation_ref=seed_decision.decision_id,
        consulted_at="2026-04-07T00:00:00Z",
        opinions=[
            {
                "expert_id": "managed-agent-expert",
                "next_slice_recommendation": "stabilize recovery lineage before expanding autonomy",
                "rationale": "lineage needs to stay replayable under auto-execute paths",
                "risks_to_avoid": ["implicit recovery state resurrection"],
            },
            {
                "expert_id": "hermes-agent-expert",
                "next_slice_recommendation": "compress operator-facing next action text",
                "rationale": "dispatch guidance is still too dense during triage",
                "risks_to_avoid": ["burying the next branch action"],
            },
        ],
        synthesis={
            "summary": "take the smallest slice that improves lineage and operator triage together",
            "chosen_next_slice": "tighten lineage plus concise operator guidance",
            "dissent_summary": "managed prioritizes lineage, hermes prioritizes triage density",
        },
    )

    continue_result = WatchdogActionResult(
        action_code="continue_session",
        project_id="repo-a",
        approval_id=None,
        idempotency_key="decision:auto-continue",
        action_status=ActionStatus.COMPLETED,
        effect=Effect.STEER_POSTED,
        reply_code=ReplyCode.ACTION_RESULT,
        message="continued",
        facts=[],
    )

    with patch(
        "watchdog.services.session_spine.orchestrator.execute_canonical_decision",
        return_value=continue_result,
    ), patch("watchdog.services.session_spine.actions.post_steer"):
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    assert [outcome.decision_result for outcome in outcomes] == ["auto_execute_and_notify"]
    stored = app.state.policy_decision_store.list_records()[0]
    consultation = stored.evidence["resident_expert_consultation"]
    assert [item["expert_id"] for item in consultation["opinions"]] == [
        "managed-agent-expert",
        "hermes-agent-expert",
    ]
    assert consultation["synthesis"]["chosen_next_slice"] == (
        "tighten lineage plus concise operator guidance"
    )


def test_resident_orchestrator_reuses_existing_decision_lifecycle_events_on_identical_replay(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "still stuck",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}
        app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    decision = app.state.policy_decision_store.list_records()[0]
    app.state.resident_orchestrator._record_decision_lifecycle(decision)

    session_events = app.state.session_service.list_events(
        session_id=decision.session_id,
        correlation_id=f"corr:decision:{decision.decision_id}",
    )

    assert [event.event_type for event in session_events] == [
        "decision_proposed",
        "decision_validated",
        "command_created",
    ]
    assert session_events[1].payload["validator_verdict"]["reason"] == "schema_and_risk_ok"


def test_resident_orchestrator_preserves_existing_lifecycle_trace_when_refreshing_legacy_decision(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "completed",
            "phase": "done",
            "pending_approval": False,
            "last_summary": "finished",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}
        app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    decision = app.state.policy_decision_store.list_records()[0]
    original_trace = decision.evidence["decision_trace"]["trace_id"]
    regenerated = decision.model_copy(
        update={
            "evidence": {
                **decision.evidence,
                "goal_contract_version": "goal-contract:test-refresh",
                "decision_input": {
                    "current_progress_summary": "当前分支目标：refreshed summary",
                },
                "brain_output": {
                    "evidence_codes": ["provider_unavailable"],
                    "remaining_work_hypothesis": ["retry provider"],
                },
                "decision_trace": {
                    **decision.evidence["decision_trace"],
                    "trace_id": "trace:regenerated",
                    "degrade_reason": "provider_unavailable",
                },
            }
        }
    )

    stored = app.state.resident_orchestrator._record_and_store_decision(regenerated)

    assert stored.evidence["decision_trace"]["trace_id"] == original_trace
    assert stored.evidence["decision_trace"]["degrade_reason"] == "provider_unavailable"
    assert stored.evidence["goal_contract_version"] == "goal-contract:test-refresh"
    assert stored.evidence["decision_input"]["current_progress_summary"] == "当前分支目标：refreshed summary"
    assert stored.evidence["brain_output"]["evidence_codes"] == ["provider_unavailable"]
    persisted = app.state.policy_decision_store.get(decision.decision_key)
    assert persisted is not None
    assert persisted.evidence["decision_trace"]["trace_id"] == original_trace
    assert persisted.evidence["decision_trace"]["degrade_reason"] == "provider_unavailable"
    assert persisted.evidence["goal_contract_version"] == "goal-contract:test-refresh"
    assert persisted.evidence["decision_input"]["current_progress_summary"] == "当前分支目标：refreshed summary"
    assert persisted.evidence["brain_output"]["evidence_codes"] == ["provider_unavailable"]

    session_events = app.state.session_service.list_events(
        session_id=decision.session_id,
        correlation_id=f"corr:decision:{decision.decision_id}",
    )
    assert [event.event_type for event in session_events] == [
        "decision_proposed",
        "decision_validated",
    ]
    assert session_events[0].payload["decision_trace_ref"] == original_trace
    assert session_events[1].payload["decision_trace"]["trace_id"] == original_trace


def test_resident_orchestrator_backfills_missing_decision_store_from_existing_lifecycle_events(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "completed",
            "phase": "done",
            "pending_approval": False,
            "last_summary": "finished",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}
        app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    decision = app.state.policy_decision_store.list_records()[0]
    correlation_id = f"corr:decision:{decision.decision_id}"
    session_events = app.state.session_service.list_events(
        session_id=decision.session_id,
        correlation_id=correlation_id,
    )
    assert [event.event_type for event in session_events] == [
        "decision_proposed",
        "decision_validated",
    ]

    decision_store_path = tmp_path / "policy_decisions.json"
    decision_store_payload = json.loads(decision_store_path.read_text(encoding="utf-8"))
    decision_store_payload.pop(decision.decision_key)
    decision_store_path.write_text(
        json.dumps(decision_store_payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    assert app.state.policy_decision_store.get(decision.decision_key) is None

    regenerated = decision.model_copy(
        update={
            "evidence": {
                **decision.evidence,
                "goal_contract_version": "goal-contract:test-backfill",
            }
        }
    )

    stored = app.state.resident_orchestrator._record_and_store_decision(regenerated)

    assert stored.decision_key == decision.decision_key
    assert stored.evidence["goal_contract_version"] == "goal-contract:test-backfill"
    persisted = app.state.policy_decision_store.get(decision.decision_key)
    assert persisted is not None
    assert persisted.evidence["goal_contract_version"] == "goal-contract:test-backfill"

    session_events = app.state.session_service.list_events(
        session_id=decision.session_id,
        correlation_id=correlation_id,
    )
    assert [event.event_type for event in session_events] == [
        "decision_proposed",
        "decision_validated",
    ]


def test_resident_orchestrator_raises_on_decision_lifecycle_payload_drift(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "still stuck",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}
        app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    decision = app.state.policy_decision_store.list_records()[0]
    mutated_decision = decision.model_copy(
        update={
            "why_not_escalated": "policy_requires_recheck",
            "uncertainty_reasons": ["mapping_incomplete", "release_gate_bundle_changed"],
            "evidence": {
                **decision.evidence,
                "release_gate_evidence_bundle": _formal_release_gate_bundle(
                    report_id="report-seed",
                    report_hash="sha256:report-rechecked",
                    input_hash="sha256:input-seed",
                ),
            }
        }
    )

    with pytest.raises(ValueError, match="conflicting session event for idempotency key"):
        app.state.resident_orchestrator._record_decision_lifecycle(mutated_decision)

    session_events = app.state.session_service.list_events(
        session_id=decision.session_id,
        correlation_id=f"corr:decision:{decision.decision_id}",
    )
    assert [event.event_type for event in session_events] == [
        "decision_proposed",
        "decision_validated",
        "command_created",
    ]
    assert session_events[1].payload["why_not_escalated"] == "policy_allows_auto_execution"
    assert session_events[1].payload["uncertainty_reasons"] == []
    assert session_events[1].payload["release_gate_evidence_fingerprint"] is None
    assert session_events[1].payload["validator_verdict"]["reason"] == "schema_and_risk_ok"


def test_resident_orchestrator_raises_on_command_created_payload_drift(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "still stuck",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()
    record = app.state.session_spine_store.get("repo-a")
    assert record is not None
    decision = app.state.policy_decision_store.put(
        _with_formal_release_gate_bundle(
            evaluate_persisted_session_policy(
                record,
                action_ref="continue_session",
                trigger="resident_orchestrator",
                brain_intent="propose_execute",
                **_runtime_gate_pass_kwargs(),
            )
        )
    )
    command_id = f"command:{decision.decision_id}"

    app.state.resident_orchestrator._record_command_created(
        decision,
        command_id=command_id,
    )
    mutated_decision = decision.model_copy(
        update={
            "evidence": {
                **decision.evidence,
                "requested_action_args": {"mode": "safe"},
            }
        }
    )

    with pytest.raises(ValueError, match="conflicting session event for idempotency key"):
        app.state.resident_orchestrator._record_command_created(
            mutated_decision,
            command_id=command_id,
        )

    session_events = app.state.session_service.list_events(
        session_id=decision.session_id,
        correlation_id=f"corr:decision:{decision.decision_id}",
    )
    assert [event.event_type for event in session_events] == ["command_created"]
    assert session_events[0].payload["action_args"] == {}


def test_resident_orchestrator_replay_reads_future_worker_events_by_decision_trace(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "still stuck",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}
        app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    decision = app.state.policy_decision_store.list_records()[0]
    command_id = f"command:{decision.decision_id}"
    trace_id = decision.evidence["decision_trace"]["trace_id"]
    app.state.session_service.record_event(
        event_type="future_worker_requested",
        project_id="repo-a",
        session_id="session:repo-a",
        occurred_at="2026-04-14T06:00:00Z",
        correlation_id="corr:future-worker:replay-1",
        related_ids={
            "worker_task_ref": "worker:replay-1",
            "decision_trace_ref": trace_id,
        },
        payload={"scope": "read_only"},
    )
    app.state.session_service.record_event(
        event_type="future_worker_completed",
        project_id="repo-a",
        session_id="session:repo-a",
        occurred_at="2026-04-14T06:01:00Z",
        correlation_id="corr:future-worker:replay-1",
        related_ids={
            "worker_task_ref": "worker:replay-1",
            "summary_ref": "summary:worker:replay-1",
        },
        payload={
            "worker_task_ref": "worker:replay-1",
            "parent_session_id": "session:repo-a",
            "decision_trace_ref": trace_id,
            "result_summary_ref": "summary:worker:replay-1",
            "artifact_refs": [],
            "input_contract_hash": "sha256:replay-input",
            "result_hash": "sha256:replay-result",
            "produced_at": "2026-04-14T06:01:00Z",
            "status": "completed",
            "worker_runtime_contract": {"provider": "codex"},
        },
    )

    relevant_events = app.state.resident_orchestrator._decision_relevant_session_events(
        decision,
        command_id=command_id,
    )

    assert [event.event_type for event in relevant_events] == [
        "decision_proposed",
        "decision_validated",
        "command_created",
        "future_worker_requested",
        "future_worker_completed",
    ]
    with patch.object(
        app.state.resident_orchestrator._replay_service,
        "session_semantic_replay",
        wraps=app.state.resident_orchestrator._replay_service.session_semantic_replay,
    ) as session_replay_mock:
        replay_summary = app.state.resident_orchestrator._command_terminal_replay_summary(
            decision,
            command_id=command_id,
        )

    assert replay_summary["session_semantic_replay"]["replay_incomplete"] is False
    assert session_replay_mock.call_args is not None
    assert session_replay_mock.call_args.kwargs["required_event_ids"] == [
        event.event_id for event in relevant_events
    ]


def test_resident_orchestrator_replay_excludes_future_worker_events_with_wrong_trace(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "still stuck",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}
        app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    decision = app.state.policy_decision_store.list_records()[0]
    command_id = f"command:{decision.decision_id}"
    app.state.session_service.record_event(
        event_type="future_worker_requested",
        project_id="repo-a",
        session_id="session:repo-a",
        occurred_at="2026-04-14T06:10:00Z",
        correlation_id="corr:future-worker:wrong-trace",
        related_ids={
            "worker_task_ref": "worker:wrong-trace",
            "decision_trace_ref": "trace:other",
        },
        payload={"scope": "read_only"},
    )
    app.state.session_service.record_event(
        event_type="future_worker_result_rejected",
        project_id="repo-a",
        session_id="session:repo-a",
        occurred_at="2026-04-14T06:11:00Z",
        correlation_id="corr:future-worker:wrong-trace",
        related_ids={
            "worker_task_ref": "worker:wrong-trace",
            "decision_trace_ref": "trace:other",
        },
        payload={
            "reason": "late_result",
            "decision_trace_ref": "trace:other",
        },
    )

    relevant_events = app.state.resident_orchestrator._decision_relevant_session_events(
        decision,
        command_id=command_id,
    )

    assert [event.event_type for event in relevant_events] == [
        "decision_proposed",
        "decision_validated",
        "command_created",
    ]


def test_resident_orchestrator_consumes_completed_future_worker_results_for_same_trace(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "still stuck",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    trace = _release_gate_trace().model_copy(update={"trace_id": "trace:consume-worker"})
    app.state.future_worker_service.request_worker(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        worker_task_ref="worker:consume-1",
        decision_trace_ref=trace.trace_id,
        goal_contract_version=trace.goal_contract_version,
        scope="read_only",
        allowed_hands=["codex"],
        input_packet_refs=["packet:consume-1"],
        retrieval_handles=["handle:consume-1"],
        distilled_summary_ref="summary:consume-1",
        execution_budget_ref="budget:consume-1",
        occurred_at="2026-04-14T06:20:00Z",
    )
    app.state.future_worker_service.record_started(
        worker_task_ref="worker:consume-1",
        project_id="repo-a",
        parent_session_id="session:repo-a",
        occurred_at="2026-04-14T06:21:00Z",
        worker_runtime_contract={"provider": "codex", "model": "gpt-5.4"},
    )
    app.state.future_worker_service.record_completed(
        worker_task_ref="worker:consume-1",
        project_id="repo-a",
        parent_session_id="session:repo-a",
        result_summary_ref="summary:worker:consume-1",
        artifact_refs=["artifact:consume-1"],
        input_contract_hash="sha256:consume-input",
        result_hash="sha256:consume-result",
        occurred_at="2026-04-14T06:22:00Z",
    )

    with patch.object(
        app.state.resident_orchestrator,
        "_decision_trace_for_intent",
        return_value=trace,
    ):
        with patch.object(
            app.state.resident_orchestrator._replay_service,
            "session_semantic_replay",
            wraps=app.state.resident_orchestrator._replay_service.session_semantic_replay,
        ) as session_replay_mock:
            with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
                steer_mock.return_value = {"success": True, "data": {"accepted": True}}
                app.state.resident_orchestrator.orchestrate_all(
                    now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
                )

    decision = app.state.policy_decision_store.list_records()[0]
    command_id = f"command:{decision.decision_id}"
    relevant_events = app.state.resident_orchestrator._decision_relevant_session_events(
        decision,
        command_id=command_id,
    )
    worker_events = [
        event
        for event in app.state.session_service.list_events(session_id="session:repo-a")
        if event.related_ids.get("worker_task_ref") == "worker:consume-1"
    ]

    assert [event.event_type for event in worker_events] == [
        "future_worker_requested",
        "future_worker_started",
        "future_worker_completed",
        "future_worker_result_consumed",
    ]
    assert worker_events[-1].related_ids["decision_id"] == decision.decision_id
    assert worker_events[-1].related_ids["decision_trace_ref"] == trace.trace_id
    assert session_replay_mock.call_args is not None
    assert session_replay_mock.call_args.kwargs["required_event_ids"] == [
        event.event_id for event in relevant_events
    ]


def test_resident_orchestrator_materializes_future_worker_requests_once_per_decision_trace(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "still stuck",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    trace = _release_gate_trace().model_copy(update={"trace_id": "trace:request-contract"})
    request = FutureWorkerExecutionRequest(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        worker_task_ref="worker:request-contract",
        decision_trace_ref=trace.trace_id,
        goal_contract_version=trace.goal_contract_version,
        scope="read_only",
        allowed_hands=["codex"],
        input_packet_refs=["packet:request-contract"],
        retrieval_handles=["handle:request-contract"],
        distilled_summary_ref="summary:request-contract",
        execution_budget_ref="budget:request-contract",
    )

    with patch.object(
        app.state.resident_orchestrator,
        "_decision_evidence_for_intent",
        return_value={
            "brain_rationale": "materialize_worker_request",
            "decision_trace": trace.model_dump(mode="json"),
            "validator_verdict": {"status": "pass", "reason": "schema_and_risk_ok"},
            "release_gate_verdict": {
                "status": "pass",
                "decision_trace_ref": trace.trace_id,
                "approval_read_ref": "approval:none",
                "report_id": "report:worker-request",
                "report_hash": "sha256:worker-request",
                "input_hash": "sha256:worker-request-input",
            },
            "release_gate_evidence_bundle": _formal_release_gate_bundle(
                report_id="report:worker-request",
                report_hash="sha256:worker-request",
                input_hash="sha256:worker-request-input",
            ),
            "future_worker_requests": [request.model_dump(mode="json")],
        },
    ):
        with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
            steer_mock.return_value = {"success": True, "data": {"accepted": True}}
            app.state.resident_orchestrator.orchestrate_all(
                now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
            )
            app.state.resident_orchestrator.orchestrate_all(
                now=datetime(2026, 4, 7, 0, 0, 1, tzinfo=UTC)
            )

    request_events = [
        event
        for event in app.state.session_service.list_events(session_id="session:repo-a")
        if event.event_type == "future_worker_requested"
        and event.related_ids.get("worker_task_ref") == "worker:request-contract"
    ]

    assert len(request_events) == 1
    assert request_events[0].related_ids["decision_trace_ref"] == trace.trace_id
    assert request_events[0].payload["allowed_hands"] == ["codex"]
    assert request_events[0].payload["execution_budget_ref"] == "budget:request-contract"


def test_resident_orchestrator_materializes_future_worker_requests_with_effective_parent_native_thread(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    app = create_app(
        settings,
        runtime_client=FakeResidentAClient(
            task={
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "still stuck",
                "files_touched": ["src/example.py"],
                "context_pressure": "low",
                "stuck_level": 2,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T05:20:00Z",
            }
        ),
        start_background_workers=False,
    )
    trace = _release_gate_trace().model_copy(update={"trace_id": "trace:legacy-parent-native"})
    request = FutureWorkerExecutionRequest(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        worker_task_ref="worker:legacy-parent-native",
        decision_trace_ref=trace.trace_id,
        goal_contract_version=trace.goal_contract_version,
        scope="read_only",
        allowed_hands=["codex"],
        input_packet_refs=["packet:legacy-parent-native"],
        retrieval_handles=["handle:legacy-parent-native"],
        distilled_summary_ref="summary:legacy-parent-native",
        execution_budget_ref="budget:legacy-parent-native",
    )
    decision = _runtime_gate_decision(
        release_gate_verdict={
            "status": "pass",
            "decision_trace_ref": trace.trace_id,
            "approval_read_ref": "approval:none",
            "report_id": "report:legacy-parent-native",
            "report_hash": "sha256:legacy-parent-native",
            "input_hash": "sha256:legacy-parent-native-input",
        }
    ).model_copy(
        update={
            "native_thread_id": None,
            "evidence": {
                "target": {
                    "session_id": "session:repo-a",
                    "project_id": "repo-a",
                    "thread_id": "session:repo-a",
                    "native_thread_id": "thr_native_legacy",
                    "approval_id": None,
                },
                "decision_trace": trace.model_dump(mode="json"),
                "future_worker_requests": [request.model_dump(mode="json")],
            },
        }
    )

    materialized = app.state.resident_orchestrator._materialize_future_worker_requests(
        decision,
        occurred_at="2026-04-14T06:20:00Z",
    )

    assert materialized == ["worker:legacy-parent-native"]
    request_events = [
        event
        for event in app.state.session_service.list_events(session_id="session:repo-a")
        if event.event_type == "future_worker_requested"
        and event.related_ids.get("worker_task_ref") == "worker:legacy-parent-native"
    ]
    assert len(request_events) == 1
    assert request_events[0].related_ids["parent_native_thread_id"] == "thr_native_legacy"
    assert request_events[0].payload["parent_native_thread_id"] == "thr_native_legacy"


def test_resident_orchestrator_rejects_partial_future_worker_request_materialization(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "still stuck",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    trace = _release_gate_trace().model_copy(update={"trace_id": "trace:request-batch"})
    valid_request = FutureWorkerExecutionRequest(
        project_id="repo-a",
        parent_session_id="session:repo-a",
        worker_task_ref="worker:valid-request",
        decision_trace_ref=trace.trace_id,
        goal_contract_version=trace.goal_contract_version,
        scope="read_only",
        allowed_hands=["codex"],
        input_packet_refs=["packet:valid-request"],
        retrieval_handles=["handle:valid-request"],
        distilled_summary_ref="summary:valid-request",
        execution_budget_ref="budget:valid-request",
    )
    invalid_request = valid_request.model_copy(
        update={
            "worker_task_ref": "worker:invalid-request",
            "decision_trace_ref": "trace:wrong-request",
        }
    )

    with patch.object(
        app.state.resident_orchestrator,
        "_decision_evidence_for_intent",
        return_value={
            "brain_rationale": "reject_partial_worker_request_batch",
            "decision_trace": trace.model_dump(mode="json"),
            "validator_verdict": {"status": "pass", "reason": "schema_and_risk_ok"},
            "release_gate_verdict": {
                "status": "pass",
                "decision_trace_ref": trace.trace_id,
                "approval_read_ref": "approval:none",
                "report_id": "report:worker-request-batch",
                "report_hash": "sha256:worker-request-batch",
                "input_hash": "sha256:worker-request-batch-input",
            },
            "release_gate_evidence_bundle": _formal_release_gate_bundle(
                report_id="report:worker-request-batch",
                report_hash="sha256:worker-request-batch",
                input_hash="sha256:worker-request-batch-input",
            ),
            "future_worker_requests": [
                valid_request.model_dump(mode="json"),
                invalid_request.model_dump(mode="json"),
            ],
        },
    ):
        with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
            steer_mock.return_value = {"success": True, "data": {"accepted": True}}
            with pytest.raises(ValueError, match="future worker request decision trace drift"):
                app.state.resident_orchestrator.orchestrate_all(
                    now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
                )

    request_events = [
        event
        for event in app.state.session_service.list_events(session_id="session:repo-a")
        if event.event_type == "future_worker_requested"
    ]

    assert request_events == []


def test_resident_orchestrator_requires_human_decision_for_incomplete_goal_contract(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "still stuck",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    GoalContractService(app.state.session_service).bootstrap_contract(
        project_id="repo-a",
        session_id="session:repo-a",
        task_title="Implement watchdog read-side goal contract",
        task_prompt="Implement watchdog read-side goal contract",
        last_user_instruction="Implement watchdog read-side goal contract",
        phase="editing_source",
        last_summary="still stuck",
        explicit_deliverables=[],
        completion_signals=[],
    )

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["require_user_decision"]
    steer_mock.assert_not_called()

    decisions = app.state.policy_decision_store.list_records()
    assert len(decisions) == 1
    assert "goal_contract_readiness_gate" in decisions[0].matched_policy_rules
    assert decisions[0].evidence["goal_contract_readiness"] == {
        "mode": "observe_only",
        "missing_fields": ["explicit_deliverables", "completion_signals"],
    }

    approvals = app.state.canonical_approval_store.list_records()
    assert len(approvals) == 1
    assert approvals[0].requested_action == "continue_session"
    approval_events = app.state.session_service.list_events(
        session_id="session:repo-a",
        event_type="approval_requested",
    )
    assert len(approval_events) == 1
    assert approval_events[0].related_ids["approval_id"] == approvals[0].approval_id
    assert approval_events[0].related_ids["decision_id"] == decisions[0].decision_id


def test_resident_orchestrator_bootstraps_missing_goal_contract_for_legacy_provider_session(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
        brain_provider_name="openai-compatible",
        brain_provider_base_url="http://provider.test/v1",
        brain_provider_api_key="provider-key",
        brain_provider_model="gpt-test",
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "task_title": "Ship the watchdog auto-continue fix",
            "task_prompt": "Ship the watchdog auto-continue fix with regression coverage.",
            "last_summary": "still stuck on the watchdog auto-continue fix",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    assert (
        GoalContractService(app.state.session_service).get_current_contract(
            project_id="repo-a",
            session_id="session:repo-a",
        )
        is None
    )

    provider_calls: list[str] = []

    def fake_provider_decide(**_: object) -> DecisionIntent:
        provider_calls.append("called")
        return DecisionIntent(
            intent="propose_execute",
            rationale="provider decided continue",
            action_arguments={
                "message": "继续推进 watchdog 修复并验证。",
                "reason_code": "brain_auto_continue",
                "stuck_level": 3,
            },
        )

    with patch.object(
        type(app.state.resident_orchestrator._brain_service._provider),
        "decide",
        side_effect=fake_provider_decide,
    ), patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        _bind_dual_resident_experts(
            app,
            observed_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        )
        steer_mock.return_value = {"success": True, "data": {"status": "running"}}
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    contract = GoalContractService(app.state.session_service).get_current_contract(
        project_id="repo-a",
        session_id="session:repo-a",
    )
    assert contract is not None
    assert contract.current_phase_goal == "Ship the watchdog auto-continue fix with regression coverage."
    assert contract.explicit_deliverables == ["Ship the watchdog auto-continue fix"]
    assert contract.completion_signals == ["autonomy golden path release blocker passes"]
    assert provider_calls == ["called"]
    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["auto_execute_and_notify"]
    goal_events = app.state.session_service.list_events(
        session_id="session:repo-a",
        event_type="goal_contract_created",
    )
    assert len(goal_events) == 1


def test_resident_orchestrator_records_release_gate_and_validator_verdict_in_session_events(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "still stuck",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()
    contract_module = importlib.import_module(
        "watchdog.services.session_spine.event_gate_payload_contract"
    )

    def _decision_with_gate(*args, **kwargs) -> CanonicalDecisionRecord:
        persisted_record = args[0]
        return build_canonical_decision_record(
            persisted_record=persisted_record,
            decision_result="auto_execute_and_notify",
            brain_intent="propose_execute",
            risk_class="none",
            action_ref="continue_session",
            matched_policy_rules=["registered_action"],
            decision_reason="registered action and complete evidence",
            why_not_escalated="policy_allows_auto_execution",
            why_escalated=None,
            uncertainty_reasons=[],
            policy_version="policy-v1",
            extra_evidence={
                "validator_verdict": {
                    "status": "pass",
                    "reason": "schema_and_risk_ok",
                },
                "release_gate_verdict": {
                    "status": "pass",
                    "decision_trace_ref": "trace:1",
                    "approval_read_ref": "approval:event:1",
                    "report_id": "report-1",
                    "report_hash": "sha256:report",
                    "input_hash": "sha256:input",
                },
                "release_gate_evidence_bundle": _formal_release_gate_bundle(
                    report_id="report-1",
                    report_hash="sha256:report",
                    input_hash="sha256:input",
                ),
            },
        )

    with patch(
        "watchdog.services.session_spine.orchestrator.evaluate_persisted_session_policy",
        side_effect=_decision_with_gate,
    ):
        with patch(
            "watchdog.services.session_spine.orchestrator.build_session_event_gate_payload",
            wraps=contract_module.build_session_event_gate_payload,
        ) as helper_mock:
            with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
                steer_mock.return_value = {"success": True, "data": {"accepted": True}}
                app.state.resident_orchestrator.orchestrate_all(
                    now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
                )

    decision = app.state.policy_decision_store.list_records()[0]
    session_events = app.state.session_service.list_events(
        session_id="session:repo-a",
        correlation_id=f"corr:decision:{decision.decision_id}",
    )
    assert session_events[0].payload["brain_intent"] == "propose_execute"
    assert session_events[1].payload["validator_verdict"]["status"] == "pass"
    assert session_events[1].payload["release_gate_verdict"]["decision_trace_ref"] == "trace:1"
    assert session_events[1].payload["release_gate_verdict"]["approval_read_ref"] == "approval:event:1"
    assert session_events[1].payload["release_gate_evidence_fingerprint"].startswith("sha256:")
    assert "release_gate_evidence_bundle" not in session_events[1].payload
    assert helper_mock.call_count >= 1


def test_resident_orchestrator_command_terminal_payload_uses_gate_payload_contract(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "release-gate-report.json"
    trace = _release_gate_trace()
    _write_release_gate_report(
        report_path,
        trace=trace,
        expires_at="2026-04-20T00:00:00Z",
    )
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
        release_gate_report_path=str(report_path),
        release_gate_risk_policy_version="risk:v1",
        release_gate_decision_input_builder_version="dib:v1",
        release_gate_policy_engine_version="policy:v1",
        release_gate_tool_schema_hash="tool:abc",
        release_gate_memory_provider_adapter_hash="memory:abc",
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "still stuck",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()
    contract_module = importlib.import_module(
        "watchdog.services.session_spine.event_gate_payload_contract"
    )

    with patch(
        "watchdog.services.session_spine.orchestrator.build_session_event_gate_payload",
        wraps=contract_module.build_session_event_gate_payload,
    ) as helper_mock:
        with patch.object(
            app.state.resident_orchestrator,
            "_decision_trace_for_intent",
            return_value=trace,
        ):
            with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
                steer_mock.return_value = {"success": True, "data": {"accepted": True}}
                outcomes = app.state.resident_orchestrator.orchestrate_all(
                    now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
                )

    assert [outcome.decision_result for outcome in outcomes] == ["auto_execute_and_notify"]
    decision = app.state.policy_decision_store.list_records()[0]
    result = WatchdogActionResult(
        action_code="continue_session",
        project_id="repo-a",
        approval_id=None,
        idempotency_key="decision:terminal",
        action_status=ActionStatus.COMPLETED,
        effect=Effect.NOOP,
        reply_code=ReplyCode.ACTION_RESULT,
        message="ok",
        facts=[],
    )
    payload = app.state.resident_orchestrator._command_terminal_payload(
        decision=decision,
        command_id=f"command:{decision.decision_id}",
        claim_seq=1,
        result=result,
    )
    assert helper_mock.call_count >= 1
    assert "release_gate_verdict" in payload
    assert "validator_verdict" not in payload


def test_resident_orchestrator_does_not_execute_when_release_gate_or_validator_do_not_pass(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "still stuck",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    def _decision_with_degraded_gate(*args, **kwargs) -> CanonicalDecisionRecord:
        persisted_record = args[0]
        return build_canonical_decision_record(
            persisted_record=persisted_record,
            decision_result="auto_execute_and_notify",
            brain_intent="propose_execute",
            risk_class="none",
            action_ref="continue_session",
            matched_policy_rules=["registered_action"],
            decision_reason="registered action and complete evidence",
            why_not_escalated="policy_allows_auto_execution",
            why_escalated=None,
            uncertainty_reasons=[],
            policy_version="policy-v1",
            extra_evidence={
                "validator_verdict": {
                    "status": "degraded",
                    "reason": "memory_conflict",
                },
                "release_gate_verdict": {
                    "status": "degraded",
                    "decision_trace_ref": "trace:1",
                    "approval_read_ref": "approval:event:1",
                    "report_id": "report-1",
                    "report_hash": "sha256:report",
                    "input_hash": "sha256:input",
                    "degrade_reason": "approval_stale",
                },
            },
        )

    with patch(
        "watchdog.services.session_spine.orchestrator.evaluate_persisted_session_policy",
        side_effect=_decision_with_degraded_gate,
    ):
        with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
            outcomes = app.state.resident_orchestrator.orchestrate_all(
                now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
            )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["auto_execute_and_notify"]
    assert app.state.command_lease_store.list_events() == []
    steer_mock.assert_not_called()


def test_resident_orchestrator_fails_closed_when_auto_execute_decision_lacks_gate_evidence(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "still stuck",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    with patch.object(
        app.state.resident_orchestrator,
        "_decision_evidence_for_intent",
        return_value={"brain_rationale": "missing_runtime_gate"},
    ):
        with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
            outcomes = app.state.resident_orchestrator.orchestrate_all(
                now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
            )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["block_and_alert"]
    assert app.state.command_lease_store.list_events() == []
    steer_mock.assert_not_called()


def test_resident_orchestrator_uses_configured_release_gate_report_for_auto_execute(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "release-gate-report.json"
    trace = _release_gate_trace()
    report = _write_release_gate_report(
        report_path,
        trace=trace,
        expires_at="2026-04-20T00:00:00Z",
    )
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
        release_gate_report_path=str(report_path),
        release_gate_risk_policy_version="risk:v1",
        release_gate_decision_input_builder_version="dib:v1",
        release_gate_policy_engine_version="policy:v1",
        release_gate_tool_schema_hash="tool:abc",
        release_gate_memory_provider_adapter_hash="memory:abc",
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "still stuck",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    write_contract_module = importlib.import_module(
        "watchdog.services.brain.release_gate_write_contract"
    )

    with patch.object(
        app.state.resident_orchestrator,
        "_decision_trace_for_intent",
        return_value=trace,
    ):
        with patch(
            "watchdog.services.session_spine.orchestrator.build_release_gate_runtime_evidence",
            wraps=write_contract_module.build_release_gate_runtime_evidence,
        ) as helper_mock:
            with patch(
                "watchdog.services.session_spine.actions.post_steer",
                return_value={
                    "accepted": True,
                    "action_ref": "continue_session",
                    "reply_code": "ok",
                },
            ):
                outcomes = app.state.resident_orchestrator.orchestrate_all(
                    now=datetime(2026, 4, 15, 0, 0, 0, tzinfo=UTC)
                )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["auto_execute_and_notify"]
    assert helper_mock.call_count == 1
    decisions = app.state.policy_decision_store.list_records()
    assert len(decisions) == 1
    release_gate_verdict = decisions[0].evidence["release_gate_verdict"]
    release_gate_bundle = decisions[0].evidence["release_gate_evidence_bundle"]
    assert release_gate_verdict["status"] == "pass"
    assert release_gate_verdict["report_id"] == report["report_id"]
    assert release_gate_verdict["report_hash"] == report["report_hash"]
    assert release_gate_verdict["input_hash"] == report["input_hash"]
    assert release_gate_bundle.get("label_manifest_ref") == report["label_manifest"]
    assert release_gate_bundle.get("generated_by") == report["generated_by"]
    assert release_gate_bundle.get("report_approved_by") == report["report_approved_by"]
    assert release_gate_bundle.get("report_id") == report["report_id"]
    assert release_gate_bundle.get("report_hash") == report["report_hash"]
    assert release_gate_bundle.get("input_hash") == report["input_hash"]
    assert app.state.command_lease_store.list_events() != []


def test_resident_orchestrator_degrades_when_configured_release_gate_report_is_expired(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "release-gate-report.json"
    trace = _release_gate_trace()
    report = _write_release_gate_report(
        report_path,
        trace=trace,
        expires_at="2026-04-10T00:00:00Z",
    )
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
        release_gate_report_path=str(report_path),
        release_gate_risk_policy_version="risk:v1",
        release_gate_decision_input_builder_version="dib:v1",
        release_gate_policy_engine_version="policy:v1",
        release_gate_tool_schema_hash="tool:abc",
        release_gate_memory_provider_adapter_hash="memory:abc",
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "still stuck",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    with patch.object(
        app.state.resident_orchestrator,
        "_decision_trace_for_intent",
        return_value=trace,
    ):
        with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
            outcomes = app.state.resident_orchestrator.orchestrate_all(
                now=datetime(2026, 4, 15, 0, 0, 0, tzinfo=UTC)
            )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["block_and_alert"]
    decisions = app.state.policy_decision_store.list_records()
    assert len(decisions) == 1
    release_gate_verdict = decisions[0].evidence["release_gate_verdict"]
    assert release_gate_verdict["status"] == "degraded"
    assert release_gate_verdict["degrade_reason"] == "report_expired"
    assert release_gate_verdict["report_id"] == report["report_id"]
    assert app.state.command_lease_store.list_events() == []
    steer_mock.assert_not_called()


def test_resident_orchestrator_degrades_when_configured_release_gate_report_governance_drifts(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "release-gate-report.json"
    trace = _release_gate_trace()
    report = _write_release_gate_report(
        report_path,
        trace=trace,
        expires_at="2026-04-20T00:00:00Z",
    )
    report["runtime_contract_surface_ref"] = "custom.builder"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
        release_gate_report_path=str(report_path),
        release_gate_risk_policy_version="risk:v1",
        release_gate_decision_input_builder_version="dib:v1",
        release_gate_policy_engine_version="policy:v1",
        release_gate_tool_schema_hash="tool:abc",
        release_gate_memory_provider_adapter_hash="memory:abc",
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "still stuck",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    with patch.object(
        app.state.resident_orchestrator,
        "_decision_trace_for_intent",
        return_value=trace,
    ):
        with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
            outcomes = app.state.resident_orchestrator.orchestrate_all(
                now=datetime(2026, 4, 15, 0, 0, 0, tzinfo=UTC)
            )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["block_and_alert"]
    decisions = app.state.policy_decision_store.list_records()
    assert len(decisions) == 1
    release_gate_verdict = decisions[0].evidence["release_gate_verdict"]
    release_gate_bundle = decisions[0].evidence["release_gate_evidence_bundle"]
    assert release_gate_verdict["status"] == "degraded"
    assert release_gate_verdict["degrade_reason"] == "report_load_failed"
    assert release_gate_verdict["report_id"] == "report:load_failed"
    assert release_gate_bundle["release_gate_report_ref"] == str(report_path)
    assert (
        release_gate_bundle["certification_packet_corpus"]["artifact_ref"]
        == settings.release_gate_certification_packet_corpus_ref
    )
    assert (
        release_gate_bundle["shadow_decision_ledger"]["artifact_ref"]
        == settings.release_gate_shadow_decision_ledger_ref
    )
    assert release_gate_bundle["report_id"] == "report:load_failed"
    assert app.state.command_lease_store.list_events() == []
    steer_mock.assert_not_called()


def test_resident_orchestrator_uses_release_gate_write_contract_for_report_load_failed_fallback(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "release-gate-report.json"
    report_path.write_text("[]", encoding="utf-8")
    trace = _release_gate_trace()
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
        release_gate_report_path=str(report_path),
        release_gate_risk_policy_version="risk:v1",
        release_gate_decision_input_builder_version="dib:v1",
        release_gate_policy_engine_version="policy:v1",
        release_gate_tool_schema_hash="tool:abc",
        release_gate_memory_provider_adapter_hash="memory:abc",
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "still stuck",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()
    write_contract_module = importlib.import_module(
        "watchdog.services.brain.release_gate_write_contract"
    )

    with patch.object(
        app.state.resident_orchestrator,
        "_decision_trace_for_intent",
        return_value=trace,
    ):
        with patch(
            "watchdog.services.session_spine.orchestrator.build_release_gate_runtime_evidence",
            wraps=write_contract_module.build_release_gate_runtime_evidence,
        ) as helper_mock:
            with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
                outcomes = app.state.resident_orchestrator.orchestrate_all(
                    now=datetime(2026, 4, 15, 0, 0, 0, tzinfo=UTC)
                )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["block_and_alert"]
    assert helper_mock.call_count == 1
    decisions = app.state.policy_decision_store.list_records()
    assert len(decisions) == 1
    release_gate_bundle = decisions[0].evidence["release_gate_evidence_bundle"]
    assert release_gate_bundle["release_gate_report_ref"] == str(report_path)
    steer_mock.assert_not_called()


def test_resident_orchestrator_degrades_when_configured_release_gate_report_is_not_json_object(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "release-gate-report.json"
    report_path.write_text("[]", encoding="utf-8")
    trace = _release_gate_trace()
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
        release_gate_report_path=str(report_path),
        release_gate_risk_policy_version="risk:v1",
        release_gate_decision_input_builder_version="dib:v1",
        release_gate_policy_engine_version="policy:v1",
        release_gate_tool_schema_hash="tool:abc",
        release_gate_memory_provider_adapter_hash="memory:abc",
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "still stuck",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    with patch.object(
        app.state.resident_orchestrator,
        "_decision_trace_for_intent",
        return_value=trace,
    ):
        with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
            outcomes = app.state.resident_orchestrator.orchestrate_all(
                now=datetime(2026, 4, 15, 0, 0, 0, tzinfo=UTC)
            )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["block_and_alert"]
    decisions = app.state.policy_decision_store.list_records()
    assert len(decisions) == 1
    release_gate_verdict = decisions[0].evidence["release_gate_verdict"]
    assert release_gate_verdict["status"] == "degraded"
    assert release_gate_verdict["degrade_reason"] == "report_load_failed"
    assert release_gate_verdict["report_id"] == "report:load_failed"
    assert app.state.command_lease_store.list_events() == []
    steer_mock.assert_not_called()


def test_resident_orchestrator_fails_closed_when_decision_event_write_fails(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "still stuck",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    original_record_event = app.state.session_service.record_event

    def _failing_record_event(*args, **kwargs):
        if kwargs.get("event_type") == "decision_validated":
            raise RuntimeError("session event write failed")
        return original_record_event(*args, **kwargs)

    app.state.session_service.record_event = _failing_record_event

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        with pytest.raises(RuntimeError, match="session event write failed"):
            app.state.resident_orchestrator.orchestrate_all(
                now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
            )

    assert app.state.policy_decision_store.list_records() == []
    assert app.state.command_lease_store.list_events() == []
    steer_mock.assert_not_called()


def test_resident_orchestrator_skips_auto_execute_when_command_is_already_claimed(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "still stuck",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()
    record = app.state.session_spine_store.get("repo-a")
    assert record is not None
    decision = app.state.policy_decision_store.put(
        _with_formal_release_gate_bundle(
            evaluate_persisted_session_policy(
                record,
                action_ref="continue_session",
                trigger="resident_orchestrator",
                brain_intent="propose_execute",
                **_runtime_gate_pass_kwargs(),
            )
        )
    )
    command_id = f"command:{decision.decision_id}"
    app.state.command_lease_store.claim_command(
        command_id=command_id,
        session_id=decision.session_id,
        worker_id="worker:other",
        claimed_at="2026-04-07T00:00:00Z",
        lease_expires_at="2026-04-07T00:05:00Z",
    )

    with patch(
        "watchdog.services.session_spine.orchestrator.execute_canonical_decision"
    ) as execute_mock:
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 1, 0, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["auto_execute_and_notify"]
    execute_mock.assert_not_called()
    events = app.state.command_lease_store.list_events(command_id=command_id)
    assert [event.event_type for event in events] == ["command_claimed"]
    state = app.state.command_lease_store.get_command(command_id)
    assert state is not None
    assert state.status == "claimed"
    assert state.worker_id == "worker:other"
    assert state.claim_seq == 1


def test_resident_orchestrator_treats_claim_race_as_nonfatal_skip(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "still stuck",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()
    record = app.state.session_spine_store.get("repo-a")
    assert record is not None
    decision = app.state.policy_decision_store.put(
        _with_formal_release_gate_bundle(
            evaluate_persisted_session_policy(
                record,
                action_ref="continue_session",
                trigger="resident_orchestrator",
                brain_intent="propose_execute",
                **_runtime_gate_pass_kwargs(),
            )
        )
    )
    command_id = f"command:{decision.decision_id}"
    original_claim_command = app.state.command_lease_store.claim_command

    def _racing_claim_command(*, command_id, session_id, worker_id, claimed_at, lease_expires_at):
        original_claim_command(
            command_id=command_id,
            session_id=session_id,
            worker_id="worker:other",
            claimed_at=claimed_at,
            lease_expires_at=lease_expires_at,
        )
        raise ValueError(f"command {command_id} is already claimed")

    with (
        patch.object(
            app.state.command_lease_store,
            "claim_command",
            side_effect=_racing_claim_command,
        ),
        patch("watchdog.services.session_spine.orchestrator.execute_canonical_decision") as execute_mock,
    ):
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 1, 0, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["auto_execute_and_notify"]
    execute_mock.assert_not_called()
    state = app.state.command_lease_store.get_command(command_id)
    assert state is not None
    assert state.status == "claimed"
    assert state.worker_id == "worker:other"
    events = app.state.command_lease_store.list_events(command_id=command_id)
    assert [event.event_type for event in events] == ["command_claimed"]


def test_resident_orchestrator_reexecutes_its_active_claim_after_renewing_lease(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
        resident_orchestrator_interval_seconds=3600,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "still stuck",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()
    record = app.state.session_spine_store.get("repo-a")
    assert record is not None
    decision = app.state.policy_decision_store.put(
        _with_formal_release_gate_bundle(
            evaluate_persisted_session_policy(
                record,
                action_ref="continue_session",
                trigger="resident_orchestrator",
                brain_intent="propose_execute",
                **_runtime_gate_pass_kwargs(),
            )
        )
    )
    command_id = f"command:{decision.decision_id}"
    app.state.command_lease_store.claim_command(
        command_id=command_id,
        session_id=decision.session_id,
        worker_id="resident_orchestrator",
        claimed_at="2026-04-07T00:00:00Z",
        lease_expires_at="2026-04-07T00:30:00Z",
    )

    result = WatchdogActionResult(
        action_code="continue_session",
        project_id="repo-a",
        approval_id=None,
        idempotency_key="resident-claimed-command",
        action_status=ActionStatus.COMPLETED,
        effect=Effect.NOOP,
        reply_code=ReplyCode.ACTION_RESULT,
        message="ok",
        facts=[],
    )

    with patch(
        "watchdog.services.session_spine.orchestrator.execute_canonical_decision",
        return_value=result,
    ) as execute_mock:
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 10, 0, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["auto_execute_and_notify"]
    execute_mock.assert_called_once()
    events = app.state.command_lease_store.list_events(command_id=command_id)
    assert [event.event_type for event in events] == [
        "command_claimed",
        "command_lease_renewed",
        "command_executed",
    ]
    assert [event.claim_seq for event in events] == [1, 1, 1]
    state = app.state.command_lease_store.get_command(command_id)
    assert state is not None
    assert state.status == "executed"
    assert state.worker_id == "resident_orchestrator"
    assert state.claim_seq == 1
    assert state.lease_expires_at == "2026-04-07T01:10:00Z"
    session_events = [
        event
        for event in app.state.session_service.list_events(session_id=decision.session_id)
        if event.related_ids.get("command_id") == command_id and event.event_type != "command_created"
    ]
    assert [event.event_type for event in session_events] == [
        "command_claimed",
        "command_lease_renewed",
        "command_executed",
    ]
    assert [event.related_ids["claim_seq"] for event in session_events] == ["1", "1", "1"]
    assert session_events[1].payload["lease_expires_at"] == "2026-04-07T01:10:00Z"


def test_resident_orchestrator_continue_on_error_skips_failed_record(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "still stuck",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()
    good_record = app.state.session_spine_store.get("repo-a")
    assert good_record is not None
    bad_record = good_record.model_copy(
        update={
            "project_id": "repo-b",
            "thread_id": "thr_native_2",
        }
    )

    def _orchestrate_record(record, *, now):
        _ = now
        if record.project_id == "repo-b":
            raise RuntimeError("synthetic resident orchestrator failure")
        return ResidentOrchestrationOutcome(
            project_id=record.project_id,
            action_ref=None,
            decision_result=None,
            emitted_progress_summary=False,
        )

    caplog.set_level("ERROR", logger="watchdog.services.session_spine.orchestrator")

    with (
        patch.object(
            app.state.session_spine_store,
            "list_records",
            return_value=[bad_record, good_record],
        ),
        patch.object(
            app.state.resident_orchestrator,
            "_orchestrate_record",
            side_effect=_orchestrate_record,
        ),
    ):
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 1, 0, tzinfo=UTC),
            continue_on_error=True,
        )

    assert [outcome.project_id for outcome in outcomes] == ["repo-a"]
    assert "resident orchestrator record failed: project=repo-b session=thr_native_2" in caplog.text


def test_resident_orchestrator_requeues_expired_claim_before_reexecuting_command(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "still stuck",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()
    record = app.state.session_spine_store.get("repo-a")
    assert record is not None
    decision = app.state.policy_decision_store.put(
        _with_formal_release_gate_bundle(
            evaluate_persisted_session_policy(
                record,
                action_ref="continue_session",
                trigger="resident_orchestrator",
                brain_intent="propose_execute",
                **_runtime_gate_pass_kwargs(),
            )
        )
    )
    command_id = f"command:{decision.decision_id}"
    app.state.command_lease_store.claim_command(
        command_id=command_id,
        session_id=decision.session_id,
        worker_id="worker:other",
        claimed_at="2026-04-07T00:00:00Z",
        lease_expires_at="2026-04-07T00:00:30Z",
    )

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 1, 0, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["auto_execute_and_notify"]
    assert steer_mock.call_count == 1
    events = app.state.command_lease_store.list_events(command_id=command_id)
    assert [event.event_type for event in events] == [
        "command_claimed",
        "command_claim_expired",
        "command_requeued",
        "command_claimed",
        "command_executed",
    ]
    assert [event.claim_seq for event in events] == [1, 1, 1, 2, 2]
    state = app.state.command_lease_store.get_command(command_id)
    assert state is not None
    assert state.status == "executed"
    assert state.claim_seq == 2
    assert state.worker_id == "resident_orchestrator"
    session_events = [
        event
        for event in app.state.session_service.list_events(session_id=decision.session_id)
        if event.related_ids.get("command_id") == command_id and event.event_type != "command_created"
    ]
    assert [event.event_type for event in session_events] == [
        "command_claimed",
        "command_claim_expired",
        "command_requeued",
        "command_claimed",
        "command_executed",
    ]
    assert [event.related_ids["claim_seq"] for event in session_events] == [
        "1",
        "1",
        "1",
        "2",
        "2",
    ]


def test_startup_reconciles_stale_pending_canonical_approval_against_later_auto_decision(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        session_spine_refresh_interval_seconds=3600,
        resident_orchestrator_interval_seconds=3600,
        delivery_worker_interval_seconds=3600,
        progress_summary_max_age_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "editing files",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2099-01-01T00:00:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=True)
    stale_decision = CanonicalDecisionRecord(
        decision_id="decision:repo-a:fact-v1:require_user_decision",
        decision_key="session:repo-a|fact-v1|policy-v1|require_user_decision|execute_recovery|",
        session_id="session:repo-a",
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="native:repo-a",
        approval_id=None,
        action_ref="execute_recovery",
        trigger="resident_orchestrator",
        decision_result="require_user_decision",
        risk_class="human_gate",
        decision_reason="manual approval required",
        matched_policy_rules=["recovery_human_gate"],
        why_not_escalated=None,
        why_escalated="manual decision required",
        uncertainty_reasons=[],
        policy_version="policy-v1",
        fact_snapshot_version="fact-v1",
        idempotency_key="session:repo-a|fact-v1|policy-v1|require_user_decision|execute_recovery|",
        created_at="2026-04-07T00:00:00Z",
        operator_notes=[],
        evidence={
            "decision": {
                "decision_result": "require_user_decision",
                "action_ref": "execute_recovery",
                "approval_id": None,
            }
        },
    )
    approval = materialize_canonical_approval(
        stale_decision,
        approval_store=app.state.canonical_approval_store,
    )
    app.state.policy_decision_store.put(
        CanonicalDecisionRecord(
            decision_id="decision:repo-a:fact-v2:auto_execute_and_notify",
            decision_key=(
                "session:repo-a|fact-v2|policy-v1|auto_execute_and_notify|continue_session|"
            ),
            session_id="session:repo-a",
            project_id="repo-a",
            thread_id="session:repo-a",
            native_thread_id="native:repo-a",
            approval_id=None,
            action_ref="continue_session",
            trigger="resident_orchestrator",
            decision_result="auto_execute_and_notify",
            risk_class="none",
            decision_reason="registered action and complete evidence",
            matched_policy_rules=["registered_action"],
            why_not_escalated="policy_allows_auto_execution",
            why_escalated=None,
            uncertainty_reasons=[],
            policy_version="policy-v1",
            fact_snapshot_version="fact-v2",
            idempotency_key=(
                "session:repo-a|fact-v2|policy-v1|auto_execute_and_notify|continue_session|"
            ),
            created_at="2026-04-07T00:05:00Z",
            operator_notes=[],
            evidence={
                "decision": {
                    "decision_result": "auto_execute_and_notify",
                    "action_ref": "continue_session",
                    "approval_id": None,
                }
            },
        )
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/watchdog/approval-inbox?project_id=repo-a",
            headers={"Authorization": "Bearer wt"},
        )

    persisted = app.state.canonical_approval_store.get(approval.envelope_id)

    assert response.status_code == 200
    assert response.json()["data"]["approvals"] == []
    assert persisted is not None
    assert persisted.status == "superseded"
    assert persisted.decided_by == "policy-startup-reconcile"


def test_resident_orchestrator_caches_auto_continue_control_link_error_per_decision(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "handoff",
            "pending_approval": False,
            "last_summary": "waiting for bridge recovery",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    with patch(
        "watchdog.services.session_spine.actions.post_steer",
        side_effect=RuntimeError("bridge unavailable"),
    ) as steer_mock:
        first = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )
        second = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 1, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in first] == ["continue_session"]
    assert [outcome.decision_result for outcome in first] == ["auto_execute_and_notify"]
    assert [outcome.action_ref for outcome in second] == ["continue_session"]
    assert [outcome.decision_result for outcome in second] == ["auto_execute_and_notify"]
    assert steer_mock.call_count == 1

    receipts = [result for _, result in app.state.action_receipt_store.list_items()]
    assert len(receipts) == 1
    assert receipts[0].action_code == "continue_session"
    assert receipts[0].action_status == "error"
    assert receipts[0].effect == "noop"
    assert receipts[0].reply_code == "control_link_error"
    assert receipts[0].message == "steer 调用失败：无法连接 Codex runtime"
    assert [fact.fact_code for fact in receipts[0].facts] == [
        "stuck_no_progress",
        "recovery_available",
    ]
    decision = app.state.policy_decision_store.list_records()[0]
    command_id = f"command:{decision.decision_id}"
    command_events = app.state.command_lease_store.list_events(command_id=command_id)
    assert [event.event_type for event in command_events] == [
        "command_claimed",
        "command_failed",
    ]
    command_state = app.state.command_lease_store.get_command(command_id)
    assert command_state is not None
    assert command_state.status == "failed"
    assert command_state.worker_id == "resident_orchestrator"
    session_events = [
        event
        for event in app.state.session_service.list_events(session_id=decision.session_id)
        if event.related_ids.get("command_id") == command_id and event.event_type != "command_created"
    ]
    assert [event.event_type for event in session_events] == [
        "command_claimed",
        "command_failed",
    ]
    assert app.state.delivery_outbox_store.list_records() == []


def test_resident_orchestrator_persists_brain_requested_action_args_for_continue_session(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "ship provider integration",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 1,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    class StructuredBrainService:
        def evaluate_session(self, **_: object) -> DecisionIntent:
            return DecisionIntent(
                intent="propose_execute",
                rationale="provider decided continue",
                action_arguments={
                    "message": "下一步建议：补齐飞书控制链路；回写验证结果。",
                    "reason_code": "brain_auto_continue",
                    "stuck_level": 1,
                },
            )

    app.state.resident_orchestrator._brain_service = StructuredBrainService()
    _bind_dual_resident_experts(
        app,
        observed_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["auto_execute_and_notify"]
    decision = app.state.policy_decision_store.list_records()[0]
    assert decision.evidence["requested_action_args"] == {
        "message": "下一步建议：补齐飞书控制链路；回写验证结果。",
        "reason_code": "brain_auto_continue",
        "stuck_level": 1,
    }
    assert decision.evidence["managed_agent_boundary"] == {
        "status": "pass",
        "action_ref": "continue_session",
        "brain_intent": "propose_execute",
        "capability": "session_control",
        "allowed_brain_intents": [
            "propose_execute",
            "require_approval",
            "suggest_only",
            "observe_only",
        ],
        "auto_execute_allowed_intents": ["propose_execute"],
        "auto_execute_eligible": True,
    }
    steer_mock.assert_called_once()


def test_resident_orchestrator_records_continuation_gate_verdict_for_provider_continue(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "ship provider integration",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 1,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    class StructuredBrainService:
        def evaluate_session(self, **_: object) -> DecisionIntent:
            return DecisionIntent(
                intent="propose_execute",
                rationale="provider decided continue",
                continuation_decision="continue_current_branch",
                routing_preference="same_thread",
                continuation_identity="repo-a:session:repo-a:thr_native_1:continue_current_branch",
                route_key=(
                    "repo-a:session:repo-a:thr_native_1:continue_current_branch:fact-v1"
                ),
                provider="openai-compatible",
                model="gpt-5.4",
                prompt_schema_ref="prompt:brain-continuation-decision-v3",
                output_schema_ref="schema:provider-continuation-decision-v3",
                provider_output_schema_ref="schema:provider-continuation-decision-v3",
                action_arguments={
                    "message": "下一步建议：补齐飞书控制链路；回写验证结果。",
                    "reason_code": "brain_auto_continue",
                    "stuck_level": 1,
                },
            )

    app.state.resident_orchestrator._brain_service = StructuredBrainService()
    _bind_dual_resident_experts(
        app,
        observed_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    gate_events = app.state.session_service.list_events(
        session_id="session:repo-a",
        event_type="continuation_gate_evaluated",
    )
    assert len(gate_events) == 1
    assert gate_events[0].payload == {
        "gate_kind": "continuation_governance",
        "gate_status": "eligible",
        "decision_source": "external_model",
        "decision_class": "continue_current_branch",
        "action_ref": "continue_session",
        "authoritative_snapshot_version": "fact-v1",
        "snapshot_epoch": "session-seq:1",
        "goal_contract_version": "goal-contract:unknown",
        "suppression_reason": None,
        "lineage_refs": [gate_events[0].payload["lineage_refs"][0]],
    }
    assert gate_events[0].payload["lineage_refs"][0].startswith("trace:")
    assert gate_events[0].related_ids == {
        "continuation_identity": (
            "repo-a:session:repo-a:thr_native_1:continue_current_branch"
        ),
        "route_key": (
            "repo-a:session:repo-a:thr_native_1:continue_current_branch:fact-v1"
        ),
    }


def test_resident_orchestrator_records_branch_switch_token_lifecycle_from_governance(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "branch wrap-up",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)

    issued_decision = CanonicalDecisionRecord(
        decision_id="decision:branch-switch-issued",
        decision_key="decision-key:branch-switch-issued",
        session_id="session:repo-a",
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="thr_native_1",
        action_ref="continue_session",
        trigger="resident_supervision",
        brain_intent="propose_execute",
        runtime_disposition="auto_execute_and_notify",
        decision_result="auto_execute_and_notify",
        risk_class="medium",
        decision_reason="branch is complete; prepare switch",
        matched_policy_rules=["brain.continuation"],
        uncertainty_reasons=[],
        policy_version="resident-policy-v1",
        fact_snapshot_version="fact-v1",
        idempotency_key="idem:branch-switch-issued",
        created_at="2026-04-07T00:00:00Z",
        evidence={
            "continuation_governance": {
                "gate_kind": "continuation_governance",
                "gate_status": "eligible",
                "decision_source": "external_model",
                "decision_class": "branch_complete_switch",
                "action_ref": "continue_session",
                "authoritative_snapshot_version": "fact-v1",
                "snapshot_epoch": "session-seq:1",
                "goal_contract_version": "goal-v7",
                "suppression_reason": None,
                "continuation_identity": (
                    "repo-a:session:repo-a:thr_native_1:branch_complete_switch"
                ),
                "route_key": (
                    "repo-a:session:repo-a:thr_native_1:branch_complete_switch:fact-v1"
                ),
                "branch_switch_token": "branch-switch:repo-a:86:fact-v1",
                "lineage_refs": ["trace:branch-switch-issued"],
            }
        },
    )
    invalidated_decision = issued_decision.model_copy(
        update={
            "decision_id": "decision:branch-switch-invalidated",
            "decision_key": "decision-key:branch-switch-invalidated",
            "idempotency_key": "idem:branch-switch-invalidated",
            "created_at": "2026-04-07T00:01:00Z",
            "evidence": {
                "continuation_governance": {
                    "gate_kind": "continuation_governance",
                    "gate_status": "suppressed",
                    "decision_source": "rules_fallback",
                    "decision_class": "branch_complete_switch",
                    "action_ref": "continue_session",
                    "authoritative_snapshot_version": "fact-v2",
                    "snapshot_epoch": "session-seq:2",
                    "goal_contract_version": "goal-v7",
                    "suppression_reason": "project_not_active",
                    "continuation_identity": (
                        "repo-a:session:repo-a:thr_native_1:branch_complete_switch"
                    ),
                    "route_key": (
                        "repo-a:session:repo-a:thr_native_1:branch_complete_switch:fact-v1"
                    ),
                    "branch_switch_token": "branch-switch:repo-a:86:fact-v1",
                    "lineage_refs": ["trace:branch-switch-invalidated"],
                }
            },
        }
    )

    app.state.resident_orchestrator._record_decision_lifecycle(issued_decision)
    app.state.resident_orchestrator._record_decision_lifecycle(invalidated_decision)

    issued_events = app.state.session_service.list_events(
        session_id="session:repo-a",
        event_type="branch_switch_token_issued",
    )
    invalidated_events = app.state.session_service.list_events(
        session_id="session:repo-a",
        event_type="branch_switch_token_invalidated",
    )

    assert len(issued_events) == 1
    assert issued_events[0].payload == {
        "state": "issued",
        "decision_source": "external_model",
        "decision_class": "branch_complete_switch",
        "authoritative_snapshot_version": "fact-v1",
        "snapshot_epoch": "session-seq:1",
        "goal_contract_version": "goal-v7",
        "suppression_reason": None,
        "lineage_refs": ["trace:branch-switch-issued"],
    }
    assert issued_events[0].related_ids == {
        "branch_switch_token": "branch-switch:repo-a:86:fact-v1",
        "continuation_identity": (
            "repo-a:session:repo-a:thr_native_1:branch_complete_switch"
        ),
        "route_key": (
            "repo-a:session:repo-a:thr_native_1:branch_complete_switch:fact-v1"
        ),
    }
    assert len(invalidated_events) == 1
    assert invalidated_events[0].payload == {
        "state": "invalidated",
        "decision_source": "rules_fallback",
        "decision_class": "branch_complete_switch",
        "authoritative_snapshot_version": "fact-v2",
        "snapshot_epoch": "session-seq:2",
        "goal_contract_version": "goal-v7",
        "suppression_reason": "project_not_active",
        "lineage_refs": ["trace:branch-switch-invalidated"],
    }


def test_resident_orchestrator_blocks_brain_continue_when_action_args_violate_contract(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "ship provider integration",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 1,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    class StructuredBrainService:
        def evaluate_session(self, **_: object) -> DecisionIntent:
            return DecisionIntent(
                intent="propose_execute",
                rationale="provider decided continue",
                action_arguments={
                    "message": "下一步建议：补齐飞书控制链路；回写验证结果。",
                    "reason_code": "brain_auto_continue",
                    "stuck_level": 9,
                },
            )

    app.state.resident_orchestrator._brain_service = StructuredBrainService()

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        outcomes = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in outcomes] == ["continue_session"]
    assert [outcome.decision_result for outcome in outcomes] == ["block_and_alert"]
    decision = app.state.policy_decision_store.list_records()[0]
    assert decision.matched_policy_rules == ["validator_gate_degraded"]
    assert decision.uncertainty_reasons == ["action_args_invalid"]
    assert decision.evidence["validator_verdict"] == {
        "status": "degraded",
        "reason": "action_args_invalid",
    }
    assert decision.evidence["managed_action_args_contract"] == {
        "status": "blocked",
        "action_ref": "continue_session",
        "allowed_keys": ["message", "reason_code", "stuck_level"],
        "required_keys": [],
        "missing_required_keys": [],
        "rejected_keys": [],
        "invalid_fields": {
            "stuck_level": "must be an integer in 0..4",
        },
    }
    steer_mock.assert_not_called()


def test_resident_orchestrator_applies_cooldown_to_repeated_auto_continue(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=300.0,
    )
    a_client = CyclingResidentAClient(
        tasks=[
            {
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "still stuck",
                "files_touched": ["src/example.py"],
                "context_pressure": "low",
                "stuck_level": 2,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T05:20:00Z",
            },
            {
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "still stuck after retry",
                "files_touched": ["src/example.py"],
                "context_pressure": "low",
                "stuck_level": 2,
                "failure_count": 3,
                "last_progress_at": "2026-04-05T05:25:00Z",
            },
        ]
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)

    with patch("watchdog.services.session_spine.actions.post_steer") as steer_mock:
        steer_mock.return_value = {"success": True, "data": {"accepted": True}}

        app.state.session_spine_runtime.refresh_all()
        first = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )

        app.state.session_spine_runtime.refresh_all()
        second = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 2, 0, tzinfo=UTC)
        )

        app.state.session_spine_runtime.refresh_all()
        third = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 6, 0, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in first] == ["continue_session"]
    assert [outcome.decision_result for outcome in first] == ["auto_execute_and_notify"]
    assert [outcome.action_ref for outcome in second] == [None]
    assert [outcome.decision_result for outcome in second] == [None]
    assert [outcome.action_ref for outcome in third] == ["continue_session"]
    assert [outcome.decision_result for outcome in third] == ["auto_execute_and_notify"]
    assert steer_mock.call_count == 2


def test_resident_orchestrator_does_not_start_cooldown_after_cached_control_link_error(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=300.0,
    )
    a_client = CyclingResidentAClient(
        tasks=[
            {
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "handoff",
                "pending_approval": False,
                "last_summary": "waiting for bridge recovery",
                "files_touched": ["src/example.py"],
                "context_pressure": "low",
                "stuck_level": 2,
                "failure_count": 0,
                "last_progress_at": "2026-04-05T05:20:00Z",
            },
            {
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "handoff",
                "pending_approval": False,
                "last_summary": "still waiting for bridge recovery",
                "files_touched": ["src/example.py"],
                "context_pressure": "low",
                "stuck_level": 3,
                "failure_count": 1,
                "last_progress_at": "2026-04-05T05:21:00Z",
            },
        ]
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)

    app.state.session_spine_runtime.refresh_all()
    with patch(
        "watchdog.services.session_spine.actions.post_steer",
        side_effect=RuntimeError("bridge unavailable"),
    ) as steer_mock:
        first = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )
        assert app.state.resident_orchestration_state_store.get_auto_continue_checkpoint("repo-a") is None

        app.state.session_spine_runtime.refresh_all()
        second = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 1, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in first] == ["continue_session"]
    assert [outcome.decision_result for outcome in first] == ["auto_execute_and_notify"]
    assert [outcome.action_ref for outcome in second] == ["continue_session"]
    assert [outcome.decision_result for outcome in second] == ["auto_execute_and_notify"]
    assert steer_mock.call_count == 2
    assert app.state.resident_orchestration_state_store.get_auto_continue_checkpoint("repo-a") is None
    checkpoint = app.state.resident_orchestration_state_store.get_latest_auto_dispatch_checkpoint(
        project_id="repo-a",
        continuation_identity="repo-a:session:repo-a:thr_native_1:continue_current_branch",
    )
    assert checkpoint is not None
    assert checkpoint.status == "failed"


def test_resident_orchestrator_does_not_start_cooldown_after_cached_error_receipt(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=300.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "handoff",
            "pending_approval": False,
            "last_summary": "waiting for bridge recovery",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-05T05:20:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    cached_error = WatchdogActionResult(
        action_code="continue_session",
        project_id="repo-a",
        approval_id=None,
        idempotency_key="decision:cached-error",
        action_status=ActionStatus.ERROR,
        effect=Effect.NOOP,
        reply_code=ReplyCode.CONTROL_LINK_ERROR,
        message="cached control-link-error receipt",
        facts=[],
    )

    with patch(
        "watchdog.services.session_spine.orchestrator.execute_canonical_decision",
        return_value=cached_error,
    ) as execute_mock:
        first = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 0, tzinfo=UTC)
        )
        second = app.state.resident_orchestrator.orchestrate_all(
            now=datetime(2026, 4, 7, 0, 0, 1, tzinfo=UTC)
        )

    assert [outcome.action_ref for outcome in first] == ["continue_session"]
    assert [outcome.decision_result for outcome in first] == ["auto_execute_and_notify"]
    assert [outcome.action_ref for outcome in second] == ["continue_session"]
    assert [outcome.decision_result for outcome in second] == ["auto_execute_and_notify"]
    assert execute_mock.call_count == 1
    assert app.state.resident_orchestration_state_store.get_auto_continue_checkpoint("repo-a") is None
    assert app.state.delivery_outbox_store.list_records() == []


def test_background_runtime_pushes_progress_summary_only_for_done_phase(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        session_spine_refresh_interval_seconds=0.01,
        resident_orchestrator_interval_seconds=0.01,
        progress_summary_interval_seconds=0.0,
    )
    a_client = CyclingResidentAClient(
        tasks=[
            {
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "running_tests",
                "pending_approval": False,
                "last_summary": "tests are running",
                "files_touched": ["src/example.py"],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2099-01-01T00:00:00Z",
            },
            {
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "done",
                "pending_approval": False,
                "last_summary": "ready for wrap-up",
                "files_touched": ["src/example.py", "tests/test_example.py"],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2099-01-01T00:01:00Z",
            },
        ]
    )
    delivery_client = RecordingDeliveryClient()
    app = create_app(settings, runtime_client=a_client, start_background_workers=True)
    app.state.delivery_worker._delivery_client = delivery_client

    with TestClient(app):
        assert wait_until(
            lambda: any(
                record.get("notification_kind") == "progress_summary"
                and record.get("summary") == "ready for wrap-up"
                for record in delivery_client.records
            ),
            timeout_s=0.5,
        )

    progress_notifications = [
        record
        for record in delivery_client.records
        if record.get("notification_kind") == "progress_summary"
    ]

    assert len(progress_notifications) >= 1
    assert progress_notifications[-1]["summary"] == "ready for wrap-up"


def test_background_runtime_pushes_progress_summary_for_handoff_ready_closing_phase(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        session_spine_refresh_interval_seconds=0.01,
        resident_orchestrator_interval_seconds=0.01,
        progress_summary_interval_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "handoff",
            "pending_approval": False,
            "last_summary": "ready for handoff after final review",
            "files_touched": ["src/example.py", "tests/test_example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2099-01-01T00:01:00Z",
        }
    )
    delivery_client = RecordingDeliveryClient()
    app = create_app(settings, runtime_client=a_client, start_background_workers=True)
    app.state.delivery_worker._delivery_client = delivery_client

    with TestClient(app):
        assert wait_until(
            lambda: any(
                record.get("notification_kind") == "progress_summary"
                and record.get("summary") == "ready for handoff after final review"
                for record in delivery_client.records
            ),
            timeout_s=0.5,
        )

    progress_notifications = [
        record
        for record in delivery_client.records
        if record.get("notification_kind") == "progress_summary"
    ]

    assert len(progress_notifications) >= 1
    assert progress_notifications[-1]["summary"] == "ready for handoff after final review"


def test_background_runtime_skips_progress_summary_for_non_closing_projects(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        session_spine_refresh_interval_seconds=0.01,
        resident_orchestrator_interval_seconds=0.01,
        progress_summary_interval_seconds=0.0,
    )
    a_client = MultiProjectResidentAClient(
        tasks=[
            {
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "repo-a editing",
                "files_touched": ["src/a.py"],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2099-01-01T00:00:00Z",
            },
            {
                "project_id": "repo-b",
                "thread_id": "thr_native_2",
                "status": "running",
                "phase": "running_tests",
                "pending_approval": False,
                "last_summary": "repo-b testing",
                "files_touched": ["src/b.py", "tests/test_b.py"],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2099-01-01T00:01:00Z",
            },
        ],
        approvals=[],
    )
    delivery_client = RecordingDeliveryClient()
    app = create_app(settings, runtime_client=a_client, start_background_workers=True)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="observe_only")
    app.state.delivery_worker._delivery_client = delivery_client

    with TestClient(app):
        assert wait_until(
            lambda: _store_path(tmp_path).exists()
            and "repo-a" in _read_store(tmp_path).get("sessions", {})
            and "repo-b" in _read_store(tmp_path).get("sessions", {}),
            timeout_s=0.5,
        )

    progress_notifications = [
        record
        for record in delivery_client.records
        if record.get("notification_kind") == "progress_summary"
    ]

    assert progress_notifications == []


def test_background_runtime_skips_progress_summary_for_non_terminal_handoff_state(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        session_spine_refresh_interval_seconds=0.01,
        resident_orchestrator_interval_seconds=0.01,
        progress_summary_interval_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "handoff",
            "pending_approval": False,
            "last_summary": "handoff drafted",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2099-01-01T00:01:00Z",
        }
    )
    delivery_client = RecordingDeliveryClient()
    app = create_app(settings, runtime_client=a_client, start_background_workers=True)
    app.state.delivery_worker._delivery_client = delivery_client

    with TestClient(app):
        assert wait_until(
            lambda: _store_path(tmp_path).exists()
            and "repo-a" in _read_store(tmp_path).get("sessions", {}),
            timeout_s=0.5,
        )

    progress_notifications = [
        record
        for record in delivery_client.records
        if record.get("notification_kind") == "progress_summary"
    ]

    assert progress_notifications == []


def test_background_runtime_does_not_push_session_directory_summary_for_multiple_projects(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        session_spine_refresh_interval_seconds=0.01,
        resident_orchestrator_interval_seconds=0.01,
        progress_summary_interval_seconds=0.0,
    )
    a_client = MultiProjectResidentAClient(
        tasks=[
            {
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "repo-a editing",
                "files_touched": ["src/a.py"],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2099-01-01T00:00:00Z",
            },
            {
                "project_id": "repo-b",
                "thread_id": "thr_native_2",
                "status": "running",
                "phase": "running_tests",
                "pending_approval": False,
                "last_summary": "repo-b testing",
                "files_touched": ["src/b.py", "tests/test_b.py"],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2099-01-01T00:01:00Z",
            },
        ],
        approvals=[],
    )
    delivery_client = RecordingDeliveryClient()
    app = create_app(settings, runtime_client=a_client, start_background_workers=True)
    app.state.resident_orchestrator._brain_service = StaticBrainService(intent="observe_only")
    app.state.delivery_worker._delivery_client = delivery_client

    with TestClient(app):
        assert wait_until(
            lambda: _store_path(tmp_path).exists()
            and "repo-a" in _read_store(tmp_path).get("sessions", {})
            and "repo-b" in _read_store(tmp_path).get("sessions", {}),
            timeout_s=0.5,
        )

    directory_notifications = [
        record
        for record in delivery_client.records
        if record.get("notification_kind") == "session_directory_summary"
    ]

    assert directory_notifications == []


def test_background_runtime_skips_stale_progress_summary_even_when_project_progress_changes(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        session_spine_refresh_interval_seconds=0.01,
        resident_orchestrator_interval_seconds=0.01,
        progress_summary_interval_seconds=0.0,
        progress_summary_max_age_seconds=600.0,
    )
    a_client = CyclingResidentAClient(
        tasks=[
            {
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "editing_source",
                "pending_approval": False,
                "last_summary": "editing files",
                "files_touched": ["src/example.py"],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-06T00:00:00Z",
            },
            {
                "project_id": "repo-a",
                "thread_id": "thr_native_1",
                "status": "running",
                "phase": "running_tests",
                "pending_approval": False,
                "last_summary": "tests are running",
                "files_touched": ["src/example.py", "tests/test_example.py"],
                "context_pressure": "low",
                "stuck_level": 0,
                "failure_count": 0,
                "last_progress_at": "2026-04-06T00:01:00Z",
            },
        ]
    )
    delivery_client = RecordingDeliveryClient()
    app = create_app(settings, runtime_client=a_client, start_background_workers=True)
    app.state.delivery_worker._delivery_client = delivery_client

    with TestClient(app):
        assert wait_until(
            lambda: _store_path(tmp_path).exists()
            and "repo-a" in _read_store(tmp_path).get("sessions", {}),
            timeout_s=0.5,
        )

    progress_notifications = [
        record
        for record in delivery_client.records
        if record.get("notification_kind") == "progress_summary"
    ]

    assert progress_notifications == []


def test_parse_iso_treats_naive_timestamps_as_utc() -> None:
    parsed = _parse_iso("2026-04-08T08:00:00")

    assert parsed == datetime(2026, 4, 8, 8, 0, 0, tzinfo=UTC)


def test_background_workers_survive_transient_startup_and_loop_failures(
    tmp_path: Path,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        session_spine_refresh_interval_seconds=0.01,
        resident_orchestrator_interval_seconds=0.01,
        delivery_worker_interval_seconds=0.01,
        progress_summary_interval_seconds=0.0,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "editing files",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2099-01-01T00:00:00Z",
        }
    )

    app = create_app(settings, runtime_client=a_client, start_background_workers=True)
    app.state.session_spine_runtime = FlakyRuntime(app.state.session_spine_runtime)
    app.state.resident_orchestrator = FlakyOrchestrator(app.state.resident_orchestrator)
    app.state.delivery_worker._delivery_client = RecordingDeliveryClient()
    app.state.delivery_worker = FlakyDeliveryWorker(app.state.delivery_worker)

    with TestClient(app):
        assert wait_until(
            lambda: _store_path(tmp_path).exists()
            and app.state.session_spine_runtime.calls >= 2
            and app.state.resident_orchestrator.calls >= 2
            and app.state.delivery_worker.calls >= 2
            ,
            timeout_s=0.5,
        )

    snapshot = _read_store(tmp_path)
    assert snapshot["sessions"]["repo-a"]["session_seq"] >= 1
    assert app.state.session_spine_runtime.calls >= 2
    assert app.state.resident_orchestrator.calls >= 2
    assert app.state.delivery_worker.calls >= 2


@pytest.mark.asyncio
async def test_delivery_loop_runs_drain_outside_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        delivery_worker_interval_seconds=3600,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "editing files",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2099-01-01T00:00:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)

    def blocking_drain(_app, *, now=None) -> None:
        _ = now
        time.sleep(0.05)

    monkeypatch.setattr("watchdog.main._drain_delivery_outbox", blocking_drain)

    started = time.perf_counter()
    ticker = asyncio.create_task(asyncio.sleep(0.01))
    delivery_loop_task = asyncio.create_task(_run_delivery_loop(app))

    try:
        await ticker
    finally:
        delivery_loop_task.cancel()
        with suppress(asyncio.CancelledError):
            await delivery_loop_task

    assert time.perf_counter() - started < 0.03


@pytest.mark.asyncio
async def test_session_spine_refresh_loop_reconciles_approvals_before_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        session_spine_refresh_interval_seconds=3600,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "editing files",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2099-01-01T00:00:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=False)
    calls: list[str] = []

    async def immediate_sleep(_seconds: float) -> None:
        return None

    async def controlled_background_step(step_name: str, fn, /, *args, **kwargs):
        calls.append(step_name)
        if step_name == "session_spine_runtime.refresh_all":
            raise asyncio.CancelledError
        result = fn(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    monkeypatch.setattr("watchdog.main.asyncio.sleep", immediate_sleep)
    monkeypatch.setattr("watchdog.main._run_background_step_async", controlled_background_step)

    with pytest.raises(asyncio.CancelledError):
        await _run_session_spine_refresh_loop(app)

    assert calls == [
        "canonical_approval_store.reconcile_pending_records_against_decisions",
        "session_spine_runtime.refresh_all",
    ]


@pytest.mark.asyncio
async def test_startup_drain_runs_outside_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        session_spine_refresh_interval_seconds=3600,
        resident_orchestrator_interval_seconds=3600,
        delivery_worker_interval_seconds=3600,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "editing files",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2099-01-01T00:00:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=True)

    def blocking_drain(_app, *, now=None) -> None:
        _ = now
        time.sleep(0.05)

    monkeypatch.setattr("watchdog.main._drain_delivery_outbox", blocking_drain)

    lifespan = app.router.lifespan_context(app)
    startup_task = asyncio.create_task(lifespan.__aenter__())
    started = time.perf_counter()
    ticker = asyncio.create_task(asyncio.sleep(0.01))

    try:
        await ticker
        assert time.perf_counter() - started < 0.03
        await startup_task
    finally:
        if startup_task.done() and not startup_task.cancelled():
            await lifespan.__aexit__(None, None, None)
        else:
            startup_task.cancel()
            with suppress(asyncio.CancelledError):
                await startup_task


@pytest.mark.asyncio
async def test_startup_does_not_wait_for_full_delivery_drain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        session_spine_refresh_interval_seconds=3600,
        resident_orchestrator_interval_seconds=3600,
        delivery_worker_interval_seconds=3600,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "editing files",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2099-01-01T00:00:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=True)

    def blocking_drain(_app, *, now=None) -> None:
        _ = (_app, now)
        time.sleep(0.2)

    monkeypatch.setattr("watchdog.main._drain_delivery_outbox", blocking_drain)

    lifespan = app.router.lifespan_context(app)
    startup_task = asyncio.create_task(lifespan.__aenter__())

    try:
        await asyncio.wait_for(startup_task, timeout=0.05)
    finally:
        if startup_task.done() and not startup_task.cancelled():
            await lifespan.__aexit__(None, None, None)
        else:
            startup_task.cancel()
            with suppress(asyncio.CancelledError):
                await startup_task


@pytest.mark.asyncio
async def test_startup_waits_for_approval_reconcile_before_starting_delivery_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        session_spine_refresh_interval_seconds=3600,
        resident_orchestrator_interval_seconds=3600,
        delivery_worker_interval_seconds=3600,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "editing files",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2099-01-01T00:00:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=True)
    reconcile_started = asyncio.Event()
    release_reconcile = asyncio.Event()
    delivery_started = asyncio.Event()

    async def controlled_background_step(step_name: str, fn, /, *args, **kwargs):
        if step_name == "canonical_approval_store.reconcile_pending_records_against_decisions":
            reconcile_started.set()
            await release_reconcile.wait()
        result = fn(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    async def gated_delivery_loop(_app) -> None:
        _ = _app
        delivery_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("watchdog.main._run_background_step_async", controlled_background_step)
    monkeypatch.setattr("watchdog.main._run_delivery_loop", gated_delivery_loop)

    lifespan = app.router.lifespan_context(app)
    startup_task = asyncio.create_task(lifespan.__aenter__())

    try:
        await asyncio.wait_for(reconcile_started.wait(), timeout=0.1)
        await asyncio.sleep(0)
        assert not delivery_started.is_set()
        release_reconcile.set()
        await asyncio.wait_for(startup_task, timeout=0.1)
        assert delivery_started.is_set()
    finally:
        if startup_task.done() and not startup_task.cancelled():
            await lifespan.__aexit__(None, None, None)
        else:
            startup_task.cancel()
            with suppress(asyncio.CancelledError):
                await startup_task


@pytest.mark.asyncio
async def test_startup_waits_for_approval_reconcile_before_starting_orchestrators(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        session_spine_refresh_interval_seconds=3600,
        resident_orchestrator_interval_seconds=3600,
        delivery_worker_interval_seconds=3600,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "editing files",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2099-01-01T00:00:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=True)
    reconcile_started = asyncio.Event()
    release_reconcile = asyncio.Event()
    startup_orchestrator_started = asyncio.Event()
    resident_orchestrator_started = asyncio.Event()

    async def controlled_background_step(step_name: str, fn, /, *args, **kwargs):
        if step_name == "canonical_approval_store.reconcile_pending_records_against_decisions":
            reconcile_started.set()
            await release_reconcile.wait()
        result = fn(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    async def gated_startup_orchestrator(_app) -> None:
        _ = _app
        startup_orchestrator_started.set()
        await asyncio.Event().wait()

    async def gated_resident_orchestrator(_app) -> None:
        _ = _app
        resident_orchestrator_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("watchdog.main._run_background_step_async", controlled_background_step)
    monkeypatch.setattr("watchdog.main._run_startup_orchestrator_once", gated_startup_orchestrator)
    monkeypatch.setattr("watchdog.main._run_resident_orchestrator_loop", gated_resident_orchestrator)

    lifespan = app.router.lifespan_context(app)
    startup_task = asyncio.create_task(lifespan.__aenter__())

    try:
        await asyncio.wait_for(reconcile_started.wait(), timeout=0.1)
        await asyncio.sleep(0)
        assert not startup_orchestrator_started.is_set()
        assert not resident_orchestrator_started.is_set()
        release_reconcile.set()
        await asyncio.wait_for(startup_task, timeout=0.1)
        assert startup_orchestrator_started.is_set()
        assert resident_orchestrator_started.is_set()
    finally:
        if startup_task.done() and not startup_task.cancelled():
            await lifespan.__aexit__(None, None, None)
        else:
            startup_task.cancel()
            with suppress(asyncio.CancelledError):
                await startup_task


@pytest.mark.asyncio
async def test_startup_does_not_start_background_loops_when_reconcile_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        session_spine_refresh_interval_seconds=3600,
        resident_orchestrator_interval_seconds=3600,
        delivery_worker_interval_seconds=3600,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "editing files",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2099-01-01T00:00:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=True)
    session_spine_started = asyncio.Event()
    memory_ingest_started = asyncio.Event()

    async def controlled_background_step(step_name: str, fn, /, *args, **kwargs):
        if step_name == "canonical_approval_store.reconcile_pending_records_against_decisions":
            raise RuntimeError("boom")
        result = fn(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    async def gated_session_spine_loop(_app) -> None:
        _ = _app
        session_spine_started.set()
        await asyncio.Event().wait()

    async def gated_memory_ingest_loop(_app) -> None:
        _ = _app
        memory_ingest_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("watchdog.main._run_background_step_async", controlled_background_step)
    monkeypatch.setattr("watchdog.main._run_session_spine_refresh_loop", gated_session_spine_loop)
    monkeypatch.setattr("watchdog.main._run_memory_ingest_loop", gated_memory_ingest_loop)

    lifespan = app.router.lifespan_context(app)
    with pytest.raises(RuntimeError, match="boom"):
        await lifespan.__aenter__()

    assert not session_spine_started.is_set()
    assert not memory_ingest_started.is_set()


@pytest.mark.asyncio
async def test_startup_does_not_wait_for_initial_orchestrator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        session_spine_refresh_interval_seconds=3600,
        resident_orchestrator_interval_seconds=3600,
        delivery_worker_interval_seconds=3600,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "editing files",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2099-01-01T00:00:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=True)

    def blocking_orchestrate(*, now=None):
        _ = now
        time.sleep(0.2)
        return []

    monkeypatch.setattr(
        app.state.resident_orchestrator,
        "orchestrate_all",
        blocking_orchestrate,
    )

    async def immediate_background_step(step_name: str, fn, /, *args, **kwargs):
        _ = step_name
        return fn(*args, **kwargs)

    monkeypatch.setattr(
        "watchdog.main._run_background_step_async",
        immediate_background_step,
    )

    lifespan = app.router.lifespan_context(app)
    startup_task = asyncio.create_task(lifespan.__aenter__())

    try:
        await asyncio.wait_for(startup_task, timeout=0.05)
    finally:
        if startup_task.done() and not startup_task.cancelled():
            await lifespan.__aexit__(None, None, None)
        else:
            startup_task.cancel()
            with suppress(asyncio.CancelledError):
                await startup_task


@pytest.mark.asyncio
async def test_startup_does_not_wait_for_background_supervision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        session_spine_refresh_interval_seconds=3600,
        resident_orchestrator_interval_seconds=3600,
        delivery_worker_interval_seconds=3600,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "editing files",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2099-01-01T00:00:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=True)

    def slow_supervision(*_args, **_kwargs):
        time.sleep(0.2)

    monkeypatch.setattr(
        "watchdog.main.supervision_routes.run_background_supervision",
        slow_supervision,
    )

    lifespan = app.router.lifespan_context(app)
    startup_task = asyncio.create_task(lifespan.__aenter__())

    try:
        await asyncio.wait_for(startup_task, timeout=0.05)
    finally:
        if startup_task.done() and not startup_task.cancelled():
            await lifespan.__aexit__(None, None, None)
        else:
            startup_task.cancel()
            with suppress(asyncio.CancelledError):
                await startup_task


@pytest.mark.asyncio
async def test_startup_spawns_feishu_long_connection_runtime_when_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        session_spine_refresh_interval_seconds=3600,
        resident_orchestrator_interval_seconds=3600,
        delivery_worker_interval_seconds=3600,
        feishu_event_ingress_mode="long_connection",
        feishu_callback_ingress_mode="long_connection",
        feishu_app_id="cli_long_connection",
        feishu_app_secret="secret-long-connection",
        feishu_verification_token="verify-token",
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "editing files",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2099-01-01T00:00:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=True)
    started: list[object] = []

    def fake_start_feishu_runtime(started_app):
        started.append(started_app)
        return None

    monkeypatch.setattr(
        "watchdog.main._start_feishu_long_connection_runtime",
        fake_start_feishu_runtime,
    )

    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()

    try:
        assert started == [app]
    finally:
        await lifespan.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_startup_and_periodic_orchestrator_runs_do_not_overlap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        api_token="wt",
        codex_runtime_token="at",
        codex_runtime_base_url="http://a.test",
        data_dir=str(tmp_path),
        session_spine_refresh_interval_seconds=3600,
        resident_orchestrator_interval_seconds=0.01,
        delivery_worker_interval_seconds=3600,
    )
    a_client = FakeResidentAClient(
        task={
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "editing files",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 0,
            "failure_count": 0,
            "last_progress_at": "2099-01-01T00:00:00Z",
        }
    )
    app = create_app(settings, runtime_client=a_client, start_background_workers=True)

    state_lock = threading.Lock()
    active_calls = 0
    max_active_calls = 0
    total_calls = 0

    def slow_orchestrate(*, now=None):
        nonlocal active_calls, max_active_calls, total_calls
        _ = now
        with state_lock:
            active_calls += 1
            total_calls += 1
            max_active_calls = max(max_active_calls, active_calls)
        try:
            time.sleep(0.03)
            return []
        finally:
            with state_lock:
                active_calls -= 1

    monkeypatch.setattr(
        app.state.resident_orchestrator,
        "orchestrate_all",
        slow_orchestrate,
    )
    monkeypatch.setattr(
        "watchdog.main._drain_delivery_outbox",
        lambda _app, *, now=None: None,
    )

    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()

    try:
        assert await wait_until_async(lambda: total_calls >= 2, timeout_s=0.5)
    finally:
        await lifespan.__aexit__(None, None, None)

    assert total_calls >= 2
    assert max_active_calls == 1
