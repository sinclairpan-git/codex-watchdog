from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _FutureWorkerModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FutureWorkerExecutionRequest(_FutureWorkerModel):
    project_id: str = Field(min_length=1)
    parent_session_id: str = Field(min_length=1)
    parent_native_thread_id: str | None = None
    worker_task_ref: str = Field(min_length=1)
    decision_trace_ref: str = Field(min_length=1)
    goal_contract_version: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    allowed_hands: list[str] = Field(default_factory=list)
    input_packet_refs: list[str] = Field(default_factory=list)
    retrieval_handles: list[str] = Field(default_factory=list)
    distilled_summary_ref: str = Field(min_length=1)
    execution_budget_ref: str = Field(min_length=1)
    worker_contract_version: str = Field(default="future-worker-contract:v1", min_length=1)


class FutureWorkerResultEnvelope(_FutureWorkerModel):
    worker_task_ref: str = Field(min_length=1)
    parent_session_id: str = Field(min_length=1)
    decision_trace_ref: str = Field(min_length=1)
    result_summary_ref: str = Field(min_length=1)
    artifact_refs: list[str] = Field(default_factory=list)
    input_contract_hash: str = Field(min_length=1)
    result_hash: str = Field(min_length=1)
    produced_at: str = Field(min_length=1)
    status: str = Field(min_length=1)
    worker_runtime_contract: dict[str, object] = Field(default_factory=dict)
