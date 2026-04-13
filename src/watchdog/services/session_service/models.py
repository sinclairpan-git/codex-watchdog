from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


CONTROLLED_SESSION_EVENT_TYPES = (
    "goal_contract_created",
    "goal_contract_revised",
    "goal_contract_adopted_by_child_session",
    "decision_proposed",
    "decision_validated",
    "command_created",
    "command_claimed",
    "command_lease_renewed",
    "command_claim_expired",
    "command_requeued",
    "command_executed",
    "command_failed",
    "approval_requested",
    "approval_approved",
    "approval_rejected",
    "approval_expired",
    "notification_announced",
    "notification_delivery_succeeded",
    "notification_delivery_failed",
    "notification_requeued",
    "notification_receipt_recorded",
    "interaction_context_superseded",
    "interaction_window_expired",
    "human_override_recorded",
    "memory_unavailable_degraded",
    "memory_conflict_detected",
    "stage_goal_conflict_detected",
    "recovery_tx_started",
    "handoff_packet_frozen",
    "child_session_created",
    "lineage_committed",
    "parent_session_closed_or_cooled",
    "recovery_tx_completed",
)

SESSION_LINEAGE_RELATIONS = (
    "supersedes",
    "forks_for_recovery",
    "forks_for_parallel_subtask",
    "resumes_after_interruption",
)

RECOVERY_TRANSACTION_STATUSES = (
    "started",
    "packet_frozen",
    "child_created",
    "lineage_pending",
    "lineage_committed",
    "parent_cooling",
    "completed",
    "failed_retryable",
    "failed_manual",
)


class _SessionServiceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SessionEventRecord(_SessionServiceModel):
    event_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    occurred_at: str = Field(min_length=1)
    causation_id: str | None = None
    correlation_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    related_ids: dict[str, str] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    log_seq: int | None = Field(default=None, ge=1)

    @field_validator("event_type")
    @classmethod
    def _validate_event_type(cls, value: str) -> str:
        if value not in CONTROLLED_SESSION_EVENT_TYPES:
            raise ValueError(f"unsupported session event type: {value}")
        return value


class SessionLineageRecord(_SessionServiceModel):
    lineage_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    parent_session_id: str = Field(min_length=1)
    child_session_id: str = Field(min_length=1)
    relation: str = Field(min_length=1)
    source_packet_id: str = Field(min_length=1)
    recovery_reason: str = Field(min_length=1)
    goal_contract_version: str = Field(min_length=1)
    recovery_transaction_id: str | None = None
    committed_at: str = Field(min_length=1)
    causation_id: str | None = None
    correlation_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    log_seq: int | None = Field(default=None, ge=1)

    @field_validator("relation")
    @classmethod
    def _validate_relation(cls, value: str) -> str:
        if value not in SESSION_LINEAGE_RELATIONS:
            raise ValueError(f"unsupported session lineage relation: {value}")
        return value


class RecoveryTransactionRecord(_SessionServiceModel):
    recovery_transaction_id: str = Field(min_length=1)
    recovery_key: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    parent_session_id: str = Field(min_length=1)
    child_session_id: str | None = None
    source_packet_id: str | None = None
    recovery_reason: str = Field(min_length=1)
    failure_family: str = Field(min_length=1)
    failure_signature: str = Field(min_length=1)
    status: str = Field(min_length=1)
    started_at: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)
    completed_at: str | None = None
    lineage_id: str | None = None
    causation_id: str | None = None
    correlation_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    log_seq: int | None = Field(default=None, ge=1)

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str) -> str:
        if value not in RECOVERY_TRANSACTION_STATUSES:
            raise ValueError(f"unsupported recovery transaction status: {value}")
        return value
