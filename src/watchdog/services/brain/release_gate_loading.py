from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from watchdog.services.brain.release_gate import ReleaseGateReport, parse_release_gate_report
from watchdog.services.brain.release_gate_evidence import (
    CertificationPacketCorpus,
    ReleaseGateEvidenceBundle,
    ShadowDecisionLedger,
)
from watchdog.services.brain.release_gate_report_material import (
    stable_release_gate_report_hash,
)


class _ReleaseGateLoadingModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoadedReleaseGateArtifacts(_ReleaseGateLoadingModel):
    report: ReleaseGateReport
    raw_payload_hash: str = Field(min_length=1)
    runtime_contract: dict[str, str] = Field(default_factory=dict)
    evidence_bundle: ReleaseGateEvidenceBundle


def load_release_gate_artifacts(
    *,
    report_path: str,
    runtime_contract: dict[str, str],
    certification_packet_corpus_ref: str,
    shadow_decision_ledger_ref: str,
) -> LoadedReleaseGateArtifacts:
    payload = json.loads(Path(report_path).read_text(encoding="utf-8"))
    report = parse_release_gate_report(payload)
    expected_report_hash = stable_release_gate_report_hash(payload)
    if report.report_hash != expected_report_hash:
        raise ValueError("report_hash drifted from canonical material")
    return LoadedReleaseGateArtifacts(
        report=report,
        raw_payload_hash=expected_report_hash,
        runtime_contract={str(key): str(value) for key, value in runtime_contract.items()},
        evidence_bundle=ReleaseGateEvidenceBundle(
            certification_packet_corpus=CertificationPacketCorpus(
                artifact_ref=certification_packet_corpus_ref
            ),
            shadow_decision_ledger=ShadowDecisionLedger(
                artifact_ref=shadow_decision_ledger_ref
            ),
            release_gate_report_ref=report_path,
            label_manifest_ref=report.label_manifest,
            generated_by=report.generated_by,
            report_approved_by=report.report_approved_by,
            report_id=report.report_id,
            report_hash=report.report_hash,
            input_hash=report.input_hash,
        ),
    )
