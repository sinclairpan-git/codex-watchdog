#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from watchdog.validation.external_integration_smoke import (  # noqa: E402
    ExternalIntegrationSmokeConfig,
    exit_code_for_results,
    render_results,
    run_smoke_checks,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run watchdog external integration smoke checks."
    )
    parser.add_argument(
        "--target",
        action="append",
        choices=("all", "health", "feishu", "provider", "memory"),
        default=None,
        help="Select a specific smoke target. May be passed multiple times.",
    )
    args = parser.parse_args(argv)

    config = ExternalIntegrationSmokeConfig(
        base_url=os.getenv("WATCHDOG_BASE_URL", "").strip(),
        api_token=os.getenv("WATCHDOG_API_TOKEN", "").strip(),
        data_dir=os.getenv("WATCHDOG_DATA_DIR", ".data/watchdog").strip(),
        http_timeout_s=float(os.getenv("WATCHDOG_HTTP_TIMEOUT_S", "3.0")),
        feishu_verification_token=_optional_env("WATCHDOG_FEISHU_VERIFICATION_TOKEN"),
        brain_provider_name=os.getenv(
            "WATCHDOG_BRAIN_PROVIDER_NAME",
            "resident_orchestrator",
        ).strip(),
        brain_provider_base_url=_optional_env("WATCHDOG_BRAIN_PROVIDER_BASE_URL"),
        brain_provider_api_key=_optional_env("WATCHDOG_BRAIN_PROVIDER_API_KEY"),
        brain_provider_model=_optional_env("WATCHDOG_BRAIN_PROVIDER_MODEL"),
        memory_preview_ai_autosdlc_cursor_enabled=_parse_bool_env(
            "WATCHDOG_MEMORY_PREVIEW_AI_AUTOSDLC_CURSOR_ENABLED"
        ),
    )
    results = run_smoke_checks(config=config, targets=tuple(args.target or ("all",)))
    print(render_results(results))
    return exit_code_for_results(results)


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _parse_bool_env(name: str) -> bool:
    value = os.getenv(name)
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
