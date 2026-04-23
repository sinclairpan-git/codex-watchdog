from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field


def _stable_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _hash_text(value: str) -> str:
    return f"sha256:{sha256(value.encode('utf-8')).hexdigest()}"


def _first_nonempty(*values: object) -> str:
    for value in values:
        normalized = str(value or "").strip()
        if normalized:
            return normalized
    return ""


def _normalize_text_list(values: object) -> list[str]:
    items: list[str] = []
    for value in values or []:
        normalized = str(value or "").strip()
        if normalized:
            items.append(normalized)
    return items


def _resume_phase(task: Mapping[str, Any]) -> str:
    phase = _first_nonempty(task.get("resume_target_phase"), task.get("phase"))
    return phase or "planning"


def _packet_id(*parts: object) -> str:
    material = _stable_json([str(part or "").strip() for part in parts])
    return f"packet:continuation:{sha256(material.encode('utf-8')).hexdigest()[:16]}"


class _PacketModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContinuationPacketRoute(_PacketModel):
    route_kind: str = Field(min_length=1)
    target_project_id: str = Field(min_length=1)
    target_session_id: str = Field(min_length=1)
    target_thread_id: str = Field(min_length=1)
    target_work_item_id: str | None = None


class ContinuationPacketSourceRefs(_PacketModel):
    decision_source: str = Field(min_length=1)
    goal_contract_version: str = Field(min_length=1)
    authoritative_snapshot_version: str | None = None
    snapshot_epoch: str | None = None
    decision_trace_ref: str | None = None
    lineage_refs: list[str] = Field(default_factory=list)


class ContinuationPacketFreshness(_PacketModel):
    generated_at: str = Field(min_length=1)
    expires_at: str = Field(min_length=1)


class ContinuationPacketDedupe(_PacketModel):
    dedupe_key: str = Field(min_length=1)
    supersedes_packet_id: str | None = None


class ContinuationPacket(_PacketModel):
    packet_id: str = Field(min_length=1)
    packet_version: str = Field(default="continuation-packet/v1")
    packet_state: str = Field(default="issued")
    decision_class: str = Field(min_length=1)
    continuation_identity: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    native_thread_id: str = Field(min_length=1)
    route_key: str | None = None
    target_route: ContinuationPacketRoute
    project_total_goal: str = Field(min_length=1)
    branch_goal: str = Field(min_length=1)
    current_progress_summary: str = Field(min_length=1)
    files_touched: list[str] = Field(default_factory=list)
    completed_work: list[str] = Field(default_factory=list)
    remaining_tasks: list[str] = Field(default_factory=list)
    first_action: str = Field(min_length=1)
    execution_mode: str = Field(min_length=1)
    action_ref: str = Field(min_length=1)
    action_args: dict[str, Any] = Field(default_factory=dict)
    expected_next_state: str = Field(min_length=1)
    continue_boundary: str = Field(min_length=1)
    stop_conditions: list[str] = Field(default_factory=list)
    operator_boundary: str = Field(min_length=1)
    approval_boundary: str | None = None
    approval_risk: str | None = None
    last_error_signature: str | None = None
    source_refs: ContinuationPacketSourceRefs
    freshness: ContinuationPacketFreshness
    dedupe: ContinuationPacketDedupe
    render_contract_ref: str = Field(default="continuation-packet-markdown/v1")


def model_validate_continuation_packet(value: ContinuationPacket | Mapping[str, Any]) -> ContinuationPacket:
    if isinstance(value, ContinuationPacket):
        return value
    return ContinuationPacket.model_validate(dict(value))


def continuation_packet_hash(value: ContinuationPacket | Mapping[str, Any]) -> str:
    packet = model_validate_continuation_packet(value)
    payload = packet.model_dump(mode="json", exclude_none=True)
    return _hash_text(_stable_json(payload))


def rendered_markdown_hash(markdown: str) -> str:
    return _hash_text(markdown)


def render_continuation_packet_markdown(
    value: ContinuationPacket | Mapping[str, Any],
) -> str:
    packet = model_validate_continuation_packet(value)
    target_route = packet.target_route
    source_refs = packet.source_refs
    freshness = packet.freshness
    dedupe = packet.dedupe
    resume_target_phase = str(packet.action_args.get("resume_target_phase") or "planning").strip() or "planning"
    current_blocker = (
        "当前存在待审批项，受限动作必须等待人工放行。"
        if any("审批" in item for item in packet.stop_conditions)
        else "当前因为恢复续跑进入 continuation handoff，需要基于现有上下文继续。"
    )
    lines = [
        "# Recovery continuation packet"
        if packet.decision_class == "recover_current_branch"
        else "# Continuation packet",
        "",
        "## Packet metadata",
        f"packet_id={packet.packet_id}",
        f"packet_version={packet.packet_version}",
        f"packet_state={packet.packet_state}",
        f"decision_class={packet.decision_class}",
        f"continuation_identity={packet.continuation_identity}",
        f"route_key={packet.route_key or '(none)'}",
        f"execution_mode={packet.execution_mode}",
        f"action_ref={packet.action_ref}",
        f"expected_next_state={packet.expected_next_state}",
        f"decision_source={source_refs.decision_source}",
        f"goal_contract_version={source_refs.goal_contract_version}",
        f"authoritative_snapshot_version={source_refs.authoritative_snapshot_version or '(none)'}",
        f"snapshot_epoch={source_refs.snapshot_epoch or '(none)'}",
        f"decision_trace_ref={source_refs.decision_trace_ref or '(none)'}",
        f"render_contract_ref={packet.render_contract_ref}",
        f"dedupe_key={dedupe.dedupe_key}",
        f"supersedes_packet_id={dedupe.supersedes_packet_id or '(none)'}",
        f"generated_at={freshness.generated_at}",
        f"expires_at={freshness.expires_at}",
        f"target_route={target_route.route_kind}:{target_route.target_project_id}:{target_route.target_session_id}:{target_route.target_thread_id}:{target_route.target_work_item_id or '(none)'}",
        "",
        "## Continue instruction",
        f"项目总目标：{packet.project_total_goal}",
        f"当前分支目标：{packet.branch_goal}",
        f"当前进度：{packet.current_progress_summary}",
        f"恢复阶段：{resume_target_phase}",
        f"当前摘要：{packet.current_progress_summary}",
    ]
    files_touched = packet.files_touched or ["(无)"]
    lines.extend(["", "## 已修改文件", ", ".join(files_touched)])
    completed_work = packet.completed_work or ["(none)"]
    lines.extend(["", "## 已完成"] + [f"- {item}" for item in completed_work])
    remaining_tasks = packet.remaining_tasks or ["(none)"]
    lines.extend(["", "## 剩余任务"] + [f"- {item}" for item in remaining_tasks])
    lines.extend(
        [
            "",
            "## 当前阻塞点",
            current_blocker,
            "",
            "## 下一步建议",
            "先按 continuation packet 执行第一步动作，再在当前目标边界内继续最小变更路径。",
            "",
            f"第一步动作：{packet.first_action}",
            f"继续边界：{packet.continue_boundary}",
            f"操作边界：{packet.operator_boundary}",
            f"任务约束：goal_contract_version={source_refs.goal_contract_version}",
            f"需要人工介入：{packet.approval_boundary or '当前没有待审批项；可在现有任务边界内继续执行。'}",
            f"approval_risk={packet.approval_risk or '(无)'}",
            f"last_error_signature={packet.last_error_signature or '(无)'}",
            "",
            "## Stop conditions",
        ]
    )
    stop_conditions = packet.stop_conditions or ["(none)"]
    lines.extend(f"- {item}" for item in stop_conditions)
    lines.extend(
        [
            "",
            "## Action arguments",
            "```json",
            json.dumps(packet.action_args, ensure_ascii=False, sort_keys=True, indent=2),
            "```",
            "",
            "## Lineage refs",
        ]
    )
    lineage_refs = source_refs.lineage_refs or ["(none)"]
    lines.extend(f"- {item}" for item in lineage_refs)
    lines.append("")
    return "\n".join(lines)


def render_continuation_packet_prompt(
    value: ContinuationPacket | Mapping[str, Any],
) -> str:
    return render_continuation_packet_markdown(value)


def build_recovery_continuation_packet(
    *,
    project_id: str,
    task: Mapping[str, Any],
    continuation_identity: str,
    route_key: str | None,
    project_total_goal: str,
    branch_goal: str,
    remaining_tasks: list[str],
    goal_contract_version: str,
    decision_source: str,
    authoritative_snapshot_version: str | None,
    snapshot_epoch: str | None,
    target_session_id: str,
    target_thread_id: str,
    target_work_item_id: str | None = None,
    decision_trace_ref: str | None = None,
    lineage_refs: list[str] | None = None,
    generated_at: str | None = None,
    ttl_seconds: int = 3600,
    packet_id: str | None = None,
) -> ContinuationPacket:
    generated_dt = datetime.now(UTC) if generated_at is None else datetime.fromisoformat(
        generated_at.replace("Z", "+00:00")
    )
    generated_at_text = generated_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    expires_at_text = (
        (generated_dt + timedelta(seconds=max(ttl_seconds, 0)))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    native_thread_id = _first_nonempty(task.get("native_thread_id"), task.get("thread_id"), "none")
    current_progress_summary = (
        _first_nonempty(task.get("last_summary"), branch_goal, project_total_goal)
        or "current progress summary unavailable"
    )
    files_touched = _normalize_text_list(task.get("files_touched"))
    if files_touched:
        first_action = (
            "先检查最近已修改文件，确认未完成的改动与验证缺口，然后继续当前目标： "
            + ", ".join(files_touched)
            + "。"
        )
        completed_work = [f"最近已修改文件：{', '.join(files_touched)}"]
    else:
        first_action = (
            "先读取 recovery packet，并只继续当前分支内的 recovery/handoff 改造。"
        )
        completed_work = [current_progress_summary]
    pending_approval = bool(task.get("pending_approval"))
    approval_boundary = (
        "当前存在待审批项；先处理审批或等待人工明确放行，再继续任何受限动作。"
        if pending_approval
        else "当前没有待审批项；可在现有任务边界内继续执行。"
    )
    approval_risk = _first_nonempty(task.get("approval_risk"), "(无)")
    last_error_signature = _first_nonempty(task.get("last_error_signature"), "(无)")
    stop_conditions = [
        "需要新的人工批准",
        "当前分支目标已完成并应切换下一 work item",
    ]
    if pending_approval:
        stop_conditions.insert(0, "当前存在待审批项，先等待人工放行")
    resolved_packet_id = packet_id or _packet_id(
        project_id,
        continuation_identity,
        route_key or "",
        authoritative_snapshot_version or "",
        goal_contract_version,
        current_progress_summary,
    )
    dedupe_key = _stable_json(
        {
            "continuation_identity": continuation_identity,
            "route_key": route_key,
            "packet_id": resolved_packet_id,
        }
    )
    return ContinuationPacket(
        packet_id=resolved_packet_id,
        decision_class="recover_current_branch",
        continuation_identity=continuation_identity,
        project_id=project_id,
        session_id=target_session_id,
        native_thread_id=native_thread_id,
        route_key=route_key,
        target_route=ContinuationPacketRoute(
            route_kind="same_thread",
            target_project_id=project_id,
            target_session_id=target_session_id,
            target_thread_id=target_thread_id,
            target_work_item_id=target_work_item_id,
        ),
        project_total_goal=project_total_goal,
        branch_goal=branch_goal,
        current_progress_summary=current_progress_summary,
        files_touched=files_touched,
        completed_work=completed_work,
        remaining_tasks=_normalize_text_list(remaining_tasks),
        first_action=first_action,
        execution_mode="resume_or_new_thread",
        action_ref="continue_current_branch",
        action_args={"resume_target_phase": _resume_phase(task)},
        expected_next_state="running",
        continue_boundary="只继续当前分支，不切到别的 work item。",
        stop_conditions=stop_conditions,
        operator_boundary="不要把渲染后的 markdown 重新当作 authoritative truth。",
        approval_boundary=approval_boundary,
        approval_risk=approval_risk,
        last_error_signature=last_error_signature,
        source_refs=ContinuationPacketSourceRefs(
            decision_source=decision_source,
            goal_contract_version=goal_contract_version,
            authoritative_snapshot_version=authoritative_snapshot_version,
            snapshot_epoch=snapshot_epoch,
            decision_trace_ref=decision_trace_ref,
            lineage_refs=_normalize_text_list(lineage_refs),
        ),
        freshness=ContinuationPacketFreshness(
            generated_at=generated_at_text,
            expires_at=expires_at_text,
        ),
        dedupe=ContinuationPacketDedupe(dedupe_key=dedupe_key),
    )


def build_legacy_recovery_continuation_packet(
    *,
    project_id: str,
    reason: str,
    task: Mapping[str, Any],
    source_packet_id: str,
    goal_contract_version: str | None,
) -> ContinuationPacket:
    goal = _first_nonempty(
        task.get("current_phase_goal"),
        task.get("last_user_instruction"),
        task.get("task_title"),
        task.get("task_prompt"),
        task.get("last_summary"),
        f"{project_id} current task",
    )
    branch_goal = _first_nonempty(task.get("current_phase_goal"), goal) or goal
    project_total_goal = _first_nonempty(task.get("task_prompt"), goal, project_id) or project_id
    continuation_identity = (
        f"{project_id}:session:{project_id}:{_first_nonempty(task.get('thread_id'), 'none')}:"
        "recover_current_branch"
    )
    route_key = None
    if task.get("goal_contract_version") or goal_contract_version:
        route_key = f"{continuation_identity}:{_first_nonempty(task.get('goal_contract_version'), goal_contract_version)}"
    return build_recovery_continuation_packet(
        project_id=project_id,
        task=task,
        continuation_identity=continuation_identity,
        route_key=route_key,
        project_total_goal=project_total_goal,
        branch_goal=branch_goal,
        remaining_tasks=[],
        goal_contract_version=_first_nonempty(goal_contract_version, "goal-contract:unknown")
        or "goal-contract:unknown",
        decision_source="recovery_guard",
        authoritative_snapshot_version=None,
        snapshot_epoch=None,
        target_session_id=f"session:{project_id}",
        target_thread_id=_first_nonempty(task.get("thread_id"), "none") or "none",
        packet_id=source_packet_id,
    )
