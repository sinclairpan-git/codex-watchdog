from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from watchdog.services.brain.release_gate import ReleaseGateVerdict
from watchdog.services.brain.release_gate_evidence import (
    CertificationPacketCorpus,
    ReleaseGateEvidenceBundle,
    ShadowDecisionLedger,
)
from watchdog.services.brain.release_gate_loading import LoadedReleaseGateArtifacts


class _ReleaseGateWriteContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReleaseGateRuntimeEvidenceWriteBundle(_ReleaseGateWriteContractModel):
    verdict: ReleaseGateVerdict
    evidence_bundle: ReleaseGateEvidenceBundle | None = None


def build_release_gate_runtime_evidence(
    *,
    verdict: ReleaseGateVerdict,
    loaded_artifacts: LoadedReleaseGateArtifacts | None,
    report_path: str | None,
    certification_packet_corpus_ref: str,
    shadow_decision_ledger_ref: str,
) -> ReleaseGateRuntimeEvidenceWriteBundle:
    evidence_bundle = loaded_artifacts.evidence_bundle if loaded_artifacts is not None else None
    if evidence_bundle is None and report_path:
        evidence_bundle = ReleaseGateEvidenceBundle(
            certification_packet_corpus=CertificationPacketCorpus(
                artifact_ref=certification_packet_corpus_ref
            ),
            shadow_decision_ledger=ShadowDecisionLedger(
                artifact_ref=shadow_decision_ledger_ref
            ),
            release_gate_report_ref=report_path,
            report_id=verdict.report_id,
            report_hash=verdict.report_hash,
            input_hash=verdict.input_hash,
        )
    return ReleaseGateRuntimeEvidenceWriteBundle(
        verdict=verdict,
        evidence_bundle=evidence_bundle,
    )
