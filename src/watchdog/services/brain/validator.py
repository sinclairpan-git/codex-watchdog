from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DecisionValidationVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(min_length=1)
    reason: str | None = None


class DecisionValidator:
    def validate(self, *, status: str, reason: str | None = None) -> DecisionValidationVerdict:
        return DecisionValidationVerdict(status=status, reason=reason)

