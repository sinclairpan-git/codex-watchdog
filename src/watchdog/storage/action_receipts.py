from __future__ import annotations

import json
import threading
from copy import deepcopy
from pathlib import Path
from typing import Callable

from watchdog.contracts.session_spine.models import WatchdogAction, WatchdogActionResult


def receipt_key(
    *,
    action_code: str,
    project_id: str,
    idempotency_key: str,
    approval_id: str | None = None,
) -> str:
    return "|".join(
        [
            str(action_code),
            project_id,
            approval_id or "",
            idempotency_key,
        ]
    )


def receipt_key_for_action(action: WatchdogAction, approval_id: str | None = None) -> str:
    return receipt_key(
        action_code=str(action.action_code),
        project_id=action.project_id,
        approval_id=approval_id or str(action.arguments.get("approval_id") or "") or None,
        idempotency_key=action.idempotency_key,
    )


class ActionReceiptStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._cache: dict[str, dict[str, object]] | None = None
        self._cache_signature: tuple[int, int] | None = None
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._write({})

    def _file_signature(self) -> tuple[int, int]:
        stat = self._path.stat()
        return (stat.st_mtime_ns, stat.st_size)

    def _read(self) -> dict[str, dict[str, object]]:
        signature = self._file_signature()
        if self._cache is not None and self._cache_signature == signature:
            return deepcopy(self._cache)
        raw = self._path.read_text(encoding="utf-8")
        data = json.loads(raw) if raw.strip() else {}
        normalized = data if isinstance(data, dict) else {}
        self._cache = deepcopy(normalized)
        self._cache_signature = signature
        return deepcopy(normalized)

    def _write(self, data: dict[str, dict[str, object]]) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)
        self._cache = deepcopy(data)
        self._cache_signature = self._file_signature()

    def get(self, key: str) -> WatchdogActionResult | None:
        with self._lock:
            row = self._read().get(key)
        if not isinstance(row, dict):
            return None
        return WatchdogActionResult.model_validate(row)

    def snapshot_rows(self) -> list[tuple[str, dict[str, object]]]:
        with self._lock:
            return list(self._read().items())

    def create_or_get(
        self,
        key: str,
        factory: Callable[[], WatchdogActionResult],
    ) -> WatchdogActionResult:
        # Serialize the idempotency check and persisted write so concurrent
        # callers cannot duplicate external action side effects.
        with self._lock:
            data = self._read()
            row = data.get(key)
            if isinstance(row, dict):
                return WatchdogActionResult.model_validate(row)
            result = factory()
            data[key] = result.model_dump(mode="json")
            self._write(data)
        return result

    def put(self, key: str, result: WatchdogActionResult) -> WatchdogActionResult:
        with self._lock:
            data = self._read()
            data[key] = result.model_dump(mode="json")
            self._write(data)
        return result

    def list_items(self) -> list[tuple[str, WatchdogActionResult]]:
        with self._lock:
            data = self._read()
        return [
            (key, WatchdogActionResult.model_validate(row))
            for key, row in data.items()
            if isinstance(row, dict)
        ]
