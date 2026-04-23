from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

REPORT_ID_SEED_FIELDS = (
    "artifact_ref",
    "sample_window",
    "shadow_window",
    "input_hash",
    "generated_by",
    "report_approved_by",
)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def canonicalize_release_gate_report_material(payload: Mapping[str, object]) -> dict[str, object]:
    material = dict(payload)
    material.pop("report_hash", None)
    return material


def build_release_gate_report_id(payload: Mapping[str, object]) -> str:
    seed = {field: payload[field] for field in REPORT_ID_SEED_FIELDS}
    serialized = json.dumps(seed, sort_keys=True)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return f"report:{digest[:16]}"


def stable_release_gate_report_hash(payload: Mapping[str, object]) -> str:
    material = canonicalize_release_gate_report_material(payload)
    return f"sha256:{hashlib.sha256(_canonical_json(material).encode('utf-8')).hexdigest()}"
