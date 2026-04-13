from __future__ import annotations

from collections.abc import Iterable

from pydantic import Field

from watchdog.services.memory_hub.models import ExpansionHandle, PacketInputRef, _MemoryHubModel


class SessionArchiveEntry(_MemoryHubModel):
    entry_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    raw_content: str = Field(min_length=1)
    expansion_handles: list[ExpansionHandle] = Field(default_factory=list)

    def to_packet_input_ref(self) -> PacketInputRef:
        return PacketInputRef(
            ref_id=self.entry_id,
            summary=self.summary,
            source_ref=self.source_ref,
            expansion_handles=[handle.handle_id for handle in self.expansion_handles],
        )


class SessionSearchArchiveIndexer:
    def __init__(self, entries: Iterable[SessionArchiveEntry] | None = None) -> None:
        self._entries = list(entries or [])

    def add_entry(self, entry: SessionArchiveEntry) -> None:
        self._entries.append(entry)

    def search(
        self,
        query: str,
        *,
        project_id: str | None = None,
        session_id: str | None = None,
        limit: int | None = None,
    ) -> list[PacketInputRef]:
        normalized = query.strip().lower()
        if not normalized:
            return []
        terms = normalized.split()
        matches = [
            entry
            for entry in self._entries
            if (project_id is None or entry.project_id == project_id)
            and (session_id is None or entry.session_id == session_id)
            and all(term in entry.summary.lower() for term in terms)
        ]
        if limit is not None:
            matches = matches[:limit]
        return [entry.to_packet_input_ref() for entry in matches]
