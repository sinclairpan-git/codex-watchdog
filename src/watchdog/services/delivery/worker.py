from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from watchdog.services.delivery.envelopes import (
    SESSION_DIRECTORY_PROJECT_ID,
    SESSION_DIRECTORY_SESSION_ID,
)
from watchdog.services.delivery.models import DeliveryAttemptResult
from watchdog.services.delivery.store import DeliveryOutboxRecord, DeliveryOutboxStore
from watchdog.services.session_service.service import SessionService
from watchdog.services.session_spine.store import SessionSpineStore
from watchdog.settings import Settings


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _iso_z(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class DeliveryWorker:
    def __init__(
        self,
        *,
        store: DeliveryOutboxStore,
        delivery_client: Any,
        settings: Settings,
        session_spine_store: SessionSpineStore | None = None,
        session_service: SessionService | None = None,
    ) -> None:
        self._store = store
        self._delivery_client = delivery_client
        self._settings = settings
        self._session_spine_store = session_spine_store
        self._session_service = session_service

    @staticmethod
    def _notification_payload(record: DeliveryOutboxRecord) -> dict[str, Any] | None:
        payload = record.envelope_payload
        if payload.get("envelope_type") != "notification":
            return None
        return payload

    @staticmethod
    def _notification_related_ids(
        record: DeliveryOutboxRecord,
        payload: dict[str, Any],
        *,
        extra: dict[str, str] | None = None,
    ) -> dict[str, str]:
        related_ids = {"envelope_id": record.envelope_id}
        native_thread_id = str(record.effective_native_thread_id or "").strip()
        if native_thread_id:
            related_ids["native_thread_id"] = native_thread_id
        event_id = payload.get("event_id")
        if isinstance(event_id, str) and event_id:
            related_ids["notification_event_id"] = event_id
        notification_kind = payload.get("notification_kind")
        if isinstance(notification_kind, str) and notification_kind:
            related_ids["notification_kind"] = notification_kind
        for field in ("interaction_context_id", "interaction_family_id", "actor_id"):
            value = payload.get(field)
            if isinstance(value, str) and value:
                related_ids[field] = value
        if extra:
            related_ids.update(extra)
        return related_ids

    @staticmethod
    def _notification_payload_fields(
        record: DeliveryOutboxRecord,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        mirrored: dict[str, Any] = {
            "outbox_seq": record.outbox_seq,
            "delivery_status": record.delivery_status,
            "delivery_attempt": record.delivery_attempt,
        }
        for field in (
            "event_id",
            "notification_kind",
            "severity",
            "title",
            "summary",
            "reason",
            "audit_ref",
            "created_at",
            "occurred_at",
            "decision_result",
            "action_name",
            "interaction_context_id",
            "interaction_family_id",
            "actor_id",
            "channel_kind",
            "action_window_expires_at",
            "facts",
            "recommended_actions",
        ):
            value = payload.get(field)
            if value is not None:
                mirrored[field] = value
        return mirrored

    @staticmethod
    def _notification_announcement_payload_fields(
        record: DeliveryOutboxRecord,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        mirrored: dict[str, Any] = {
            "outbox_seq": record.outbox_seq,
            "delivery_status": "pending",
            "delivery_attempt": 0,
        }
        for field in (
            "event_id",
            "notification_kind",
            "severity",
            "title",
            "summary",
            "reason",
            "audit_ref",
            "created_at",
            "occurred_at",
            "decision_result",
            "action_name",
            "interaction_context_id",
            "interaction_family_id",
            "actor_id",
            "channel_kind",
            "action_window_expires_at",
            "facts",
            "recommended_actions",
        ):
            value = payload.get(field)
            if value is not None:
                mirrored[field] = value
        return mirrored

    def _record_notification_event(
        self,
        *,
        event_type: str,
        record: DeliveryOutboxRecord,
        payload: dict[str, Any],
        correlation_id: str,
        causation_id: str | None = None,
        related_ids: dict[str, str] | None = None,
        event_payload: dict[str, Any] | None = None,
        replay_safe: bool = False,
    ) -> None:
        if self._session_service is None:
            return
        recorder = (
            self._session_service.record_event_once
            if replay_safe and hasattr(self._session_service, "record_event_once")
            else self._session_service.record_event
        )
        recorder(
            event_type=event_type,
            project_id=record.project_id,
            session_id=record.session_id,
            occurred_at=_iso_z(datetime.now(UTC)),
            correlation_id=correlation_id,
            causation_id=causation_id,
            related_ids=self._notification_related_ids(
                record,
                payload,
                extra=related_ids,
            ),
            payload=event_payload
            or self._notification_payload_fields(record, payload),
        )

    def _record_notification_announced(
        self,
        *,
        record: DeliveryOutboxRecord,
        payload: dict[str, Any],
    ) -> None:
        announce_payload = self._notification_announcement_payload_fields(record, payload)
        announce_version = hashlib.sha256(
            json.dumps(
                announce_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:16]
        self._record_notification_event(
            event_type="notification_announced",
            record=record,
            payload=payload,
            correlation_id=f"corr:notification:{record.envelope_id}:announce:{announce_version}",
            causation_id=str(payload.get("event_id") or record.envelope_id),
            event_payload=announce_payload,
            replay_safe=True,
        )

    def _record_notification_delivery_result(
        self,
        *,
        record: DeliveryOutboxRecord,
        payload: dict[str, Any],
        result: DeliveryAttemptResult,
    ) -> None:
        attempt = record.delivery_attempt
        outcome_payload = self._notification_payload_fields(record, payload)
        outcome_payload.update(
            {
                "delivery_status": result.delivery_status,
                "accepted": result.accepted,
            }
        )
        if result.failure_code is not None:
            outcome_payload["failure_code"] = result.failure_code
        if result.status_code is not None:
            outcome_payload["status_code"] = result.status_code
        event_type = (
            "notification_delivery_succeeded"
            if result.delivery_status == "delivered"
            else "notification_delivery_failed"
        )
        self._record_notification_event(
            event_type=event_type,
            record=record,
            payload=payload,
            correlation_id=f"corr:notification:{record.envelope_id}:attempt:{attempt}",
            causation_id=str(payload.get("event_id") or record.envelope_id),
            event_payload=outcome_payload,
            replay_safe=True,
        )
        if result.receipt_id:
            receipt_payload = self._notification_payload_fields(record, payload)
            receipt_payload["receipt_id"] = result.receipt_id
            if result.received_at is not None:
                receipt_payload["received_at"] = result.received_at
            self._record_notification_event(
                event_type="notification_receipt_recorded",
                record=record,
                payload=payload,
                correlation_id=f"corr:notification:{record.envelope_id}:receipt:{result.receipt_id}",
                causation_id=str(payload.get("event_id") or record.envelope_id),
                related_ids={"receipt_id": result.receipt_id},
                event_payload=receipt_payload,
                replay_safe=True,
            )

    def _record_notification_requeued(
        self,
        *,
        record: DeliveryOutboxRecord,
        payload: dict[str, Any],
        reason: str,
        next_retry_at: str | None = None,
        failure_code: str | None = None,
    ) -> None:
        requeue_payload = self._notification_payload_fields(record, payload)
        requeue_payload["reason"] = reason
        if next_retry_at is not None:
            requeue_payload["next_retry_at"] = next_retry_at
        if failure_code is not None:
            requeue_payload["failure_code"] = failure_code
        retry_point = next_retry_at or f"attempt:{record.delivery_attempt}"
        self._record_notification_event(
            event_type="notification_requeued",
            record=record,
            payload=payload,
            correlation_id=f"corr:notification:{record.envelope_id}:requeue:{retry_point}",
            causation_id=str(payload.get("event_id") or record.envelope_id),
            event_payload=requeue_payload,
            replay_safe=True,
        )

    def _next_ready_record(
        self,
        *,
        now: datetime,
        session_id: str | None,
    ) -> DeliveryOutboxRecord | None:
        records = self._store.list_pending_delivery_records(session_id=session_id)
        if not records:
            return None
        if session_id is not None:
            head = records[0]
            next_retry = _parse_iso(head.next_retry_at)
            if next_retry is None or next_retry <= now:
                return head
            return None
        seen_sessions: set[str] = set()
        for record in records:
            if record.session_id in seen_sessions:
                continue
            next_retry = _parse_iso(record.next_retry_at)
            if next_retry is None or next_retry <= now:
                return record
            if record.failure_code == "suppressed_local_manual_activity":
                continue
            seen_sessions.add(record.session_id)
        return None

    def _apply_retryable_failure(
        self,
        *,
        record: DeliveryOutboxRecord,
        result: DeliveryAttemptResult,
        now: datetime,
    ) -> DeliveryOutboxRecord:
        attempt = record.delivery_attempt + 1
        if attempt >= self._settings.delivery_max_attempts:
            notes = list(record.operator_notes)
            notes.append(
                f"delivery_dead_letter failure_code={result.failure_code or 'unknown'} attempts={attempt}"
            )
            updated = record.model_copy(
                update={
                    "delivery_status": "delivery_failed",
                    "delivery_attempt": attempt,
                    "failure_code": result.failure_code,
                    "next_retry_at": None,
                    "operator_notes": notes,
                    "updated_at": _iso_z(now),
                }
            )
            return self._store.update_delivery_record(updated)
        delay = self._settings.delivery_initial_backoff_seconds * (2 ** (attempt - 1))
        next_retry_at = _iso_z(now + timedelta(seconds=delay))
        notes = list(record.operator_notes)
        notes.append(
            "delivery_retry_scheduled "
            f"failure_code={result.failure_code or 'unknown'} "
            f"attempts={attempt} next_retry_at={next_retry_at}"
        )
        updated = record.model_copy(
            update={
                "delivery_status": "retrying",
                "delivery_attempt": attempt,
                "failure_code": result.failure_code,
                "next_retry_at": next_retry_at,
                "operator_notes": notes,
                "updated_at": _iso_z(now),
            }
        )
        return self._store.update_delivery_record(updated)

    def _apply_stale_progress_summary(
        self,
        *,
        record: DeliveryOutboxRecord,
        occurred_at: str,
        age_seconds: int,
        now: datetime,
    ) -> DeliveryOutboxRecord:
        notes = list(record.operator_notes)
        notes.append(
            "delivery_skipped "
            "failure_code=stale_progress_summary "
            f"occurred_at={occurred_at} age_seconds={age_seconds}"
        )
        updated = record.model_copy(
            update={
                "delivery_status": "delivery_failed",
                "failure_code": "stale_progress_summary",
                "next_retry_at": None,
                "operator_notes": notes,
                "updated_at": _iso_z(now),
            }
        )
        return self._store.update_delivery_record(updated)

    def _apply_inactive_project_suppression(
        self,
        *,
        record: DeliveryOutboxRecord,
        reason: str,
        now: datetime,
    ) -> DeliveryOutboxRecord:
        notes = list(record.operator_notes)
        notes.append(f"delivery_skipped failure_code=inactive_project reason={reason}")
        updated = record.model_copy(
            update={
                "delivery_status": "delivery_failed",
                "failure_code": "inactive_project",
                "next_retry_at": None,
                "operator_notes": notes,
                "updated_at": _iso_z(now),
            }
        )
        return self._store.update_delivery_record(updated)

    def _apply_duplicate_delivery_suppression(
        self,
        *,
        record: DeliveryOutboxRecord,
        duplicate_of: str,
        now: datetime,
    ) -> DeliveryOutboxRecord:
        notes = list(record.operator_notes)
        notes.append(
            "delivery_skipped "
            "failure_code=duplicate_delivery_notice "
            f"duplicate_of={duplicate_of}"
        )
        updated = record.model_copy(
            update={
                "delivery_status": "delivery_failed",
                "failure_code": "duplicate_delivery_notice",
                "next_retry_at": None,
                "operator_notes": notes,
                "updated_at": _iso_z(now),
            }
        )
        return self._store.update_delivery_record(updated)

    def _apply_local_manual_activity_deferral(
        self,
        *,
        record: DeliveryOutboxRecord,
        last_local_manual_activity_at: str,
        age_seconds: int,
        next_retry_at: str,
        now: datetime,
    ) -> DeliveryOutboxRecord:
        notes = list(record.operator_notes)
        notes.append(
            "delivery_deferred "
            "failure_code=suppressed_local_manual_activity "
            f"last_local_manual_activity_at={last_local_manual_activity_at} "
            f"age_seconds={age_seconds} "
            f"next_retry_at={next_retry_at}"
        )
        updated = record.model_copy(
            update={
                "delivery_status": "retrying",
                "failure_code": "suppressed_local_manual_activity",
                "next_retry_at": next_retry_at,
                "operator_notes": notes,
                "updated_at": _iso_z(now),
            }
        )
        updated = self._store.update_delivery_record(updated)
        notification_payload = self._notification_payload(record)
        if notification_payload is not None:
            self._record_notification_requeued(
                record=updated,
                payload=notification_payload,
                reason="suppressed_local_manual_activity",
                next_retry_at=next_retry_at,
                failure_code="suppressed_local_manual_activity",
            )
        return updated

    def _stale_progress_summary(
        self,
        *,
        record: DeliveryOutboxRecord,
        now: datetime,
    ) -> tuple[str, int] | None:
        payload = record.envelope_payload
        if payload.get("envelope_type") != "notification":
            return None
        if payload.get("notification_kind") != "progress_summary":
            return None
        occurred_at = payload.get("occurred_at") or payload.get("created_at") or record.created_at
        parsed = _parse_iso(occurred_at)
        if parsed is None:
            return None
        age_seconds = int((now - parsed.astimezone(UTC)).total_seconds())
        if age_seconds <= max(self._settings.progress_summary_max_age_seconds, 0.0):
            return None
        return (occurred_at, age_seconds)

    @staticmethod
    def _record_fact_codes(session_record: object) -> set[str]:
        facts = getattr(session_record, "facts", None)
        if not isinstance(facts, list):
            return set()
        return {
            str(getattr(fact, "fact_code", "") or "").strip()
            for fact in facts
            if str(getattr(fact, "fact_code", "") or "").strip()
        }

    def _inactive_project_suppression_reason(
        self,
        *,
        record: DeliveryOutboxRecord,
        now: datetime,
    ) -> str | None:
        if self._session_spine_store is None:
            return None
        payload = record.envelope_payload if isinstance(record.envelope_payload, dict) else {}
        envelope_type = str(payload.get("envelope_type") or "").strip()
        notification_kind = str(payload.get("notification_kind") or "").strip()
        if envelope_type != "approval" and not (
            envelope_type == "notification" and notification_kind == "decision_result"
        ):
            return None
        try:
            session_record = self._session_spine_store.get(record.project_id)
        except Exception:
            return None
        if session_record is None:
            if envelope_type == "notification" and notification_kind == "decision_result":
                return None
            return "project_record_missing"
        fact_codes = self._record_fact_codes(session_record)
        if "project_not_active" in fact_codes:
            return "project_not_active"
        return None

    @staticmethod
    def _semantic_fact_signature(facts: Any) -> list[dict[str, str]]:
        if not isinstance(facts, list):
            return []
        normalized: list[dict[str, str]] = []
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            related_ids = fact.get("related_ids") if isinstance(fact.get("related_ids"), dict) else {}
            normalized.append(
                {
                    "fact_code": str(fact.get("fact_code") or "").strip(),
                    "fact_kind": str(fact.get("fact_kind") or "").strip(),
                    "severity": str(fact.get("severity") or "").strip(),
                    "summary": str(fact.get("summary") or "").strip(),
                    "detail": str(fact.get("detail") or "").strip(),
                    "source": str(fact.get("source") or "").strip(),
                    "project_execution_state": str(
                        related_ids.get("project_execution_state") or ""
                    ).strip(),
                }
            )
        return sorted(
            normalized,
            key=lambda item: (
                item["fact_code"],
                item["severity"],
                item["summary"],
                item["detail"],
                item["source"],
                item["project_execution_state"],
            ),
        )

    @staticmethod
    def _duplicate_delivery_fingerprint(record: DeliveryOutboxRecord) -> str | None:
        payload = record.envelope_payload if isinstance(record.envelope_payload, dict) else {}
        envelope_type = str(payload.get("envelope_type") or "").strip()
        if envelope_type == "approval":
            action_args = payload.get("requested_action_args")
            return json.dumps(
                [
                    "approval",
                    record.project_id,
                    record.session_id,
                    str(record.effective_native_thread_id or ""),
                    str(payload.get("receive_id") or "").strip(),
                    str(payload.get("receive_id_type") or "").strip(),
                    str(payload.get("requested_action") or "").strip(),
                    action_args if isinstance(action_args, dict) else {},
                    str(payload.get("reason") or payload.get("summary") or "").strip(),
                ],
                sort_keys=True,
                separators=(",", ":"),
            )
        if envelope_type == "notification":
            notification_kind = str(payload.get("notification_kind") or "").strip()
            if notification_kind != "decision_result":
                return None
            action_args = payload.get("action_args")
            return json.dumps(
                [
                    "notification",
                    notification_kind,
                    record.project_id,
                    record.session_id,
                    str(record.effective_native_thread_id or ""),
                    str(payload.get("receive_id") or "").strip(),
                    str(payload.get("receive_id_type") or "").strip(),
                    str(payload.get("decision_result") or "").strip(),
                    str(payload.get("action_name") or "").strip(),
                    action_args if isinstance(action_args, dict) else {},
                    str(payload.get("reason") or payload.get("summary") or "").strip(),
                    DeliveryWorker._semantic_fact_signature(payload.get("facts")),
                    payload.get("recommended_actions")
                    if isinstance(payload.get("recommended_actions"), list)
                    else [],
                ],
                sort_keys=True,
                separators=(",", ":"),
            )
        return None

    def _within_duplicate_suppression_window(
        self,
        *,
        record: DeliveryOutboxRecord,
        candidate: DeliveryOutboxRecord,
    ) -> bool:
        if self._uses_sticky_duplicate_suppression(record):
            return True
        window_seconds = max(
            self._settings.delivery_duplicate_suppression_window_seconds,
            0.0,
        )
        if window_seconds <= 0:
            return False
        record_created_at = _parse_iso(record.created_at)
        candidate_created_at = _parse_iso(candidate.created_at)
        if record_created_at is None or candidate_created_at is None:
            return False
        elapsed = abs(
            (
                record_created_at.astimezone(UTC)
                - candidate_created_at.astimezone(UTC)
            ).total_seconds()
        )
        return elapsed <= window_seconds

    @staticmethod
    def _uses_sticky_duplicate_suppression(record: DeliveryOutboxRecord) -> bool:
        payload = record.envelope_payload if isinstance(record.envelope_payload, dict) else {}
        if str(payload.get("envelope_type") or "").strip() != "notification":
            return False
        if str(payload.get("notification_kind") or "").strip() != "decision_result":
            return False
        if str(payload.get("decision_result") or "").strip() != "block_and_alert":
            return False
        reason = str(payload.get("reason") or payload.get("summary") or "").strip()
        return reason in {
            "brain observed state without proposing execution",
            "brain suggested a non-executing follow-up",
        }

    @staticmethod
    def _approval_id(record: DeliveryOutboxRecord) -> str:
        payload = record.envelope_payload if isinstance(record.envelope_payload, dict) else {}
        if str(payload.get("envelope_type") or "").strip() != "approval":
            return ""
        return str(payload.get("approval_id") or "").strip()

    def _current_pending_approval_ids(self, record: DeliveryOutboxRecord) -> set[str] | None:
        if self._session_spine_store is None:
            return set()
        try:
            session_record = self._session_spine_store.get(record.project_id)
        except Exception:
            return None
        if session_record is None:
            return set()
        approval_queue = getattr(session_record, "approval_queue", None)
        if not isinstance(approval_queue, list):
            return set()
        pending_ids: set[str] = set()
        for approval in approval_queue:
            approval_id = str(getattr(approval, "approval_id", "") or "").strip()
            status = str(getattr(approval, "status", "pending") or "").strip()
            if approval_id and status == "pending":
                pending_ids.add(approval_id)
        return pending_ids

    def _approval_duplicate_suppression_should_be_skipped(
        self,
        *,
        record: DeliveryOutboxRecord,
        candidate: DeliveryOutboxRecord,
    ) -> bool:
        record_approval_id = self._approval_id(record)
        candidate_approval_id = self._approval_id(candidate)
        if not record_approval_id or not candidate_approval_id:
            return False
        if record_approval_id == candidate_approval_id:
            return False
        pending_ids = self._current_pending_approval_ids(record)
        if pending_ids is None:
            return True
        if not pending_ids:
            return False
        return record_approval_id in pending_ids and candidate_approval_id not in pending_ids

    def _duplicate_delivered_record(self, record: DeliveryOutboxRecord) -> str | None:
        fingerprint = self._duplicate_delivery_fingerprint(record)
        if fingerprint is None:
            return None
        for candidate in self._store.list_records():
            if candidate.envelope_id == record.envelope_id:
                continue
            if candidate.delivery_status != "delivered":
                continue
            if self._duplicate_delivery_fingerprint(candidate) == fingerprint:
                if not self._within_duplicate_suppression_window(
                    record=record,
                    candidate=candidate,
                ):
                    continue
                if self._approval_duplicate_suppression_should_be_skipped(
                    record=record,
                    candidate=candidate,
                ):
                    continue
                return candidate.envelope_id
        return None

    @staticmethod
    def _suppressed_by_notification_policy(
        *,
        record: DeliveryOutboxRecord,
    ) -> str | None:
        payload = record.envelope_payload
        envelope_type = str(payload.get("envelope_type") or "").strip()
        if envelope_type == "decision":
            return "suppressed_notification_policy"
        if envelope_type != "notification":
            return None
        notification_kind = str(payload.get("notification_kind") or "").strip()
        if notification_kind == "decision_result" and not str(
            payload.get("decision_result") or ""
        ).strip():
            return "suppressed_notification_policy"
        return None

    def _apply_notification_policy_suppression(
        self,
        *,
        record: DeliveryOutboxRecord,
        failure_code: str,
        now: datetime,
    ) -> DeliveryOutboxRecord:
        notes = list(record.operator_notes)
        notes.append(
            f"delivery_skipped failure_code={failure_code} envelope_type={record.envelope_type}"
        )
        updated = record.model_copy(
            update={
                "delivery_status": "delivery_failed",
                "failure_code": failure_code,
                "next_retry_at": None,
                "operator_notes": notes,
                "updated_at": _iso_z(now),
            }
        )
        return self._store.update_delivery_record(updated)

    def _suppressed_for_local_manual_activity(
        self,
        *,
        record: DeliveryOutboxRecord,
        now: datetime,
    ) -> tuple[str, int, str] | None:
        if self._session_spine_store is None:
            return None
        payload = record.envelope_payload
        if payload.get("envelope_type") != "notification":
            return None
        severity = str(payload.get("severity") or "")
        if severity == "critical":
            return None
        notification_kind = str(payload.get("notification_kind") or "")
        if notification_kind not in {"progress_summary", "decision_result", "approval_result"}:
            return None
        try:
            session_record = self._session_spine_store.get(record.project_id)
        except Exception:
            return None
        if session_record is None:
            return None
        last_local_manual_activity_at = getattr(
            session_record,
            "last_local_manual_activity_at",
            None,
        )
        parsed = _parse_iso(last_local_manual_activity_at)
        if parsed is None:
            return None
        parsed_utc = parsed.astimezone(UTC)
        age_seconds = int((now - parsed_utc).total_seconds())
        if age_seconds < 0:
            return None
        quiet_window_seconds = max(self._settings.local_manual_activity_quiet_window_seconds, 0.0)
        if quiet_window_seconds <= 0:
            return None
        next_retry = parsed_utc + timedelta(seconds=quiet_window_seconds)
        if next_retry <= now:
            return None
        return (str(last_local_manual_activity_at), age_seconds, _iso_z(next_retry))

    def _apply_dynamic_delivery_route(
        self,
        *,
        record: DeliveryOutboxRecord,
        now: datetime,
    ) -> DeliveryOutboxRecord:
        transport = str(self._settings.delivery_transport or "").strip().lower()
        if transport not in {"feishu", "feishu-app"}:
            return record
        payload = dict(record.envelope_payload)
        existing_receive_id = str(payload.get("receive_id") or "").strip()
        existing_receive_id_type = str(payload.get("receive_id_type") or "").strip()
        static_receive_id = str(self._settings.feishu_receive_id or "").strip()
        if static_receive_id:
            receive_id_type = str(self._settings.feishu_receive_id_type or "").strip()
            if not receive_id_type:
                return record
            if (
                existing_receive_id == static_receive_id
                and existing_receive_id_type == receive_id_type
            ):
                return record
            payload["receive_id"] = static_receive_id
            payload["receive_id_type"] = receive_id_type
            notes = list(record.operator_notes)
            notes.append(
                "delivery_route_resolved "
                "source=settings "
                f"receive_id_type={receive_id_type}"
            )
            updated = record.model_copy(
                update={
                    "envelope_payload": payload,
                    "operator_notes": notes,
                    "updated_at": _iso_z(now),
                }
            )
            return self._store.update_delivery_record(updated)
        if existing_receive_id and existing_receive_id_type:
            return record
        if self._session_service is None:
            return record
        resolved = self._resolve_dynamic_delivery_route(record)
        if resolved is None:
            return record
        receive_id, receive_id_type, source_event_id = resolved
        payload["receive_id"] = receive_id
        payload["receive_id_type"] = receive_id_type
        notes = list(record.operator_notes)
        notes.append(
            "delivery_route_resolved "
            f"source_event_id={source_event_id} "
            f"receive_id_type={receive_id_type}"
        )
        updated = record.model_copy(
            update={
                "envelope_payload": payload,
                "operator_notes": notes,
                "updated_at": _iso_z(now),
            }
        )
        return self._store.update_delivery_record(updated)

    def _resolve_dynamic_delivery_route(
        self,
        record: DeliveryOutboxRecord,
    ) -> tuple[str, str, str] | None:
        if self._session_service is None or not hasattr(self._session_service, "list_events"):
            return None
        global_route = self._resolve_global_delivery_route()
        if (
            record.project_id == SESSION_DIRECTORY_PROJECT_ID
            and record.session_id == SESSION_DIRECTORY_SESSION_ID
        ):
            return global_route
        events = [
            event
            for event in self._session_service.list_events(session_id=record.session_id)
            if event.project_id == record.project_id
        ]
        if not events:
            return global_route
        scoped_events = self._scope_dynamic_route_candidate_events(events=events, record=record)
        scoped_route = self._resolve_dynamic_route_candidate_set(
            scoped_events,
            require_unique=scoped_events is events,
        )
        if scoped_route is not None:
            return scoped_route
        if scoped_events is events and self._has_dynamic_route_candidate(scoped_events):
            return None
        return global_route

    def _resolve_global_delivery_route(self) -> tuple[str, str, str] | None:
        if self._session_service is None or not hasattr(self._session_service, "list_events"):
            return None
        all_events = list(self._session_service.list_events())
        if not all_events:
            return None
        portfolio_events = [
            event
            for event in all_events
            if event.project_id == SESSION_DIRECTORY_PROJECT_ID
            and event.session_id == SESSION_DIRECTORY_SESSION_ID
        ]
        for candidate_events in (portfolio_events, all_events):
            if not candidate_events:
                continue
            candidate = self._resolve_dynamic_route_candidate_set(
                candidate_events,
                require_unique=False,
            )
            if candidate is not None:
                return candidate
        return None

    @staticmethod
    def _scope_dynamic_route_candidate_events(
        *,
        events: list,
        record: DeliveryOutboxRecord,
    ) -> list:
        payload = record.envelope_payload if isinstance(record.envelope_payload, dict) else {}
        interaction_family_id = str(payload.get("interaction_family_id") or "").strip()
        if interaction_family_id:
            family_events = [
                event
                for event in events
                if str(
                    (
                        event.related_ids if isinstance(event.related_ids, dict) else {}
                    ).get("interaction_family_id")
                    or ""
                ).strip()
                == interaction_family_id
            ]
            if family_events:
                return family_events
        actor_id = str(payload.get("actor_id") or "").strip()
        if actor_id:
            actor_events = [
                event
                for event in events
                if str(
                    (
                        event.related_ids if isinstance(event.related_ids, dict) else {}
                    ).get("feishu_actor_id")
                    or ""
                ).strip()
                == actor_id
            ]
            if actor_events:
                return actor_events
        return events

    @staticmethod
    def _resolve_dynamic_route_candidate_set(
        events: list,
        *,
        require_unique: bool = False,
    ) -> tuple[str, str, str] | None:
        for candidate in (
            DeliveryWorker._unique_route_candidate(
                events=events,
                value_key="feishu_receive_id",
                type_key="feishu_receive_id_type",
                default_type=None,
                require_unique=require_unique,
            ),
            DeliveryWorker._unique_route_candidate(
                events=events,
                value_key="feishu_chat_id",
                type_key=None,
                default_type="chat_id",
                require_unique=require_unique,
            ),
            DeliveryWorker._unique_route_candidate(
                events=events,
                value_key="feishu_actor_id",
                type_key=None,
                default_type="open_id",
                require_unique=require_unique,
            ),
        ):
            if candidate is not None:
                return candidate
        return None

    @staticmethod
    def _has_dynamic_route_candidate(events: list) -> bool:
        for event in events:
            related_ids = event.related_ids if isinstance(event.related_ids, dict) else {}
            for key in ("feishu_receive_id", "feishu_chat_id", "feishu_actor_id"):
                if str(related_ids.get(key) or "").strip():
                    return True
        return False

    @staticmethod
    def _unique_route_candidate(
        *,
        events: list,
        value_key: str,
        type_key: str | None,
        default_type: str | None,
        require_unique: bool,
    ) -> tuple[str, str, str] | None:
        selected: tuple[str, str, str] | None = None
        for event in reversed(events):
            related_ids = event.related_ids if isinstance(event.related_ids, dict) else {}
            receive_id = str(related_ids.get(value_key) or "").strip()
            if not receive_id:
                continue
            receive_id_type = (
                str(related_ids.get(type_key) or "").strip() if type_key is not None else ""
            )
            if not receive_id_type:
                receive_id_type = str(default_type or "").strip()
            if not receive_id_type:
                continue
            candidate = (receive_id, receive_id_type, event.event_id)
            if selected is None:
                selected = candidate
                continue
            if require_unique and candidate[:2] != selected[:2]:
                return None
        return selected

    def process_next_ready(
        self,
        *,
        now: datetime,
        session_id: str | None = None,
    ) -> DeliveryOutboxRecord | None:
        record = self._next_ready_record(now=now, session_id=session_id)
        if record is None:
            return None
        notification_payload = self._notification_payload(record)
        stale_progress = self._stale_progress_summary(record=record, now=now)
        if stale_progress is not None:
            occurred_at, age_seconds = stale_progress
            return self._apply_stale_progress_summary(
                record=record,
                occurred_at=occurred_at,
                age_seconds=age_seconds,
                now=now,
            )
        suppressed_by_policy = self._suppressed_by_notification_policy(record=record)
        if suppressed_by_policy is not None:
            return self._apply_notification_policy_suppression(
                record=record,
                failure_code=suppressed_by_policy,
                now=now,
            )
        inactive_project_reason = self._inactive_project_suppression_reason(
            record=record,
            now=now,
        )
        if inactive_project_reason is not None:
            return self._apply_inactive_project_suppression(
                record=record,
                reason=inactive_project_reason,
                now=now,
            )
        suppressed = self._suppressed_for_local_manual_activity(record=record, now=now)
        if suppressed is not None:
            last_local_manual_activity_at, age_seconds, next_retry_at = suppressed
            return self._apply_local_manual_activity_deferral(
                record=record,
                last_local_manual_activity_at=last_local_manual_activity_at,
                age_seconds=age_seconds,
                next_retry_at=next_retry_at,
                now=now,
            )
        record = self._apply_dynamic_delivery_route(record=record, now=now)
        notification_payload = self._notification_payload(record)
        duplicate_of = self._duplicate_delivered_record(record)
        if duplicate_of is not None:
            return self._apply_duplicate_delivery_suppression(
                record=record,
                duplicate_of=duplicate_of,
                now=now,
            )
        if notification_payload is not None:
            self._record_notification_announced(record=record, payload=notification_payload)
        result = self._delivery_client.deliver_record(record)
        if result.delivery_status == "delivered":
            notes = list(record.operator_notes)
            notes.append(
                "delivery_succeeded "
                f"receipt_id={result.receipt_id or ''} "
                f"attempts={record.delivery_attempt + 1}"
            )
            updated = record.model_copy(
                update={
                    "delivery_status": "delivered",
                    "delivery_attempt": record.delivery_attempt + 1,
                    "receipt_id": result.receipt_id,
                    "failure_code": None,
                    "next_retry_at": None,
                    "operator_notes": notes,
                    "updated_at": _iso_z(now),
                }
            )
            updated = self._store.update_delivery_record(updated)
            if notification_payload is not None:
                self._record_notification_delivery_result(
                    record=updated,
                    payload=notification_payload,
                    result=result,
                )
            return updated
        if result.delivery_status == "retryable_failure":
            updated = self._apply_retryable_failure(record=record, result=result, now=now)
            if notification_payload is not None:
                self._record_notification_delivery_result(
                    record=updated,
                    payload=notification_payload,
                    result=result,
                )
                if updated.delivery_status == "retrying":
                    self._record_notification_requeued(
                        record=updated,
                        payload=notification_payload,
                        reason="retryable_delivery_failure",
                        next_retry_at=updated.next_retry_at,
                        failure_code=result.failure_code,
                    )
            return updated
        notes = list(record.operator_notes)
        notes.append(
            f"delivery_failed failure_code={result.failure_code or 'unknown'} attempts={record.delivery_attempt + 1}"
        )
        updated = record.model_copy(
            update={
                "delivery_status": "delivery_failed",
                "delivery_attempt": record.delivery_attempt + 1,
                "failure_code": result.failure_code,
                "next_retry_at": None,
                "operator_notes": notes,
                "updated_at": _iso_z(now),
            }
        )
        updated = self._store.update_delivery_record(updated)
        if notification_payload is not None:
            self._record_notification_delivery_result(
                record=updated,
                payload=notification_payload,
                result=result,
            )
        return updated
