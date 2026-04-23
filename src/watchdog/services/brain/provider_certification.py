from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from watchdog.settings import Settings


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


class ProviderCompatibilityEvaluator:
    _FIELDS = (
        "provider",
        "model",
        "prompt_schema_ref",
        "output_schema_ref",
        "tool_schema_hash",
        "risk_policy_version",
        "decision_input_builder_version",
        "policy_engine_version",
        "memory_provider_adapter_hash",
    )

    def compare(
        self,
        *,
        matrix: ProviderCompatibilityMatrix,
        runtime_contract: dict[str, str],
    ) -> list[str]:
        mismatches: list[str] = []
        for field_name in self._FIELDS:
            expected = str(getattr(matrix, field_name))
            actual = str(runtime_contract.get(field_name, ""))
            if actual != expected:
                mismatches.append(field_name)
        return mismatches


def build_runtime_contract(
    *,
    settings: Settings,
    provider: str,
    model: str,
    prompt_schema_ref: str,
    output_schema_ref: str,
    memory_provider_adapter_hash: str | None = None,
) -> dict[str, str]:
    return settings.build_runtime_contract(
        provider=provider,
        model=model,
        prompt_schema_ref=prompt_schema_ref,
        output_schema_ref=output_schema_ref,
        memory_provider_adapter_hash=memory_provider_adapter_hash,
    )
