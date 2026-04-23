from __future__ import annotations

from typing import Mapping

from pydantic import BaseModel, ConfigDict, ValidationError

from watchdog.services.brain.validator import DecisionValidationVerdict


class _ValidatorReadContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ValidatorDecisionReadSnapshot(_ValidatorReadContractModel):
    verdict: DecisionValidationVerdict | None = None
    has_verdict_payload: bool = False


def _read_optional_verdict(payload: object) -> DecisionValidationVerdict | None:
    if not isinstance(payload, dict):
        return None
    try:
        return DecisionValidationVerdict.model_validate(payload)
    except ValidationError:
        return None


def _looks_like_legacy_validator_payload(payload: Mapping[str, object]) -> bool:
    return "status" in payload or "reason" in payload


def read_validator_decision_evidence(
    evidence: Mapping[str, object] | None,
) -> ValidatorDecisionReadSnapshot:
    source = evidence if isinstance(evidence, Mapping) else {}
    verdict = _read_optional_verdict(source.get("validator_verdict"))
    has_verdict_payload = "validator_verdict" in source
    if not has_verdict_payload:
        has_verdict_payload = _looks_like_legacy_validator_payload(source)
        legacy_verdict = _read_optional_verdict(source)
        if legacy_verdict is not None:
            verdict = legacy_verdict
    return ValidatorDecisionReadSnapshot(
        verdict=verdict,
        has_verdict_payload=has_verdict_payload,
    )
