from __future__ import annotations

import fcntl
import os
import threading
import uuid
from contextlib import contextmanager, suppress
from pathlib import Path

from pydantic import BaseModel, Field

from watchdog.services.memory_hub.indexer import SessionArchiveEntry
from watchdog.services.memory_hub.models import ProjectRegistration, ResidentMemoryRecord
from watchdog.services.memory_hub.skills import SkillMetadata

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


class _MemoryHubStoreFile(BaseModel):
    projects: list[ProjectRegistration] = Field(default_factory=list)
    resident: list[ResidentMemoryRecord] = Field(default_factory=list)
    archive: list[SessionArchiveEntry] = Field(default_factory=list)
    skills: list[SkillMetadata] = Field(default_factory=list)


class MemoryHubStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = _path_lock(path)
        self._lock_path = path.with_name(f".{path.name}.lock")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._guard_io():
            if not self._path.exists():
                self._write(_MemoryHubStoreFile())

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

    def _read(self) -> _MemoryHubStoreFile:
        raw = self._path.read_text(encoding="utf-8")
        if not raw.strip():
            return _MemoryHubStoreFile()
        return _MemoryHubStoreFile.model_validate_json(raw)

    def _write(self, data: _MemoryHubStoreFile) -> None:
        tmp = self._path.with_name(f"{self._path.name}.{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_text(data.model_dump_json(indent=2), encoding="utf-8")
            tmp.replace(self._path)
        finally:
            with suppress(FileNotFoundError):
                tmp.unlink()

    def upsert_project(self, record: ProjectRegistration) -> ProjectRegistration:
        with self._guard_io():
            data = self._read()
            data.projects = [row for row in data.projects if row.project_id != record.project_id]
            data.projects.append(record)
            self._write(data)
        return record

    def list_projects(self) -> list[ProjectRegistration]:
        with self._guard_io():
            return list(self._read().projects)

    def upsert_resident(self, record: ResidentMemoryRecord) -> ResidentMemoryRecord:
        with self._guard_io():
            data = self._read()
            data.resident = [row for row in data.resident if row.memory_id != record.memory_id]
            data.resident.append(record)
            self._write(data)
        return record

    def list_resident(self, *, project_id: str | None = None) -> list[ResidentMemoryRecord]:
        with self._guard_io():
            records = list(self._read().resident)
        if project_id is not None:
            records = [row for row in records if row.project_id == project_id]
        return records

    def append_archive(self, record: SessionArchiveEntry) -> SessionArchiveEntry:
        with self._guard_io():
            data = self._read()
            if all(existing.entry_id != record.entry_id for existing in data.archive):
                data.archive.append(record)
                self._write(data)
        return record

    def list_archive(self) -> list[SessionArchiveEntry]:
        with self._guard_io():
            return list(self._read().archive)

    def replace_skills(self, records: list[SkillMetadata]) -> list[SkillMetadata]:
        with self._guard_io():
            data = self._read()
            data.skills = list(records)
            self._write(data)
        return records

    def list_skills(self) -> list[SkillMetadata]:
        with self._guard_io():
            return list(self._read().skills)
