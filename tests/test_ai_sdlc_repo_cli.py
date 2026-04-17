from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import ai_sdlc.cli as ai_sdlc_cli
from watchdog.validation.ai_sdlc_reconciliation import ReconciliationInventory


def test_repo_local_ai_sdlc_status_reports_current_checkpoint() -> None:
    root = ROOT
    checkpoint_text = (root / ".ai-sdlc/state/checkpoint.yml").read_text(encoding="utf-8")
    project_state_text = (root / ".ai-sdlc/project/config/project-state.yaml").read_text(encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "ai_sdlc", "status"],
        cwd=root,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert (
        f"linked_wi_id={ai_sdlc_cli._extract_scalar(checkpoint_text, 'linked_wi_id')}" in result.stdout
    )
    assert (
        f"current_stage={ai_sdlc_cli._extract_scalar(checkpoint_text, 'current_stage')}" in result.stdout
    )
    assert (
        f"current_branch={ai_sdlc_cli._extract_scalar(checkpoint_text, 'current_branch')}" in result.stdout
    )
    assert (
        f"next_work_item_seq={ai_sdlc_cli._extract_scalar(project_state_text, 'next_work_item_seq')}"
        in result.stdout
    )


def test_repo_local_ai_sdlc_verify_constraints_passes_in_repo() -> None:
    root = ROOT

    result = subprocess.run(
        [sys.executable, "-m", "ai_sdlc", "verify", "constraints"],
        cwd=root,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert "Constraints OK" in result.stdout


def test_repo_local_ai_sdlc_verify_constraints_reports_release_docs_drift(tmp_path) -> None:
    root = ROOT
    (tmp_path / ".ai-sdlc/project/config").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".ai-sdlc/project/config/project-state.yaml").write_text(
        "status: initialized\nnext_work_item_seq: 1\n",
        encoding="utf-8",
    )
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs/framework-defect-backlog.zh-CN.md").write_text(
        "# Framework Defect Backlog\n\n"
        "## FD-2026-04-05-001 示例\n"
        "- 现象: 示例\n"
        "- 触发场景: 示例\n"
        "- 影响范围: 示例\n"
        "- 根因分类: 示例\n"
        "- 未来杜绝方案摘要: 示例\n"
        "- 建议改动层级: rule\n"
        "- 风险等级: 高\n"
        "- 可验证成功标准: 示例\n"
        "- 是否需要回归测试补充: 需要\n",
        encoding="utf-8",
    )
    (tmp_path / "docs/architecture").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs/architecture/codex-long-running-autonomy-design.md").write_text(
        "\n".join(
            [
                "- `stage_goal_conflict_detected`",
                "stage_goal_conflict_detected",
                "降级为参考信息",
                "label_manifest",
                "generated_by",
                "approved_by",
                "artifact_ref",
                "上一版 `release_gate_report` 立即失效",
                "Memory Hub",
                "Goal Contract",
                "Brain",
                "Recovery",
                "飞书",
                "Release Gate",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "docs/plans").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md").write_text(
        "\n".join(
            [
                "scripts/generate_release_gate_report.py",
                "docs/operations/release-gate-runbook.md",
                "release_gate_report` 必须引用冻结窗口、`label_manifest`、`generated_by`、`approved_by`",
                "禁止靠人工拼接放行材料",
                "报告与当前输入哈希不一致时，e2e 必须阻断自动执行",
                "low-risk 放行前已经产出并校验对应的 `release_gate_report`",
                "stage_goal_conflict_detected",
                "基础事件 schema 与 query facade",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# AI-SDLC\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "ai_sdlc", "verify", "constraints", "--repo-root", str(tmp_path)],
        cwd=root,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "release docs consistency" in result.stdout


def test_collect_constraint_violations_includes_active_work_item_lifecycle(
    monkeypatch, tmp_path: Path
) -> None:
    no_violations = lambda _repo_root: []
    monkeypatch.setattr(ai_sdlc_cli, "validate_checkpoint_yaml_string_compatibility", no_violations)
    monkeypatch.setattr(ai_sdlc_cli, "validate_coverage_audit_snapshot_contracts", no_violations)
    monkeypatch.setattr(ai_sdlc_cli, "validate_release_docs_consistency", no_violations)
    monkeypatch.setattr(ai_sdlc_cli, "validate_task_doc_status_contracts", no_violations)
    monkeypatch.setattr(ai_sdlc_cli, "validate_framework_contracts", no_violations)
    monkeypatch.setattr(ai_sdlc_cli, "validate_backlog_reference_sync", no_violations)
    monkeypatch.setattr(ai_sdlc_cli, "validate_verification_profile_surfaces", no_violations)
    monkeypatch.setattr(ai_sdlc_cli, "validate_long_running_autonomy_docs", no_violations)
    monkeypatch.setattr(ai_sdlc_cli, "validate_long_running_residual_contracts", no_violations)

    inventory = ReconciliationInventory(
        spec_work_items=(),
        mirrored_work_items=(),
        missing_work_item_mirrors=(),
        next_work_item_seq=74,
        active_work_item_id="073-ai-sdlc-active-lifecycle-constraint-gate",
        stale_pointers=(),
    )
    monkeypatch.setattr(ai_sdlc_cli, "collect_reconciliation_inventory", lambda _repo_root: inventory)

    called_with: dict[str, Path] = {}

    def fake_validate_work_item_lifecycle(work_item_root: Path) -> list[str]:
        called_with["path"] = work_item_root
        return ["runtime.yaml: review_approval_status must be approved"]

    monkeypatch.setattr(ai_sdlc_cli, "validate_work_item_lifecycle", fake_validate_work_item_lifecycle)

    violations = ai_sdlc_cli._collect_constraint_violations(tmp_path)

    assert called_with["path"] == tmp_path / ".ai-sdlc/work-items" / inventory.active_work_item_id
    assert violations == [
        "work-item lifecycle (073-ai-sdlc-active-lifecycle-constraint-gate): "
        "runtime.yaml: review_approval_status must be approved"
    ]


def test_collect_constraint_violations_includes_completed_review_gate_mirror_drift(
    monkeypatch, tmp_path: Path
) -> None:
    no_violations = lambda _repo_root: []
    monkeypatch.setattr(ai_sdlc_cli, "validate_checkpoint_yaml_string_compatibility", no_violations)
    monkeypatch.setattr(ai_sdlc_cli, "validate_coverage_audit_snapshot_contracts", no_violations)
    monkeypatch.setattr(ai_sdlc_cli, "validate_release_docs_consistency", no_violations)
    monkeypatch.setattr(ai_sdlc_cli, "validate_task_doc_status_contracts", no_violations)
    monkeypatch.setattr(ai_sdlc_cli, "validate_framework_contracts", no_violations)
    monkeypatch.setattr(ai_sdlc_cli, "validate_backlog_reference_sync", no_violations)
    monkeypatch.setattr(ai_sdlc_cli, "validate_verification_profile_surfaces", no_violations)
    monkeypatch.setattr(ai_sdlc_cli, "validate_long_running_autonomy_docs", no_violations)
    monkeypatch.setattr(ai_sdlc_cli, "validate_long_running_residual_contracts", no_violations)
    monkeypatch.setattr(
        ai_sdlc_cli,
        "collect_reconciliation_inventory",
        lambda _repo_root: ReconciliationInventory(
            spec_work_items=(),
            mirrored_work_items=(),
            missing_work_item_mirrors=(),
            next_work_item_seq=79,
            active_work_item_id=None,
            stale_pointers=(),
        ),
    )
    monkeypatch.setattr(ai_sdlc_cli, "validate_work_item_lifecycle", lambda _work_item_root: [])
    monkeypatch.setattr(
        ai_sdlc_cli,
        "validate_completed_review_gate_mirror_drift",
        lambda _repo_root: [
            "completed work-item review gate mirror "
            "(049-feishu-and-openclaw-entrypoint-closure): "
            "runtime.yaml: review_approval_status must be removed once current_stage=completed"
        ],
    )

    violations = ai_sdlc_cli._collect_constraint_violations(tmp_path)

    assert violations == [
        "completed work-item review gate mirror "
        "(049-feishu-and-openclaw-entrypoint-closure): "
        "runtime.yaml: review_approval_status must be removed once current_stage=completed"
    ]
