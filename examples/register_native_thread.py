#!/usr/bin/env python3
"""向 A-Control-Agent 注册或更新一个原生 Codex thread。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import httpx


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("A_AGENT_BASE_URL", "http://127.0.0.1:8710"),
        help="A-Control-Agent base URL",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("A_AGENT_API_TOKEN", ""),
        help="A-Control-Agent bearer token",
    )
    parser.add_argument(
        "--payload",
        type=Path,
        help="Path to a JSON payload file; if omitted, build one from flags.",
    )
    parser.add_argument("--thread-id")
    parser.add_argument("--project-id")
    parser.add_argument("--cwd")
    parser.add_argument("--task-title", default="")
    parser.add_argument("--status", default="running")
    parser.add_argument("--phase", default="planning")
    parser.add_argument("--last-summary", default="")
    return parser


def load_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.payload:
        return json.loads(args.payload.read_text(encoding="utf-8"))
    payload = {
        "thread_id": args.thread_id,
        "project_id": args.project_id,
        "cwd": args.cwd,
        "task_title": args.task_title,
        "status": args.status,
        "phase": args.phase,
        "last_summary": args.last_summary,
    }
    return {key: value for key, value in payload.items() if value not in (None, "")}


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    payload = load_payload(args)
    if not payload.get("thread_id"):
        parser.error("thread_id is required unless provided in --payload")
    if not (payload.get("project_id") or payload.get("cwd")):
        parser.error("project_id or cwd is required unless provided in --payload")
    if not args.token:
        parser.error("token is required via --token or A_AGENT_API_TOKEN")

    url = f"{args.base_url.rstrip('/')}/api/v1/tasks/native-threads"
    headers = {"Authorization": f"Bearer {args.token}"}
    with httpx.Client(timeout=10.0) as client:
        response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
