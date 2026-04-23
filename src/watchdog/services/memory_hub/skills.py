from __future__ import annotations

from collections.abc import Iterable

from pydantic import Field, model_validator

from watchdog.services.memory_hub.contracts import SecurityVerdict, SkillSourceKind
from watchdog.services.memory_hub.models import _MemoryHubModel

_SOURCE_PRIORITY: dict[str, int] = {
    "local": 0,
    "shared": 1,
    "external": 2,
}


class SkillMetadata(_MemoryHubModel):
    name: str = Field(min_length=1)
    short_description: str = Field(min_length=1)
    trust_level: str = Field(min_length=1)
    security_verdict: SecurityVerdict
    content_hash: str = Field(min_length=1)
    installed_version: str | None = None
    last_scanned_at: str | None = None
    source_ref: str = Field(min_length=1)
    source_kind: SkillSourceKind
    read_only: bool | None = None

    @model_validator(mode="after")
    def _default_read_only(self) -> SkillMetadata:
        if self.read_only is None:
            object.__setattr__(self, "read_only", self.source_kind != "local")
        return self


class SkillRegistry:
    def __init__(self, *, records: Iterable[SkillMetadata] | None = None) -> None:
        self._records: dict[tuple[str, str], SkillMetadata] = {}
        for record in records or ():
            self.register(record)

    def register(self, record: SkillMetadata) -> SkillMetadata:
        key = (record.source_ref, record.content_hash)
        self._records[key] = record
        return record

    def list_metadata(self) -> list[SkillMetadata]:
        selected: dict[str, SkillMetadata] = {}
        for record in sorted(
            self._records.values(),
            key=lambda item: (_SOURCE_PRIORITY.get(item.source_kind, 99), item.name, item.source_ref),
        ):
            selected.setdefault(record.name, record)
        return list(selected.values())
