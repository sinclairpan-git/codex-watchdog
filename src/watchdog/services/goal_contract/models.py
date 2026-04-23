from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _GoalContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GoalContractSnapshot(_GoalContractModel):
    contract_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    original_goal: str = Field(min_length=1)
    explicit_deliverables: list[str] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list)
    completion_signals: list[str] = Field(default_factory=list)
    inference_boundary: str = Field(min_length=1)
    constraints: list[str] = Field(default_factory=list)
    status: str = Field(min_length=1)
    current_phase_goal: str = Field(min_length=1)
    phase: str | None = None
    stage: str | None = None
    active_goal: str | None = None
    source_session_id: str | None = None
    provenance: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GoalContractReadiness(_GoalContractModel):
    mode: str = Field(min_length=1)
    missing_fields: list[str] = Field(default_factory=list)


class StageGoalAlignmentOutcome(_GoalContractModel):
    blocked: bool
    conflict_event_id: str | None = None
    conflict_summary: str = ""
