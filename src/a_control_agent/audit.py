from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

_locks: dict[Path, threading.Lock] = {}


def _lock_for(path: Path) -> threading.Lock:
    with threading.Lock():
        if path not in _locks:
            _locks[path] = threading.Lock()
    return _locks[path]


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    lk = _lock_for(path)
    with lk:
        path.open("a", encoding="utf-8").write(line)
