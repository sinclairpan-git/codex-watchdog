#!/usr/bin/env python3
"""导出 Codex runtime service 与 codex-watchdog 的 OpenAPI JSON（PRD §22 API 文档最低交付）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> None:
    from a_control_agent.main import create_app as create_a
    from watchdog.main import create_app as create_wd

    out = ROOT / "docs" / "openapi"
    out.mkdir(parents=True, exist_ok=True)
    (out / "a-control-agent.json").write_text(
        json.dumps(create_a().openapi(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out / "watchdog.json").write_text(
        json.dumps(create_wd().openapi(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {out / 'a-control-agent.json'}")
    print(f"Wrote {out / 'watchdog.json'}")


if __name__ == "__main__":
    main()
