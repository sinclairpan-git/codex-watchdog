from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import yaml

from watchdog.services.resident_experts.models import (
    ResidentExpertConsultationRecord,
    ResidentExpertConsultationSynthesis,
    ResidentExpertDefinition,
    ResidentExpertOpinion,
    ResidentExpertRuntimeBinding,
    ResidentExpertRuntimeStatus,
    ResidentExpertRuntimeView,
)
from watchdog.services.resident_experts.store import (
    ResidentExpertConsultationStore,
    ResidentExpertRuntimeStore,
)

_REGISTRY_PATH = Path("docs/operations/resident-expert-agents.yaml")
_CHARTER_PATH = Path("docs/operations/resident-expert-agents.zh-CN.md")


def _utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    normalized = str(value).strip()
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _charter_version_hash(*, registry_text: str, charter_text: str) -> str:
    payload = f"{registry_text}\n---\n{charter_text}".encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


class ResidentExpertRuntimeService:
    def __init__(
        self,
        *,
        store: ResidentExpertRuntimeStore,
        consultation_store: ResidentExpertConsultationStore | None = None,
        repo_root: Path | None = None,
        registry_path: Path | None = None,
        charter_path: Path | None = None,
        stale_after_seconds: float = 900.0,
    ) -> None:
        self._store = store
        self._consultation_store = consultation_store
        self._repo_root = repo_root or _repo_root()
        self._registry_path = registry_path or (self._repo_root / _REGISTRY_PATH)
        self._charter_path = charter_path or (self._repo_root / _CHARTER_PATH)
        self._stale_after_seconds = max(float(stale_after_seconds), 0.0)
        registry_text = _read_text(self._registry_path)
        charter_text = _read_text(self._charter_path)
        self._charter_source_ref = ",".join(
            [
                str(_REGISTRY_PATH),
                str(_CHARTER_PATH),
            ]
        )
        self._charter_version_hash = _charter_version_hash(
            registry_text=registry_text,
            charter_text=charter_text,
        )
        payload = yaml.safe_load(registry_text) or {}
        resident_agents = payload.get("resident_expert_agents")
        if not isinstance(resident_agents, list):
            raise ValueError("resident_expert_agents registry missing list payload")
        self._definitions = tuple(
            ResidentExpertDefinition(
                expert_id=str(item.get("id") or "").strip(),
                name=str(item.get("name") or "").strip(),
                display_name_zh_cn=str(item.get("display_name_zh_cn") or "").strip(),
                layer=str(item.get("layer") or "").strip(),
                independence=str(item.get("independence") or "").strip(),
                role_summary=str(item.get("role_summary") or "").strip(),
                consult_before=[str(value).strip() for value in item.get("consult_before") or []],
                focus_areas=[str(value).strip() for value in item.get("focus_areas") or []],
                non_goals=[str(value).strip() for value in item.get("non_goals") or []],
                expected_output=[
                    str(value).strip() for value in item.get("expected_output") or []
                ],
            )
            for item in resident_agents
        )

    @classmethod
    def from_data_dir(
        cls,
        data_dir: str | Path,
        *,
        repo_root: Path | None = None,
        registry_path: Path | None = None,
        charter_path: Path | None = None,
        stale_after_seconds: float = 900.0,
    ) -> ResidentExpertRuntimeService:
        return cls(
            store=ResidentExpertRuntimeStore(Path(data_dir) / "resident_experts.json"),
            consultation_store=ResidentExpertConsultationStore(
                Path(data_dir) / "resident_expert_consultations.json"
            ),
            repo_root=repo_root,
            registry_path=registry_path,
            charter_path=charter_path,
            stale_after_seconds=stale_after_seconds,
        )

    def ensure_registry(self) -> list[ResidentExpertRuntimeBinding]:
        ensured: list[ResidentExpertRuntimeBinding] = []
        existing_by_id = {binding.expert_id: binding for binding in self._store.list_bindings()}
        for definition in self._definitions:
            existing = existing_by_id.get(definition.expert_id)
            status = "unavailable"
            runtime_handle = None
            last_seen_at = None
            last_consulted_at = None
            last_consultation_ref = None
            if existing is not None:
                runtime_handle = existing.runtime_handle
                last_seen_at = existing.last_seen_at
                last_consulted_at = existing.last_consulted_at
                last_consultation_ref = existing.last_consultation_ref
                if existing.charter_version_hash == self._charter_version_hash:
                    status = existing.status
                elif runtime_handle:
                    status = "restoring"
            binding = ResidentExpertRuntimeBinding(
                expert_id=definition.expert_id,
                charter_source_ref=self._charter_source_ref,
                charter_version_hash=self._charter_version_hash,
                status=status,
                runtime_handle=runtime_handle,
                last_seen_at=last_seen_at,
                last_consulted_at=last_consulted_at,
                last_consultation_ref=last_consultation_ref,
            )
            ensured.append(self._store.upsert_binding(binding))
        return ensured

    def bind_runtime_handle(
        self,
        *,
        expert_id: str,
        runtime_handle: str,
        observed_at: str | None = None,
    ) -> ResidentExpertRuntimeBinding:
        binding = self._require_binding(expert_id)
        updated = binding.model_copy(
            update={
                "runtime_handle": runtime_handle,
                "status": "bound",
                "last_seen_at": observed_at or _utcnow(),
            }
        )
        return self._store.upsert_binding(updated)

    def consult_or_restore(
        self,
        *,
        expert_ids: list[str] | None = None,
        consultation_ref: str | None = None,
        observed_runtime_handles: dict[str, str] | None = None,
        consulted_at: str | None = None,
    ) -> list[ResidentExpertRuntimeBinding]:
        now = consulted_at or _utcnow()
        now_dt = _parse_utc(now)
        self.ensure_registry()
        if expert_ids is None:
            requested_ids = [definition.expert_id for definition in self._definitions]
        else:
            requested_ids = []
            seen_ids: set[str] = set()
            for expert_id in expert_ids:
                normalized = str(expert_id or "").strip()
                if not normalized or normalized in seen_ids:
                    continue
                requested_ids.append(normalized)
                seen_ids.add(normalized)
        observed = {key: value for key, value in (observed_runtime_handles or {}).items() if value}
        updated: list[ResidentExpertRuntimeBinding] = []
        for expert_id in requested_ids:
            binding = self._require_binding(expert_id)
            next_status = binding.status
            runtime_handle = binding.runtime_handle
            last_seen_at = binding.last_seen_at
            observed_handle = observed.get(expert_id)
            if observed_handle:
                runtime_handle = observed_handle
                next_status = "available"
                last_seen_at = now
            elif runtime_handle:
                next_status = self._effective_status(binding, now=now_dt)
                if next_status != "stale":
                    next_status = "restoring"
            else:
                next_status = "unavailable"
            refreshed = binding.model_copy(
                update={
                    "runtime_handle": runtime_handle,
                    "status": next_status,
                    "last_seen_at": last_seen_at,
                    "last_consulted_at": now,
                    "last_consultation_ref": consultation_ref,
                }
            )
            updated.append(self._store.upsert_binding(refreshed))
        return updated

    def list_runtime_views(
        self,
        *,
        now: str | datetime | None = None,
    ) -> list[ResidentExpertRuntimeView]:
        self.ensure_registry()
        bindings = {binding.expert_id: binding for binding in self._store.list_bindings()}
        now_dt = _parse_utc(now)
        return [
            ResidentExpertRuntimeView(
                expert_id=definition.expert_id,
                name=definition.name,
                display_name_zh_cn=definition.display_name_zh_cn,
                layer=definition.layer,
                independence=definition.independence,
                role_summary=definition.role_summary,
                consult_before=list(definition.consult_before),
                focus_areas=list(definition.focus_areas),
                non_goals=list(definition.non_goals),
                expected_output=list(definition.expected_output),
                charter_source_ref=self._charter_source_ref,
                charter_version_hash=bindings[definition.expert_id].charter_version_hash,
                status=(status := self._effective_status(bindings[definition.expert_id], now=now_dt)),
                runtime_handle_bound=bool(bindings[definition.expert_id].runtime_handle),
                oversight_ready=(status == "available"),
                runtime_handle=bindings[definition.expert_id].runtime_handle,
                last_seen_at=bindings[definition.expert_id].last_seen_at,
                last_consulted_at=bindings[definition.expert_id].last_consulted_at,
                last_consultation_ref=bindings[definition.expert_id].last_consultation_ref,
            )
            for definition in self._definitions
        ]

    def record_consultation_payload(
        self,
        *,
        consultation_ref: str,
        consulted_at: str,
        opinions: list[ResidentExpertOpinion] | None = None,
        synthesis: ResidentExpertConsultationSynthesis | None = None,
    ) -> ResidentExpertConsultationRecord:
        if self._consultation_store is None:
            raise RuntimeError("resident expert consultation store is not configured")
        record = ResidentExpertConsultationRecord(
            consultation_ref=consultation_ref,
            consulted_at=consulted_at,
            opinions=list(opinions or []),
            synthesis=synthesis,
        )
        return self._consultation_store.upsert_consultation(record)

    def get_consultation_payload(
        self,
        consultation_ref: str,
    ) -> ResidentExpertConsultationRecord | None:
        if self._consultation_store is None:
            return None
        return self._consultation_store.get_consultation(consultation_ref)

    def _require_binding(self, expert_id: str) -> ResidentExpertRuntimeBinding:
        binding = self._store.get_binding(expert_id)
        if binding is None:
            self.ensure_registry()
            binding = self._store.get_binding(expert_id)
        if binding is None:
            raise KeyError(f"resident expert binding missing: {expert_id}")
        return binding

    def _effective_status(
        self,
        binding: ResidentExpertRuntimeBinding,
        *,
        now: datetime | None,
    ) -> ResidentExpertRuntimeStatus:
        if not binding.runtime_handle:
            return "unavailable"
        if self._is_stale(binding.last_seen_at, now=now):
            return "stale"
        if binding.status in {"available", "bound", "restoring"}:
            return binding.status
        return "bound"

    def _is_stale(self, value: str | None, *, now: datetime | None) -> bool:
        if self._stale_after_seconds <= 0:
            return False
        last_seen_at = _parse_utc(value)
        if last_seen_at is None or now is None:
            return False
        return (now - last_seen_at).total_seconds() >= self._stale_after_seconds
