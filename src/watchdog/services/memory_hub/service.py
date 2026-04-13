from __future__ import annotations

from watchdog.services.memory_hub.contracts import (
    MemoryFallbackMode,
    MemoryPreviewContractName,
    MemoryProviderOperation,
)
from watchdog.services.memory_hub.indexer import SessionSearchArchiveIndexer
from watchdog.services.memory_hub.models import ContextQualitySnapshot, PacketInputRef, PreviewContract, WorkerScopedPacketInput
from watchdog.services.memory_hub.packets import build_packet_inputs
from watchdog.services.memory_hub.skills import SkillMetadata, SkillRegistry


class MemoryHubService:
    def __init__(
        self,
        *,
        active_provider: str | None = None,
        indexer: SessionSearchArchiveIndexer | None = None,
        skill_registry: SkillRegistry | None = None,
    ) -> None:
        self.active_provider = active_provider
        self._indexer = indexer or SessionSearchArchiveIndexer()
        self._skill_registry = skill_registry or SkillRegistry()
        self._preview_contracts: dict[MemoryPreviewContractName, PreviewContract] = {
            "user-model": PreviewContract(contract_name="user-model"),
            "periodic-nudge": PreviewContract(contract_name="periodic-nudge"),
            "ai-autosdlc-cursor": PreviewContract(contract_name="ai-autosdlc-cursor"),
        }

    def supported_operations(self) -> tuple[MemoryProviderOperation, ...]:
        return ("search", "store", "manage")

    def activate_provider(self, provider_name: str | None) -> None:
        self.active_provider = provider_name

    def provider_memory_ops(self) -> tuple[MemoryProviderOperation, ...]:
        return self.supported_operations()

    def search_session_archive(
        self,
        query: str,
        *,
        project_id: str | None = None,
        session_id: str | None = None,
        limit: int | None = None,
    ) -> list[PacketInputRef]:
        return self._indexer.search(
            query,
            project_id=project_id,
            session_id=session_id,
            limit=limit,
        )

    def list_skill_metadata(self) -> list[SkillMetadata]:
        return self._skill_registry.list_metadata()

    def preview_contracts(self) -> dict[MemoryPreviewContractName, PreviewContract]:
        return {
            name: contract.model_copy(deep=True)
            for name, contract in self._preview_contracts.items()
        }

    def packet_inputs(
        self,
        *,
        refs: list[PacketInputRef],
        quality: ContextQualitySnapshot,
        worker_scope: WorkerScopedPacketInput | None = None,
    ) -> dict[str, object]:
        return build_packet_inputs(refs=refs, quality=quality, worker_scope=worker_scope)

    def resolve_fallback_mode(
        self,
        *,
        reason_code: str,
    ) -> MemoryFallbackMode:
        if reason_code in {"conflict", "security_blocked", "skill_incompatible"}:
            return "reference_only"
        return "session_service_runtime_snapshot"
