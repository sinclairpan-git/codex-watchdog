from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _ProviderCertificationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InferenceProviderCertification(_ProviderCertificationModel):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    prompt_schema_ref: str = Field(min_length=1)
    output_schema_ref: str = Field(min_length=1)


class MemoryProviderAdapterCertification(_ProviderCertificationModel):
    adapter_name: str = Field(min_length=1)
    adapter_hash: str = Field(min_length=1)


class ProviderCompatibilityMatrix(_ProviderCertificationModel):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    prompt_schema_ref: str = Field(min_length=1)
    output_schema_ref: str = Field(min_length=1)
    tool_schema_hash: str = Field(min_length=1)
    risk_policy_version: str = Field(min_length=1)
    decision_input_builder_version: str = Field(min_length=1)
    policy_engine_version: str = Field(min_length=1)
    memory_provider_adapter_hash: str = Field(min_length=1)

