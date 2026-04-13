from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


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
    def evaluate(self, *, verdict: ReleaseGateVerdict) -> ReleaseGateVerdict:
        return verdict

