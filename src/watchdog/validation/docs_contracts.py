from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ARCHITECTURE_DOC = Path("docs/architecture/codex-long-running-autonomy-design.md")
IMPLEMENTATION_PLAN_DOC = Path("docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md")
GETTING_STARTED_DOC = Path("docs/getting-started.zh-CN.md")
WATCHDOG_ENV_EXAMPLE = Path("config/examples/watchdog.env.example")


@dataclass(frozen=True)
class DocContractCheck:
    name: str
    path: Path
    must_contain: tuple[str, ...]


DOC_CONTRACT_CHECKS: tuple[DocContractCheck, ...] = (
    DocContractCheck(
        name="arch_has_stage_goal_conflict_event",
        path=ARCHITECTURE_DOC,
        must_contain=("- `stage_goal_conflict_detected`",),
    ),
    DocContractCheck(
        name="arch_stage_conflict_degrades_to_reference",
        path=ARCHITECTURE_DOC,
        must_contain=("stage_goal_conflict_detected", "降级为参考信息"),
    ),
    DocContractCheck(
        name="arch_release_gate_has_label_manifest",
        path=ARCHITECTURE_DOC,
        must_contain=("label_manifest",),
    ),
    DocContractCheck(
        name="arch_release_gate_has_generated_by",
        path=ARCHITECTURE_DOC,
        must_contain=("generated_by",),
    ),
    DocContractCheck(
        name="arch_release_gate_has_approved_by",
        path=ARCHITECTURE_DOC,
        must_contain=("approved_by",),
    ),
    DocContractCheck(
        name="arch_release_gate_has_artifact_ref",
        path=ARCHITECTURE_DOC,
        must_contain=("artifact_ref",),
    ),
    DocContractCheck(
        name="arch_release_gate_invalidates_on_provider_change",
        path=ARCHITECTURE_DOC,
        must_contain=("上一版 `release_gate_report` 立即失效",),
    ),
    DocContractCheck(
        name="plan_task6_creates_runbook_and_script",
        path=IMPLEMENTATION_PLAN_DOC,
        must_contain=(
            "scripts/generate_release_gate_report.py",
            "docs/operations/release-gate-runbook.md",
        ),
    ),
    DocContractCheck(
        name="plan_task6_requires_label_manifest",
        path=IMPLEMENTATION_PLAN_DOC,
        must_contain=(
            "release_gate_report` 必须引用冻结窗口、`label_manifest`、`generated_by`、`approved_by`",
        ),
    ),
    DocContractCheck(
        name="plan_task6_forbids_manual_splicing",
        path=IMPLEMENTATION_PLAN_DOC,
        must_contain=("禁止靠人工拼接放行材料",),
    ),
    DocContractCheck(
        name="plan_task8_e2e_blocks_without_report",
        path=IMPLEMENTATION_PLAN_DOC,
        must_contain=("报告与当前输入哈希不一致时，e2e 必须阻断自动执行",),
    ),
    DocContractCheck(
        name="plan_acceptance_requires_report_before_low_risk",
        path=IMPLEMENTATION_PLAN_DOC,
        must_contain=("low-risk 放行前已经产出并校验对应的 `release_gate_report`",),
    ),
    DocContractCheck(
        name="plan_risk_control_requires_stage_goal_conflict_schema",
        path=IMPLEMENTATION_PLAN_DOC,
        must_contain=("stage_goal_conflict_detected", "基础事件 schema 与 query facade"),
    ),
    DocContractCheck(
        name="arch_covers_memory_hub",
        path=ARCHITECTURE_DOC,
        must_contain=("Memory Hub",),
    ),
    DocContractCheck(
        name="arch_covers_goal_contract",
        path=ARCHITECTURE_DOC,
        must_contain=("Goal Contract",),
    ),
    DocContractCheck(
        name="arch_covers_brain",
        path=ARCHITECTURE_DOC,
        must_contain=("Brain",),
    ),
    DocContractCheck(
        name="arch_covers_recovery",
        path=ARCHITECTURE_DOC,
        must_contain=("Recovery",),
    ),
    DocContractCheck(
        name="arch_covers_feishu",
        path=ARCHITECTURE_DOC,
        must_contain=("飞书",),
    ),
    DocContractCheck(
        name="arch_covers_release_gate",
        path=ARCHITECTURE_DOC,
        must_contain=("Release Gate",),
    ),
    DocContractCheck(
        name="env_example_covers_feishu_ingress_and_delivery",
        path=WATCHDOG_ENV_EXAMPLE,
        must_contain=(
            "WATCHDOG_DELIVERY_TRANSPORT=feishu",
            "WATCHDOG_FEISHU_APP_ID=",
            "WATCHDOG_FEISHU_APP_SECRET=",
            "WATCHDOG_FEISHU_VERIFICATION_TOKEN=",
            "WATCHDOG_FEISHU_RECEIVE_ID=",
            "WATCHDOG_FEISHU_RECEIVE_ID_TYPE=",
        ),
    ),
    DocContractCheck(
        name="env_example_covers_openai_compatible_provider",
        path=WATCHDOG_ENV_EXAMPLE,
        must_contain=(
            "WATCHDOG_BRAIN_PROVIDER_NAME=openai-compatible",
            "WATCHDOG_BRAIN_PROVIDER_BASE_URL=",
            "WATCHDOG_BRAIN_PROVIDER_API_KEY=",
            "WATCHDOG_BRAIN_PROVIDER_MODEL=",
        ),
    ),
    DocContractCheck(
        name="getting_started_covers_feishu_official_ingress",
        path=GETTING_STARTED_DOC,
        must_contain=(
            "WATCHDOG_DELIVERY_TRANSPORT=feishu",
            "WATCHDOG_FEISHU_VERIFICATION_TOKEN",
            "/api/v1/watchdog/feishu/events",
        ),
    ),
    DocContractCheck(
        name="getting_started_covers_openai_compatible_provider",
        path=GETTING_STARTED_DOC,
        must_contain=(
            "WATCHDOG_BRAIN_PROVIDER_NAME=openai-compatible",
            "WATCHDOG_BRAIN_PROVIDER_BASE_URL",
            "WATCHDOG_BRAIN_PROVIDER_API_KEY",
            "WATCHDOG_BRAIN_PROVIDER_MODEL",
        ),
    ),
)


def validate_long_running_autonomy_docs(repo_root: Path | None = None) -> list[str]:
    root = repo_root or Path(__file__).resolve().parents[3]
    cache: dict[Path, str] = {}
    violations: list[str] = []

    for check in DOC_CONTRACT_CHECKS:
        doc_path = root / check.path
        if not doc_path.exists():
            violations.append(f"{check.name}: missing file {check.path}")
            continue

        contents = cache.setdefault(check.path, doc_path.read_text(encoding="utf-8"))
        missing = [phrase for phrase in check.must_contain if phrase not in contents]
        if missing:
            joined = ", ".join(repr(phrase) for phrase in missing)
            violations.append(f"{check.name}: missing {joined} in {check.path}")

    return violations
