#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from watchdog.main import create_app  # noqa: E402
from watchdog.services.feishu_long_connection import (  # noqa: E402
    FeishuLongConnectionConfigError,
    FeishuLongConnectionGateway,
    FeishuLongConnectionRuntime,
)
from watchdog.settings import Settings  # noqa: E402


def main() -> int:
    settings = Settings()
    app = create_app(settings=settings)
    runtime = FeishuLongConnectionRuntime(
        settings=settings,
        gateway=FeishuLongConnectionGateway.from_app(app),
    )
    try:
        runtime.run_forever()
    except FeishuLongConnectionConfigError as exc:
        print(f"watchdog feishu long-connection config error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
