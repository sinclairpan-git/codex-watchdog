from __future__ import annotations

import argparse
import json
from pathlib import Path

from watchdog.services.brain.release_gate import (
    DEFAULT_RUNTIME_CONTRACT_SURFACE_REF,
    DEFAULT_RUNTIME_GATE_REASON_TAXONOMY,
)
from watchdog.services.brain.release_gate_report_material import (
    build_release_gate_report_id,
    stable_release_gate_report_hash,
)


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        rows.append(json.loads(stripped))
    return rows


def _single_value(rows: list[dict[str, object]], field: str) -> str:
    values = {str(row[field]) for row in rows}
    if len(values) != 1:
        raise ValueError(f"expected exactly one {field}, got: {sorted(values)}")
    return next(iter(values))


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def build_report(
    *,
    packets: list[dict[str, object]],
    shadow_runs: list[dict[str, object]],
    label_manifest_path: str,
    label_manifest: dict[str, object],
    generated_by: str,
    report_approved_by: str,
    artifact_ref: str,
    sample_window: str,
    shadow_window: str,
) -> dict[str, object]:
    if not packets:
        raise ValueError("packets fixture must not be empty")
    if not shadow_runs:
        raise ValueError("shadow runs fixture must not be empty")

    input_hash = _single_value(packets, "input_hash")
    payload = {
        "sample_window": sample_window,
        "shadow_window": shadow_window,
        "label_manifest": label_manifest_path,
        "generated_by": generated_by,
        "report_approved_by": report_approved_by,
        "artifact_ref": artifact_ref,
        "expires_at": str(label_manifest["expires_at"]),
        "provider": _single_value(packets, "provider"),
        "model": _single_value(packets, "model"),
        "prompt_schema_ref": _single_value(packets, "prompt_schema_ref"),
        "output_schema_ref": _single_value(packets, "output_schema_ref"),
        "risk_policy_version": _single_value(packets, "risk_policy_version"),
        "decision_input_builder_version": _single_value(
            packets, "decision_input_builder_version"
        ),
        "policy_engine_version": _single_value(packets, "policy_engine_version"),
        "tool_schema_hash": _single_value(packets, "tool_schema_hash"),
        "memory_provider_adapter_hash": _single_value(
            packets, "memory_provider_adapter_hash"
        ),
        "input_hash": input_hash,
        "runtime_contract_surface_ref": DEFAULT_RUNTIME_CONTRACT_SURFACE_REF,
        "runtime_gate_reason_taxonomy": DEFAULT_RUNTIME_GATE_REASON_TAXONOMY,
        "shadow_decision_count": len(shadow_runs),
        "certification_packet_count": len(packets),
    }
    payload["report_id"] = build_release_gate_report_id(payload)
    payload["report_hash"] = stable_release_gate_report_hash(payload)
    return payload


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

    label_manifest_path = Path(args.label_manifest)
    report = build_report(
        packets=_read_jsonl(Path(args.packets)),
        shadow_runs=_read_jsonl(Path(args.shadow_runs)),
        label_manifest_path=_display_path(label_manifest_path),
        label_manifest=_read_json(label_manifest_path),
        generated_by=args.generated_by,
        report_approved_by=args.report_approved_by,
        artifact_ref=args.artifact_ref,
        sample_window=args.sample_window,
        shadow_window=args.shadow_window,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
