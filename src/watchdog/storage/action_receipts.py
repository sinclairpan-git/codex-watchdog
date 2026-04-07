from __future__ import annotations

import json
import threading
from pathlib import Path

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
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._write({})

    def _read(self) -> dict[str, dict[str, object]]:
        raw = self._path.read_text(encoding="utf-8")
        data = json.loads(raw) if raw.strip() else {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict[str, dict[str, object]]) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    def get(self, key: str) -> WatchdogActionResult | None:
        with self._lock:
            row = self._read().get(key)
        if not isinstance(row, dict):
            return None
        return WatchdogActionResult.model_validate(row)

    def put(self, key: str, result: WatchdogActionResult) -> WatchdogActionResult:
        with self._lock:
            data = self._read()
            data[key] = result.model_dump(mode="json")
            self._write(data)
        return result
