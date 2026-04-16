from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlparse

import httpx

SOFT_STEER_MESSAGE = (
    "请汇总当前进展：\n"
    "1. 已完成内容\n"
    "2. 当前阻塞点\n"
    "3. 下一步最小动作\n"
    "如果无阻塞，请立即继续执行。"
)
WAITING_FOR_DIRECTION_MESSAGE = (
    "当前缺少继续执行所需的人类指引。\n"
    "请明确目标、范围或下一步决策，再继续执行。"
)
BREAK_LOOP_STEER_MESSAGE = (
    "当前路径重复失败，请停止扩大尝试范围。\n"
    "请改走保守路径，并先说明最小下一步。"
)
HANDOFF_SUMMARY_PROMPT = (
    "请生成 handoff 摘要，包含当前状态、未完成事项、已知风险与建议续跑入口。"
)
SEVERE_TAKEOVER_MESSAGE = (
    "已达到严重阈值，需要人工接管。\n"
    "请立即停止高风险动作并输出当前交接摘要。"
)


@dataclass(frozen=True, slots=True)
class SteerTemplate:
    reason_code: str
    message: str


def steer_template_registry() -> dict[str, SteerTemplate]:
    return {
        "soft": SteerTemplate(reason_code="soft_steer", message=SOFT_STEER_MESSAGE),
        "waiting_for_direction": SteerTemplate(
            reason_code="waiting_for_direction",
            message=WAITING_FOR_DIRECTION_MESSAGE,
        ),
        "break_loop": SteerTemplate(
            reason_code="break_loop",
            message=BREAK_LOOP_STEER_MESSAGE,
        ),
        "handoff_summary": SteerTemplate(
            reason_code="handoff_summary",
            message=HANDOFF_SUMMARY_PROMPT,
        ),
        "severe_takeover": SteerTemplate(
            reason_code="severe_takeover",
            message=SEVERE_TAKEOVER_MESSAGE,
        ),
    }


def _trust_env_for_base_url(base_url: str) -> bool:
    host = urlparse(base_url).hostname
    if not host:
        return True
    if host.lower() == "localhost":
        return False
    try:
        return not ip_address(host).is_loopback
    except ValueError:
        return True


def post_steer(
    base_url: str,
    token: str,
    project_id: str,
    *,
    message: str,
    reason: str,
    stuck_level: int | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/api/v1/tasks/{project_id}/steer"
    headers = {"Authorization": f"Bearer {token}"}
    body: dict[str, Any] = {"message": message, "source": "watchdog", "reason": reason}
    if stuck_level is not None:
        body["stuck_level"] = stuck_level
    with httpx.Client(timeout=timeout, trust_env=_trust_env_for_base_url(base_url)) as client:
        r = client.post(url, json=body, headers=headers)
        r.raise_for_status()
        try:
            return r.json()
        except ValueError as exc:
            raise RuntimeError("invalid_json_from_a_agent") from exc
