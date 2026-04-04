from __future__ import annotations

from typing import Any

import httpx

SOFT_STEER_MESSAGE = (
    "请汇总当前进展：\n"
    "1. 已完成内容\n"
    "2. 当前阻塞点\n"
    "3. 下一步最小动作\n"
    "如果无阻塞，请立即继续执行。"
)


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
    with httpx.Client(timeout=timeout) as client:
        r = client.post(url, json=body, headers=headers)
        r.raise_for_status()
        try:
            return r.json()
        except ValueError as exc:
            raise RuntimeError("invalid_json_from_a_agent") from exc
