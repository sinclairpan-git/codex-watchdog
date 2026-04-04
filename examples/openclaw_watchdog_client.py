#!/usr/bin/env python3
"""
OpenClaw 侧调用 Watchdog 的最小示例（仅 HTTP，无飞书依赖）。

部署时设置环境变量：
  WATCHDOG_BASE_URL  例如 https://watchdog.internal:8720
  WATCHDOG_API_TOKEN  与 Watchdog 配置的 token 一致
"""

from __future__ import annotations

import os
import sys

import httpx


def fetch_progress(project_id: str) -> dict:
    base = os.environ.get("WATCHDOG_BASE_URL", "http://127.0.0.1:8720").rstrip("/")
    token = os.environ.get("WATCHDOG_API_TOKEN", "")
    url = f"{base}/api/v1/watchdog/tasks/{project_id}/progress"
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=30.0) as client:
        r = client.get(url, headers=headers)
        r.raise_for_status()
        return r.json()


def main() -> None:
    pid = sys.argv[1] if len(sys.argv) > 1 else "demo-project"
    body = fetch_progress(pid)
    print(body)


if __name__ == "__main__":
    main()
