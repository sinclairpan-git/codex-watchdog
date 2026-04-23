from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _ResidentExpertModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResidentExpertDefinition(_ResidentExpertModel):
    expert_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    display_name_zh_cn: str = Field(min_length=1)
    layer: str = Field(min_length=1)
    independence: str = Field(min_length=1)
    role_summary: str = Field(min_length=1)
    consult_before: list[str] = Field(default_factory=list)
    focus_areas: list[str] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list)
    expected_output: list[str] = Field(default_factory=list)


ResidentExpertRuntimeStatus = Literal[
    "available",
    "bound",
    "stale",
    "unavailable",
    "restoring",
]


class ResidentExpertRuntimeBinding(_ResidentExpertModel):
    expert_id: str = Field(min_length=1)
    charter_source_ref: str = Field(min_length=1)
    charter_version_hash: str = Field(min_length=1)
    status: ResidentExpertRuntimeStatus
    runtime_handle: str | None = None
    last_seen_at: str | None = None
    last_consulted_at: str | None = None
    last_consultation_ref: str | None = None


class ResidentExpertRuntimeView(_ResidentExpertModel):
    expert_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    display_name_zh_cn: str = Field(min_length=1)
    layer: str = Field(min_length=1)
    independence: str = Field(min_length=1)
    role_summary: str = Field(min_length=1)
    consult_before: list[str] = Field(default_factory=list)
    focus_areas: list[str] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list)
    expected_output: list[str] = Field(default_factory=list)
    charter_source_ref: str = Field(min_length=1)
    charter_version_hash: str = Field(min_length=1)
    status: ResidentExpertRuntimeStatus
    runtime_handle_bound: bool = False
    oversight_ready: bool = False
    runtime_handle: str | None = None
    last_seen_at: str | None = None
    last_consulted_at: str | None = None
    last_consultation_ref: str | None = None


class ResidentExpertOpinion(_ResidentExpertModel):
    expert_id: str = Field(min_length=1)
    next_slice_recommendation: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    risks_to_avoid: list[str] = Field(default_factory=list)


class ResidentExpertConsultationSynthesis(_ResidentExpertModel):
    summary: str = Field(min_length=1)
    chosen_next_slice: str | None = None
    dissent_summary: str | None = None


class ResidentExpertConsultationRecord(_ResidentExpertModel):
    consultation_ref: str = Field(min_length=1)
    consulted_at: str = Field(min_length=1)
    opinions: list[ResidentExpertOpinion] = Field(default_factory=list)
    synthesis: ResidentExpertConsultationSynthesis | None = None
