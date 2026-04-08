from __future__ import annotations

import threading
from pathlib import Path

from pydantic import BaseModel, Field


class ProgressSummaryCheckpoint(BaseModel):
    project_id: str
    progress_fingerprint: str
    last_progress_notification_at: str


class AutoContinueCheckpoint(BaseModel):
    project_id: str
    last_auto_continue_at: str


class ResidentOrchestrationStateFile(BaseModel):
    progress_summaries: dict[str, ProgressSummaryCheckpoint] = Field(default_factory=dict)
    auto_continue_checkpoints: dict[str, AutoContinueCheckpoint] = Field(default_factory=dict)


class ResidentOrchestrationStateStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._write(ResidentOrchestrationStateFile())

    def _read(self) -> ResidentOrchestrationStateFile:
        raw = self._path.read_text(encoding="utf-8")
        if not raw.strip():
            return ResidentOrchestrationStateFile()
        return ResidentOrchestrationStateFile.model_validate_json(raw)

    def _write(self, data: ResidentOrchestrationStateFile) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(data.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def get_progress_checkpoint(self, project_id: str) -> ProgressSummaryCheckpoint | None:
        with self._lock:
            data = self._read()
            return data.progress_summaries.get(project_id)

    def put_progress_checkpoint(
        self,
        *,
        project_id: str,
        progress_fingerprint: str,
        last_progress_notification_at: str,
    ) -> ProgressSummaryCheckpoint:
        checkpoint = ProgressSummaryCheckpoint(
            project_id=project_id,
            progress_fingerprint=progress_fingerprint,
            last_progress_notification_at=last_progress_notification_at,
        )
        with self._lock:
            data = self._read()
            data.progress_summaries[project_id] = checkpoint
            self._write(data)
        return checkpoint

    def get_auto_continue_checkpoint(self, project_id: str) -> AutoContinueCheckpoint | None:
        with self._lock:
            data = self._read()
            return data.auto_continue_checkpoints.get(project_id)

    def put_auto_continue_checkpoint(
        self,
        *,
        project_id: str,
        last_auto_continue_at: str,
    ) -> AutoContinueCheckpoint:
        checkpoint = AutoContinueCheckpoint(
            project_id=project_id,
            last_auto_continue_at=last_auto_continue_at,
        )
        with self._lock:
            data = self._read()
            data.auto_continue_checkpoints[project_id] = checkpoint
            self._write(data)
        return checkpoint
