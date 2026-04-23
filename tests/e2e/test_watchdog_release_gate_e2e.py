from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from watchdog.main import create_app
from watchdog.services.brain.models import DecisionTrace
from watchdog.services.brain.release_gate import ReleaseGateEvaluator
from watchdog.settings import Settings


class _ResidentAClient:
    def __init__(self) -> None:
        self._task = {
            "project_id": "repo-a",
            "thread_id": "thr_native_1",
            "status": "running",
            "phase": "editing_source",
            "pending_approval": False,
            "last_summary": "ready for low-risk auto execute",
            "files_touched": ["src/example.py"],
            "context_pressure": "low",
            "stuck_level": 2,
            "failure_count": 0,
            "last_progress_at": "2026-04-14T03:20:00Z",
        }

    def list_tasks(self) -> list[dict[str, object]]:
        return [dict(self._task)]

    def get_envelope(self, project_id: str) -> dict[str, object]:
        assert project_id == self._task["project_id"]
        return {"success": True, "data": dict(self._task)}

    def list_approvals(self, **_: object) -> list[dict[str, object]]:
        return []


def _settings(tmp_path: Path, report_path: Path) -> Settings:
    return Settings(
        api_token="watchdog-token",
        codex_runtime_token="a-agent-token",
        codex_runtime_base_url="http://a-control.test",
        data_dir=str(tmp_path),
        auto_continue_cooldown_seconds=0.0,
        release_gate_report_path=str(report_path),
        release_gate_risk_policy_version="risk:v1",
        release_gate_decision_input_builder_version="dib:v1",
        release_gate_policy_engine_version="policy:v1",
        release_gate_tool_schema_hash="tool:abc",
        release_gate_memory_provider_adapter_hash="memory:abc",
    )


def _trace() -> DecisionTrace:
    return DecisionTrace(
        trace_id="trace:e2e-release-gate",
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


def _write_report(path: Path, *, trace: DecisionTrace) -> None:
    evaluator = ReleaseGateEvaluator()
    report = {
        "report_id": "report:e2e-qualified",
        "report_hash": "sha256:e2e-qualified",
        "sample_window": "2026-04-01/2026-04-05",
        "shadow_window": "2026-04-06/2026-04-07",
        "label_manifest": "tests/fixtures/release_gate_label_manifest.json",
        "generated_by": "tests/e2e",
        "report_approved_by": "qa/e2e",
        "artifact_ref": "tests/fixtures/release_gate_expected_report.json",
        "expires_at": "2026-04-20T00:00:00Z",
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
        "runtime_contract_surface_ref": "watchdog.settings.Settings.build_runtime_contract",
        "runtime_gate_reason_taxonomy": {
            "passthrough_reasons": [
                "approval_stale",
                "report_expired",
                "report_load_failed",
                "input_hash_mismatch",
            ],
            "validator_reasons": [
                "memory_conflict",
                "memory_unavailable",
                "goal_contract_not_ready",
                "validator_missing",
                "validator_blocked",
            ],
            "validator_bucket": "validator_degraded",
            "contract_mismatch_suffix": "_mismatch",
            "contract_mismatch_bucket": "contract_mismatch",
            "fallback_bucket": "unknown",
            "raw_reason_labels_forbidden": True,
        },
    }
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def test_low_risk_auto_execute_requires_formal_release_gate_evidence_bundle(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "release-gate-report.json"
    trace = _trace()
    _write_report(report_path, trace=trace)
    settings = _settings(tmp_path, report_path)
    app = create_app(settings=settings, runtime_client=_ResidentAClient(), start_background_workers=False)
    app.state.session_spine_runtime.refresh_all()

    with patch.object(
        app.state.resident_orchestrator,
        "_decision_trace_for_intent",
        return_value=trace,
    ):
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
    decisions = app.state.policy_decision_store.list_records()
    assert len(decisions) == 1

    evidence = decisions[0].evidence
    assert "release_gate_evidence_bundle" in evidence
    bundle = evidence["release_gate_evidence_bundle"]
    assert bundle["certification_packet_corpus"]["artifact_ref"]
    assert bundle["shadow_decision_ledger"]["artifact_ref"]
    assert bundle["release_gate_report_ref"] == str(report_path)

