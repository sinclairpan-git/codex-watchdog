from __future__ import annotations

import fcntl
import hashlib
import json
import os
import threading
import uuid
from contextlib import contextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from watchdog.contracts.session_spine.models import (
    ApprovalProjection,
    FactRecord,
    SessionProjection,
    TaskProgressView,
)
from watchdog.services.session_spine.text import sanitize_session_summary


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fingerprint(payload: object) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class PersistedSessionRecord(BaseModel):
    project_id: str
    thread_id: str
    native_thread_id: str | None = None
    session_seq: int
    fact_snapshot_version: str
    last_refreshed_at: str
    last_local_manual_activity_at: str | None = None
    session: SessionProjection
    progress: TaskProgressView
    facts: list[FactRecord] = Field(default_factory=list)
    approval_queue: list[ApprovalProjection] = Field(default_factory=list)
    snapshot_fingerprint: str | None = None
    facts_fingerprint: str | None = None

    @property
    def effective_native_thread_id(self) -> str | None:
        for candidate in (
            self.native_thread_id,
            self.session.native_thread_id,
            self.progress.native_thread_id,
        ):
            normalized = str(candidate or "").strip()
            if normalized:
                return normalized
        return None


class PersistedSessionSpineFile(BaseModel):
    sessions: dict[str, PersistedSessionRecord] = Field(default_factory=dict)


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


class SessionSpineStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = _path_lock(path)
        self._lock_path = path.with_name(f".{path.name}.lock")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._guard_io():
            if not self._path.exists():
                self._write(PersistedSessionSpineFile())

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

    def _read(self) -> PersistedSessionSpineFile:
        raw = self._path.read_text(encoding="utf-8")
        if not raw.strip():
            return PersistedSessionSpineFile()
        data = PersistedSessionSpineFile.model_validate_json(raw)
        changed = False
        for project_id, record in list(data.sessions.items()):
            sanitized_headline = sanitize_session_summary(record.session.headline)
            sanitized_summary = sanitize_session_summary(record.progress.summary)
            if (
                sanitized_headline == record.session.headline
                and sanitized_summary == record.progress.summary
            ):
                continue
            changed = True
            data.sessions[project_id] = record.model_copy(
                update={
                    "session": record.session.model_copy(update={"headline": sanitized_headline}),
                    "progress": record.progress.model_copy(update={"summary": sanitized_summary}),
                }
            )
        if changed:
            self._write(data)
        return data

    def _write(self, data: PersistedSessionSpineFile) -> None:
        tmp = self._path.with_name(f"{self._path.name}.{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_text(
                data.model_dump_json(indent=2),
                encoding="utf-8",
            )
            tmp.replace(self._path)
        finally:
            with suppress(FileNotFoundError):
                tmp.unlink()

    def get(self, project_id: str) -> PersistedSessionRecord | None:
        with self._guard_io():
            data = self._read()
            return data.sessions.get(project_id)

    def get_by_native_thread(self, native_thread_id: str) -> PersistedSessionRecord | None:
        with self._guard_io():
            data = self._read()
            for record in data.sessions.values():
                if record.effective_native_thread_id == native_thread_id:
                    return record
        return None

    def list_records(self) -> list[PersistedSessionRecord]:
        with self._guard_io():
            data = self._read()
            return list(data.sessions.values())

    def put(
        self,
        *,
        project_id: str,
        session: SessionProjection,
        progress: TaskProgressView,
        facts: list[FactRecord],
        approval_queue: list[ApprovalProjection],
        last_refreshed_at: str | None = None,
        last_local_manual_activity_at: str | None = None,
    ) -> PersistedSessionRecord:
        facts_payload = [fact.model_dump(mode="json") for fact in facts]
        snapshot_payload = {
            "session": session.model_dump(mode="json"),
            "progress": progress.model_dump(mode="json"),
            "facts": facts_payload,
            "approval_queue": [approval.model_dump(mode="json") for approval in approval_queue],
        }
        snapshot_fingerprint = _fingerprint(snapshot_payload)
        facts_fingerprint = _fingerprint(facts_payload)
        refreshed_at = last_refreshed_at or _utc_now_iso()

        with self._guard_io():
            data = self._read()
            existing = data.sessions.get(project_id)

            if existing is None:
                session_seq = 1
                fact_snapshot_version = "fact-v1"
            else:
                session_seq = (
                    existing.session_seq
                    if existing.snapshot_fingerprint == snapshot_fingerprint
                    else existing.session_seq + 1
                )
                fact_snapshot_version = (
                    existing.fact_snapshot_version
                    if existing.facts_fingerprint == facts_fingerprint
                    else f"fact-v{existing.session_seq + 1}"
                )

            record = PersistedSessionRecord(
                project_id=project_id,
                thread_id=session.thread_id,
                native_thread_id=session.native_thread_id,
                session_seq=session_seq,
                fact_snapshot_version=fact_snapshot_version,
                last_refreshed_at=refreshed_at,
                last_local_manual_activity_at=last_local_manual_activity_at,
                session=session,
                progress=progress,
                facts=facts,
                approval_queue=approval_queue,
                snapshot_fingerprint=snapshot_fingerprint,
                facts_fingerprint=facts_fingerprint,
            )
            data.sessions[project_id] = record
            self._write(data)
            return record
