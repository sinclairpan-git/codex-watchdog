from __future__ import annotations

import fcntl
import os
import threading
import uuid
from contextlib import contextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from watchdog.services.session_service.service import SessionService

_PATH_LOCKS: dict[str, threading.Lock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


def _path_lock(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _PATH_LOCKS_GUARD:
        existing = _PATH_LOCKS.get(key)
        if existing is not None:
            return existing
        created = threading.Lock()
        _PATH_LOCKS[key] = created
        return created


def _parse_timestamp(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class CommandLeaseEvent(BaseModel):
    event_id: str
    command_id: str
    session_id: str
    event_type: str
    occurred_at: str
    claim_seq: int
    worker_id: str | None = None
    lease_expires_at: str | None = None
    reason: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class CommandLeaseState(BaseModel):
    command_id: str
    session_id: str
    status: str
    claim_seq: int = 0
    worker_id: str | None = None
    lease_expires_at: str | None = None
    updated_at: str


class _CommandLeaseFile(BaseModel):
    next_event_seq: int = 1
    commands: dict[str, CommandLeaseState] = Field(default_factory=dict)
    events: list[CommandLeaseEvent] = Field(default_factory=list)


class CommandLeaseStore:
    def __init__(
        self,
        path: Path,
        *,
        session_service: SessionService | None = None,
    ) -> None:
        self._path = path
        self._lock = _path_lock(path)
        self._lock_path = path.with_name(f".{path.name}.lock")
        self._session_service = session_service
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._guard_io():
            if not self._path.exists():
                self._write(_CommandLeaseFile())

    @contextmanager
    def _guard_io(self):
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def _read(self) -> _CommandLeaseFile:
        raw = self._path.read_text(encoding="utf-8")
        if not raw.strip():
            return _CommandLeaseFile()
        return _CommandLeaseFile.model_validate_json(raw)

    def _write(self, data: _CommandLeaseFile) -> None:
        tmp = self._path.with_name(f"{self._path.name}.{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_text(data.model_dump_json(indent=2), encoding="utf-8")
            tmp.replace(self._path)
        finally:
            with suppress(FileNotFoundError):
                tmp.unlink()

    def _append_event(
        self,
        data: _CommandLeaseFile,
        *,
        command_id: str,
        session_id: str,
        event_type: str,
        occurred_at: str,
        claim_seq: int,
        worker_id: str | None,
        lease_expires_at: str | None,
        reason: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> CommandLeaseEvent:
        event = CommandLeaseEvent(
            event_id=f"command-event:{data.next_event_seq}",
            command_id=command_id,
            session_id=session_id,
            event_type=event_type,
            occurred_at=occurred_at,
            claim_seq=claim_seq,
            worker_id=worker_id,
            lease_expires_at=lease_expires_at,
            reason=reason,
            payload=dict(payload or {}),
        )
        data.next_event_seq += 1
        data.events.append(event)
        return event

    @staticmethod
    def _session_correlation_id(event: CommandLeaseEvent) -> str:
        if event.event_type == "command_lease_renewed" and event.lease_expires_at:
            return (
                f"corr:command:{event.command_id}:claim:{event.claim_seq}:"
                f"renew:{event.lease_expires_at}"
            )
        return f"corr:command:{event.command_id}:claim:{event.claim_seq}"

    def _mirror_event_to_session_service(self, event: CommandLeaseEvent) -> None:
        if self._session_service is None:
            return
        payload = dict(event.payload)
        if event.worker_id is not None:
            payload["worker_id"] = event.worker_id
        if event.lease_expires_at is not None:
            payload["lease_expires_at"] = event.lease_expires_at
        if event.reason is not None:
            payload["reason"] = event.reason
        self._session_service.record_event(
            event_type=event.event_type,
            project_id=event.session_id.removeprefix("session:"),
            session_id=event.session_id,
            occurred_at=event.occurred_at,
            correlation_id=self._session_correlation_id(event),
            causation_id=event.command_id,
            related_ids={
                "command_id": event.command_id,
                "claim_seq": str(event.claim_seq),
            },
            payload=payload,
        )

    def _mirror_events_to_session_service(self, events: list[CommandLeaseEvent]) -> None:
        for event in events:
            self._mirror_event_to_session_service(event)

    @staticmethod
    def _require_current_claim(
        state: CommandLeaseState | None,
        *,
        command_id: str,
        worker_id: str,
        claim_seq: int,
    ) -> CommandLeaseState:
        if state is None:
            raise ValueError(f"unknown command: {command_id}")
        if (
            state.status != "claimed"
            or state.worker_id != worker_id
            or state.claim_seq != claim_seq
        ):
            raise ValueError(f"stale claim for {command_id}")
        return state

    def get_command(self, command_id: str) -> CommandLeaseState | None:
        with self._guard_io():
            data = self._read()
            return data.commands.get(command_id)

    def list_events(self, *, command_id: str | None = None) -> list[CommandLeaseEvent]:
        with self._guard_io():
            data = self._read()
        if command_id is None:
            return list(data.events)
        return [event for event in data.events if event.command_id == command_id]

    def claim_command(
        self,
        *,
        command_id: str,
        session_id: str,
        worker_id: str,
        claimed_at: str,
        lease_expires_at: str,
    ) -> CommandLeaseEvent:
        with self._guard_io():
            data = self._read()
            existing = data.commands.get(command_id)
            if existing is not None:
                if existing.session_id != session_id:
                    raise ValueError(f"command {command_id} belongs to another session")
                if existing.status == "claimed":
                    raise ValueError(f"command {command_id} is already claimed")
                if existing.status in {"executed", "failed"}:
                    raise ValueError(f"command {command_id} is already terminal")
                claim_seq = existing.claim_seq + 1
            else:
                claim_seq = 1
            event = self._append_event(
                data,
                command_id=command_id,
                session_id=session_id,
                event_type="command_claimed",
                occurred_at=claimed_at,
                claim_seq=claim_seq,
                worker_id=worker_id,
                lease_expires_at=lease_expires_at,
            )
            data.commands[command_id] = CommandLeaseState(
                command_id=command_id,
                session_id=session_id,
                status="claimed",
                claim_seq=claim_seq,
                worker_id=worker_id,
                lease_expires_at=lease_expires_at,
                updated_at=claimed_at,
            )
            self._mirror_events_to_session_service([event])
            self._write(data)
        return event

    def renew_lease(
        self,
        *,
        command_id: str,
        worker_id: str,
        claim_seq: int,
        renewed_at: str,
        lease_expires_at: str,
    ) -> CommandLeaseEvent:
        with self._guard_io():
            data = self._read()
            state = self._require_current_claim(
                data.commands.get(command_id),
                command_id=command_id,
                worker_id=worker_id,
                claim_seq=claim_seq,
            )
            event = self._append_event(
                data,
                command_id=command_id,
                session_id=state.session_id,
                event_type="command_lease_renewed",
                occurred_at=renewed_at,
                claim_seq=claim_seq,
                worker_id=worker_id,
                lease_expires_at=lease_expires_at,
            )
            data.commands[command_id] = state.model_copy(
                update={
                    "lease_expires_at": lease_expires_at,
                    "updated_at": renewed_at,
                }
            )
            self._mirror_events_to_session_service([event])
            self._write(data)
        return event

    def expire_and_requeue_expired(
        self,
        *,
        now: str,
        reason: str,
    ) -> list[CommandLeaseEvent]:
        expired_events: list[CommandLeaseEvent] = []
        now_ts = _parse_timestamp(now)
        with self._guard_io():
            data = self._read()
            for command_id in sorted(data.commands):
                state = data.commands[command_id]
                if state.status != "claimed" or state.lease_expires_at is None:
                    continue
                if _parse_timestamp(state.lease_expires_at) > now_ts:
                    continue
                expired_events.append(
                    self._append_event(
                        data,
                        command_id=command_id,
                        session_id=state.session_id,
                        event_type="command_claim_expired",
                        occurred_at=now,
                        claim_seq=state.claim_seq,
                        worker_id=state.worker_id,
                        lease_expires_at=state.lease_expires_at,
                        reason=reason,
                    )
                )
                expired_events.append(
                    self._append_event(
                        data,
                        command_id=command_id,
                        session_id=state.session_id,
                        event_type="command_requeued",
                        occurred_at=now,
                        claim_seq=state.claim_seq,
                        worker_id=state.worker_id,
                        lease_expires_at=state.lease_expires_at,
                        reason=reason,
                    )
                )
                data.commands[command_id] = state.model_copy(
                    update={
                        "status": "requeued",
                        "updated_at": now,
                    }
                )
            if expired_events:
                self._mirror_events_to_session_service(expired_events)
                self._write(data)
        return expired_events

    def record_terminal_result(
        self,
        *,
        command_id: str,
        worker_id: str,
        claim_seq: int,
        result_type: str,
        occurred_at: str,
    ) -> CommandLeaseEvent:
        if result_type not in {"command_executed", "command_failed"}:
            raise ValueError(f"unsupported result type: {result_type}")
        with self._guard_io():
            data = self._read()
            state = self._require_current_claim(
                data.commands.get(command_id),
                command_id=command_id,
                worker_id=worker_id,
                claim_seq=claim_seq,
            )
            event = self._append_event(
                data,
                command_id=command_id,
                session_id=state.session_id,
                event_type=result_type,
                occurred_at=occurred_at,
                claim_seq=claim_seq,
                worker_id=worker_id,
                lease_expires_at=state.lease_expires_at,
            )
            data.commands[command_id] = state.model_copy(
                update={
                    "status": "executed" if result_type == "command_executed" else "failed",
                    "updated_at": occurred_at,
                }
            )
            self._mirror_events_to_session_service([event])
            self._write(data)
        return event
