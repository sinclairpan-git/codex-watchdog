from __future__ import annotations

import httpx
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from watchdog.services.runtime_client.client import CodexRuntimeClient
from watchdog.services.session_spine.service import (
    _build_session_read_bundle,
    _list_actionable_canonical_approval_rows,
    _load_approvals_or_raise,
    _task_from_persisted_record,
)
from watchdog.services.session_spine.projection import task_native_thread_id
from watchdog.services.session_spine.store import PersistedSessionRecord, SessionSpineStore

if TYPE_CHECKING:
    from watchdog.services.approvals.service import CanonicalApprovalStore


class SessionSpineRuntime:
    def __init__(
        self,
        *,
        client: CodexRuntimeClient,
        store: SessionSpineStore,
        approval_store: CanonicalApprovalStore | None = None,
    ) -> None:
        self._client = client
        self._store = store
        self._approval_store = approval_store

    def refresh_all(self) -> None:
        liveness_now = datetime.now(UTC)
        try:
            tasks = self._client.list_tasks()
        except (httpx.RequestError, RuntimeError, OSError):
            return
        existing_records = {
            record.project_id: record for record in self._store.list_records()
        }
        try:
            approvals = _load_approvals_or_raise(self._client)
        except RuntimeError:
            approvals = None

        approvals_by_project: dict[str, list[dict[str, Any]]] | None = {}
        if approvals is None:
            approvals_by_project = None
        else:
            for approval in approvals:
                project_id = str(approval.get("project_id") or "")
                if not project_id:
                    continue
                approvals_by_project.setdefault(project_id, []).append(dict(approval))

        project_ids: list[str] = []
        tasks_by_project: dict[str, dict[str, Any]] = {}
        duplicate_project_ids: set[str] = set()
        for task in tasks:
            if not isinstance(task, dict):
                continue
            project_id = str(task.get("project_id") or "")
            if not project_id:
                continue
            existing_task = tasks_by_project.get(project_id)
            if existing_task is None:
                project_ids.append(project_id)
                tasks_by_project[project_id] = task
                continue
            duplicate_project_ids.add(project_id)
            if self._task_liveness_reference_time(task) >= self._task_liveness_reference_time(
                existing_task
            ):
                tasks_by_project[project_id] = task

        for project_id in project_ids:
            self.refresh_project(
                project_id,
                task=None if project_id in duplicate_project_ids else tasks_by_project.get(project_id),
                approvals=(
                    approvals_by_project.get(project_id, [])
                    if approvals_by_project is not None
                    else None
                ),
                liveness_now=liveness_now,
            )
        for project_id, record in existing_records.items():
            if project_id in tasks_by_project:
                continue
            self._refresh_missing_project(
                record,
                approvals=(
                    approvals_by_project.get(project_id, [])
                    if approvals_by_project is not None
                    else None
                ),
                liveness_now=liveness_now,
            )

    def refresh_project(
        self,
        project_id: str,
        *,
        task: dict[str, Any] | None = None,
        approvals: list[dict[str, Any]] | None = None,
        liveness_now: datetime | None = None,
    ) -> None:
        if task is None:
            try:
                body = self._client.get_envelope(project_id)
            except (httpx.RequestError, RuntimeError, OSError):
                return
            if not body.get("success"):
                return
            data = body.get("data")
            if not isinstance(data, dict):
                return
            task = data

        task = self._task_with_workspace_manual_activity(
            project_id=project_id,
            task=task,
        )

        if approvals is None:
            try:
                approvals = _load_approvals_or_raise(self._client, project_id)
            except RuntimeError:
                return
        approvals = self._merge_local_approvals(
            project_id=project_id,
            approvals=approvals,
            task=task,
        )

        bundle = _build_session_read_bundle(
            project_id=project_id,
            task=task,
            approvals=approvals,
            liveness_now=liveness_now or self._task_liveness_reference_time(task),
        )
        self._store.put(
            project_id=project_id,
            session=bundle.session,
            progress=bundle.progress,
            facts=bundle.facts,
            approval_queue=bundle.approval_queue,
            last_local_manual_activity_at=(
                str(task.get("last_local_manual_activity_at") or "") or None
            ),
        )

    def _task_with_workspace_manual_activity(
        self,
        *,
        project_id: str,
        task: dict[str, Any],
    ) -> dict[str, Any]:
        updated = dict(task)
        try:
            body = self._client.get_workspace_activity_envelope(project_id, recent_minutes=30)
        except (httpx.RequestError, RuntimeError, OSError, AttributeError):
            return updated
        if not body.get("success"):
            return updated
        data = body.get("data")
        if not isinstance(data, dict):
            return updated
        activity = data.get("activity")
        if not isinstance(activity, dict):
            return updated
        updated["workspace_cwd_exists"] = bool(activity.get("cwd_exists"))
        updated["workspace_files_scanned"] = int(activity.get("files_scanned") or 0)
        updated["workspace_recent_change_count"] = int(activity.get("recent_change_count") or 0)
        latest_mtime_iso = str(activity.get("latest_mtime_iso") or "").strip()
        updated["workspace_latest_mtime_iso"] = latest_mtime_iso or None
        if not bool(activity.get("cwd_exists")):
            return updated
        if not latest_mtime_iso:
            return updated
        recent_change_count = int(activity.get("recent_change_count") or 0)
        if recent_change_count <= 0 and not self._workspace_mtime_supersedes_task_progress(
            task=updated,
            latest_mtime_iso=latest_mtime_iso,
        ):
            return updated
        current_manual_activity = str(updated.get("last_local_manual_activity_at") or "").strip()
        chosen = self._max_iso_timestamp(current_manual_activity, latest_mtime_iso) or latest_mtime_iso
        updated["last_local_manual_activity_at"] = chosen
        return updated

    def _refresh_missing_project(
        self,
        record: PersistedSessionRecord,
        *,
        approvals: list[dict[str, Any]] | None,
        liveness_now: datetime | None = None,
    ) -> None:
        task: dict[str, Any] | None = None
        try:
            body = self._client.get_envelope(record.project_id)
        except (AttributeError, httpx.RequestError, RuntimeError, OSError):
            body = None
        if isinstance(body, dict) and body.get("success"):
            data = body.get("data")
            if isinstance(data, dict):
                task = data

        if task is None:
            approvals = []
            synthesized_task = _task_from_persisted_record(record, approvals=[])
            synthesized_task["runtime_task_missing"] = True
            task = synthesized_task

        if not bool(task.get("runtime_task_missing")):
            task = self._task_with_workspace_manual_activity(
                project_id=record.project_id,
                task=task,
            )
            approvals = self._merge_local_approvals(
                project_id=record.project_id,
                approvals=approvals or [],
                task=task,
            )
        else:
            approvals = []
        bundle = _build_session_read_bundle(
            project_id=record.project_id,
            task=task,
            approvals=approvals,
            liveness_now=liveness_now or self._task_liveness_reference_time(task),
        )
        self._store.put(
            project_id=record.project_id,
            session=bundle.session,
            progress=bundle.progress,
            facts=bundle.facts,
            approval_queue=bundle.approval_queue,
            last_local_manual_activity_at=(
                str(task.get("last_local_manual_activity_at") or "") or None
            ),
        )

    def _merge_local_approvals(
        self,
        *,
        project_id: str,
        approvals: list[dict[str, Any]],
        task: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        rows_by_id: dict[str, dict[str, Any]] = {}
        for approval in approvals:
            if not self._approval_matches_task_thread(task=task, approval=approval):
                continue
            approval_id = str(approval.get("approval_id") or "").strip()
            if not approval_id:
                continue
            rows_by_id[approval_id] = dict(approval)
        for approval in _list_actionable_canonical_approval_rows(
            self._approval_store,
            project_id=project_id,
        ):
            if not self._approval_matches_task_thread(task=task, approval=approval):
                continue
            approval_id = str(approval.get("approval_id") or "").strip()
            if not approval_id:
                continue
            if not rows_by_id and bool((task or {}).get("pending_approval")):
                continue
            if approval_id not in rows_by_id and self._canonical_overlay_is_stale_for_task(
                task=task,
                approval=approval,
            ):
                continue
            rows_by_id.setdefault(approval_id, dict(approval))
        return sorted(
            rows_by_id.values(),
            key=lambda row: (
                str(row.get("requested_at") or row.get("created_at") or "") == "",
                str(row.get("requested_at") or row.get("created_at") or ""),
                str(row.get("approval_id") or ""),
            ),
        )

    @staticmethod
    def _approval_matches_task_thread(
        *,
        task: dict[str, Any] | None,
        approval: dict[str, Any],
    ) -> bool:
        target = task_native_thread_id(task)
        if not target:
            return True
        approval_thread = str(
            approval.get("native_thread_id") or approval.get("thread_id") or ""
        ).strip()
        if not approval_thread or approval_thread.startswith("session:"):
            return True
        return approval_thread == target

    @classmethod
    def _canonical_overlay_is_stale_for_task(
        cls,
        *,
        task: dict[str, Any] | None,
        approval: dict[str, Any],
    ) -> bool:
        if not isinstance(task, dict):
            return False
        if bool(task.get("pending_approval")):
            return False
        task_last_progress = cls._parse_iso(str(task.get("last_progress_at") or "").strip() or None)
        if task_last_progress is None:
            return False
        approval_requested_at = cls._parse_iso(
            str(approval.get("requested_at") or approval.get("created_at") or "").strip() or None
        )
        if approval_requested_at is None:
            return False
        return task_last_progress > approval_requested_at

    @staticmethod
    def _max_iso_timestamp(*values: str) -> str | None:
        best_raw: str | None = None
        best_dt: datetime | None = None
        for value in values:
            normalized = str(value or "").strip()
            if not normalized:
                continue
            parsed = SessionSpineRuntime._parse_iso(normalized)
            if parsed is None:
                continue
            if best_dt is None or parsed > best_dt:
                best_dt = parsed
                best_raw = normalized
        return best_raw

    @classmethod
    def _task_liveness_reference_time(cls, task: dict[str, Any]) -> datetime | None:
        best: datetime | None = None
        for key in (
            "last_local_manual_activity_at",
            "last_substantive_user_input_at",
            "workspace_latest_mtime_iso",
            "last_progress_at",
        ):
            parsed = cls._parse_iso(str(task.get(key) or "").strip() or None)
            if parsed is not None and (best is None or parsed > best):
                best = parsed
        return best

    @staticmethod
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
        return parsed.astimezone(UTC)

    @classmethod
    def _workspace_mtime_supersedes_task_progress(
        cls,
        *,
        task: dict[str, Any],
        latest_mtime_iso: str,
    ) -> bool:
        latest_mtime = cls._parse_iso(latest_mtime_iso)
        if latest_mtime is None:
            return False
        last_progress = cls._parse_iso(str(task.get("last_progress_at") or "").strip() or None)
        if last_progress is None:
            return True
        return latest_mtime > last_progress
