from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _MemoryHubModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExpansionHandle(_MemoryHubModel):
    handle_id: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)


class PacketInputRef(_MemoryHubModel):
    ref_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    expansion_handles: list[str] = Field(default_factory=list)


class ContextQualitySnapshot(_MemoryHubModel):
    key_fact_recall: float = Field(ge=0.0, le=1.0)
    irrelevant_summary_precision: float = Field(ge=0.0, le=1.0)
    token_budget_utilization: float = Field(ge=0.0)
    expansion_miss_rate: float = Field(ge=0.0, le=1.0)


class WorkerScopedPacketInput(_MemoryHubModel):
    scope: str = Field(min_length=1)
    parent_session_id: str = Field(min_length=1)
    worker_task_ref: str = Field(min_length=1)
    retrieval_handles: list[str] = Field(default_factory=list)
    distilled_summary_ref: str = Field(min_length=1)


class PreviewContract(_MemoryHubModel):
    contract_name: str = Field(min_length=1)
    enabled: bool = False
