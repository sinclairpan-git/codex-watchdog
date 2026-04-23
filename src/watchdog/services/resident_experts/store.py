from __future__ import annotations

import fcntl
import os
import threading
import uuid
from contextlib import contextmanager, suppress
from pathlib import Path

from pydantic import BaseModel, Field

from watchdog.services.resident_experts.models import (
    ResidentExpertConsultationRecord,
    ResidentExpertRuntimeBinding,
)

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


class _ResidentExpertRuntimeStoreFile(BaseModel):
    bindings: list[ResidentExpertRuntimeBinding] = Field(default_factory=list)


class ResidentExpertRuntimeStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = _path_lock(path)
        self._lock_path = path.with_name(f".{path.name}.lock")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._guard_io():
            if not self._path.exists():
                self._write(_ResidentExpertRuntimeStoreFile())

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

    def _read(self) -> _ResidentExpertRuntimeStoreFile:
        raw = self._path.read_text(encoding="utf-8")
        if not raw.strip():
            return _ResidentExpertRuntimeStoreFile()
        return _ResidentExpertRuntimeStoreFile.model_validate_json(raw)

    def _write(self, data: _ResidentExpertRuntimeStoreFile) -> None:
        tmp = self._path.with_name(f"{self._path.name}.{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_text(data.model_dump_json(indent=2), encoding="utf-8")
            tmp.replace(self._path)
        finally:
            with suppress(FileNotFoundError):
                tmp.unlink()

    def upsert_binding(
        self, binding: ResidentExpertRuntimeBinding
    ) -> ResidentExpertRuntimeBinding:
        with self._guard_io():
            data = self._read()
            data.bindings = [row for row in data.bindings if row.expert_id != binding.expert_id]
            data.bindings.append(binding)
            self._write(data)
        return binding

    def get_binding(self, expert_id: str) -> ResidentExpertRuntimeBinding | None:
        with self._guard_io():
            for binding in self._read().bindings:
                if binding.expert_id == expert_id:
                    return binding
        return None

    def list_bindings(self) -> list[ResidentExpertRuntimeBinding]:
        with self._guard_io():
            return list(self._read().bindings)


class _ResidentExpertConsultationStoreFile(BaseModel):
    consultations: list[ResidentExpertConsultationRecord] = Field(default_factory=list)


class ResidentExpertConsultationStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = _path_lock(path)
        self._lock_path = path.with_name(f".{path.name}.lock")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._guard_io():
            if not self._path.exists():
                self._write(_ResidentExpertConsultationStoreFile())

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

    def _read(self) -> _ResidentExpertConsultationStoreFile:
        raw = self._path.read_text(encoding="utf-8")
        if not raw.strip():
            return _ResidentExpertConsultationStoreFile()
        return _ResidentExpertConsultationStoreFile.model_validate_json(raw)

    def _write(self, data: _ResidentExpertConsultationStoreFile) -> None:
        tmp = self._path.with_name(f"{self._path.name}.{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_text(data.model_dump_json(indent=2), encoding="utf-8")
            tmp.replace(self._path)
        finally:
            with suppress(FileNotFoundError):
                tmp.unlink()

    def upsert_consultation(
        self, record: ResidentExpertConsultationRecord
    ) -> ResidentExpertConsultationRecord:
        with self._guard_io():
            data = self._read()
            data.consultations = [
                row for row in data.consultations if row.consultation_ref != record.consultation_ref
            ]
            data.consultations.append(record)
            self._write(data)
        return record

    def get_consultation(self, consultation_ref: str) -> ResidentExpertConsultationRecord | None:
        with self._guard_io():
            for record in self._read().consultations:
                if record.consultation_ref == consultation_ref:
                    return record
        return None
