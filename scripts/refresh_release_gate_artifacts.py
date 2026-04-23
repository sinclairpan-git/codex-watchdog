from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

from watchdog.services.brain.release_gate_loading import load_release_gate_artifacts


def _load_generate_module():
    module_path = Path(__file__).with_name("generate_release_gate_report.py")
    spec = importlib.util.spec_from_file_location(
        "generate_release_gate_report", module_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"unable to load {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def refresh_release_gate_artifacts(
    *,
    packets_path: str,
    shadow_runs_path: str,
    label_manifest_path: str,
    generated_by: str,
    report_approved_by: str,
    artifact_ref: str,
    sample_window: str,
    shadow_window: str,
    output_path: str,
) -> dict[str, object]:
    generate_module = _load_generate_module()
    packets = generate_module._read_jsonl(Path(packets_path))
    shadow_runs = generate_module._read_jsonl(Path(shadow_runs_path))
    label_manifest_file = Path(label_manifest_path)
    report = generate_module.build_report(
        packets=packets,
        shadow_runs=shadow_runs,
        label_manifest_path=generate_module._display_path(label_manifest_file),
        label_manifest=generate_module._read_json(label_manifest_file),
        generated_by=generated_by,
        report_approved_by=report_approved_by,
        artifact_ref=artifact_ref,
        sample_window=sample_window,
        shadow_window=shadow_window,
    )
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    load_release_gate_artifacts(
        report_path=str(output_file),
        runtime_contract={
            "risk_policy_version": str(report["risk_policy_version"]),
            "decision_input_builder_version": str(report["decision_input_builder_version"]),
            "policy_engine_version": str(report["policy_engine_version"]),
            "tool_schema_hash": str(report["tool_schema_hash"]),
            "memory_provider_adapter_hash": str(report["memory_provider_adapter_hash"]),
        },
        certification_packet_corpus_ref=packets_path,
        shadow_decision_ledger_ref=shadow_runs_path,
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packets", required=True)
    parser.add_argument("--shadow-runs", required=True)
    parser.add_argument("--label-manifest", required=True)
    parser.add_argument("--generated-by", required=True)
    parser.add_argument("--report-approved-by", required=True)
    parser.add_argument("--artifact-ref", required=True)
    parser.add_argument("--sample-window", required=True)
    parser.add_argument("--shadow-window", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    refresh_release_gate_artifacts(
        packets_path=args.packets,
        shadow_runs_path=args.shadow_runs,
        label_manifest_path=args.label_manifest,
        generated_by=args.generated_by,
        report_approved_by=args.report_approved_by,
        artifact_ref=args.artifact_ref,
        sample_window=args.sample_window,
        shadow_window=args.shadow_window,
        output_path=args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
