"""Structured handoff packet rendering and file writing."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from watchdog.services.session_spine.continuation_packet import (
    ContinuationPacket,
    build_legacy_recovery_continuation_packet,
    model_validate_continuation_packet,
    render_continuation_packet_markdown,
)


def build_source_packet_id(
    *,
    handoff_path: Path,
    project_id: str,
    reason: str,
    task: dict[str, Any],
) -> str:
    material = json.dumps(
        {
            "project_id": project_id,
            "reason": reason,
            "handoff_path": str(handoff_path.resolve()),
            "task": task,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return f"packet:handoff:{sha256(material.encode('utf-8')).hexdigest()[:16]}"


def _resolve_continuation_packet(
    *,
    project_id: str,
    reason: str,
    task: dict[str, Any],
    source_packet_id: str,
    continuation_packet: Mapping[str, Any] | ContinuationPacket | None,
) -> ContinuationPacket:
    if continuation_packet is not None:
        return model_validate_continuation_packet(continuation_packet)
    goal_contract_version = str(task.get("goal_contract_version") or "").strip() or None
    return build_legacy_recovery_continuation_packet(
        project_id=project_id,
        reason=reason,
        task=task,
        source_packet_id=source_packet_id,
        goal_contract_version=goal_contract_version,
    )


def build_handoff_markdown(
    *,
    project_id: str,
    reason: str,
    task: dict[str, Any],
    source_packet_id: str,
    continuation_packet: Mapping[str, Any] | ContinuationPacket | None = None,
) -> tuple[str, dict[str, Any]]:
    _ = (project_id, reason, task)
    packet = _resolve_continuation_packet(
        project_id=project_id,
        reason=reason,
        task=task,
        source_packet_id=source_packet_id,
        continuation_packet=continuation_packet,
    )
    body = render_continuation_packet_markdown(packet)
    return body, packet.model_dump(mode="json", exclude_none=True)


def write_handoff_file(
    handoffs_dir: Path,
    project_id: str,
    reason: str,
    task: dict[str, Any],
    *,
    continuation_packet: Mapping[str, Any] | ContinuationPacket | None = None,
) -> tuple[str, str, str, dict[str, Any]]:
    handoffs_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"handoff_{project_id}_{ts}.md"
    path = handoffs_dir / name
    source_packet_id = build_source_packet_id(
        handoff_path=path,
        project_id=project_id,
        reason=reason,
        task=task,
    )
    body, packet = build_handoff_markdown(
        project_id=project_id,
        reason=reason,
        task=task,
        source_packet_id=source_packet_id,
        continuation_packet=continuation_packet,
    )
    resolved_source_packet_id = str(packet.get("packet_id") or source_packet_id).strip() or source_packet_id
    path.write_text(body, encoding="utf-8")
    return str(path.resolve()), body, resolved_source_packet_id, packet
