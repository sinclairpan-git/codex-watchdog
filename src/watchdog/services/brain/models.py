from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _BrainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DecisionIntent(_BrainModel):
    intent: str = Field(min_length=1)
    rationale: str | None = None
    action_arguments: dict[str, object] = Field(default_factory=dict)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    continuation_decision: str | None = None
    routing_preference: str | None = None
    completion_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    next_branch_hypothesis: str | None = None
    continuation_identity: str | None = None
    route_key: str | None = None
    branch_switch_token: str | None = None
    target_work_item_seq: int | None = Field(default=None, ge=1)
    goal_coverage: str | None = None
    remaining_work_hypothesis: list[str] = Field(default_factory=list)
    evidence_codes: list[str] = Field(default_factory=list)
    provider: str = Field(default="resident_orchestrator", min_length=1)
    model: str = Field(default="rule-based-brain", min_length=1)
    prompt_schema_ref: str = Field(default="prompt:none", min_length=1)
    output_schema_ref: str = Field(default="schema:decision-trace-v1", min_length=1)
    provider_output_schema_ref: str | None = None
    provider_request_id: str | None = None
    degrade_reason: str | None = None


class DecisionPacketInput(_BrainModel):
    packet_version: str = Field(min_length=1)
    refs: list[dict[str, object]] = Field(default_factory=list)
    quality: dict[str, object] = Field(default_factory=dict)
    provenance: dict[str, object] = Field(default_factory=dict)
    freshness: dict[str, object] = Field(default_factory=dict)


class PCDIProjectRef(_BrainModel):
    project_id: str = Field(min_length=1)
    project_execution_state: str = Field(min_length=1)
    project_total_goal: str = Field(min_length=1)


class PCDIBranchRef(_BrainModel):
    active_work_item_id: str | None = None
    active_branch: str | None = None
    branch_goal: str = Field(min_length=1)
    branch_completion_signals: list[str] = Field(default_factory=list)
    next_work_item_seq: int | None = None
    next_branch_candidate: str | None = None
    target_work_item_seq: int | None = None


class PCDIProgressRef(_BrainModel):
    current_phase: str = Field(min_length=1)
    current_progress_summary: str = Field(min_length=1)
    files_touched: list[str] = Field(default_factory=list)
    remaining_tasks: list[str] = Field(default_factory=list)
    next_recommended_tasks: list[str] = Field(default_factory=list)


class PCDISessionRef(_BrainModel):
    session_id: str = Field(min_length=1)
    native_thread_id: str | None = None
    task_status: str = Field(min_length=1)
    available_intents: list[str] = Field(default_factory=list)


class PCDIGovernanceRef(_BrainModel):
    goal_contract_version: str = Field(min_length=1)
    goal_contract_readiness: str | None = None
    pending_approval: bool = False


class PCDIFreshnessRef(_BrainModel):
    snapshot_epoch: str = Field(min_length=1)
    snapshot_version: str = Field(min_length=1)
    snapshot_observed_at: str = Field(min_length=1)


class ProjectContinuationDecisionInput(_BrainModel):
    packet_version: str = Field(min_length=1)
    project_ref: PCDIProjectRef
    branch_ref: PCDIBranchRef
    progress_ref: PCDIProgressRef
    session_ref: PCDISessionRef
    governance_ref: PCDIGovernanceRef
    freshness_ref: PCDIFreshnessRef
    continuation_identity: str | None = None
    route_key: str | None = None
    branch_switch_token: str | None = None


class ApprovalReadSnapshot(_BrainModel):
    approval_event_id: str = Field(min_length=1)
    approval_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    requested_action: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    native_thread_id: str | None = None
    fact_snapshot_version: str = Field(min_length=1)
    goal_contract_version: str = Field(min_length=1)
    expires_at: str = Field(min_length=1)
    decided_by: str | None = None
    log_seq: int | None = Field(default=None, ge=1)

    @property
    def effective_native_thread_id(self) -> str | None:
        normalized = str(self.native_thread_id or "").strip()
        return normalized or None


class DecisionTrace(_BrainModel):
    trace_id: str = Field(min_length=1)
    session_event_cursor: str | None = None
    goal_contract_version: str = Field(min_length=1)
    policy_ruleset_hash: str = Field(min_length=1)
    memory_packet_input_ids: list[str] = Field(default_factory=list)
    memory_packet_input_hashes: list[str] = Field(default_factory=list)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    prompt_schema_ref: str = Field(min_length=1)
    output_schema_ref: str = Field(min_length=1)
    provider_output_schema_ref: str | None = None
    approval_read: ApprovalReadSnapshot | None = None
    degrade_reason: str | None = None


class ReplayResult(_BrainModel):
    replay_mode: str = Field(min_length=1)
    replay_incomplete: bool = False
    drift_detected: bool = False
    missing_context: list[str] = Field(default_factory=list)
    failure_reasons: list[str] = Field(default_factory=list)


class FutureWorkerTraceRef(_BrainModel):
    parent_session_id: str = Field(min_length=1)
    worker_task_ref: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    allowed_hands: list[str] = Field(default_factory=list)
    input_packet_refs: list[str] = Field(default_factory=list)
    retrieval_handles: list[str] = Field(default_factory=list)
    distilled_summary_ref: str = Field(min_length=1)
    decision_trace_ref: str = Field(min_length=1)
