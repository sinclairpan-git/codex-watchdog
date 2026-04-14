from __future__ import annotations

from typing import Mapping, TypeVar

from pydantic import BaseModel, ConfigDict, ValidationError

from watchdog.services.brain.release_gate import ReleaseGateVerdict
from watchdog.services.brain.release_gate_evidence import ReleaseGateEvidenceBundle


class _ReleaseGateReadContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReleaseGateDecisionReadSnapshot(_ReleaseGateReadContractModel):
    verdict: ReleaseGateVerdict | None = None
    evidence_bundle: ReleaseGateEvidenceBundle | None = None
    has_verdict_payload: bool = False
    has_evidence_bundle_payload: bool = False


_T = TypeVar("_T", bound=BaseModel)


def _read_optional_model(payload: object, model_type: type[_T]) -> _T | None:
    if not isinstance(payload, dict):
        return None
    try:
        return model_type.model_validate(payload)
    except ValidationError:
        return None


def read_release_gate_decision_evidence(
    evidence: Mapping[str, object] | None,
) -> ReleaseGateDecisionReadSnapshot:
    source = evidence if isinstance(evidence, Mapping) else {}
    return ReleaseGateDecisionReadSnapshot(
        verdict=_read_optional_model(
            source.get("release_gate_verdict"),
            ReleaseGateVerdict,
        ),
        evidence_bundle=_read_optional_model(
            source.get("release_gate_evidence_bundle"),
            ReleaseGateEvidenceBundle,
        ),
        has_verdict_payload="release_gate_verdict" in source,
        has_evidence_bundle_payload="release_gate_evidence_bundle" in source,
    )
