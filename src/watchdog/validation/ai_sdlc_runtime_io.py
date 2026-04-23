from __future__ import annotations

import os
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any, Mapping

import yaml


def write_yaml_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    serialized = yaml.safe_dump(dict(payload), sort_keys=False, allow_unicode=True)
    if not serialized.endswith("\n"):
        serialized = f"{serialized}\n"

    tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())

        tmp_path.replace(path)
        _fsync_directory(path.parent)
    finally:
        with suppress(FileNotFoundError):
            tmp_path.unlink()


def _fsync_directory(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
