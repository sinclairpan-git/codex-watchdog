from __future__ import annotations

from typing import Mapping

from watchdog.services.brain.release_gate_read_contract import (
    read_release_gate_decision_evidence,
)
from watchdog.services.brain.validator_read_contract import (
    read_validator_decision_evidence,
)


def build_session_event_gate_payload(
    *,
    evidence: Mapping[str, object] | None,
    include_validator: bool,
    include_bundle: bool,
) -> dict[str, object]:
    payload: dict[str, object] = {}
    # Typed read contracts drop malformed gate payloads to avoid propagating raw dicts.
    validator = read_validator_decision_evidence(evidence)
    if include_validator and validator.verdict is not None:
        payload["validator_verdict"] = validator.verdict.model_dump(mode="json")
    release_gate = read_release_gate_decision_evidence(evidence)
    if release_gate.verdict is not None:
        payload["release_gate_verdict"] = release_gate.verdict.model_dump(mode="json")
    if include_bundle and release_gate.evidence_bundle is not None:
        payload["release_gate_evidence_bundle"] = release_gate.evidence_bundle.model_dump(
            mode="json",
            exclude_none=True,
        )
    return payload
