from __future__ import annotations

import asyncio
import time
from collections.abc import Callable


def wait_until(
    predicate: Callable[[], bool],
    *,
    timeout_s: float = 0.5,
    interval_s: float = 0.01,
) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval_s)
    return predicate()


async def wait_until_async(
    predicate: Callable[[], bool],
    *,
    timeout_s: float = 0.5,
    interval_s: float = 0.01,
) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval_s)
    return predicate()
