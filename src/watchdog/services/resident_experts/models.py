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
