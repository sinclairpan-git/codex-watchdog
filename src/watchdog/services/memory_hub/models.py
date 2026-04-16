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


class AIAutoSDLCCursorRequest(_MemoryHubModel):
    project_id: str = Field(min_length=1)
    repo_fingerprint: str = Field(min_length=1)
    stage: str = Field(min_length=1)
    task_kind: str = Field(min_length=1)
    capability_request: str = Field(min_length=1)
    requested_packet_kind: str = Field(min_length=1)
    active_goal: str | None = None
    current_phase_goal: str | None = None
    session_id: str | None = None


class AIAutoSDLCCursorGoalAlignment(_MemoryHubModel):
    status: str = Field(min_length=1)
    mode: str = Field(min_length=1)
    summary: str = Field(min_length=1)


class AIAutoSDLCCursorResponse(_MemoryHubModel):
    contract_name: str = Field(min_length=1)
    enabled: bool
    precedence: str = Field(min_length=1)
    requested_packet_kind: str = Field(min_length=1)
    request_context: dict[str, str | None] = Field(default_factory=dict)
    goal_alignment: AIAutoSDLCCursorGoalAlignment
    resident_capsule: list[dict[str, object]] = Field(default_factory=list)
    packet_inputs: dict[str, object] = Field(default_factory=dict)
    skills: list[dict[str, object]] = Field(default_factory=list)


class ProjectRegistration(_MemoryHubModel):
    project_id: str = Field(min_length=1)
    repo_root: str = Field(min_length=1)
    repo_fingerprint: str = Field(min_length=1)
    registered_at: str = Field(min_length=1)


class ResidentMemoryRecord(_MemoryHubModel):
    memory_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    memory_key: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    source_scope: str = Field(min_length=1)
    source_runtime: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)
