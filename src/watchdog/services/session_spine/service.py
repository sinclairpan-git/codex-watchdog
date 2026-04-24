from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import yaml

from watchdog.contracts.session_spine.models import (
    ApprovalProjection,
    ContinuationControlPlaneView,
    ContinuationDispatchCooldownView,
    ContinuationDispatchResultView,
    FactRecord,
    ResidentExpertCoverageView,
    SessionProjection,
    SnapshotReadSemantics,
    TaskProgressView,
    WorkspaceActivityView,
)
from watchdog.services.resident_experts.service import ResidentExpertRuntimeService
from watchdog.services.policy.decisions import (
    CanonicalDecisionRecord,
    PolicyDecisionStore,
)
from watchdog.services.policy.engine import evaluate_persisted_session_policy
from watchdog.services.runtime_client.client import CodexRuntimeClient
from watchdog.services.session_service.models import SessionEventRecord
from watchdog.services.session_service.service import SessionService
from watchdog.services.session_spine.facts import build_fact_records
from watchdog.services.goal_contract.models import GoalContractSnapshot
from watchdog.services.session_spine.orchestration_store import ResidentOrchestrationStateStore
from watchdog.services.session_spine.projection import (
    build_approval_inbox_projections,
    build_approval_projections,
    build_session_projection,
    build_session_service_fact_records,
    build_task_progress_view,
    build_workspace_activity_view,
    stable_thread_id_for_project,
    task_native_thread_id,
)
from watchdog.services.session_spine.store import PersistedSessionRecord, SessionSpineStore
from watchdog.services.session_spine.approval_visibility import (
    is_actionable_approval,
    is_deferred_policy_auto_approval,
)
from watchdog.services.session_spine.task_state import (
    DEFAULT_ACTIVE_SESSION_STALE_AFTER_SECONDS,
    derive_project_execution_state_liveness_override,
    is_non_active_project_execution_state,
    normalize_project_execution_state,
    normalize_task_status,
)
from watchdog.storage.action_receipts import ActionReceiptStore, receipt_key

if TYPE_CHECKING:
    from watchdog.services.approvals.service import CanonicalApprovalStore


CONTROL_LINK_ERROR = {
    "code": "CONTROL_LINK_ERROR",
    "message": "无法连接 Codex runtime 控制链路；请检查网络与 runtime 服务状态。",
}
PERSISTED_SESSION_SPINE_REQUIRED_ERROR = {
    "code": "PERSISTED_SESSION_SPINE_REQUIRED",
    "message": "缺少 canonical persisted session spine；请先刷新 resident session spine。",
}
PERSISTED_SPINE_READ_SOURCE = "persisted_spine"
SESSION_EVENTS_PROJECTION_READ_SOURCE = "session_events_projection"
LIVE_QUERY_FALLBACK_READ_SOURCE = "live_query_fallback"
DEFAULT_SESSION_SPINE_FRESHNESS_WINDOW_SECONDS = 60.0


def _read_yaml_mapping(relative_path: str, *, repo_root: Path | None = None) -> dict[str, object]:
    root = repo_root or Path(__file__).resolve().parents[4]
    path = root / relative_path
    if not path.is_file():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _normalized_scope_values(*values: object) -> set[str]:
    normalized: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        normalized.add(text)
        normalized.add(text.lower())
        if "/" in text:
            tail = text.rsplit("/", 1)[-1].strip()
            if tail:
                normalized.add(tail)
                normalized.add(tail.lower())
    return normalized


def _task_targets_workspace_project(
    task: dict[str, Any] | None,
    *,
    project_state: dict[str, object],
    checkpoint: dict[str, object],
    state_resume: dict[str, object],
    repo_root: Path | None = None,
) -> bool:
    if not isinstance(task, dict):
        return False
    project_id = str(task.get("project_id") or "").strip()
    if not project_id:
        return False
    feature = checkpoint.get("feature")
    feature_mapping = feature if isinstance(feature, dict) else {}
    root = repo_root or Path(__file__).resolve().parents[4]
    workspace_scope = _normalized_scope_values(
        project_state.get("project_id"),
        project_state.get("project_name"),
        checkpoint.get("project_id"),
        checkpoint.get("project_name"),
        checkpoint.get("linked_wi_id"),
        state_resume.get("project_id"),
        state_resume.get("project_name"),
        feature_mapping.get("id"),
        feature_mapping.get("current_branch"),
        feature_mapping.get("feature_branch"),
        root.name,
    )
    return project_id in workspace_scope or project_id.lower() in workspace_scope


def _authoritative_project_execution_state(
    task: dict[str, Any] | None = None,
    *,
    repo_root: Path | None = None,
) -> str:
    from watchdog.services.brain.service import BrainDecisionService

    project_state = _read_yaml_mapping(".ai-sdlc/project/config/project-state.yaml", repo_root=repo_root)
    checkpoint = _read_yaml_mapping(".ai-sdlc/state/checkpoint.yml", repo_root=repo_root)
    state_resume = _read_yaml_mapping(".ai-sdlc/state/resume-pack.yaml", repo_root=repo_root)
    if not _task_targets_workspace_project(
        task,
        project_state=project_state,
        checkpoint=checkpoint,
        state_resume=state_resume,
        repo_root=repo_root,
    ):
        return "unknown"
    record_project_id = str((task or {}).get("project_id") or "").strip()
    return BrainDecisionService._normalize_project_execution_state(
        record_project_id=record_project_id,
        project_state=project_state,
        checkpoint=checkpoint,
        state_resume=state_resume,
    )


def _task_with_authoritative_project_execution_state(
    task: dict[str, Any] | None,
    *,
    repo_root: Path | None = None,
    now: datetime | None = None,
    stale_active_session_after_seconds: float = DEFAULT_ACTIVE_SESSION_STALE_AFTER_SECONDS,
) -> dict[str, Any] | None:
    if not isinstance(task, dict):
        return task
    authoritative_state = _authoritative_project_execution_state(task, repo_root=repo_root)
    explicit_state = normalize_project_execution_state(task)
    updated = dict(task)
    if authoritative_state == "unknown":
        updated.pop("authoritative_project_execution_state_missing", None)
        updated["project_execution_state"] = derive_project_execution_state_liveness_override(
            updated,
            project_execution_state=explicit_state,
            now=now,
            stale_after_seconds=stale_active_session_after_seconds,
        )
        return updated
    updated.pop("authoritative_project_execution_state_missing", None)
    if explicit_state == "unknown":
        updated["project_execution_state"] = derive_project_execution_state_liveness_override(
            updated,
            project_execution_state=authoritative_state,
            now=now,
            stale_after_seconds=stale_active_session_after_seconds,
        )
        return updated
    updated["project_execution_state"] = explicit_state
    if (
        is_non_active_project_execution_state(authoritative_state)
        and not is_non_active_project_execution_state(explicit_state)
    ):
        updated["project_execution_state"] = authoritative_state
    updated["project_execution_state"] = derive_project_execution_state_liveness_override(
        updated,
        project_execution_state=str(updated.get("project_execution_state") or explicit_state),
        now=now,
        stale_after_seconds=stale_active_session_after_seconds,
    )
    return updated
SESSION_EVENT_APPROVAL_TYPES = frozenset(
    {
        "approval_requested",
        "approval_approved",
        "approval_rejected",
        "approval_expired",
    }
)
SESSION_EVENT_FACT_TYPES = frozenset(
    {
        "memory_unavailable_degraded",
        "memory_conflict_detected",
        "human_override_recorded",
        "notification_announced",
        "notification_delivery_succeeded",
        "notification_delivery_failed",
        "notification_requeued",
        "notification_receipt_recorded",
    }
)
SESSION_EVENT_GOAL_CONTRACT_TYPES = frozenset(
    {
        "goal_contract_created",
        "goal_contract_revised",
        "goal_contract_adopted_by_child_session",
    }
)
SESSION_EVENT_EVENT_ONLY_FALLBACK_TYPES = frozenset(
    {
        "recovery_execution_suppressed",
        "interaction_context_superseded",
        "interaction_window_expired",
    }
)
SESSION_EVENT_EVENT_ONLY_FALLBACK_TYPES |= SESSION_EVENT_GOAL_CONTRACT_TYPES
SESSION_EVENT_PROJECTION_TYPES = SESSION_EVENT_APPROVAL_TYPES | SESSION_EVENT_FACT_TYPES
SESSION_EVENT_RUNTIME_OPTIONAL_FALLBACK_TYPES = frozenset(
    {
        "interaction_context_superseded",
        "interaction_window_expired",
    }
)


def _approval_sort_key(approval: ApprovalProjection) -> tuple[bool, str, str]:
    return (
        approval.requested_at == "",
        approval.requested_at,
        approval.approval_id,
    )


class SessionSpineUpstreamError(RuntimeError):
    def __init__(self, error: dict[str, Any]) -> None:
        super().__init__(str(error.get("code") or "upstream_error"))
        self.error = error


@dataclass(frozen=True, slots=True)
class SessionReadBundle:
    project_id: str
    task: dict[str, Any] | None
    approvals: list[dict[str, Any]]
    facts: list[FactRecord]
    session: SessionProjection
    progress: TaskProgressView
    approval_queue: list[ApprovalProjection]
    snapshot: SnapshotReadSemantics | None = None


@dataclass(frozen=True, slots=True)
class ApprovalInboxReadBundle:
    project_id: str | None
    approvals: list[dict[str, Any]]
    approval_inbox: list[ApprovalProjection]


@dataclass(frozen=True, slots=True)
class SessionDirectoryReadBundle:
    tasks: list[dict[str, Any]]
    approvals: list[dict[str, Any]]
    sessions: list[SessionProjection]
    progresses: list[TaskProgressView] = field(default_factory=list)
    resident_expert_coverage: ResidentExpertCoverageView | None = None


def _canonical_decision_sort_key(record: CanonicalDecisionRecord) -> tuple[str, str]:
    return (str(record.created_at or ""), record.decision_id)


def _build_decision_trace_projection(
    decision_store: PolicyDecisionStore | None,
    *,
    project_id: str,
    session_id: str | None = None,
    native_thread_id: str | None = None,
) -> dict[str, Any] | None:
    if decision_store is None:
        return None
    normalized_session_id = str(session_id or "").strip()
    normalized_native_thread_id = str(native_thread_id or "").strip()
    project_records = [
        record for record in decision_store.list_records() if record.project_id == project_id
    ]
    if not project_records:
        return None
    matched_records = [
        record
        for record in project_records
        if (
            normalized_session_id
            and record.session_id == normalized_session_id
            or normalized_native_thread_id
            and record.effective_native_thread_id == normalized_native_thread_id
        )
    ]
    candidate_records = matched_records or project_records
    latest = max(candidate_records, key=_canonical_decision_sort_key)
    evidence = latest.evidence if isinstance(latest.evidence, dict) else {}
    trace = evidence.get("decision_trace")
    if not isinstance(trace, dict):
        return None
    return {
        "decision_trace_ref": str(trace.get("trace_id") or "") or None,
        "decision_degrade_reason": str(trace.get("degrade_reason") or "") or None,
        "provider_output_schema_ref": str(trace.get("provider_output_schema_ref") or "") or None,
    }


def _build_resident_expert_coverage_view(
    resident_expert_runtime_service: ResidentExpertRuntimeService | None,
) -> ResidentExpertCoverageView | None:
    if resident_expert_runtime_service is None:
        return None
    views = resident_expert_runtime_service.list_runtime_views(now=datetime.now(timezone.utc))
    if not views:
        return None
    if not any(
        view.runtime_handle_bound or view.last_consulted_at or view.last_consultation_ref
        for view in views
    ):
        return None

    latest_view = max(
        (
            view
            for view in views
            if view.last_consulted_at or view.last_consultation_ref
        ),
        key=lambda item: (
            _parse_iso8601(item.last_consulted_at) or datetime.min.replace(tzinfo=timezone.utc),
            item.expert_id,
        ),
        default=None,
    )
    degraded_expert_ids = [
        view.expert_id
        for view in views
        if view.status != "available"
    ]
    return ResidentExpertCoverageView(
        coverage_status="healthy" if not degraded_expert_ids else "degraded",
        available_expert_count=sum(1 for view in views if view.status == "available"),
        bound_expert_count=sum(1 for view in views if view.status == "bound"),
        restoring_expert_count=sum(1 for view in views if view.status == "restoring"),
        stale_expert_count=sum(1 for view in views if view.status == "stale"),
        unavailable_expert_count=sum(1 for view in views if view.status == "unavailable"),
        degraded_expert_ids=degraded_expert_ids,
        latest_consultation_ref=(
            str(latest_view.last_consultation_ref or "") or None
            if latest_view is not None
            else None
        ),
        latest_consulted_at=(
            str(latest_view.last_consulted_at or "") or None
            if latest_view is not None
            else None
        ),
    )


@dataclass(frozen=True, slots=True)
class WorkspaceActivityReadBundle:
    project_id: str
    task: dict[str, Any] | None
    approvals: list[dict[str, Any]]
    facts: list[FactRecord]
    session: SessionProjection
    workspace_activity: WorkspaceActivityView


def _parse_iso8601(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _task_liveness_reference_time(task: dict[str, Any] | None) -> datetime | None:
    if not isinstance(task, dict):
        return None
    best: datetime | None = None
    for key in (
        "last_local_manual_activity_at",
        "last_substantive_user_input_at",
        "workspace_latest_mtime_iso",
        "last_progress_at",
    ):
        parsed = _parse_iso8601(str(task.get(key) or "").strip() or None)
        if parsed is not None and (best is None or parsed > best):
            best = parsed
    return best


def _max_iso8601_timestamp(*values: str | None) -> str | None:
    best_raw: str | None = None
    best_dt: datetime | None = None
    for value in values:
        normalized = str(value or "").strip()
        if not normalized:
            continue
        parsed = _parse_iso8601(normalized)
        if parsed is None:
            continue
        if best_dt is None or parsed > best_dt:
            best_dt = parsed
            best_raw = normalized
    return best_raw


def _approval_row_is_stale_after_progress_at(
    progress_at: str | None,
    approval: dict[str, Any],
) -> bool:
    task_last_progress = _parse_iso8601(str(progress_at or "").strip() or None)
    if task_last_progress is None:
        return False
    approval_requested_at = _parse_iso8601(
        str(approval.get("requested_at") or approval.get("created_at") or "").strip() or None
    )
    if approval_requested_at is None:
        return False
    return task_last_progress > approval_requested_at


def _approval_row_matches_native_thread(
    approval: dict[str, Any],
    native_thread_id: str | None,
) -> bool:
    target = str(native_thread_id or "").strip()
    if not target:
        return True
    approval_thread = str(approval.get("native_thread_id") or "").strip()
    return not approval_thread or approval_thread == target


def _directory_human_activity_reference_time(task: dict[str, Any] | None) -> datetime | None:
    if not isinstance(task, dict):
        return None
    best: datetime | None = None
    for key in (
        "last_local_manual_activity_at",
        "last_substantive_user_input_at",
        "workspace_latest_mtime_iso",
    ):
        parsed = _parse_iso8601(str(task.get(key) or "").strip() or None)
        if parsed is not None and (best is None or parsed > best):
            best = parsed
    return best


def _iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _directory_task_liveness_reference_time(
    task: dict[str, Any] | None,
    *,
    now: datetime,
) -> datetime | None:
    if not isinstance(task, dict):
        return None
    phase = str(task.get("phase") or "").strip().lower()
    status = str(task.get("status") or "").strip().lower()
    if phase == "handoff" or status in {"handoff_in_progress", "resuming"}:
        return now
    if str(task.get("created_at") or "").strip():
        return now
    return _task_liveness_reference_time(task)


def _directory_projected_task_liveness_reference_time(
    task: dict[str, Any] | None,
    *,
    now: datetime,
) -> datetime | None:
    if not isinstance(task, dict):
        return None
    return now


def _directory_task_with_projected_active_state(
    task: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(task, dict):
        return task
    if normalize_project_execution_state(task) != "unknown":
        return task
    status = normalize_task_status(task)
    if status in {"paused", "completed", "failed"}:
        return task
    updated = dict(task)
    updated["project_execution_state"] = "active"
    phase = str(updated.get("phase") or "").strip().lower()
    raw_status = str(updated.get("status") or "").strip().lower()
    if phase == "handoff" or raw_status in {"handoff_in_progress", "resuming"}:
        human_activity_at = _directory_human_activity_reference_time(updated)
        if human_activity_at is not None:
            updated["last_progress_at"] = _iso_z(human_activity_at)
    return updated


def _directory_task_with_active_state(task: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(task, dict):
        return task
    if not str(task.get("created_at") or "").strip():
        return task
    if normalize_project_execution_state(task) != "unknown":
        return task
    status = normalize_task_status(task)
    if status in {"paused", "completed", "failed"}:
        return task
    updated = dict(task)
    updated["project_execution_state"] = "active"
    phase = str(updated.get("phase") or "").strip().lower()
    raw_status = str(updated.get("status") or "").strip().lower()
    if phase == "handoff" or raw_status in {"handoff_in_progress", "resuming"}:
        human_activity_at = _directory_human_activity_reference_time(updated)
        if human_activity_at is not None:
            updated["last_progress_at"] = _iso_z(human_activity_at)
    return updated


def _directory_project_id_is_valid(project_id: str) -> bool:
    normalized = str(project_id or "").strip()
    if not normalized:
        return False
    if normalized.startswith("watchdog-smoke-"):
        return False
    home_name = Path.home().name.strip()
    return normalized.casefold() != home_name.casefold()


def _directory_bundle_is_active(bundle: SessionReadBundle) -> bool:
    if not _directory_project_id_is_valid(bundle.project_id):
        return False
    status = normalize_task_status(bundle.task)
    if status in {"paused", "completed", "failed"}:
        return False
    project_execution_state = normalize_project_execution_state(bundle.task)
    if is_non_active_project_execution_state(project_execution_state):
        return False
    return not any(fact.fact_code == "project_not_active" for fact in bundle.facts)


def _append_active_directory_bundle(
    *,
    sessions: list[SessionProjection],
    progresses: list[TaskProgressView],
    bundle: SessionReadBundle,
) -> None:
    if not _directory_bundle_is_active(bundle):
        return
    sessions.append(bundle.session)
    progresses.append(bundle.progress)


def _event_payload_text(event: SessionEventRecord | None, key: str) -> str | None:
    if event is None:
        return None
    payload = event.payload if isinstance(event.payload, dict) else {}
    value = str(payload.get(key) or "").strip()
    return value or None


def _event_related_text(event: SessionEventRecord | None, key: str) -> str | None:
    if event is None:
        return None
    related_ids = event.related_ids if isinstance(event.related_ids, dict) else {}
    value = str(related_ids.get(key) or "").strip()
    return value or None


def _latest_session_event(
    events: list[SessionEventRecord],
    *,
    event_types: set[str] | frozenset[str],
) -> SessionEventRecord | None:
    for event in sorted(events, key=_session_event_sort_key, reverse=True):
        if event.event_type in event_types:
            return event
    return None


def _build_dispatch_cooldown_projection(
    *,
    state_store: ResidentOrchestrationStateStore | None,
    project_id: str,
    continuation_identity: str | None,
    route_key: str | None,
    cooldown_seconds: float,
) -> ContinuationDispatchCooldownView | None:
    normalized_identity = str(continuation_identity or "").strip()
    normalized_route_key = str(route_key or "").strip()
    if state_store is None or not normalized_identity or not normalized_route_key:
        return None
    checkpoint = state_store.get_auto_dispatch_checkpoint(
        project_id=project_id,
        continuation_identity=normalized_identity,
        route_key=normalized_route_key,
    )
    if checkpoint is None:
        checkpoint = state_store.get_latest_auto_dispatch_checkpoint(
            project_id=project_id,
            continuation_identity=normalized_identity,
        )
    if checkpoint is None:
        return None
    normalized_cooldown = max(float(cooldown_seconds or 0.0), 0.0)
    remaining_seconds: float | None = None
    active = False
    dispatched_at = _parse_iso8601(checkpoint.last_auto_dispatch_at)
    if dispatched_at is not None and normalized_cooldown > 0.0:
        elapsed = (datetime.now(timezone.utc) - dispatched_at).total_seconds()
        remaining_seconds = max(normalized_cooldown - elapsed, 0.0)
        active = checkpoint.status in {"claimed", "completed"} and remaining_seconds > 0.0
    return ContinuationDispatchCooldownView(
        action_ref=checkpoint.action_ref,
        checkpoint_state=checkpoint.status,
        last_dispatched_at=checkpoint.last_auto_dispatch_at,
        cooldown_seconds=normalized_cooldown if normalized_cooldown > 0.0 else None,
        remaining_seconds=remaining_seconds,
        active=active,
    )


def _build_last_dispatch_result_projection(
    events: list[SessionEventRecord],
    *,
    project_id: str,
    continuation_identity: str | None,
    route_key: str | None,
    decision_store: PolicyDecisionStore | None = None,
    receipt_store: ActionReceiptStore | None = None,
) -> ContinuationDispatchResultView | None:
    command_created_by_id: dict[str, SessionEventRecord] = {}
    gate_by_decision_id: dict[str, SessionEventRecord] = {}
    for event in sorted(events, key=_session_event_sort_key):
        if event.event_type == "command_created":
            command_id = _event_related_text(event, "command_id") or _event_payload_text(
                event, "command_id"
            )
            if command_id:
                command_created_by_id[command_id] = event
        elif event.event_type == "continuation_gate_evaluated":
            decision_id = str(event.causation_id or "").strip()
            if decision_id:
                gate_by_decision_id[decision_id] = event

    normalized_identity = str(continuation_identity or "").strip() or None
    normalized_route_key = str(route_key or "").strip() or None
    event_projection: ContinuationDispatchResultView | None = None
    event_projection_decision_id: str | None = None
    for event in sorted(events, key=_session_event_sort_key, reverse=True):
        if event.event_type not in {"command_executed", "command_failed"}:
            continue
        command_id = _event_related_text(event, "command_id")
        if command_id is None:
            continue
        created_event = command_created_by_id.get(command_id)
        if created_event is None:
            continue
        action_ref = _event_payload_text(created_event, "action_ref")
        if action_ref not in {
            "continue_session",
            "request_recovery",
            "post_operator_guidance",
            "execute_recovery",
        }:
            continue
        decision_id = _event_related_text(created_event, "decision_id") or str(
            created_event.causation_id or ""
        ).strip()
        gate_event = gate_by_decision_id.get(decision_id)
        if normalized_identity is not None and gate_event is not None:
            gate_identity = _event_related_text(gate_event, "continuation_identity")
            if gate_identity not in {None, normalized_identity}:
                continue
        if normalized_route_key is not None and gate_event is not None:
            gate_route_key = _event_related_text(gate_event, "route_key")
            if gate_route_key not in {None, normalized_route_key}:
                continue
        payload = event.payload if isinstance(event.payload, dict) else {}
        completion = (
            payload.get("completion_judgment")
            if isinstance(payload.get("completion_judgment"), dict)
            else {}
        )
        metrics = (
            payload.get("metrics_summary")
            if isinstance(payload.get("metrics_summary"), dict)
            else {}
        )
        event_projection = ContinuationDispatchResultView(
            command_id=command_id,
            decision_id=decision_id or None,
            action_ref=action_ref,
            status=str(completion.get("status") or "").strip()
            or ("completed" if event.event_type == "command_executed" else "failed"),
            action_status=str(completion.get("action_status") or "").strip() or None,
            reply_code=str(completion.get("reply_code") or "").strip() or None,
            decision_result=str(
                metrics.get("decision_result")
                or (created_event.payload if isinstance(created_event.payload, dict) else {}).get(
                    "decision_result"
                )
                or ""
            ).strip()
            or None,
            observed_at=event.occurred_at,
            receipt_ref=str(completion.get("receipt_ref") or "").strip() or None,
        )
        event_projection_decision_id = decision_id or None
        break

    if decision_store is None or receipt_store is None:
        return event_projection

    candidate_records = [
        record
        for record in decision_store.list_records()
        if record.project_id == project_id
        and record.action_ref
        in {"continue_session", "request_recovery", "post_operator_guidance", "execute_recovery"}
    ]
    if not candidate_records:
        return event_projection

    def _governance(record: CanonicalDecisionRecord) -> dict[str, Any]:
        evidence = record.evidence if isinstance(record.evidence, dict) else {}
        governance = evidence.get("continuation_governance")
        return governance if isinstance(governance, dict) else {}

    def _matches(record: CanonicalDecisionRecord, *, exact_route: bool) -> bool:
        governance = _governance(record)
        record_identity = str(governance.get("continuation_identity") or "").strip() or None
        record_route_key = str(governance.get("route_key") or "").strip() or None
        if normalized_identity is not None and record_identity != normalized_identity:
            return False
        if exact_route and normalized_route_key is not None and record_route_key != normalized_route_key:
            return False
        return normalized_identity is not None or normalized_route_key is not None

    matched_records = [
        record for record in candidate_records if _matches(record, exact_route=True)
    ] or [record for record in candidate_records if _matches(record, exact_route=False)]
    if event_projection_decision_id is not None:
        matched_records = [
            record for record in matched_records if record.decision_id == event_projection_decision_id
        ] or matched_records
    if not matched_records:
        return event_projection
    latest = max(matched_records, key=_canonical_decision_sort_key)
    authoritative_receipt = receipt_store.get(
        receipt_key(
            action_code=latest.action_ref,
            project_id=latest.project_id,
            approval_id=latest.approval_id or None,
            idempotency_key=latest.idempotency_key,
        )
    )
    if authoritative_receipt is None:
        return event_projection
    return ContinuationDispatchResultView(
        command_id=event_projection.command_id if event_projection is not None else None,
        decision_id=latest.decision_id,
        action_ref=latest.action_ref,
        status=str(authoritative_receipt.action_status or "").strip().lower() or None,
        action_status=str(authoritative_receipt.action_status or "").strip() or None,
        reply_code=str(authoritative_receipt.reply_code or "").strip() or None,
        decision_result=latest.decision_result,
        observed_at=event_projection.observed_at if event_projection is not None else latest.created_at,
        receipt_ref=event_projection.receipt_ref if event_projection is not None else None,
    )


def _build_continuation_control_plane_projection(
    *,
    project_id: str,
    events: list[SessionEventRecord],
    decision_store: PolicyDecisionStore | None = None,
    receipt_store: ActionReceiptStore | None = None,
    state_store: ResidentOrchestrationStateStore | None = None,
    dispatch_cooldown_seconds: float = 0.0,
) -> ContinuationControlPlaneView | None:
    gate_event = _latest_session_event(
        events,
        event_types=frozenset({"continuation_gate_evaluated"}),
    )
    identity_event = _latest_session_event(
        events,
        event_types=frozenset(
            {
                "continuation_identity_issued",
                "continuation_identity_consumed",
                "continuation_identity_invalidated",
            }
        ),
    )
    token_event = _latest_session_event(
        events,
        event_types=frozenset(
            {
                "branch_switch_token_issued",
                "branch_switch_token_consumed",
                "branch_switch_token_invalidated",
            }
        ),
    )
    replay_event = _latest_session_event(
        events,
        event_types=frozenset({"continuation_replay_invalidated"}),
    )
    packet_event = _latest_session_event(
        events,
        event_types=frozenset({"handoff_packet_frozen"}),
    )
    continuation_identity = (
        _event_related_text(identity_event, "continuation_identity")
        or _event_related_text(gate_event, "continuation_identity")
        or _event_related_text(token_event, "continuation_identity")
        or _event_related_text(packet_event, "continuation_identity")
    )
    route_key = (
        _event_related_text(identity_event, "route_key")
        or _event_related_text(gate_event, "route_key")
        or _event_related_text(token_event, "route_key")
        or _event_related_text(packet_event, "route_key")
    )
    branch_switch_token = _event_related_text(token_event, "branch_switch_token") or _event_related_text(
        gate_event, "branch_switch_token"
    )
    packet_id = (
        _event_related_text(identity_event, "source_packet_id")
        or _event_related_text(gate_event, "source_packet_id")
        or _event_related_text(replay_event, "source_packet_id")
        or _event_related_text(packet_event, "source_packet_id")
    )
    packet_hash = _event_payload_text(packet_event, "packet_hash")
    rendered_from_packet_id = _event_payload_text(packet_event, "rendered_from_packet_id")
    rendered_from_packet_hash = _event_payload_text(packet_event, "rendered_markdown_hash")
    decision_source = (
        _event_payload_text(gate_event, "decision_source")
        or _event_payload_text(identity_event, "decision_source")
        or _event_payload_text(token_event, "decision_source")
        or _event_payload_text(replay_event, "decision_source")
        or _event_payload_text(packet_event, "decision_source")
    )
    suppression_reason = (
        _event_payload_text(gate_event, "suppression_reason")
        or _event_payload_text(identity_event, "suppression_reason")
        or _event_payload_text(token_event, "suppression_reason")
        or _event_payload_text(replay_event, "invalidation_reason")
    )
    snapshot_version = (
        _event_payload_text(gate_event, "authoritative_snapshot_version")
        or _event_payload_text(identity_event, "authoritative_snapshot_version")
        or _event_payload_text(token_event, "authoritative_snapshot_version")
        or _event_payload_text(replay_event, "authoritative_snapshot_version")
        or _event_payload_text(packet_event, "authoritative_snapshot_version")
    )
    snapshot_epoch = (
        _event_payload_text(gate_event, "snapshot_epoch")
        or _event_payload_text(identity_event, "snapshot_epoch")
        or _event_payload_text(token_event, "snapshot_epoch")
        or _event_payload_text(replay_event, "snapshot_epoch")
        or _event_payload_text(packet_event, "snapshot_epoch")
    )
    last_dispatch_result = _build_last_dispatch_result_projection(
        events,
        project_id=project_id,
        continuation_identity=continuation_identity,
        route_key=route_key,
        decision_store=decision_store,
        receipt_store=receipt_store,
    )
    dispatch_cooldown = _build_dispatch_cooldown_projection(
        state_store=state_store,
        project_id=project_id,
        continuation_identity=continuation_identity,
        route_key=route_key,
        cooldown_seconds=dispatch_cooldown_seconds,
    )
    if not any(
        (
            continuation_identity,
            branch_switch_token,
            packet_id,
            packet_hash,
            rendered_from_packet_id,
            rendered_from_packet_hash,
            decision_source,
            suppression_reason,
            snapshot_version,
            snapshot_epoch,
            last_dispatch_result,
            dispatch_cooldown,
        )
    ):
        return None
    return ContinuationControlPlaneView(
        continuation_identity=continuation_identity,
        identity_state=_event_payload_text(identity_event, "state"),
        branch_switch_token=branch_switch_token,
        token_state=_event_payload_text(token_event, "state"),
        consumed_at=_event_payload_text(identity_event, "consumed_at")
        or _event_payload_text(token_event, "consumed_at"),
        route_key=route_key,
        packet_id=packet_id,
        packet_hash=packet_hash,
        rendered_from_packet_id=rendered_from_packet_id,
        rendered_from_packet_hash=rendered_from_packet_hash,
        last_dispatch_result=last_dispatch_result,
        suppression_reason=suppression_reason,
        decision_source=decision_source,
        snapshot_version=snapshot_version,
        snapshot_epoch=snapshot_epoch,
        dispatch_cooldown=dispatch_cooldown,
    )


def _build_snapshot_read_semantics_from_persisted_record(
    record: PersistedSessionRecord,
    *,
    freshness_window_seconds: float,
) -> SnapshotReadSemantics:
    last_refreshed = _parse_iso8601(record.last_refreshed_at)
    snapshot_age_seconds: float | None = None
    if last_refreshed is not None:
        snapshot_age_seconds = max(
            0.0,
            (datetime.now(timezone.utc) - last_refreshed).total_seconds(),
        )
    is_fresh = (
        snapshot_age_seconds is not None
        and snapshot_age_seconds <= max(freshness_window_seconds, 0.0)
    )
    return SnapshotReadSemantics(
        read_source=PERSISTED_SPINE_READ_SOURCE,
        is_persisted=True,
        is_fresh=is_fresh,
        is_stale=not is_fresh,
        last_refreshed_at=record.last_refreshed_at,
        snapshot_age_seconds=snapshot_age_seconds,
        session_seq=record.session_seq,
        fact_snapshot_version=record.fact_snapshot_version,
    )


def _build_snapshot_read_semantics_for_live_query() -> SnapshotReadSemantics:
    return SnapshotReadSemantics(
        read_source=LIVE_QUERY_FALLBACK_READ_SOURCE,
        is_persisted=False,
        is_fresh=True,
        is_stale=False,
    )


def _build_snapshot_read_semantics_for_session_events(
    last_observed_at: str | None = None,
) -> SnapshotReadSemantics:
    return SnapshotReadSemantics(
        read_source=SESSION_EVENTS_PROJECTION_READ_SOURCE,
        is_persisted=False,
        is_fresh=True,
        is_stale=False,
        last_refreshed_at=last_observed_at,
    )


def _session_event_sort_key(event: SessionEventRecord) -> tuple[str, int, str, str]:
    return (
        "0" if event.log_seq is not None else "1",
        event.log_seq or 0,
        event.occurred_at,
        event.event_id,
    )


def _latest_goal_contract_snapshot_from_events(
    events: list[SessionEventRecord],
) -> GoalContractSnapshot | None:
    for event in sorted(events, key=_session_event_sort_key, reverse=True):
        if event.event_type not in SESSION_EVENT_GOAL_CONTRACT_TYPES:
            continue
        payload = event.payload if isinstance(event.payload, dict) else {}
        contract_payload = payload.get("contract")
        if not isinstance(contract_payload, dict):
            continue
        return GoalContractSnapshot.model_validate(contract_payload)
    return None


def _list_project_session_events(
    session_service: SessionService,
    project_id: str,
    *,
    include_child_event_only_fallbacks: bool = False,
    native_thread_id: str | None = None,
) -> list[SessionEventRecord]:
    stable_session_id = stable_thread_id_for_project(project_id)
    normalized_native_thread_id = str(native_thread_id or "").strip()
    return sorted(
        [
            event
            for event in session_service.list_events()
            if event.project_id == project_id
            and (
                event.session_id == stable_session_id
                or (
                    include_child_event_only_fallbacks
                    and event.event_type in SESSION_EVENT_EVENT_ONLY_FALLBACK_TYPES
                    and (
                        not normalized_native_thread_id
                        or _session_event_native_thread_id(event) == normalized_native_thread_id
                    )
                )
            )
        ],
        key=_session_event_sort_key,
    )


def _group_project_session_events(
    session_service: SessionService,
    *,
    relevant_types: set[str] | frozenset[str],
    include_child_event_only_fallbacks: bool = False,
) -> dict[str, list[SessionEventRecord]]:
    grouped: dict[str, list[SessionEventRecord]] = {}
    for event in sorted(session_service.list_events(), key=_session_event_sort_key):
        if event.event_type not in relevant_types:
            continue
        if event.session_id != stable_thread_id_for_project(event.project_id):
            if not (
                include_child_event_only_fallbacks
                and event.event_type in SESSION_EVENT_EVENT_ONLY_FALLBACK_TYPES
            ):
                continue
        if not event.project_id:
            continue
        grouped.setdefault(event.project_id, []).append(event)
    return grouped


def _has_relevant_session_projection_events(events: list[SessionEventRecord]) -> bool:
    return any(event.event_type in SESSION_EVENT_PROJECTION_TYPES for event in events)


def _has_event_only_fallback_events(events: list[SessionEventRecord]) -> bool:
    return any(event.event_type in SESSION_EVENT_EVENT_ONLY_FALLBACK_TYPES for event in events)


def _has_session_event_bundle_source(events: list[SessionEventRecord]) -> bool:
    return _has_relevant_session_projection_events(events) or _has_event_only_fallback_events(events)


def _has_relevant_approval_projection_events(events: list[SessionEventRecord]) -> bool:
    return any(event.event_type in SESSION_EVENT_APPROVAL_TYPES for event in events)


def _session_event_native_thread_id(event: SessionEventRecord) -> str:
    payload = event.payload if isinstance(event.payload, dict) else {}
    related_ids = event.related_ids if isinstance(event.related_ids, dict) else {}
    return str(
        payload.get("native_thread_id")
        or payload.get("parent_native_thread_id")
        or related_ids.get("native_thread_id")
        or related_ids.get("parent_native_thread_id")
        or ""
    ).strip()


def _latest_session_event_native_thread_id(events: list[SessionEventRecord]) -> str | None:
    for event in sorted(events, key=_session_event_sort_key, reverse=True):
        native_thread_id = _session_event_native_thread_id(event)
        if native_thread_id:
            return native_thread_id
    return None


def _project_session_events_for_native_thread(
    session_service: SessionService,
    native_thread_id: str,
) -> tuple[str | None, list[SessionEventRecord]]:
    normalized_native_thread_id = str(native_thread_id or "").strip()
    if not normalized_native_thread_id:
        return None, []
    ordered_events = sorted(session_service.list_events(), key=_session_event_sort_key)
    matched_event = next(
        (
            event
            for event in reversed(ordered_events)
            if _session_event_native_thread_id(event) == normalized_native_thread_id
        ),
        None,
    )
    if matched_event is None:
        return None, []
    project_id = matched_event.project_id
    return (
        project_id,
        _list_project_session_events(
            session_service,
            project_id,
            include_child_event_only_fallbacks=True,
            native_thread_id=normalized_native_thread_id,
        ),
    )


def _build_approval_rows_from_session_events(
    events: list[SessionEventRecord],
) -> list[dict[str, Any]]:
    approvals_by_id: dict[str, dict[str, Any]] = {}
    for event in sorted(events, key=_session_event_sort_key):
        if event.event_type not in SESSION_EVENT_APPROVAL_TYPES:
            continue
        approval_id = str(event.related_ids.get("approval_id") or "")
        if not approval_id:
            continue
        if event.event_type == "approval_requested":
            requested_action = str(event.payload.get("requested_action") or "").strip()
            approvals_by_id[approval_id] = {
                "approval_id": approval_id,
                "project_id": event.project_id,
                "thread_id": stable_thread_id_for_project(event.project_id),
                "native_thread_id": (
                    str(
                        event.payload.get("native_thread_id")
                        or event.related_ids.get("native_thread_id")
                        or ""
                    ).strip()
                    or None
                ),
                "command": requested_action,
                "requested_action": requested_action,
                "reason": str(event.payload.get("reason") or event.payload.get("note") or ""),
                "alternative": str(event.payload.get("alternative") or ""),
                "status": "pending",
                "requested_at": event.occurred_at,
                "created_at": event.occurred_at,
                "risk_level": (
                    str(event.payload.get("risk_level") or event.payload.get("risk_class") or "")
                    or None
                ),
            }
            continue
        approvals_by_id.pop(approval_id, None)
    return sorted(
        approvals_by_id.values(),
        key=lambda row: (
            str(row.get("requested_at") or row.get("created_at") or "") == "",
            str(row.get("requested_at") or row.get("created_at") or ""),
            str(row.get("approval_id") or ""),
        ),
    )


def _latest_event_timestamp(events: list[SessionEventRecord]) -> str | None:
    if not events:
        return None
    return sorted(events, key=_session_event_sort_key)[-1].occurred_at


def _build_goal_context_projection(
    *,
    session_service: SessionService | None,
    project_id: str,
) -> dict[str, Any] | None:
    if session_service is None:
        return None
    relevant_events = [
        event
        for event in session_service.list_events()
        if event.project_id == project_id
        and event.event_type
        in {
            "goal_contract_created",
            "goal_contract_revised",
            "goal_contract_adopted_by_child_session",
        }
    ]
    if not relevant_events:
        return None
    latest_event = sorted(relevant_events, key=_session_event_sort_key)[-1]
    contract_payload = latest_event.payload.get("contract")
    if not isinstance(contract_payload, dict):
        return None
    contract = GoalContractSnapshot.model_validate(contract_payload)
    return {
        "goal_contract_version": contract.version,
        "current_phase_goal": contract.current_phase_goal,
        "last_user_instruction": str(contract.metadata.get("last_user_instruction") or "") or None,
    }


def _recovery_sort_key(record: Any) -> tuple[str, int, str, str]:
    return (
        "0" if getattr(record, "log_seq", None) is not None else "1",
        getattr(record, "log_seq", None) or 0,
        str(getattr(record, "updated_at", "")),
        str(getattr(record, "recovery_transaction_id", "")),
    )


def _build_recovery_projection(
    *,
    session_service: SessionService | None,
    project_id: str,
    last_progress_at: str | None = None,
) -> dict[str, Any] | None:
    projection: dict[str, Any] = {}
    if session_service is None:
        return None
    records = session_service.list_recovery_transactions(
        parent_session_id=stable_thread_id_for_project(project_id),
    )
    if records:
        latest = sorted(records, key=_recovery_sort_key)[-1]
        resume_outcome = str(latest.metadata.get("resume_outcome") or "").strip() or None
        if resume_outcome not in {"same_thread_resume", "new_child_session"}:
            resume_outcome = None
        if resume_outcome is None and latest.status in {"failed_retryable", "failed_manual"}:
            resume_outcome = "resume_failed"
        if resume_outcome is None and str(latest.metadata.get("resume_error") or "").strip():
            resume_outcome = "resume_failed"
        projection.update(
            {
                "recovery_outcome": resume_outcome,
                "recovery_status": latest.status,
                "recovery_updated_at": latest.updated_at,
                "recovery_child_session_id": latest.child_session_id,
            }
        )

    suppression_events = session_service.list_events(
        session_id=stable_thread_id_for_project(project_id),
        event_type="recovery_execution_suppressed",
    )
    if suppression_events:
        latest_suppression = sorted(suppression_events, key=_session_event_sort_key)[-1]
        payload = latest_suppression.payload if isinstance(latest_suppression.payload, dict) else {}
        suppression_last_progress_at = str(payload.get("last_progress_at") or "").strip() or None
        normalized_last_progress_at = str(last_progress_at or "").strip() or None
        if suppression_last_progress_at == normalized_last_progress_at:
            projection.update(
                {
                    "recovery_suppression_reason": str(
                        payload.get("suppression_reason") or ""
                    ).strip()
                    or None,
                    "recovery_suppression_source": str(
                        payload.get("suppression_source") or ""
                    ).strip()
                    or None,
                    "recovery_suppression_observed_at": latest_suppression.occurred_at,
                }
            )

    return projection or None


def _merge_fact_records(
    *collections: list[FactRecord],
) -> list[FactRecord]:
    merged: list[FactRecord] = []
    seen_codes: set[str] = set()
    for collection in collections:
        for fact in collection:
            if fact.fact_code in seen_codes:
                continue
            merged.append(fact)
            seen_codes.add(fact.fact_code)
    return merged


def _build_event_projection_task(
    *,
    project_id: str,
    approvals: list[dict[str, Any]],
    events: list[SessionEventRecord],
    persisted_record: PersistedSessionRecord | None = None,
    task: dict[str, Any] | None = None,
) -> dict[str, Any]:
    goal_contract = _latest_goal_contract_snapshot_from_events(events)
    goal_contract_summary = (
        str((goal_contract.metadata if goal_contract is not None else {}).get("last_summary") or "").strip()
        or (goal_contract.current_phase_goal if goal_contract is not None else None)
    )
    event_native_thread_id = _latest_session_event_native_thread_id(events)
    native_thread_id = str(
        task_native_thread_id(task)
        or (
            event_native_thread_id
            if persisted_record is None or _has_event_only_fallback_events(events)
            else ""
        )
        or ""
    ).strip()
    if not native_thread_id:
        native_thread_id = str(
            next(
                (
                    str(approval.get("native_thread_id") or "").strip()
                    for approval in approvals
                    if str(approval.get("native_thread_id") or "").strip()
                ),
                (
                    persisted_record.effective_native_thread_id
                    if persisted_record is not None
                    else event_native_thread_id or ""
                ),
            )
            or ""
        ).strip()
    if not native_thread_id:
        for event in sorted(events, key=_session_event_sort_key, reverse=True):
            payload = event.payload if isinstance(event.payload, dict) else {}
            related_ids = event.related_ids if isinstance(event.related_ids, dict) else {}
            native_thread_id = str(
                payload.get("native_thread_id")
                or payload.get("parent_native_thread_id")
                or related_ids.get("native_thread_id")
                or related_ids.get("parent_native_thread_id")
                or ""
            ).strip()
            if native_thread_id:
                break
    activity_phase = str(
        (task or {}).get("phase")
        or (
            persisted_record.progress.activity_phase
            if persisted_record is not None
            else (goal_contract.phase if goal_contract is not None else "unknown")
        )
        or "unknown"
    )
    files_touched = list(
        (task or {}).get("files_touched")
        or (
            list(persisted_record.progress.files_touched)
            if persisted_record is not None
            else []
        )
    )
    event_last_progress_at = _latest_event_timestamp(events)
    for event in sorted(events, key=_session_event_sort_key, reverse=True):
        if event.event_type != "recovery_execution_suppressed":
            continue
        payload = event.payload if isinstance(event.payload, dict) else {}
        suppression_last_progress_at = str(payload.get("last_progress_at") or "").strip()
        if suppression_last_progress_at:
            event_last_progress_at = suppression_last_progress_at
            break
    last_progress_at = _max_iso8601_timestamp(
        event_last_progress_at,
        str((task or {}).get("last_progress_at") or "").strip() or None,
        (
            persisted_record.progress.last_progress_at
            if persisted_record is not None
            else None
        ),
    )
    preserve_source_state = (
        task is not None
        or persisted_record is not None
        or (
            _has_event_only_fallback_events(events)
            and not _has_relevant_session_projection_events(events)
        )
    )
    pending_approval = bool(approvals)
    summary = "waiting for approval" if pending_approval else "session active"
    status = "waiting_human" if pending_approval else "running"
    context_pressure = "low"
    stuck_level = 0
    failure_count = 0
    if preserve_source_state:
        pending_approval = bool((task or {}).get("pending_approval")) or bool(approvals)
        summary = str(
            (task or {}).get("last_summary")
            or (
                persisted_record.progress.summary or persisted_record.session.headline
                if persisted_record is not None
                else ""
            )
            or goal_contract_summary
            or ("waiting for approval" if pending_approval else "session active")
        ).strip()
        status = str((task or {}).get("status") or "").strip()
        if not status:
            status = "waiting_human" if pending_approval else "running"
        context_pressure = str(
            (task or {}).get("context_pressure")
            or (
                persisted_record.progress.context_pressure
                if persisted_record is not None
                else "low"
            )
            or "low"
        ).strip()
        stuck_level = int(
            (task or {}).get("stuck_level")
            if (task or {}).get("stuck_level") is not None
            else (
                persisted_record.progress.stuck_level
                if persisted_record is not None
                else 0
            )
        )
        failure_count = int(
            (task or {}).get("failure_count")
            if (task or {}).get("failure_count") is not None
            else (
                3
                if persisted_record is not None
                and any(fact.fact_code == "repeat_failure" for fact in persisted_record.facts)
                else 0
            )
        )
    return _task_with_authoritative_project_execution_state(
        {
        "project_id": project_id,
        "thread_id": stable_thread_id_for_project(project_id),
        "native_thread_id": native_thread_id or None,
        "project_execution_state": (
            str((task or {}).get("project_execution_state") or "").strip()
            or (
                "paused"
                if persisted_record is not None
                and any(fact.fact_code == "project_not_active" for fact in persisted_record.facts)
                else None
            )
        ),
        "status": status,
        "phase": activity_phase,
        "pending_approval": pending_approval,
        "last_summary": summary,
        "files_touched": files_touched,
        "context_pressure": context_pressure,
        "stuck_level": stuck_level,
        "failure_count": failure_count,
        "last_progress_at": last_progress_at,
        "last_local_manual_activity_at": (
            str((task or {}).get("last_local_manual_activity_at") or "").strip()
            or (
                persisted_record.last_local_manual_activity_at
                if persisted_record is not None
                else None
            )
        ),
        "last_error_signature": str((task or {}).get("last_error_signature") or "").strip() or None,
        }
    ) or {}


def _build_session_read_bundle_from_session_events(
    *,
    project_id: str,
    events: list[SessionEventRecord],
    persisted_record: PersistedSessionRecord | None = None,
    task: dict[str, Any] | None = None,
    approval_store: CanonicalApprovalStore | None = None,
    session_service: SessionService | None = None,
    decision_store: PolicyDecisionStore | None = None,
    receipt_store: ActionReceiptStore | None = None,
    orchestration_state_store: ResidentOrchestrationStateStore | None = None,
    dispatch_cooldown_seconds: float = 0.0,
    liveness_now: datetime | None = None,
) -> SessionReadBundle:
    event_approvals = _build_approval_rows_from_session_events(events)
    has_approval_projection_events = _has_relevant_approval_projection_events(events)
    terminal_event_approval_ids: set[str] = set()
    for event in events:
        if event.event_type == "approval_requested":
            continue
        if event.event_type not in SESSION_EVENT_APPROVAL_TYPES:
            continue
        approval_id = str(event.related_ids.get("approval_id") or "").strip()
        if approval_id:
            terminal_event_approval_ids.add(approval_id)
    canonical_rows = _list_actionable_canonical_approval_rows(
        approval_store,
        project_id=project_id,
    )
    persisted_rows = (
        [_approval_projection_to_row(approval) for approval in persisted_record.approval_queue]
        if persisted_record is not None and not has_approval_projection_events
        else []
    )
    known_canonical_ids: set[str] = set()
    actionable_canonical_ids = {
        str(row.get("approval_id") or "")
        for row in canonical_rows
        if str(row.get("approval_id") or "")
    }
    if approval_store is not None:
        known_canonical_ids = {
            record.approval_id
            for record in approval_store.list_records()
            if record.project_id == project_id
        }
    approvals_by_id: dict[str, dict[str, Any]] = {}
    for row in persisted_rows:
        approval_id = str(row.get("approval_id") or "")
        if not approval_id or approval_id in terminal_event_approval_ids:
            continue
        if approval_store is not None:
            if approval_id in known_canonical_ids and approval_id not in actionable_canonical_ids:
                continue
        approvals_by_id[approval_id] = dict(row)
    for row in event_approvals:
        approval_id = str(row.get("approval_id") or "")
        if not approval_id:
            continue
        if approval_store is not None:
            if approval_id not in actionable_canonical_ids:
                continue
        approvals_by_id[approval_id] = dict(row)
    for row in canonical_rows:
        approval_id = str(row.get("approval_id") or "")
        if approval_id and approval_id not in terminal_event_approval_ids:
            approvals_by_id[approval_id] = dict(row)
    approvals = sorted(
        approvals_by_id.values(),
        key=lambda row: (
            str(row.get("requested_at") or row.get("created_at") or "") == "",
            str(row.get("requested_at") or row.get("created_at") or ""),
            str(row.get("approval_id") or ""),
        ),
    )
    projected_task = _build_event_projection_task(
        project_id=project_id,
        approvals=approvals,
        events=events,
        persisted_record=persisted_record,
        task=task,
    )
    projected_native_thread_id = task_native_thread_id(projected_task)
    stale_approval_progress_at = _max_iso8601_timestamp(
        str((task or {}).get("last_progress_at") or "").strip() or None,
        (
            persisted_record.progress.last_progress_at
            if persisted_record is not None and persisted_record.progress is not None
            else None
        ),
    )
    filtered_approvals = [
        approval
        for approval in approvals
        if _approval_row_matches_native_thread(approval, projected_native_thread_id)
        and not _approval_row_is_stale_after_progress_at(stale_approval_progress_at, approval)
    ]
    if filtered_approvals != approvals:
        approvals = filtered_approvals
        projected_task = _build_event_projection_task(
            project_id=project_id,
            approvals=approvals,
            events=events,
            persisted_record=persisted_record,
            task=task,
        )
    if liveness_now is not None:
        projected_task = _directory_task_with_projected_active_state(projected_task) or projected_task
        projected_task = _task_with_authoritative_project_execution_state(
            projected_task,
            now=_directory_projected_task_liveness_reference_time(
                projected_task,
                now=liveness_now,
            ),
        ) or projected_task
    approval_facts = build_fact_records(
        project_id=project_id,
        task=projected_task,
        approvals=approvals,
    )
    if any(fact.fact_code == "project_not_active" for fact in approval_facts):
        approvals = []
        approval_facts = build_fact_records(
            project_id=project_id,
            task=projected_task,
            approvals=approvals,
        )
    event_facts = build_session_service_fact_records(
        project_id=project_id,
        events=events,
    )
    facts = _merge_fact_records(approval_facts, event_facts)
    native_thread_id = task_native_thread_id(projected_task)
    recovery = _build_recovery_projection(
        session_service=session_service,
        project_id=project_id,
        last_progress_at=str(projected_task.get("last_progress_at") or "") or None,
    )
    goal_context = _build_goal_context_projection(
        session_service=session_service,
        project_id=project_id,
    )
    decision_trace = _build_decision_trace_projection(
        decision_store,
        project_id=project_id,
        session_id=stable_thread_id_for_project(project_id),
        native_thread_id=native_thread_id,
    )
    continuation_control_plane = _build_continuation_control_plane_projection(
        project_id=project_id,
        events=events,
        decision_store=decision_store,
        receipt_store=receipt_store,
        state_store=orchestration_state_store,
        dispatch_cooldown_seconds=dispatch_cooldown_seconds,
    )
    return SessionReadBundle(
        project_id=project_id,
        task=projected_task,
        approvals=approvals,
        facts=facts,
        session=build_session_projection(
            project_id=project_id,
            task=projected_task,
            approvals=approvals,
            facts=facts,
        ),
        progress=build_task_progress_view(
            project_id=project_id,
            task=projected_task,
            facts=facts,
            recovery=recovery,
            decision_trace=decision_trace,
            goal_context=goal_context,
            continuation_control_plane=continuation_control_plane,
        ),
        approval_queue=build_approval_projections(
            project_id=project_id,
            native_thread_id=native_thread_id,
            approvals=approvals,
        ),
        snapshot=_build_snapshot_read_semantics_for_session_events(
            _latest_event_timestamp(events),
        ),
    )


def _load_task_or_raise(
    client: CodexRuntimeClient,
    project_id: str,
) -> dict[str, Any] | None:
    try:
        body = client.get_envelope(project_id)
    except (httpx.RequestError, RuntimeError, OSError) as exc:
        raise SessionSpineUpstreamError(dict(CONTROL_LINK_ERROR)) from exc
    if not body.get("success"):
        error = body.get("error")
        if isinstance(error, dict):
            raise SessionSpineUpstreamError(dict(error))
        raise SessionSpineUpstreamError(dict(CONTROL_LINK_ERROR))
    data = body.get("data")
    if not isinstance(data, dict):
        raise SessionSpineUpstreamError(
            {"code": "CONTROL_LINK_ERROR", "message": "runtime 返回数据格式异常"}
        )
    return data


def _load_task_by_native_thread_or_raise(
    client: CodexRuntimeClient,
    native_thread_id: str,
) -> dict[str, Any] | None:
    try:
        body = client.get_envelope_by_thread(native_thread_id)
    except (httpx.RequestError, RuntimeError, OSError) as exc:
        raise SessionSpineUpstreamError(dict(CONTROL_LINK_ERROR)) from exc
    if not body.get("success"):
        error = body.get("error")
        if isinstance(error, dict):
            raise SessionSpineUpstreamError(dict(error))
        raise SessionSpineUpstreamError(dict(CONTROL_LINK_ERROR))
    data = body.get("data")
    if not isinstance(data, dict):
        raise SessionSpineUpstreamError(
            {"code": "CONTROL_LINK_ERROR", "message": "runtime 返回数据格式异常"}
        )
    return data


def _load_approvals_or_raise(
    client: CodexRuntimeClient,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    try:
        pending_items = client.list_approvals(status="pending", project_id=project_id)
    except (httpx.RequestError, RuntimeError, OSError) as exc:
        raise SessionSpineUpstreamError(dict(CONTROL_LINK_ERROR)) from exc
    deferred_items = _load_deferred_approvals_or_raise(client, project_id)
    rows_by_id: dict[str, dict[str, Any]] = {}
    for item in [*pending_items, *deferred_items]:
        row = dict(item)
        if not is_actionable_approval(row):
            continue
        if project_id is not None and str(row.get("project_id") or "") != project_id:
            continue
        approval_id = str(row.get("approval_id") or "")
        if approval_id:
            rows_by_id[approval_id] = row
    return sorted(
        rows_by_id.values(),
        key=lambda row: (
            str(row.get("requested_at") or row.get("created_at") or "") == "",
            str(row.get("requested_at") or row.get("created_at") or ""),
            str(row.get("approval_id") or ""),
        ),
    )


def _load_deferred_approvals_or_raise(
    client: CodexRuntimeClient,
    project_id: str | None,
) -> list[dict[str, Any]]:
    try:
        return client.list_approvals(
            status="approved",
            project_id=project_id,
            decided_by="policy-auto",
            callback_status="deferred",
        )
    except (httpx.RequestError, RuntimeError, OSError):
        try:
            approved_items = client.list_approvals(
                status="approved",
                project_id=project_id,
            )
        except (httpx.RequestError, RuntimeError, OSError) as exc:
            raise SessionSpineUpstreamError(dict(CONTROL_LINK_ERROR)) from exc
        return [
            dict(item)
            for item in approved_items
            if is_deferred_policy_auto_approval(dict(item))
        ]


def _load_tasks_or_raise(client: CodexRuntimeClient) -> list[dict[str, Any]]:
    try:
        return client.list_tasks()
    except (httpx.RequestError, RuntimeError, OSError) as exc:
        raise SessionSpineUpstreamError(dict(CONTROL_LINK_ERROR)) from exc


def _load_workspace_activity_or_raise(
    client: CodexRuntimeClient,
    project_id: str,
    *,
    recent_minutes: int,
) -> dict[str, Any]:
    try:
        body = client.get_workspace_activity_envelope(
            project_id,
            recent_minutes=recent_minutes,
        )
    except AttributeError:
        return {}
    except (httpx.RequestError, RuntimeError, OSError) as exc:
        raise SessionSpineUpstreamError(dict(CONTROL_LINK_ERROR)) from exc
    if not body.get("success"):
        error = body.get("error")
        if isinstance(error, dict):
            raise SessionSpineUpstreamError(dict(error))
        raise SessionSpineUpstreamError(dict(CONTROL_LINK_ERROR))
    data = body.get("data")
    if not isinstance(data, dict):
        raise SessionSpineUpstreamError(
            {"code": "CONTROL_LINK_ERROR", "message": "runtime 返回数据格式异常"}
        )
    activity = data.get("activity")
    if not isinstance(activity, dict):
        raise SessionSpineUpstreamError(
            {"code": "CONTROL_LINK_ERROR", "message": "runtime 返回数据格式异常"}
        )
    return dict(activity)


def _task_with_workspace_activity(
    task: dict[str, Any] | None,
    activity: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(task, dict) or not isinstance(activity, dict):
        return task
    if not activity:
        return task
    updated = dict(task)
    updated["workspace_cwd_exists"] = bool(activity.get("cwd_exists"))
    updated["workspace_files_scanned"] = int(activity.get("files_scanned") or 0)
    updated["workspace_recent_change_count"] = int(activity.get("recent_change_count") or 0)
    latest_mtime_iso = str(activity.get("latest_mtime_iso") or "").strip()
    updated["workspace_latest_mtime_iso"] = latest_mtime_iso or None
    if not bool(activity.get("cwd_exists")) or not latest_mtime_iso:
        return updated
    latest_mtime = _parse_iso8601(latest_mtime_iso)
    if latest_mtime is None:
        return updated
    recent_change_count = int(activity.get("recent_change_count") or 0)
    last_progress = _parse_iso8601(str(updated.get("last_progress_at") or "").strip() or None)
    if recent_change_count <= 0 and last_progress is not None and latest_mtime <= last_progress:
        return updated
    current_manual = str(updated.get("last_local_manual_activity_at") or "").strip()
    current_manual_dt = _parse_iso8601(current_manual or None)
    last_progress = _parse_iso8601(str(updated.get("last_progress_at") or "").strip() or None)
    if last_progress is not None and latest_mtime > last_progress:
        updated["workspace_local_activity_at"] = latest_mtime_iso
        return updated
    if current_manual_dt is None or latest_mtime > current_manual_dt:
        updated["last_local_manual_activity_at"] = latest_mtime_iso
    return updated


def _build_session_read_bundle(
    *,
    project_id: str,
    task: dict[str, Any] | None,
    approvals: list[dict[str, Any]],
    session_service: SessionService | None = None,
    decision_store: PolicyDecisionStore | None = None,
    receipt_store: ActionReceiptStore | None = None,
    orchestration_state_store: ResidentOrchestrationStateStore | None = None,
    dispatch_cooldown_seconds: float = 0.0,
    liveness_now: datetime | None = None,
) -> SessionReadBundle:
    if liveness_now is None:
        liveness_now = _task_liveness_reference_time(task)
    task = _task_with_authoritative_project_execution_state(task, now=liveness_now)
    task_facts = build_fact_records(project_id=project_id, task=task, approvals=approvals)
    if any(fact.fact_code == "project_not_active" for fact in task_facts):
        approvals = []
        task_facts = build_fact_records(project_id=project_id, task=task, approvals=approvals)
    session_events = (
        _list_project_session_events(
            session_service,
            project_id,
            include_child_event_only_fallbacks=True,
        )
        if session_service is not None
        else []
    )
    event_facts = (
        build_session_service_fact_records(project_id=project_id, events=session_events)
        if session_events
        else []
    )
    facts = _merge_fact_records(task_facts, event_facts)
    native_thread_id = task_native_thread_id(task)
    recovery = _build_recovery_projection(
        session_service=session_service,
        project_id=project_id,
        last_progress_at=str(task.get("last_progress_at") or "") or None,
    )
    goal_context = _build_goal_context_projection(
        session_service=session_service,
        project_id=project_id,
    )
    decision_trace = _build_decision_trace_projection(
        decision_store,
        project_id=project_id,
        session_id=stable_thread_id_for_project(project_id),
        native_thread_id=native_thread_id,
    )
    continuation_control_plane = _build_continuation_control_plane_projection(
        project_id=project_id,
        events=session_events,
        decision_store=decision_store,
        receipt_store=receipt_store,
        state_store=orchestration_state_store,
        dispatch_cooldown_seconds=dispatch_cooldown_seconds,
    )
    return SessionReadBundle(
        project_id=project_id,
        task=task,
        approvals=approvals,
        facts=facts,
        session=build_session_projection(
            project_id=project_id,
            task=task,
            approvals=approvals,
            facts=facts,
        ),
        progress=build_task_progress_view(
            project_id=project_id,
            task=task,
            facts=facts,
            recovery=recovery,
            decision_trace=decision_trace,
            goal_context=goal_context,
            continuation_control_plane=continuation_control_plane,
        ),
        approval_queue=build_approval_projections(
            project_id=project_id,
            native_thread_id=native_thread_id,
            approvals=approvals,
        ),
        snapshot=None,
    )


def _approval_projection_to_row(approval: ApprovalProjection) -> dict[str, Any]:
    return {
        "approval_id": approval.approval_id,
        "project_id": approval.project_id,
        "native_thread_id": approval.native_thread_id,
        "command": approval.command,
        "reason": approval.reason,
        "alternative": approval.alternative,
        "status": approval.status,
        "requested_at": approval.requested_at,
        "decided_at": approval.decided_at,
        "decided_by": approval.decided_by,
        "risk_level": approval.risk_level,
    }


def _canonical_approval_to_row(approval: Any) -> dict[str, Any]:
    return {
        "approval_id": approval.approval_id,
        "project_id": approval.project_id,
        "thread_id": approval.thread_id,
        "native_thread_id": approval.effective_native_thread_id,
        "command": approval.requested_action,
        "requested_action": approval.requested_action,
        "status": approval.status,
        "requested_at": approval.created_at,
        "created_at": approval.created_at,
        "decided_at": approval.decided_at,
        "decided_by": approval.decided_by,
        "decision": approval.decision.model_dump(mode="json"),
    }


def _list_actionable_canonical_approval_rows(
    approval_store: CanonicalApprovalStore | None,
    *,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    if approval_store is None:
        return []
    rows = [
        _canonical_approval_to_row(record)
        for record in approval_store.list_records()
        if project_id is None or record.project_id == project_id
    ]
    actionable = [row for row in rows if is_actionable_approval(row)]
    return sorted(
        actionable,
        key=lambda row: (
            str(row.get("requested_at") or row.get("created_at") or "") == "",
            str(row.get("requested_at") or row.get("created_at") or ""),
            str(row.get("approval_id") or ""),
        ),
    )


def _canonical_approval_id_sets(
    approval_store: CanonicalApprovalStore | None,
    *,
    project_id: str | None = None,
) -> tuple[set[str], set[str]]:
    if approval_store is None:
        return set(), set()
    known_ids = {
        record.approval_id
        for record in approval_store.list_records()
        if project_id is None or record.project_id == project_id
    }
    actionable_ids = {
        str(row.get("approval_id") or "")
        for row in _list_actionable_canonical_approval_rows(
            approval_store,
            project_id=project_id,
        )
        if str(row.get("approval_id") or "")
    }
    return known_ids, actionable_ids


def _filter_persisted_approval_projections(
    approvals: list[ApprovalProjection],
    *,
    approval_store: CanonicalApprovalStore | None,
    project_id: str | None = None,
) -> list[ApprovalProjection]:
    known_ids, actionable_ids = _canonical_approval_id_sets(
        approval_store,
        project_id=project_id,
    )
    if not known_ids:
        return list(approvals)
    return [
        approval
        for approval in approvals
        if approval.approval_id not in known_ids or approval.approval_id in actionable_ids
    ]


def _persisted_record_has_orphaned_approval_state(
    record: PersistedSessionRecord,
    *,
    canonical_approvals: list[dict[str, Any]],
    session_events: list[SessionEventRecord],
) -> bool:
    has_persisted_approval_state = bool(record.approval_queue) or any(
        fact.fact_code in {"approval_pending", "awaiting_human_direction"}
        for fact in record.facts
    )
    if not has_persisted_approval_state:
        return False
    if canonical_approvals:
        return False
    if not any(event.event_type in SESSION_EVENT_FACT_TYPES for event in session_events):
        return False
    if _has_relevant_approval_projection_events(session_events):
        return False
    return True


def _merge_approval_rows(
    persisted_approvals: list[ApprovalProjection],
    canonical_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows_by_id: dict[str, dict[str, Any]] = {}
    for approval in persisted_approvals:
        row = _approval_projection_to_row(approval)
        approval_id = str(row.get("approval_id") or "")
        if approval_id:
            rows_by_id[approval_id] = row
    for row in canonical_rows:
        approval_id = str(row.get("approval_id") or "")
        if approval_id and approval_id not in rows_by_id:
            rows_by_id[approval_id] = dict(row)
    return sorted(
        rows_by_id.values(),
        key=lambda row: (
            str(row.get("requested_at") or row.get("created_at") or "") == "",
            str(row.get("requested_at") or row.get("created_at") or ""),
            str(row.get("approval_id") or ""),
        ),
    )


def _task_from_persisted_record(
    record: PersistedSessionRecord,
    *,
    approvals: list[dict[str, Any]],
    native_thread_id: str | None = None,
) -> dict[str, Any]:
    fact_codes = {fact.fact_code for fact in record.facts}
    session_state = str(record.session.session_state or "").strip()
    status_by_session_state = {
        "active": "running",
        "blocked": "running",
        "awaiting_approval": "waiting_human",
        "unavailable": "running",
    }
    status = "waiting_human" if approvals else status_by_session_state.get(session_state, "running")
    return {
        "project_id": record.project_id,
        "thread_id": record.thread_id,
        "native_thread_id": native_thread_id or record.effective_native_thread_id,
        "status": status,
        "phase": record.progress.activity_phase,
        "pending_approval": bool(approvals),
        "last_summary": record.progress.summary or record.session.headline,
        "files_touched": list(record.progress.files_touched),
        "context_pressure": record.progress.context_pressure,
        "stuck_level": record.progress.stuck_level,
        "failure_count": 3 if "repeat_failure" in fact_codes else 0,
        "last_progress_at": record.progress.last_progress_at,
        "last_local_manual_activity_at": record.last_local_manual_activity_at,
    }


def _build_session_read_bundle_from_persisted_record(
    record: PersistedSessionRecord,
    *,
    approval_store: CanonicalApprovalStore | None = None,
    freshness_window_seconds: float,
    session_service: SessionService | None = None,
    decision_store: PolicyDecisionStore | None = None,
    receipt_store: ActionReceiptStore | None = None,
    orchestration_state_store: ResidentOrchestrationStateStore | None = None,
    dispatch_cooldown_seconds: float = 0.0,
    liveness_now: datetime | None = None,
) -> SessionReadBundle:
    approval_fact_codes = {"approval_pending", "awaiting_human_direction"}
    session_events = (
        _list_project_session_events(
            session_service,
            record.project_id,
            include_child_event_only_fallbacks=True,
        )
        if session_service is not None
        else []
    )
    canonical_approvals = _list_actionable_canonical_approval_rows(
        approval_store,
        project_id=record.project_id,
    )
    if (
        canonical_approvals
        or _has_session_event_bundle_source(session_events)
    ):
        bundle = _build_session_read_bundle_from_session_events(
            project_id=record.project_id,
            events=session_events,
            persisted_record=record,
            approval_store=approval_store,
            session_service=session_service,
            decision_store=decision_store,
            receipt_store=receipt_store,
            orchestration_state_store=orchestration_state_store,
            dispatch_cooldown_seconds=dispatch_cooldown_seconds,
            liveness_now=liveness_now,
        )
        return SessionReadBundle(
            project_id=bundle.project_id,
            task=bundle.task,
            approvals=bundle.approvals,
            facts=bundle.facts,
            session=bundle.session,
            progress=bundle.progress,
            approval_queue=bundle.approval_queue,
            snapshot=_build_snapshot_read_semantics_from_persisted_record(
                record,
                freshness_window_seconds=freshness_window_seconds,
            ),
        )
    projected_task = _task_from_persisted_record(record, approvals=[])
    if liveness_now is not None:
        projected_task = _directory_task_with_projected_active_state(projected_task) or projected_task
        projected_task = _task_with_authoritative_project_execution_state(
            projected_task,
            now=_directory_projected_task_liveness_reference_time(
                projected_task,
                now=liveness_now,
            ),
        ) or projected_task
        active_facts = build_fact_records(
            project_id=record.project_id,
            task=projected_task,
            approvals=[],
        )
        if any(fact.fact_code == "project_not_active" for fact in active_facts):
            return SessionReadBundle(
                project_id=record.project_id,
                task=projected_task,
                approvals=[],
                facts=active_facts,
                session=build_session_projection(
                    project_id=record.project_id,
                    task=projected_task,
                    approvals=[],
                    facts=active_facts,
                ),
                progress=build_task_progress_view(
                    project_id=record.project_id,
                    task=projected_task,
                    facts=active_facts,
                ),
                approval_queue=[],
                snapshot=_build_snapshot_read_semantics_from_persisted_record(
                    record,
                    freshness_window_seconds=freshness_window_seconds,
                ),
            )
    recovery = _build_recovery_projection(
        session_service=session_service,
        project_id=record.project_id,
        last_progress_at=record.progress.last_progress_at,
    )
    goal_context = _build_goal_context_projection(
        session_service=session_service,
        project_id=record.project_id,
    )
    decision_trace = _build_decision_trace_projection(
        decision_store,
        project_id=record.project_id,
        session_id=record.thread_id,
        native_thread_id=record.effective_native_thread_id,
    )
    continuation_control_plane = _build_continuation_control_plane_projection(
        project_id=record.project_id,
        events=session_events,
        decision_store=decision_store,
        receipt_store=receipt_store,
        state_store=orchestration_state_store,
        dispatch_cooldown_seconds=dispatch_cooldown_seconds,
    )
    effective_approval_queue = _filter_persisted_approval_projections(
        record.approval_queue,
        approval_store=approval_store,
        project_id=record.project_id,
    )
    effective_facts = list(record.facts)
    effective_session = record.session
    if effective_approval_queue != list(record.approval_queue):
        if not effective_approval_queue:
            effective_facts = [
                fact for fact in record.facts if fact.fact_code not in approval_fact_codes
            ]
        projected_task = _task_from_persisted_record(record, approvals=effective_approval_queue)
        effective_session = build_session_projection(
            project_id=record.project_id,
            task=projected_task,
            approvals=[
                approval.model_dump(mode="json") for approval in effective_approval_queue
            ],
            facts=effective_facts,
        )
    return SessionReadBundle(
        project_id=record.project_id,
        task=None,
        approvals=[],
        facts=effective_facts,
        session=effective_session,
        progress=record.progress.model_copy(
            update={
                "recovery_outcome": (recovery or {}).get("recovery_outcome"),
                "recovery_status": (recovery or {}).get("recovery_status"),
                "recovery_updated_at": (recovery or {}).get("recovery_updated_at"),
                "recovery_child_session_id": (recovery or {}).get("recovery_child_session_id"),
                "recovery_suppression_reason": (recovery or {}).get(
                    "recovery_suppression_reason"
                ),
                "recovery_suppression_source": (recovery or {}).get(
                    "recovery_suppression_source"
                ),
                "recovery_suppression_observed_at": (recovery or {}).get(
                    "recovery_suppression_observed_at"
                ),
                "goal_contract_version": (goal_context or {}).get("goal_contract_version"),
                "current_phase_goal": (goal_context or {}).get("current_phase_goal"),
                "last_user_instruction": (goal_context or {}).get("last_user_instruction"),
                "decision_trace_ref": (decision_trace or {}).get("decision_trace_ref"),
                "decision_degrade_reason": (decision_trace or {}).get("decision_degrade_reason"),
                "provider_output_schema_ref": (decision_trace or {}).get(
                    "provider_output_schema_ref"
                ),
                "continuation_control_plane": continuation_control_plane,
            }
        ),
        approval_queue=effective_approval_queue,
        snapshot=_build_snapshot_read_semantics_from_persisted_record(
            record,
            freshness_window_seconds=freshness_window_seconds,
        ),
    )


def load_persisted_session_record_or_raise(
    project_id: str,
    *,
    store: SessionSpineStore,
) -> PersistedSessionRecord:
    record = store.get(project_id)
    if record is None:
        raise SessionSpineUpstreamError(dict(PERSISTED_SESSION_SPINE_REQUIRED_ERROR))
    return record


def evaluate_session_policy_from_persisted_spine(
    project_id: str,
    *,
    action_ref: str,
    trigger: str,
    store: SessionSpineStore,
    decision_store: PolicyDecisionStore | None = None,
    delivery_outbox_store: object | None = None,
) -> CanonicalDecisionRecord:
    record = load_persisted_session_record_or_raise(project_id, store=store)
    decision = evaluate_persisted_session_policy(
        record,
        action_ref=action_ref,
        trigger=trigger,
    )
    canonical_decision = decision_store.put(decision) if decision_store is not None else decision
    if delivery_outbox_store is not None:
        from watchdog.services.delivery.envelopes import build_envelopes_for_decision

        delivery_outbox_store.enqueue_envelopes(build_envelopes_for_decision(canonical_decision))
    return canonical_decision


def build_session_read_bundle(
    client: CodexRuntimeClient,
    project_id: str,
    *,
    session_service: SessionService | None = None,
    store: SessionSpineStore | None = None,
    approval_store: CanonicalApprovalStore | None = None,
    decision_store: PolicyDecisionStore | None = None,
    receipt_store: ActionReceiptStore | None = None,
    orchestration_state_store: ResidentOrchestrationStateStore | None = None,
    dispatch_cooldown_seconds: float = 0.0,
    freshness_window_seconds: float = DEFAULT_SESSION_SPINE_FRESHNESS_WINDOW_SECONDS,
) -> SessionReadBundle:
    session_events: list[SessionEventRecord] = []
    persisted_record = store.get(project_id) if store is not None else None
    canonical_approvals = _list_actionable_canonical_approval_rows(
        approval_store,
        project_id=project_id,
    )
    should_verify_orphaned_persisted_approval = False
    if session_service is not None:
        session_events = _list_project_session_events(
            session_service,
            project_id,
            include_child_event_only_fallbacks=True,
        )
    if store is not None:
        if persisted_record is not None:
            should_verify_orphaned_persisted_approval = _persisted_record_has_orphaned_approval_state(
                persisted_record,
                canonical_approvals=canonical_approvals,
                session_events=session_events,
            )
            if not should_verify_orphaned_persisted_approval:
                return _build_session_read_bundle_from_persisted_record(
                    persisted_record,
                    approval_store=approval_store,
                    freshness_window_seconds=freshness_window_seconds,
                    session_service=session_service,
                    decision_store=decision_store,
                    receipt_store=receipt_store,
                    orchestration_state_store=orchestration_state_store,
                    dispatch_cooldown_seconds=dispatch_cooldown_seconds,
                )
    if (
        persisted_record is None
        and session_service is not None
        and _has_relevant_session_projection_events(session_events)
    ):
        return _build_session_read_bundle_from_session_events(
            project_id=project_id,
            events=session_events,
            approval_store=approval_store,
            session_service=session_service,
            decision_store=decision_store,
            receipt_store=receipt_store,
            orchestration_state_store=orchestration_state_store,
            dispatch_cooldown_seconds=dispatch_cooldown_seconds,
        )
    try:
        task = _load_task_or_raise(client, project_id)
        approvals = _load_approvals_or_raise(client, project_id)
    except SessionSpineUpstreamError:
        if should_verify_orphaned_persisted_approval and persisted_record is not None:
            return _build_session_read_bundle_from_persisted_record(
                persisted_record,
                approval_store=approval_store,
                freshness_window_seconds=freshness_window_seconds,
                session_service=session_service,
                decision_store=decision_store,
                receipt_store=receipt_store,
                orchestration_state_store=orchestration_state_store,
                dispatch_cooldown_seconds=dispatch_cooldown_seconds,
            )
        if session_service is not None and _has_session_event_bundle_source(session_events):
            return _build_session_read_bundle_from_session_events(
                project_id=project_id,
                events=session_events,
                persisted_record=persisted_record,
                approval_store=approval_store,
                session_service=session_service,
                decision_store=decision_store,
                receipt_store=receipt_store,
                orchestration_state_store=orchestration_state_store,
                dispatch_cooldown_seconds=dispatch_cooldown_seconds,
            )
        raise
    try:
        task = _task_with_workspace_activity(
            task,
            _load_workspace_activity_or_raise(client, project_id, recent_minutes=30),
        )
    except SessionSpineUpstreamError:
        pass
    bundle = _build_session_read_bundle(
        project_id=project_id,
        task=task,
        approvals=approvals,
        session_service=session_service,
        decision_store=decision_store,
        receipt_store=receipt_store,
        orchestration_state_store=orchestration_state_store,
        dispatch_cooldown_seconds=dispatch_cooldown_seconds,
    )
    return SessionReadBundle(
        project_id=bundle.project_id,
        task=bundle.task,
        approvals=bundle.approvals,
        facts=bundle.facts,
        session=bundle.session,
        progress=bundle.progress,
        approval_queue=bundle.approval_queue,
        snapshot=_build_snapshot_read_semantics_for_live_query(),
    )


def build_session_read_bundle_by_native_thread(
    client: CodexRuntimeClient,
    native_thread_id: str,
    *,
    session_service: SessionService | None = None,
    store: SessionSpineStore | None = None,
    approval_store: CanonicalApprovalStore | None = None,
    decision_store: PolicyDecisionStore | None = None,
    receipt_store: ActionReceiptStore | None = None,
    orchestration_state_store: ResidentOrchestrationStateStore | None = None,
    dispatch_cooldown_seconds: float = 0.0,
    freshness_window_seconds: float = DEFAULT_SESSION_SPINE_FRESHNESS_WINDOW_SECONDS,
) -> SessionReadBundle:
    session_events: list[SessionEventRecord] = []
    fallback_project_id: str | None = None
    fallback_session_events: list[SessionEventRecord] = []
    persisted_record = store.get_by_native_thread(native_thread_id) if store is not None else None
    if session_service is not None and persisted_record is not None:
        session_events = _list_project_session_events(
            session_service,
            persisted_record.project_id,
            include_child_event_only_fallbacks=True,
            native_thread_id=native_thread_id,
        )
        if (
            _has_session_event_bundle_source(session_events)
        ):
            return _build_session_read_bundle_from_session_events(
                project_id=persisted_record.project_id,
                events=session_events,
                persisted_record=persisted_record,
                approval_store=approval_store,
                session_service=session_service,
                decision_store=decision_store,
                receipt_store=receipt_store,
                orchestration_state_store=orchestration_state_store,
                dispatch_cooldown_seconds=dispatch_cooldown_seconds,
            )
    if session_service is not None and persisted_record is None:
        fallback_project_id, fallback_session_events = _project_session_events_for_native_thread(
            session_service,
            native_thread_id,
        )
    if store is not None:
        if persisted_record is not None:
            return _build_session_read_bundle_from_persisted_record(
                persisted_record,
                approval_store=approval_store,
                freshness_window_seconds=freshness_window_seconds,
                session_service=session_service,
                decision_store=decision_store,
                receipt_store=receipt_store,
                orchestration_state_store=orchestration_state_store,
                dispatch_cooldown_seconds=dispatch_cooldown_seconds,
            )
    try:
        task = _load_task_by_native_thread_or_raise(client, native_thread_id)
    except SessionSpineUpstreamError:
        if session_service is not None and fallback_project_id is not None:
            session_events = fallback_session_events or _list_project_session_events(
                session_service,
                fallback_project_id,
            )
            if (
                _has_session_event_bundle_source(session_events)
            ):
                return _build_session_read_bundle_from_session_events(
                    project_id=fallback_project_id,
                    events=session_events,
                    persisted_record=persisted_record,
                    approval_store=approval_store,
                    session_service=session_service,
                    decision_store=decision_store,
                    receipt_store=receipt_store,
                    orchestration_state_store=orchestration_state_store,
                    dispatch_cooldown_seconds=dispatch_cooldown_seconds,
                )
        raise
    if not task_native_thread_id(task):
        task = dict(task)
        task["native_thread_id"] = native_thread_id
    project_id = str(task.get("project_id") or "")
    if not project_id:
        raise SessionSpineUpstreamError(
            {"code": "CONTROL_LINK_ERROR", "message": "runtime 返回数据格式异常"}
        )
    if session_service is not None:
        session_events = _list_project_session_events(
            session_service,
            project_id,
            include_child_event_only_fallbacks=True,
            native_thread_id=native_thread_id,
        )
        if (
            _has_session_event_bundle_source(session_events)
        ):
            return _build_session_read_bundle_from_session_events(
                project_id=project_id,
                events=session_events,
                task=task,
                approval_store=approval_store,
                session_service=session_service,
                decision_store=decision_store,
                receipt_store=receipt_store,
                orchestration_state_store=orchestration_state_store,
                dispatch_cooldown_seconds=dispatch_cooldown_seconds,
            )
    approvals = _load_approvals_or_raise(client, project_id)
    bundle = _build_session_read_bundle(
        project_id=project_id,
        task=task,
        approvals=approvals,
        session_service=session_service,
        decision_store=decision_store,
        receipt_store=receipt_store,
        orchestration_state_store=orchestration_state_store,
        dispatch_cooldown_seconds=dispatch_cooldown_seconds,
    )
    return SessionReadBundle(
        project_id=bundle.project_id,
        task=bundle.task,
        approvals=bundle.approvals,
        facts=bundle.facts,
        session=bundle.session,
        progress=bundle.progress,
        approval_queue=bundle.approval_queue,
        snapshot=_build_snapshot_read_semantics_for_live_query(),
    )


def build_workspace_activity_bundle(
    client: CodexRuntimeClient,
    project_id: str,
    *,
    recent_minutes: int = 15,
) -> WorkspaceActivityReadBundle:
    activity = _load_workspace_activity_or_raise(
        client,
        project_id,
        recent_minutes=recent_minutes,
    )
    task = _task_with_workspace_activity(
        _task_with_authoritative_project_execution_state(
            _load_task_or_raise(client, project_id)
        ),
        activity,
    )
    approvals = _load_approvals_or_raise(client, project_id)
    facts = build_fact_records(project_id=project_id, task=task, approvals=approvals)
    return WorkspaceActivityReadBundle(
        project_id=project_id,
        task=task,
        approvals=approvals,
        facts=facts,
        session=build_session_projection(
            project_id=project_id,
            task=task,
            approvals=approvals,
            facts=facts,
        ),
        workspace_activity=build_workspace_activity_view(
            project_id=project_id,
            task=task,
            activity=activity,
        ),
    )


def build_approval_inbox_bundle(
    client: CodexRuntimeClient,
    project_id: str | None = None,
    *,
    session_service: SessionService | None = None,
    store: SessionSpineStore | None = None,
    approval_store: CanonicalApprovalStore | None = None,
) -> ApprovalInboxReadBundle:
    if session_service is not None:
        if project_id is not None:
            session_events = _list_project_session_events(session_service, project_id)
            if _has_relevant_approval_projection_events(session_events):
                persisted_record = store.get(project_id) if store is not None else None
                approvals = _build_session_read_bundle_from_session_events(
                    project_id=project_id,
                    events=session_events,
                    persisted_record=persisted_record,
                    approval_store=approval_store,
                    session_service=session_service,
                ).approvals
                return ApprovalInboxReadBundle(
                    project_id=project_id,
                    approvals=approvals,
                    approval_inbox=build_approval_inbox_projections(approvals=approvals),
                )
        else:
            grouped_events = _group_project_session_events(
                session_service,
                relevant_types=SESSION_EVENT_APPROVAL_TYPES,
            )
            if grouped_events:
                event_project_ids = set(grouped_events)
                event_approvals: list[dict[str, Any]] = []
                for grouped_project_id, events in grouped_events.items():
                    persisted_record = store.get(grouped_project_id) if store is not None else None
                    event_approvals.extend(
                        _build_session_read_bundle_from_session_events(
                            project_id=grouped_project_id,
                            events=events,
                            persisted_record=persisted_record,
                            approval_store=approval_store,
                            session_service=session_service,
                        ).approvals
                    )

                canonical_rows = [
                    row
                    for row in _list_actionable_canonical_approval_rows(approval_store)
                    if str(row.get("project_id") or "") not in event_project_ids
                ]
                persisted: list[ApprovalProjection] = []
                if store is not None:
                    persisted = sorted(
                        [
                            approval
                            for record in store.list_records()
                            for approval in record.approval_queue
                            if approval.project_id not in event_project_ids
                        ],
                        key=_approval_sort_key,
                    )
                fallback_rows = _merge_approval_rows(persisted, canonical_rows)
                merged_rows = sorted(
                    [*event_approvals, *fallback_rows],
                    key=lambda row: (
                        str(row.get("requested_at") or row.get("created_at") or "") == "",
                        str(row.get("requested_at") or row.get("created_at") or ""),
                        str(row.get("approval_id") or ""),
                    ),
                )
                return ApprovalInboxReadBundle(
                    project_id=None,
                    approvals=merged_rows,
                    approval_inbox=build_approval_inbox_projections(approvals=merged_rows),
                )
    canonical_rows = _list_actionable_canonical_approval_rows(
        approval_store,
        project_id=project_id,
    )
    if store is not None:
        persisted_records = [
            record
            for record in store.list_records()
            if project_id is None or record.project_id == project_id
        ]
        persisted = sorted(
            _filter_persisted_approval_projections(
                [
                    approval
                    for record in persisted_records
                    for approval in record.approval_queue
                ],
                approval_store=approval_store,
                project_id=project_id,
            ),
            key=_approval_sort_key,
        )
        if project_id is not None:
            persisted_record = next(
                (record for record in persisted_records if record.project_id == project_id),
                None,
            )
            session_events = (
                _list_project_session_events(session_service, project_id)
                if session_service is not None
                else []
            )
            if (
                persisted_record is not None
                and persisted
                and _persisted_record_has_orphaned_approval_state(
                    persisted_record,
                    canonical_approvals=canonical_rows,
                    session_events=session_events,
                )
            ):
                try:
                    approvals = _load_approvals_or_raise(client, project_id)
                except SessionSpineUpstreamError:
                    approvals = None
                else:
                    return ApprovalInboxReadBundle(
                        project_id=project_id,
                        approvals=approvals,
                        approval_inbox=build_approval_inbox_projections(approvals=approvals),
                    )
        if persisted or canonical_rows:
            merged = list(persisted)
            existing_ids = {approval.approval_id for approval in merged}
            merged.extend(
                projection
                for projection in build_approval_inbox_projections(approvals=canonical_rows)
                if projection.approval_id not in existing_ids
            )
            merged.sort(key=_approval_sort_key)
            return ApprovalInboxReadBundle(
                project_id=project_id,
                approvals=[approval.model_dump(mode="json") for approval in merged],
                approval_inbox=merged,
            )
    approvals = _load_approvals_or_raise(client, project_id)
    return ApprovalInboxReadBundle(
        project_id=project_id,
        approvals=approvals,
        approval_inbox=build_approval_inbox_projections(approvals=approvals),
    )


def build_session_directory_bundle(
    client: CodexRuntimeClient,
    *,
    session_service: SessionService | None = None,
    store: SessionSpineStore | None = None,
    approval_store: CanonicalApprovalStore | None = None,
    decision_store: PolicyDecisionStore | None = None,
    receipt_store: ActionReceiptStore | None = None,
    orchestration_state_store: ResidentOrchestrationStateStore | None = None,
    dispatch_cooldown_seconds: float = 0.0,
    resident_expert_runtime_service: ResidentExpertRuntimeService | None = None,
    liveness_now: datetime | None = None,
) -> SessionDirectoryReadBundle:
    directory_liveness_now = liveness_now or datetime.now(timezone.utc)
    persisted_records = store.list_records() if store is not None else []
    persisted_by_project = {record.project_id: record for record in persisted_records}
    resident_expert_coverage = _build_resident_expert_coverage_view(
        resident_expert_runtime_service
    )
    merged_grouped_events: dict[str, list[SessionEventRecord]] = {}
    fallback_only_grouped_events: dict[str, list[SessionEventRecord]] = {}
    if session_service is not None:
        grouped_events = _group_project_session_events(
            session_service,
            relevant_types=SESSION_EVENT_PROJECTION_TYPES,
        )
        fallback_grouped_events = _group_project_session_events(
            session_service,
            relevant_types=SESSION_EVENT_EVENT_ONLY_FALLBACK_TYPES,
            include_child_event_only_fallbacks=True,
        )
        merged_grouped_events = dict(grouped_events)
        for project_id, events in fallback_grouped_events.items():
            if project_id in persisted_by_project:
                continue
            merged_grouped_events.setdefault(project_id, events)
        fallback_only_grouped_events = (
            fallback_grouped_events
            if fallback_grouped_events and not grouped_events and not persisted_by_project
            else {}
        )
    try:
        tasks = _load_tasks_or_raise(client)
    except SessionSpineUpstreamError:
        if merged_grouped_events and session_service is not None:
            sessions: list[SessionProjection] = []
            progresses: list[TaskProgressView] = []
            ordered_project_ids = list(
                dict.fromkeys([*merged_grouped_events.keys(), *persisted_by_project.keys()])
            )
            for current_project_id in ordered_project_ids:
                if current_project_id in merged_grouped_events:
                    bundle = _build_session_read_bundle_from_session_events(
                        project_id=current_project_id,
                        events=merged_grouped_events[current_project_id],
                        persisted_record=persisted_by_project.get(current_project_id),
                        session_service=session_service,
                        decision_store=decision_store,
                        receipt_store=receipt_store,
                        orchestration_state_store=orchestration_state_store,
                        dispatch_cooldown_seconds=dispatch_cooldown_seconds,
                        liveness_now=directory_liveness_now,
                    )
                    _append_active_directory_bundle(
                        sessions=sessions,
                        progresses=progresses,
                        bundle=bundle,
                    )
                    continue
                record = persisted_by_project.get(current_project_id)
                if record is None:
                    continue
                bundle = _build_session_read_bundle_from_persisted_record(
                    record,
                    approval_store=approval_store,
                    freshness_window_seconds=DEFAULT_SESSION_SPINE_FRESHNESS_WINDOW_SECONDS,
                    session_service=session_service,
                    decision_store=decision_store,
                    receipt_store=receipt_store,
                    orchestration_state_store=orchestration_state_store,
                    dispatch_cooldown_seconds=dispatch_cooldown_seconds,
                    liveness_now=directory_liveness_now,
                )
                _append_active_directory_bundle(
                    sessions=sessions,
                    progresses=progresses,
                    bundle=bundle,
                )
            return SessionDirectoryReadBundle(
                tasks=[],
                approvals=[],
                sessions=sessions,
                progresses=progresses,
                resident_expert_coverage=resident_expert_coverage,
            )
        if fallback_only_grouped_events and session_service is not None:
            bundles = [
                _build_session_read_bundle_from_session_events(
                    project_id=project_id,
                    events=events,
                    session_service=session_service,
                    decision_store=decision_store,
                    receipt_store=receipt_store,
                    orchestration_state_store=orchestration_state_store,
                    dispatch_cooldown_seconds=dispatch_cooldown_seconds,
                    liveness_now=directory_liveness_now,
                )
                for project_id, events in fallback_only_grouped_events.items()
            ]
            bundles = [bundle for bundle in bundles if _directory_bundle_is_active(bundle)]
            return SessionDirectoryReadBundle(
                tasks=[],
                approvals=[],
                sessions=[bundle.session for bundle in bundles],
                progresses=[bundle.progress for bundle in bundles],
                resident_expert_coverage=resident_expert_coverage,
            )
        if persisted_records:
            bundles = [
                _build_session_read_bundle_from_persisted_record(
                    record,
                    approval_store=approval_store,
                    freshness_window_seconds=DEFAULT_SESSION_SPINE_FRESHNESS_WINDOW_SECONDS,
                    session_service=session_service,
                    decision_store=decision_store,
                    receipt_store=receipt_store,
                    orchestration_state_store=orchestration_state_store,
                    dispatch_cooldown_seconds=dispatch_cooldown_seconds,
                    liveness_now=directory_liveness_now,
                )
                for record in persisted_records
            ]
            bundles = [bundle for bundle in bundles if _directory_bundle_is_active(bundle)]
            return SessionDirectoryReadBundle(
                tasks=[],
                approvals=[],
                sessions=[bundle.session for bundle in bundles],
                progresses=[bundle.progress for bundle in bundles],
                resident_expert_coverage=resident_expert_coverage,
            )
        raise
    try:
        approvals = _load_approvals_or_raise(client)
    except SessionSpineUpstreamError:
        approvals = _list_actionable_canonical_approval_rows(approval_store)
    tasks_by_project: dict[str, dict[str, Any]] = {}
    for task in tasks:
        project_id = str(task.get("project_id") or "")
        if not project_id:
            continue
        if project_id in tasks_by_project:
            tasks_by_project.pop(project_id)
        tasks_by_project[project_id] = dict(task)

    sessions: list[SessionProjection] = []
    progresses: list[TaskProgressView] = []
    active_tasks: list[dict[str, Any]] = []
    for project_id, task in tasks_by_project.items():
        task = _directory_task_with_active_state(task) or task
        project_approvals = [
            row for row in approvals if str(row.get("project_id") or "") == project_id
        ]
        bundle = _build_session_read_bundle(
            project_id=project_id,
            task=task,
            approvals=project_approvals,
            session_service=session_service,
            decision_store=decision_store,
            receipt_store=receipt_store,
            orchestration_state_store=orchestration_state_store,
            dispatch_cooldown_seconds=dispatch_cooldown_seconds,
            liveness_now=_directory_task_liveness_reference_time(
                task,
                now=directory_liveness_now,
            ),
        )
        _append_active_directory_bundle(
            sessions=sessions,
            progresses=progresses,
            bundle=bundle,
        )
        if _directory_bundle_is_active(bundle):
            active_tasks.append(task)
    covered_project_ids = set(tasks_by_project)
    supplemental_project_ids = [
        project_id
        for project_id in dict.fromkeys([*merged_grouped_events.keys(), *persisted_by_project.keys()])
        if project_id not in covered_project_ids
    ]
    for project_id in supplemental_project_ids:
        if project_id in merged_grouped_events and session_service is not None:
            bundle = _build_session_read_bundle_from_session_events(
                project_id=project_id,
                events=merged_grouped_events[project_id],
                persisted_record=persisted_by_project.get(project_id),
                session_service=session_service,
                decision_store=decision_store,
                receipt_store=receipt_store,
                orchestration_state_store=orchestration_state_store,
                dispatch_cooldown_seconds=dispatch_cooldown_seconds,
                liveness_now=directory_liveness_now,
            )
            _append_active_directory_bundle(
                sessions=sessions,
                progresses=progresses,
                bundle=bundle,
            )
            continue
        record = persisted_by_project.get(project_id)
        if record is None:
            continue
        bundle = _build_session_read_bundle_from_persisted_record(
            record,
            approval_store=approval_store,
            freshness_window_seconds=DEFAULT_SESSION_SPINE_FRESHNESS_WINDOW_SECONDS,
            session_service=session_service,
            decision_store=decision_store,
            receipt_store=receipt_store,
            orchestration_state_store=orchestration_state_store,
            dispatch_cooldown_seconds=dispatch_cooldown_seconds,
            liveness_now=directory_liveness_now,
        )
        _append_active_directory_bundle(
            sessions=sessions,
            progresses=progresses,
            bundle=bundle,
        )

    return SessionDirectoryReadBundle(
        tasks=active_tasks,
        approvals=approvals,
        sessions=sessions,
        progresses=progresses,
        resident_expert_coverage=resident_expert_coverage,
    )
