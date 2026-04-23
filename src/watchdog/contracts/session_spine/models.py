from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from watchdog.contracts.session_spine.enums import (
    ActionCode,
    ActionStatus,
    AttentionState,
    Effect,
    EventCode,
    EventKind,
    ReplyCode,
    ReplyKind,
    SessionState,
    SupervisionReasonCode,
)
from watchdog.contracts.session_spine.versioning import (
    SESSION_EVENTS_CONTRACT_VERSION,
    SESSION_EVENTS_SCHEMA_VERSION,
    SESSION_SPINE_CONTRACT_VERSION,
    SESSION_SPINE_SCHEMA_VERSION,
)


class SessionSpineModel(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    contract_version: str = Field(default=SESSION_SPINE_CONTRACT_VERSION)
    schema_version: str = Field(default=SESSION_SPINE_SCHEMA_VERSION)


class SessionEventModel(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    contract_version: str = Field(default=SESSION_EVENTS_CONTRACT_VERSION)
    schema_version: str = Field(default=SESSION_EVENTS_SCHEMA_VERSION)


class SessionEvent(SessionEventModel):
    event_id: str
    event_code: EventCode
    event_kind: EventKind
    project_id: str
    thread_id: str
    native_thread_id: str | None = None
    source: str
    observed_at: str
    summary: str
    related_ids: dict[str, Any] = Field(default_factory=dict)
    attributes: dict[str, Any] = Field(default_factory=dict)


class FactRecord(SessionSpineModel):
    fact_id: str
    fact_code: str
    fact_kind: str
    severity: str
    summary: str
    detail: str
    source: str
    observed_at: str
    related_ids: dict[str, Any] = Field(default_factory=dict)


class ApprovalProjection(SessionSpineModel):
    approval_id: str
    project_id: str
    thread_id: str
    native_thread_id: str | None = None
    risk_level: str | None = None
    command: str
    reason: str
    alternative: str = ""
    status: str
    requested_at: str
    decided_at: str | None = None
    decided_by: str | None = None


class ContinuationDispatchResultView(SessionSpineModel):
    command_id: str | None = None
    decision_id: str | None = None
    action_ref: str | None = None
    status: str | None = None
    action_status: str | None = None
    reply_code: str | None = None
    decision_result: str | None = None
    observed_at: str | None = None
    receipt_ref: str | None = None


class ContinuationDispatchCooldownView(SessionSpineModel):
    action_ref: str | None = None
    checkpoint_state: str | None = None
    last_dispatched_at: str | None = None
    cooldown_seconds: float | None = None
    remaining_seconds: float | None = None
    active: bool = False


class ContinuationControlPlaneView(SessionSpineModel):
    continuation_identity: str | None = None
    identity_state: str | None = None
    branch_switch_token: str | None = None
    token_state: str | None = None
    consumed_at: str | None = None
    route_key: str | None = None
    packet_id: str | None = None
    packet_hash: str | None = None
    rendered_from_packet_id: str | None = None
    rendered_from_packet_hash: str | None = None
    last_dispatch_result: ContinuationDispatchResultView | None = None
    suppression_reason: str | None = None
    decision_source: str | None = None
    snapshot_version: str | None = None
    snapshot_epoch: str | None = None
    dispatch_cooldown: ContinuationDispatchCooldownView | None = None


class TaskProgressView(SessionSpineModel):
    project_id: str
    thread_id: str
    native_thread_id: str | None = None
    activity_phase: str
    summary: str
    goal_contract_version: str | None = None
    current_phase_goal: str | None = None
    last_user_instruction: str | None = None
    files_touched: list[str] = Field(default_factory=list)
    context_pressure: str
    stuck_level: int
    primary_fact_codes: list[str] = Field(default_factory=list)
    blocker_fact_codes: list[str] = Field(default_factory=list)
    last_progress_at: str | None = None
    recovery_outcome: str | None = None
    recovery_status: str | None = None
    recovery_updated_at: str | None = None
    recovery_child_session_id: str | None = None
    recovery_suppression_reason: str | None = None
    recovery_suppression_source: str | None = None
    recovery_suppression_observed_at: str | None = None
    decision_trace_ref: str | None = None
    decision_degrade_reason: str | None = None
    provider_output_schema_ref: str | None = None
    continuation_control_plane: ContinuationControlPlaneView | None = None


class ResidentExpertCoverageView(SessionSpineModel):
    coverage_status: str
    available_expert_count: int = 0
    bound_expert_count: int = 0
    restoring_expert_count: int = 0
    stale_expert_count: int = 0
    unavailable_expert_count: int = 0
    degraded_expert_ids: list[str] = Field(default_factory=list)
    latest_consultation_ref: str | None = None
    latest_consulted_at: str | None = None


class WorkspaceActivityView(SessionSpineModel):
    project_id: str
    thread_id: str
    native_thread_id: str | None = None
    recent_window_minutes: int
    cwd_exists: bool
    files_scanned: int
    latest_mtime_iso: str | None = None
    recent_change_count: int


class SessionProjection(SessionSpineModel):
    project_id: str
    thread_id: str
    native_thread_id: str | None = None
    session_state: SessionState
    activity_phase: str
    attention_state: AttentionState
    headline: str
    pending_approval_count: int
    available_intents: list[str] = Field(default_factory=list)


class SnapshotReadSemantics(SessionSpineModel):
    read_source: str
    is_persisted: bool
    is_fresh: bool
    is_stale: bool
    last_refreshed_at: str | None = None
    snapshot_age_seconds: float | None = None
    session_seq: int | None = None
    fact_snapshot_version: str | None = None


class ActionReceiptQuery(SessionSpineModel):
    action_code: ActionCode
    project_id: str
    approval_id: str | None = None
    idempotency_key: str = Field(min_length=1)


class ReplyModel(SessionSpineModel):
    reply_kind: ReplyKind
    reply_code: ReplyCode
    intent_code: str
    message: str
    session: SessionProjection | None = None
    sessions: list[SessionProjection] = Field(default_factory=list)
    progress: TaskProgressView | None = None
    progresses: list[TaskProgressView] = Field(default_factory=list)
    resident_expert_coverage: ResidentExpertCoverageView | None = None
    workspace_activity: WorkspaceActivityView | None = None
    action_result: WatchdogActionResult | None = None
    snapshot: SnapshotReadSemantics | None = None
    approvals: list[ApprovalProjection] = Field(default_factory=list)
    events: list[SessionEvent] = Field(default_factory=list)
    facts: list[FactRecord] = Field(default_factory=list)


class WatchdogAction(SessionSpineModel):
    action_code: ActionCode
    project_id: str
    operator: str
    idempotency_key: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    note: str = ""


class SupervisionEvaluation(SessionSpineModel):
    project_id: str
    thread_id: str
    native_thread_id: str | None = None
    evaluated_at: str
    reason_code: SupervisionReasonCode
    detail: str
    current_stuck_level: int
    next_stuck_level: int
    repo_recent_change_count: int
    threshold_minutes: float
    should_steer: bool
    steer_sent: bool


class WatchdogActionResult(SessionSpineModel):
    action_code: ActionCode
    project_id: str
    approval_id: str | None = None
    idempotency_key: str
    action_status: ActionStatus
    effect: Effect
    reply_code: ReplyCode | None = None
    message: str
    facts: list[FactRecord] = Field(default_factory=list)
    supervision_evaluation: SupervisionEvaluation | None = None
