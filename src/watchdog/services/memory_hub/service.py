from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from watchdog.services.memory_hub.contracts import (
    MemoryFallbackMode,
    MemoryPreviewContractName,
    MemoryProviderOperation,
)
from watchdog.services.memory_hub.indexer import SessionSearchArchiveIndexer
from watchdog.services.memory_hub.models import (
    AIAutoSDLCCursorGoalAlignment,
    AIAutoSDLCCursorRequest,
    AIAutoSDLCCursorResponse,
    ContextQualitySnapshot,
    PacketInputRef,
    PreviewContract,
    ProjectRegistration,
    ResidentMemoryRecord,
    WorkerScopedPacketInput,
)
from watchdog.services.memory_hub.packets import build_packet_inputs
from watchdog.services.memory_hub.store import MemoryHubStore
from watchdog.services.memory_hub.skills import SkillMetadata, SkillRegistry


def _utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class MemoryHubService:
    def __init__(
        self,
        *,
        active_provider: str | None = None,
        store: MemoryHubStore | None = None,
        indexer: SessionSearchArchiveIndexer | None = None,
        skill_registry: SkillRegistry | None = None,
        preview_contract_overrides: dict[MemoryPreviewContractName, bool] | None = None,
    ) -> None:
        self.active_provider = active_provider
        self._store = store
        persisted_archive = [] if store is None else store.list_archive()
        persisted_skills = [] if store is None else store.list_skills()
        self._indexer = indexer or SessionSearchArchiveIndexer(persisted_archive)
        self._skill_registry = skill_registry or SkillRegistry(records=persisted_skills)
        self._resident_records: dict[str, ResidentMemoryRecord] = {
            record.memory_id: record
            for record in ([] if store is None else store.list_resident())
        }
        overrides = dict(preview_contract_overrides or {})
        self._preview_contracts: dict[MemoryPreviewContractName, PreviewContract] = {
            "user-model": PreviewContract(
                contract_name="user-model",
                enabled=bool(overrides.get("user-model", False)),
            ),
            "periodic-nudge": PreviewContract(
                contract_name="periodic-nudge",
                enabled=bool(overrides.get("periodic-nudge", False)),
            ),
            "ai-autosdlc-cursor": PreviewContract(
                contract_name="ai-autosdlc-cursor",
                enabled=bool(overrides.get("ai-autosdlc-cursor", False)),
            ),
        }

    @classmethod
    def from_data_dir(cls, data_dir: str | Path) -> MemoryHubService:
        return cls(store=MemoryHubStore(Path(data_dir) / "memory_hub.json"))

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

    def register_project(
        self,
        *,
        project_id: str,
        repo_root: str,
        repo_fingerprint: str,
    ) -> ProjectRegistration:
        record = ProjectRegistration(
            project_id=project_id,
            repo_root=repo_root,
            repo_fingerprint=repo_fingerprint,
            registered_at=_utcnow(),
        )
        if self._store is not None:
            self._store.upsert_project(record)
        return record

    def upsert_resident_memory(
        self,
        *,
        project_id: str,
        memory_key: str,
        summary: str,
        source_ref: str,
        source_scope: str,
        source_runtime: str,
    ) -> ResidentMemoryRecord:
        memory_id = f"{project_id}:{memory_key}"
        record = ResidentMemoryRecord(
            memory_id=memory_id,
            project_id=project_id,
            memory_key=memory_key,
            summary=summary,
            source_ref=source_ref,
            source_scope=source_scope,
            source_runtime=source_runtime,
            updated_at=_utcnow(),
        )
        self._resident_records[memory_id] = record
        if self._store is not None:
            self._store.upsert_resident(record)
        return record

    def resident_capsule(
        self,
        *,
        project_id: str | None = None,
    ) -> list[ResidentMemoryRecord]:
        records = list(self._resident_records.values())
        if project_id is not None:
            records = [record for record in records if record.project_id == project_id]
        records.sort(key=lambda record: (record.project_id, record.memory_key))
        return records

    def store_archive_entry(
        self,
        *,
        project_id: str,
        session_id: str,
        summary: str,
        source_ref: str,
        raw_content: str,
    ):
        from watchdog.services.memory_hub.indexer import ExpansionHandle, SessionArchiveEntry

        content_hash = f"sha256:{hashlib.sha256(raw_content.encode('utf-8')).hexdigest()}"
        entry_id = f"archive:{project_id}:{hashlib.sha256((session_id + source_ref + summary).encode('utf-8')).hexdigest()[:12]}"
        record = SessionArchiveEntry(
            entry_id=entry_id,
            project_id=project_id,
            session_id=session_id,
            summary=summary,
            source_ref=source_ref,
            content_hash=content_hash,
            raw_content=raw_content,
            expansion_handles=[
                ExpansionHandle(
                    handle_id=f"{entry_id}:raw",
                    source_ref=source_ref,
                    content_hash=content_hash,
                )
            ],
        )
        self._indexer.add_entry(record)
        if self._store is not None:
            self._store.append_archive(record)
        return record

    def ingest_session_event(self, event) -> None:
        payload = event.payload if isinstance(event.payload, dict) else {}
        summary_parts = [event.event_type]
        for key in ("current_phase_goal", "task_title", "status", "summary", "decision_reason"):
            value = str(payload.get(key) or "").strip()
            if value:
                summary_parts.append(value)
        summary = " ".join(summary_parts)
        raw_content = json.dumps(
            {
                "event_type": event.event_type,
                "related_ids": event.related_ids,
                "payload": event.payload,
                "occurred_at": event.occurred_at,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        source_ref = str(event.related_ids.get("source_ref") or event.event_id)
        self.store_archive_entry(
            project_id=event.project_id,
            session_id=event.session_id,
            summary=summary,
            source_ref=source_ref,
            raw_content=raw_content,
        )
        if event.event_type in {
            "goal_contract_created",
            "goal_contract_revised",
            "goal_contract_adopted_by_child_session",
        }:
            current_phase_goal = str(payload.get("current_phase_goal") or payload.get("task_title") or "").strip()
            if current_phase_goal:
                self.upsert_resident_memory(
                    project_id=event.project_id,
                    memory_key="goal.current",
                    summary=current_phase_goal,
                    source_ref=source_ref,
                    source_scope="project-local",
                    source_runtime="watchdog",
                )

    def preview_contracts(self) -> dict[MemoryPreviewContractName, PreviewContract]:
        return {
            name: contract.model_copy(deep=True)
            for name, contract in self._preview_contracts.items()
        }

    def ai_autosdlc_cursor(
        self,
        *,
        request: AIAutoSDLCCursorRequest,
        quality: ContextQualitySnapshot,
    ) -> AIAutoSDLCCursorResponse:
        contract = self._preview_contracts["ai-autosdlc-cursor"]
        goal_alignment = self._ai_autosdlc_goal_alignment(
            active_goal=request.active_goal,
            current_phase_goal=request.current_phase_goal,
        )
        refs = (
            []
            if not contract.enabled
            else self.search_session_archive(
                str(request.active_goal or request.capability_request),
                project_id=request.project_id,
                session_id=request.session_id,
                limit=4,
            )
        )
        resident_capsule = (
            []
            if not contract.enabled
            else [
                record.model_dump(mode="json")
                for record in self.resident_capsule(project_id=request.project_id)
            ]
        )
        skills = (
            []
            if not contract.enabled
            else [skill.model_dump(mode="json") for skill in self.list_skill_metadata()]
        )
        packet_inputs = (
            {"refs": [], "quality": quality.model_dump(mode="json")}
            if not contract.enabled
            else self.packet_inputs(refs=refs, quality=quality)
        )
        return AIAutoSDLCCursorResponse(
            contract_name=contract.contract_name,
            enabled=contract.enabled,
            precedence="session_service",
            requested_packet_kind=request.requested_packet_kind,
            request_context={
                "project_id": request.project_id,
                "repo_fingerprint": request.repo_fingerprint,
                "stage": request.stage,
                "task_kind": request.task_kind,
                "capability_request": request.capability_request,
                "active_goal": request.active_goal,
                "current_phase_goal": request.current_phase_goal,
                "session_id": request.session_id,
            },
            goal_alignment=goal_alignment,
            resident_capsule=resident_capsule,
            packet_inputs=packet_inputs,
            skills=skills,
        )

    @staticmethod
    def _ai_autosdlc_goal_alignment(
        *,
        active_goal: str | None,
        current_phase_goal: str | None,
    ) -> AIAutoSDLCCursorGoalAlignment:
        normalized_active_goal = str(active_goal or "").strip()
        normalized_current_goal = str(current_phase_goal or "").strip()
        if not normalized_current_goal:
            return AIAutoSDLCCursorGoalAlignment(
                status="missing_goal_contract",
                mode="reference_only",
                summary="goal contract current_phase_goal missing; stage context stays advisory only",
            )
        if normalized_active_goal and normalized_active_goal != normalized_current_goal:
            return AIAutoSDLCCursorGoalAlignment(
                status="conflict",
                mode="reference_only",
                summary=(
                    f"stage active_goal '{normalized_active_goal}' conflicts with current phase goal "
                    f"'{normalized_current_goal}'"
                ),
            )
        return AIAutoSDLCCursorGoalAlignment(
            status="aligned",
            mode="advisory",
            summary="stage context aligns with current goal contract",
        )

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

    def build_runtime_advisory_context(
        self,
        *,
        query: str,
        project_id: str | None = None,
        session_id: str | None = None,
        limit: int | None = None,
        quality: ContextQualitySnapshot,
        session_truth: dict[str, object] | None = None,
        memory_goal_candidate: str | None = None,
    ) -> dict[str, object]:
        refs = self.search_session_archive(
            query,
            project_id=project_id,
            session_id=session_id,
            limit=limit,
        )
        skills = [skill.model_dump(mode="json") for skill in self.list_skill_metadata()]
        payload: dict[str, object] = {
            "resident_capsule": [
                record.model_dump(mode="json")
                for record in self.resident_capsule(project_id=project_id)
            ],
            "packet_inputs": self.packet_inputs(refs=refs, quality=quality),
            "skills": skills,
            "precedence": "session_service",
        }
        current_phase_goal = str((session_truth or {}).get("current_phase_goal") or "").strip()
        if current_phase_goal:
            payload["goal_context"] = {
                "source": "session_service",
                "current_phase_goal": current_phase_goal,
            }
        elif memory_goal_candidate:
            payload["goal_context"] = {
                "source": "memory_hub",
                "current_phase_goal": memory_goal_candidate,
            }
        if (
            current_phase_goal
            and memory_goal_candidate
            and current_phase_goal.strip().lower() != memory_goal_candidate.strip().lower()
        ):
            payload["degradation"] = {
                "reason_code": "memory_conflict_detected",
                "resolution": "session_service_truth",
            }
        return payload
