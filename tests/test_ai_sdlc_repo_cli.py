from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_repo_local_ai_sdlc_status_reports_current_checkpoint() -> None:
    root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, "-m", "ai_sdlc", "status"],
        cwd=root,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert "061-openclaw-entry-routing-and-steer-contracts" in result.stdout
    assert "current_stage=completed" in result.stdout
    assert "next_work_item_seq=62" in result.stdout


def test_repo_local_ai_sdlc_verify_constraints_passes_in_repo() -> None:
    root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, "-m", "ai_sdlc", "verify", "constraints"],
        cwd=root,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert "Constraints OK" in result.stdout


def test_repo_local_ai_sdlc_verify_constraints_reports_release_docs_drift(tmp_path) -> None:
    root = Path(__file__).resolve().parents[1]
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
