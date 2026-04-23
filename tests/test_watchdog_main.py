import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from watchdog.main import _run_resident_orchestrator_once


@pytest.mark.asyncio
async def test_run_resident_orchestrator_once_skips_delivery_drain_when_orchestrator_step_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    now = datetime(2026, 4, 17, 10, 0, 0, tzinfo=UTC)

    def _orchestrate_all(*, now: datetime, continue_on_error: bool = False):
        _ = now, continue_on_error
        raise RuntimeError("synthetic orchestrator failure")

    app = SimpleNamespace(
        state=SimpleNamespace(
            resident_orchestrator_run_lock=asyncio.Lock(),
            resident_orchestrator=SimpleNamespace(orchestrate_all=_orchestrate_all),
        )
    )

    caplog.set_level("ERROR", logger="watchdog.main")
    with patch("watchdog.main._drain_delivery_outbox", new=Mock()) as drain_mock:
        await _run_resident_orchestrator_once(app, now=now)

    drain_mock.assert_not_called()
    assert "watchdog background step failed: resident_orchestrator.orchestrate_all" in caplog.text


@pytest.mark.asyncio
async def test_run_resident_orchestrator_once_drains_delivery_after_successful_orchestration() -> None:
    now = datetime(2026, 4, 17, 10, 5, 0, tzinfo=UTC)
    calls: dict[str, object] = {}

    def _orchestrate_all(*, now: datetime, continue_on_error: bool = False):
        calls["now"] = now
        calls["continue_on_error"] = continue_on_error
        return []

    app = SimpleNamespace(
        state=SimpleNamespace(
            resident_orchestrator_run_lock=asyncio.Lock(),
            resident_orchestrator=SimpleNamespace(orchestrate_all=_orchestrate_all),
        )
    )

    with patch("watchdog.main._drain_delivery_outbox", new=Mock()) as drain_mock:
        await _run_resident_orchestrator_once(app, now=now)

    assert calls == {
        "now": now,
        "continue_on_error": True,
    }
    drain_mock.assert_called_once_with(app, now=now)
