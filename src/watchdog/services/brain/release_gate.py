from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field

from watchdog.services.brain.models import ApprovalReadSnapshot, DecisionTrace
from watchdog.services.brain.validator import DecisionValidationVerdict


class _ReleaseGateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


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
        return ReleaseGateVerdict(
            status="pass",
            decision_trace_ref=trace.trace_id,
            approval_read_ref=approval_read_ref,
            report_id="report:resident_default",
            report_hash="sha256:resident_default",
            input_hash=input_hash,
        )

    @staticmethod
    def _input_hash_for_trace(trace: DecisionTrace) -> str:
        payload = trace.model_dump(mode="json")
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return f"sha256:{hashlib.sha256(serialized.encode('utf-8')).hexdigest()}"
