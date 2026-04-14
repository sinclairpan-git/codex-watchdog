from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _ReleaseGateEvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CertificationPacketCorpus(_ReleaseGateEvidenceModel):
    artifact_ref: str = Field(min_length=1)


class ShadowDecisionLedger(_ReleaseGateEvidenceModel):
    artifact_ref: str = Field(min_length=1)


class ReleaseGateEvidenceBundle(_ReleaseGateEvidenceModel):
    certification_packet_corpus: CertificationPacketCorpus
    shadow_decision_ledger: ShadowDecisionLedger
    release_gate_report_ref: str = Field(min_length=1)
    label_manifest_ref: str | None = None
    generated_by: str | None = None
    report_approved_by: str | None = None
    report_id: str | None = None
    report_hash: str | None = None
    input_hash: str | None = None
