from __future__ import annotations

import hashlib
import re


def fingerprint_input_text(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
