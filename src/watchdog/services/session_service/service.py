from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from watchdog.services.session_service.models import (
    RecoveryTransactionRecord,
    SessionEventRecord,
    SessionLineageRecord,
)
from watchdog.services.session_service.store import SessionServiceStore

_TERMINAL_RECOVERY_TRANSACTION_STATUSES = {
    "completed",
    "failed_retryable",
    "failed_manual",
}


def _utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stable_digest(*parts: object) -> str:
    material = "|".join(str(part).strip() for part in parts)
    return sha256(material.encode("utf-8")).hexdigest()[:16]


def _stable_id(prefix: str, *parts: object) -> str:
    return f"{prefix}:{_stable_digest(*parts)}"


@dataclass(frozen=True, slots=True)
class RecordedRecoveryExecution:
    recovery_transaction_id: str
    correlation_id: str
    parent_session_id: str
    child_session_id: str | None
    source_packet_id: str
    lineage_id: str | None


class SessionService:
    def __init__(self, store: SessionServiceStore) -> None:
        self._store = store

    @classmethod
    def from_data_dir(cls, data_dir: str | Path) -> SessionService:
        return cls(SessionServiceStore(Path(data_dir) / "session_service.json"))

    def list_events(self, **filters: Any) -> list[SessionEventRecord]:
        return self._store.list_events(**filters)

    def list_lineage(self, **filters: Any) -> list[SessionLineageRecord]:
        return self._store.list_lineage(**filters)

    def list_recovery_transactions(self, **filters: Any) -> list[RecoveryTransactionRecord]:
        return self._store.list_recovery_transactions(**filters)

    def record_event(
        self,
        *,
        event_type: str,
        project_id: str,
        session_id: str,
        correlation_id: str,
        payload: dict[str, Any],
        causation_id: str | None = None,
        related_ids: dict[str, str] | None = None,
        occurred_at: str | None = None,
    ) -> SessionEventRecord:
        return self._append_event(
            event_type=event_type,
            project_id=project_id,
            session_id=session_id,
            occurred_at=occurred_at or _utcnow(),
            causation_id=causation_id,
            correlation_id=correlation_id,
            related_ids=dict(related_ids or {}),
            payload=dict(payload),
        )

    def record_memory_unavailable_degraded(
        self,
        *,
        project_id: str,
        session_id: str,
        memory_scope: str,
        fallback_mode: str,
        degradation_reason: str,
        causation_id: str | None = None,
        related_ids: dict[str, str] | None = None,
        occurred_at: str | None = None,
    ) -> SessionEventRecord:
        event_related_ids = {"memory_scope": memory_scope}
        event_related_ids.update(dict(related_ids or {}))
        return self.record_event(
            event_type="memory_unavailable_degraded",
            project_id=project_id,
            session_id=session_id,
            correlation_id=_stable_id(
                "corr:memory-unavailable",
                session_id,
                memory_scope,
                degradation_reason,
                causation_id or "",
            ),
            causation_id=causation_id,
            related_ids=event_related_ids,
            occurred_at=occurred_at,
            payload={
                "fallback_mode": fallback_mode,
                "degradation_reason": degradation_reason,
            },
        )

    def record_memory_conflict_detected(
        self,
        *,
        project_id: str,
        session_id: str,
        memory_scope: str,
        conflict_reason: str,
        resolution: str,
        causation_id: str | None = None,
        related_ids: dict[str, str] | None = None,
        occurred_at: str | None = None,
    ) -> SessionEventRecord:
        event_related_ids = {"memory_scope": memory_scope}
        event_related_ids.update(dict(related_ids or {}))
        return self.record_event(
            event_type="memory_conflict_detected",
            project_id=project_id,
            session_id=session_id,
            correlation_id=_stable_id(
                "corr:memory-conflict",
                session_id,
                memory_scope,
                conflict_reason,
                resolution,
                causation_id or "",
            ),
            causation_id=causation_id,
            related_ids=event_related_ids,
            occurred_at=occurred_at,
            payload={
                "conflict_reason": conflict_reason,
                "resolution": resolution,
            },
        )

    def record_approval_expired(
        self,
        *,
        project_id: str,
        session_id: str,
        approval_id: str,
        decision_id: str,
        envelope_id: str,
        requested_action: str,
        expiration_reason: str,
        causation_id: str | None = None,
        occurred_at: str | None = None,
    ) -> SessionEventRecord:
        return self.record_event(
            event_type="approval_expired",
            project_id=project_id,
            session_id=session_id,
            correlation_id=f"corr:approval:{approval_id}",
            causation_id=causation_id,
            related_ids={
                "approval_id": approval_id,
                "decision_id": decision_id,
                "envelope_id": envelope_id,
            },
            occurred_at=occurred_at,
            payload={
                "approval_status": "expired",
                "requested_action": requested_action,
                "expiration_reason": expiration_reason,
            },
        )

    def record_recovery_execution(
        self,
        *,
        project_id: str,
        parent_session_id: str,
        parent_native_thread_id: str | None,
        recovery_reason: str,
        failure_family: str,
        failure_signature: str,
        handoff: dict[str, Any],
        resume: dict[str, Any] | None = None,
        resume_error: str | None = None,
        goal_contract_version: str = "goal-contract:unknown",
        source_packet_id: str | None = None,
    ) -> RecordedRecoveryExecution:
        handoff_file = str(handoff.get("handoff_file") or "").strip()
        handoff_summary = str(handoff.get("summary") or "").strip()
        if not handoff_file:
            raise ValueError("handoff.handoff_file is required")
        identity = (
            project_id,
            parent_session_id,
            parent_native_thread_id or "",
            recovery_reason,
            failure_family,
            failure_signature,
            handoff_file,
            handoff_summary,
        )
        recovery_transaction_id = _stable_id("recovery-tx", *identity)
        correlation_id = _stable_id("corr:recovery", recovery_transaction_id)
        source_packet_id = (
            str(source_packet_id or "").strip()
            or _stable_id("packet:handoff", recovery_transaction_id, handoff_file)
        )
        child_session_id = self._resolve_child_session_id(
            project_id=project_id,
            resume=resume,
            recovery_transaction_id=recovery_transaction_id,
        )
        lineage_id = (
            _stable_id("lineage", recovery_transaction_id, child_session_id)
            if child_session_id is not None
            else None
        )
        recovery_key = "|".join((parent_session_id, recovery_reason, failure_signature))
        self._assert_no_conflicting_active_recovery_transaction(
            parent_session_id=parent_session_id,
            recovery_key=recovery_key,
            recovery_transaction_id=recovery_transaction_id,
        )
        started_at = _utcnow()

        self._append_event(
            event_type="recovery_tx_started",
            project_id=project_id,
            session_id=parent_session_id,
            occurred_at=started_at,
            causation_id=None,
            correlation_id=correlation_id,
            related_ids={
                "recovery_transaction_id": recovery_transaction_id,
            },
            payload={
                "recovery_reason": recovery_reason,
                "failure_family": failure_family,
                "failure_signature": failure_signature,
                "parent_native_thread_id": parent_native_thread_id,
            },
        )
        self._append_recovery_status(
            recovery_transaction_id=recovery_transaction_id,
            recovery_key=recovery_key,
            project_id=project_id,
            parent_session_id=parent_session_id,
            child_session_id=None,
            source_packet_id=source_packet_id,
            recovery_reason=recovery_reason,
            failure_family=failure_family,
            failure_signature=failure_signature,
            status="started",
            started_at=started_at,
            updated_at=started_at,
            correlation_id=correlation_id,
            lineage_id=None,
            metadata={
                "parent_native_thread_id": parent_native_thread_id,
            },
        )

        packet_frozen_at = _utcnow()
        self._append_event(
            event_type="handoff_packet_frozen",
            project_id=project_id,
            session_id=parent_session_id,
            occurred_at=packet_frozen_at,
            causation_id=recovery_transaction_id,
            correlation_id=correlation_id,
            related_ids={
                "recovery_transaction_id": recovery_transaction_id,
                "source_packet_id": source_packet_id,
            },
            payload={
                "handoff_file": handoff_file,
                "summary": handoff_summary,
            },
        )
        self._append_recovery_status(
            recovery_transaction_id=recovery_transaction_id,
            recovery_key=recovery_key,
            project_id=project_id,
            parent_session_id=parent_session_id,
            child_session_id=None,
            source_packet_id=source_packet_id,
            recovery_reason=recovery_reason,
            failure_family=failure_family,
            failure_signature=failure_signature,
            status="packet_frozen",
            started_at=started_at,
            updated_at=packet_frozen_at,
            correlation_id=correlation_id,
            lineage_id=None,
            metadata={
                "handoff_file": handoff_file,
            },
        )

        if child_session_id is not None and lineage_id is not None and resume is not None:
            child_created_at = _utcnow()
            self._append_event(
                event_type="child_session_created",
                project_id=project_id,
                session_id=child_session_id,
                occurred_at=child_created_at,
                causation_id=recovery_transaction_id,
                correlation_id=correlation_id,
                related_ids={
                    "recovery_transaction_id": recovery_transaction_id,
                    "parent_session_id": parent_session_id,
                    "source_packet_id": source_packet_id,
                },
                payload=dict(resume),
            )
            self._append_recovery_status(
                recovery_transaction_id=recovery_transaction_id,
                recovery_key=recovery_key,
                project_id=project_id,
                parent_session_id=parent_session_id,
                child_session_id=child_session_id,
                source_packet_id=source_packet_id,
                recovery_reason=recovery_reason,
                failure_family=failure_family,
                failure_signature=failure_signature,
                status="child_created",
                started_at=started_at,
                updated_at=child_created_at,
                correlation_id=correlation_id,
                lineage_id=None,
                metadata=dict(resume),
            )
            lineage_pending_at = _utcnow()
            self._append_recovery_status(
                recovery_transaction_id=recovery_transaction_id,
                recovery_key=recovery_key,
                project_id=project_id,
                parent_session_id=parent_session_id,
                child_session_id=child_session_id,
                source_packet_id=source_packet_id,
                recovery_reason=recovery_reason,
                failure_family=failure_family,
                failure_signature=failure_signature,
                status="lineage_pending",
                started_at=started_at,
                updated_at=lineage_pending_at,
                correlation_id=correlation_id,
                lineage_id=lineage_id,
                metadata={
                    "goal_contract_version": goal_contract_version,
                },
            )
            lineage_committed_at = _utcnow()
            self._store.append_lineage(
                SessionLineageRecord(
                    lineage_id=lineage_id,
                    project_id=project_id,
                    parent_session_id=parent_session_id,
                    child_session_id=child_session_id,
                    relation="resumes_after_interruption",
                    source_packet_id=source_packet_id,
                    recovery_reason=recovery_reason,
                    goal_contract_version=goal_contract_version,
                    recovery_transaction_id=recovery_transaction_id,
                    committed_at=lineage_committed_at,
                    causation_id=recovery_transaction_id,
                    correlation_id=correlation_id,
                    idempotency_key=f"idem:lineage:{lineage_id}",
                    metadata={
                        "handoff_file": handoff_file,
                    },
                )
            )
            self._append_event(
                event_type="lineage_committed",
                project_id=project_id,
                session_id=child_session_id,
                occurred_at=lineage_committed_at,
                causation_id=recovery_transaction_id,
                correlation_id=correlation_id,
                related_ids={
                    "recovery_transaction_id": recovery_transaction_id,
                    "lineage_id": lineage_id,
                    "parent_session_id": parent_session_id,
                },
                payload={
                    "goal_contract_version": goal_contract_version,
                    "relation": "resumes_after_interruption",
                },
            )
            self._append_recovery_status(
                recovery_transaction_id=recovery_transaction_id,
                recovery_key=recovery_key,
                project_id=project_id,
                parent_session_id=parent_session_id,
                child_session_id=child_session_id,
                source_packet_id=source_packet_id,
                recovery_reason=recovery_reason,
                failure_family=failure_family,
                failure_signature=failure_signature,
                status="lineage_committed",
                started_at=started_at,
                updated_at=lineage_committed_at,
                correlation_id=correlation_id,
                lineage_id=lineage_id,
                metadata={
                    "goal_contract_version": goal_contract_version,
                },
            )
            parent_cooled_at = _utcnow()
            self._append_event(
                event_type="parent_session_closed_or_cooled",
                project_id=project_id,
                session_id=parent_session_id,
                occurred_at=parent_cooled_at,
                causation_id=recovery_transaction_id,
                correlation_id=correlation_id,
                related_ids={
                    "recovery_transaction_id": recovery_transaction_id,
                    "child_session_id": child_session_id,
                    "lineage_id": lineage_id,
                },
                payload={
                    "status": "cooled",
                },
            )
            self._append_recovery_status(
                recovery_transaction_id=recovery_transaction_id,
                recovery_key=recovery_key,
                project_id=project_id,
                parent_session_id=parent_session_id,
                child_session_id=child_session_id,
                source_packet_id=source_packet_id,
                recovery_reason=recovery_reason,
                failure_family=failure_family,
                failure_signature=failure_signature,
                status="parent_cooling",
                started_at=started_at,
                updated_at=parent_cooled_at,
                correlation_id=correlation_id,
                lineage_id=lineage_id,
                metadata={
                    "status": "cooled",
                },
            )
            completed_at = _utcnow()
            self._append_event(
                event_type="recovery_tx_completed",
                project_id=project_id,
                session_id=parent_session_id,
                occurred_at=completed_at,
                causation_id=recovery_transaction_id,
                correlation_id=correlation_id,
                related_ids={
                    "recovery_transaction_id": recovery_transaction_id,
                    "child_session_id": child_session_id,
                    "lineage_id": lineage_id,
                    "source_packet_id": source_packet_id,
                },
                payload={
                    "status": "completed",
                },
            )
            self._append_recovery_status(
                recovery_transaction_id=recovery_transaction_id,
                recovery_key=recovery_key,
                project_id=project_id,
                parent_session_id=parent_session_id,
                child_session_id=child_session_id,
                source_packet_id=source_packet_id,
                recovery_reason=recovery_reason,
                failure_family=failure_family,
                failure_signature=failure_signature,
                status="completed",
                started_at=started_at,
                updated_at=completed_at,
                completed_at=completed_at,
                correlation_id=correlation_id,
                lineage_id=lineage_id,
                metadata={
                    "resume_status": str(resume.get("status") or ""),
                },
            )
            return RecordedRecoveryExecution(
                recovery_transaction_id=recovery_transaction_id,
                correlation_id=correlation_id,
                parent_session_id=parent_session_id,
                child_session_id=child_session_id,
                source_packet_id=source_packet_id,
                lineage_id=lineage_id,
            )

        terminal_status = "failed_retryable" if resume_error else "completed"
        completed_at = _utcnow()
        self._append_event(
            event_type="recovery_tx_completed",
            project_id=project_id,
            session_id=parent_session_id,
            occurred_at=completed_at,
            causation_id=recovery_transaction_id,
            correlation_id=correlation_id,
            related_ids={
                "recovery_transaction_id": recovery_transaction_id,
                "source_packet_id": source_packet_id,
            },
            payload={
                "status": terminal_status,
                "resume_error": resume_error,
            },
        )
        self._append_recovery_status(
            recovery_transaction_id=recovery_transaction_id,
            recovery_key=recovery_key,
            project_id=project_id,
            parent_session_id=parent_session_id,
            child_session_id=None,
            source_packet_id=source_packet_id,
            recovery_reason=recovery_reason,
            failure_family=failure_family,
            failure_signature=failure_signature,
            status=terminal_status,
            started_at=started_at,
            updated_at=completed_at,
            completed_at=completed_at if terminal_status == "completed" else None,
            correlation_id=correlation_id,
            lineage_id=None,
            metadata={
                "resume_error": resume_error,
            },
        )
        return RecordedRecoveryExecution(
            recovery_transaction_id=recovery_transaction_id,
            correlation_id=correlation_id,
            parent_session_id=parent_session_id,
            child_session_id=None,
            source_packet_id=source_packet_id,
            lineage_id=None,
        )

    @staticmethod
    def _resolve_child_session_id(
        *,
        project_id: str,
        resume: dict[str, Any] | None,
        recovery_transaction_id: str,
    ) -> str | None:
        if resume is None:
            return None
        for key in ("session_id", "child_session_id"):
            value = str(resume.get(key) or "").strip()
            if value:
                return value
        native_thread_id = str(resume.get("thread_id") or resume.get("native_thread_id") or "").strip()
        if native_thread_id:
            return f"session:{project_id}:{native_thread_id}"
        return _stable_id("session", project_id, recovery_transaction_id, "child")

    def _append_event(
        self,
        *,
        event_type: str,
        project_id: str,
        session_id: str,
        occurred_at: str,
        causation_id: str | None,
        correlation_id: str,
        related_ids: dict[str, str],
        payload: dict[str, Any],
    ) -> SessionEventRecord:
        event_id = _stable_id("event", correlation_id, session_id, event_type)
        return self._store.append_event(
            SessionEventRecord(
                event_id=event_id,
                project_id=project_id,
                session_id=session_id,
                event_type=event_type,
                occurred_at=occurred_at,
                causation_id=causation_id,
                correlation_id=correlation_id,
                idempotency_key=f"idem:event:{event_id}",
                related_ids=related_ids,
                payload=payload,
            )
        )

    def _assert_no_conflicting_active_recovery_transaction(
        self,
        *,
        parent_session_id: str,
        recovery_key: str,
        recovery_transaction_id: str,
    ) -> None:
        records = self._store.list_recovery_transactions(parent_session_id=parent_session_id)
        matching_records = [
            record for record in records if record.recovery_key == recovery_key
        ]
        if not matching_records:
            return
        latest = max(matching_records, key=lambda record: record.log_seq or 0)
        if latest.recovery_transaction_id == recovery_transaction_id:
            return
        if latest.status in _TERMINAL_RECOVERY_TRANSACTION_STATUSES:
            return
        raise ValueError(
            "active recovery transaction already exists for recovery_key "
            f"{recovery_key}: {latest.recovery_transaction_id}"
        )

    def _append_recovery_status(
        self,
        *,
        recovery_transaction_id: str,
        recovery_key: str,
        project_id: str,
        parent_session_id: str,
        child_session_id: str | None,
        source_packet_id: str,
        recovery_reason: str,
        failure_family: str,
        failure_signature: str,
        status: str,
        started_at: str,
        updated_at: str,
        correlation_id: str,
        lineage_id: str | None,
        metadata: dict[str, Any],
        completed_at: str | None = None,
    ) -> RecoveryTransactionRecord:
        return self._store.append_recovery_transaction(
            RecoveryTransactionRecord(
                recovery_transaction_id=recovery_transaction_id,
                recovery_key=recovery_key,
                project_id=project_id,
                parent_session_id=parent_session_id,
                child_session_id=child_session_id,
                source_packet_id=source_packet_id,
                recovery_reason=recovery_reason,
                failure_family=failure_family,
                failure_signature=failure_signature,
                status=status,
                started_at=started_at,
                updated_at=updated_at,
                completed_at=completed_at,
                lineage_id=lineage_id,
                causation_id=recovery_transaction_id,
                correlation_id=correlation_id,
                idempotency_key=f"idem:recovery:{recovery_transaction_id}:{status}",
                metadata=metadata,
            )
        )
