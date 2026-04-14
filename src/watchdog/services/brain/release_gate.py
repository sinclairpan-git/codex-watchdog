from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from watchdog.services.brain.models import ApprovalReadSnapshot, DecisionTrace
from watchdog.services.brain.validator import DecisionValidationVerdict


class _ReleaseGateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


DEFAULT_RUNTIME_CONTRACT_SURFACE_REF = (
    "watchdog.settings.Settings.build_runtime_contract"
)
RUNTIME_GATE_REASON_FALLBACK = "unknown"
RUNTIME_GATE_PASSTHROUGH_REASONS = (
    "approval_stale",
    "report_expired",
    "report_load_failed",
    "input_hash_mismatch",
)
RUNTIME_GATE_VALIDATOR_REASONS = (
    "memory_conflict",
    "memory_unavailable",
    "goal_contract_not_ready",
    "validator_missing",
    "validator_blocked",
)
RUNTIME_GATE_CONTRACT_MISMATCH_SUFFIX = "_mismatch"
RUNTIME_GATE_VALIDATOR_BUCKET = "validator_degraded"
RUNTIME_GATE_CONTRACT_MISMATCH_BUCKET = "contract_mismatch"
DEFAULT_RUNTIME_GATE_REASON_TAXONOMY = {
    "passthrough_reasons": list(RUNTIME_GATE_PASSTHROUGH_REASONS),
    "validator_reasons": list(RUNTIME_GATE_VALIDATOR_REASONS),
    "validator_bucket": RUNTIME_GATE_VALIDATOR_BUCKET,
    "contract_mismatch_suffix": RUNTIME_GATE_CONTRACT_MISMATCH_SUFFIX,
    "contract_mismatch_bucket": RUNTIME_GATE_CONTRACT_MISMATCH_BUCKET,
    "fallback_bucket": RUNTIME_GATE_REASON_FALLBACK,
    "raw_reason_labels_forbidden": True,
}


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class RuntimeGateReasonTaxonomy(_ReleaseGateModel):
    passthrough_reasons: list[str] = Field(min_length=1)
    validator_reasons: list[str] = Field(min_length=1)
    validator_bucket: str = Field(min_length=1)
    contract_mismatch_suffix: str = Field(min_length=1)
    contract_mismatch_bucket: str = Field(min_length=1)
    fallback_bucket: str = Field(min_length=1)
    raw_reason_labels_forbidden: bool = True


def normalize_runtime_gate_reason(reason: str) -> str:
    normalized = str(reason).strip()
    if not normalized:
        return RUNTIME_GATE_REASON_FALLBACK
    if normalized in RUNTIME_GATE_PASSTHROUGH_REASONS:
        return normalized
    if normalized in RUNTIME_GATE_VALIDATOR_REASONS:
        return RUNTIME_GATE_VALIDATOR_BUCKET
    if normalized.endswith(RUNTIME_GATE_CONTRACT_MISMATCH_SUFFIX):
        return RUNTIME_GATE_CONTRACT_MISMATCH_BUCKET
    return RUNTIME_GATE_REASON_FALLBACK


class ReleaseGateReport(_ReleaseGateModel):
    report_id: str = Field(min_length=1)
    report_hash: str = Field(min_length=1)
    sample_window: str = Field(min_length=1)
    shadow_window: str = Field(min_length=1)
    label_manifest: str = Field(min_length=1)
    generated_by: str = Field(min_length=1)
    report_approved_by: str = Field(min_length=1)
    artifact_ref: str = Field(min_length=1)
    expires_at: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    prompt_schema_ref: str = Field(min_length=1)
    output_schema_ref: str = Field(min_length=1)
    risk_policy_version: str = Field(min_length=1)
    decision_input_builder_version: str = Field(min_length=1)
    policy_engine_version: str = Field(min_length=1)
    tool_schema_hash: str = Field(min_length=1)
    memory_provider_adapter_hash: str = Field(min_length=1)
    input_hash: str = Field(min_length=1)
    runtime_contract_surface_ref: str = Field(min_length=1)
    runtime_gate_reason_taxonomy: RuntimeGateReasonTaxonomy
    shadow_decision_count: int | None = None
    certification_packet_count: int | None = None


def parse_release_gate_report(payload: dict[str, object]) -> ReleaseGateReport:
    if not isinstance(payload, dict):
        raise ValueError("release_gate_report payload must be a JSON object")
    if payload.get("runtime_contract_surface_ref") != DEFAULT_RUNTIME_CONTRACT_SURFACE_REF:
        raise ValueError("runtime_contract_surface_ref drifted from canonical source")
    if _canonical_json(payload.get("runtime_gate_reason_taxonomy")) != _canonical_json(
        DEFAULT_RUNTIME_GATE_REASON_TAXONOMY
    ):
        raise ValueError("runtime_gate_reason_taxonomy drifted from canonical taxonomy")
    report = ReleaseGateReport.model_validate(payload)
    return report


class ReleaseGateVerdict(_ReleaseGateModel):
    status: str = Field(min_length=1)
    decision_trace_ref: str = Field(min_length=1)
    approval_read_ref: str = Field(min_length=1)
    degrade_reason: str | None = None
    report_id: str = Field(min_length=1)
    report_hash: str = Field(min_length=1)
    input_hash: str = Field(min_length=1)


class ReleaseGateEvaluator:
    def evaluate(
        self,
        *,
        brain_intent: str,
        trace: DecisionTrace,
        validator_verdict: DecisionValidationVerdict,
        approval_read: ApprovalReadSnapshot | None = None,
        verdict: ReleaseGateVerdict | None = None,
        report: ReleaseGateReport | None = None,
        runtime_contract: dict[str, str] | None = None,
        now: str | None = None,
    ) -> ReleaseGateVerdict:
        if verdict is not None:
            return verdict
        input_hash = self._input_hash_for_trace(trace)
        approval_read_ref = (
            f"approval:event:{approval_read.approval_event_id}"
            if approval_read is not None
            else "approval:none"
        )
        if brain_intent != "propose_execute":
            return ReleaseGateVerdict(
                status="not_applicable",
                decision_trace_ref=trace.trace_id,
                approval_read_ref=approval_read_ref,
                report_id="report:not_applicable",
                report_hash="sha256:not_applicable",
                input_hash=input_hash,
            )
        if validator_verdict.status != "pass":
            return ReleaseGateVerdict(
                status="degraded",
                decision_trace_ref=trace.trace_id,
                approval_read_ref=approval_read_ref,
                degrade_reason=validator_verdict.reason or "validator_blocked",
                report_id="report:validator_gated",
                report_hash="sha256:validator_gated",
                input_hash=input_hash,
            )
        if report is not None:
            degrade_reason = self._degrade_reason_for_report(
                report=report,
                trace=trace,
                runtime_contract=runtime_contract or {},
                input_hash=input_hash,
                now=now,
            )
            if degrade_reason is not None:
                return ReleaseGateVerdict(
                    status="degraded",
                    decision_trace_ref=trace.trace_id,
                    approval_read_ref=approval_read_ref,
                    degrade_reason=degrade_reason,
                    report_id=report.report_id,
                    report_hash=report.report_hash,
                    input_hash=input_hash,
                )
        return ReleaseGateVerdict(
            status="pass",
            decision_trace_ref=trace.trace_id,
            approval_read_ref=approval_read_ref,
            report_id=report.report_id if report is not None else "report:resident_default",
            report_hash=(
                report.report_hash if report is not None else "sha256:resident_default"
            ),
            input_hash=input_hash,
        )

    @staticmethod
    def _input_hash_for_trace(trace: DecisionTrace) -> str:
        payload = trace.model_dump(mode="json")
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return f"sha256:{hashlib.sha256(serialized.encode('utf-8')).hexdigest()}"

    def _degrade_reason_for_report(
        self,
        *,
        report: ReleaseGateReport,
        trace: DecisionTrace,
        runtime_contract: dict[str, str],
        input_hash: str,
        now: str | None,
    ) -> str | None:
        current_time = self._parse_time(now)
        expires_at = self._parse_time(report.expires_at)
        if current_time is not None and expires_at is not None and current_time >= expires_at:
            return "report_expired"
        if report.input_hash != input_hash:
            return "input_hash_mismatch"
        field_pairs = {
            "provider": trace.provider,
            "model": trace.model,
            "prompt_schema_ref": trace.prompt_schema_ref,
            "output_schema_ref": trace.output_schema_ref,
            "risk_policy_version": runtime_contract.get("risk_policy_version"),
            "decision_input_builder_version": runtime_contract.get(
                "decision_input_builder_version"
            ),
            "policy_engine_version": runtime_contract.get("policy_engine_version"),
            "tool_schema_hash": runtime_contract.get("tool_schema_hash"),
            "memory_provider_adapter_hash": runtime_contract.get(
                "memory_provider_adapter_hash"
            ),
        }
        for field_name, expected in field_pairs.items():
            if expected is None:
                continue
            if str(getattr(report, field_name)) != str(expected):
                return f"{field_name}_mismatch"
        return None

    @staticmethod
    def _parse_time(value: str | None) -> datetime | None:
        if not value:
            return None
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
