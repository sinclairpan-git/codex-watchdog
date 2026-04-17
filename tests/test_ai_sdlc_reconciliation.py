from __future__ import annotations

import importlib
import textwrap
from pathlib import Path

import pytest


def _load_reconciliation_module():
    try:
        return importlib.import_module("watchdog.validation.ai_sdlc_reconciliation")
    except ModuleNotFoundError as exc:
        pytest.fail(f"missing reconciliation validator module: {exc}")


def _write(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(contents).lstrip(), encoding="utf-8")


def test_collect_reconciliation_inventory_tracks_missing_mirrors_and_stale_top_level_state(
    tmp_path: Path,
) -> None:
    reconciliation = _load_reconciliation_module()

    _write(tmp_path / "specs/006-m5-hardening/spec.md", "# 006\n")
    _write(
        tmp_path / "specs/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/spec.md",
        "# 047\n",
    )
    _write(
        tmp_path
        / ".ai-sdlc/work-items/023-codex-client-openclaw-route-template/runtime.yaml",
        """
        current_stage: completed
        current_batch: 5
        current_task: ''
        last_committed_task: T235
        current_branch: codex/023-codex-client-openclaw-route-template
        """,
    )
    _write(
        tmp_path
        / ".ai-sdlc/work-items/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/runtime.yaml",
        """
        current_stage: verify
        current_batch: 2
        current_task: T472
        last_committed_task: T471
        current_branch: codex/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair
        """,
    )
    _write(
        tmp_path / ".ai-sdlc/state/checkpoint.yml",
        """
        current_stage: verify
        feature:
          id: 023-codex-client-openclaw-route-template
        linked_wi_id: 023-codex-client-openclaw-route-template
        """,
    )
    _write(
        tmp_path / ".ai-sdlc/project/config/project-state.yaml",
        """
        status: initialized
        next_work_item_seq: 24
        """,
    )

    inventory = reconciliation.collect_reconciliation_inventory(tmp_path)

    assert inventory.next_work_item_seq == 48
    assert inventory.active_work_item_id == "047-ai-sdlc-state-reconciliation-and-canonical-gate-repair"
    assert inventory.missing_work_item_mirrors == ("006-m5-hardening",)
    assert any(
        ".ai-sdlc/state/checkpoint.yml" in violation
        and "023-codex-client-openclaw-route-template" in violation
        and "047-ai-sdlc-state-reconciliation-and-canonical-gate-repair" in violation
        for violation in inventory.stale_pointers
    )
    assert any(
        ".ai-sdlc/project/config/project-state.yaml" in violation
        and "24" in violation
        and "48" in violation
        for violation in inventory.stale_pointers
    )


def test_validate_work_item_lifecycle_requires_review_gate_before_t472(tmp_path: Path) -> None:
    reconciliation = _load_reconciliation_module()
    wi_root = (
        tmp_path / ".ai-sdlc/work-items/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair"
    )

    _write(
        wi_root / "runtime.yaml",
        """
        current_stage: verify
        current_batch: 2
        current_task: T472
        last_committed_task: T471
        current_branch: codex/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair
        """,
    )
    _write(
        wi_root / "execution-plan.yaml",
        """
        current_batch: 2
        tasks:
        - task_id: T471
          status: completed
        - task_id: T472
          status: in_progress
        batches:
        - batch_id: 2
          tasks:
          - T472
          status: in_progress
        """,
    )
    _write(
        wi_root / "resume-pack.yaml",
        """
        current_stage: verify
        current_batch: 2
        last_committed_task: T471
        current_branch: codex/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair
        timestamp: '2026-04-16T06:51:02Z'
        """,
    )
    _write(
        wi_root / "latest-summary.md",
        """
        # Development Summary

        Status: active
        Last Committed Task: T471

        ## Handoff
        - 当前下一执行入口固定为 `T472`
        """,
    )

    violations = reconciliation.validate_work_item_lifecycle(wi_root)

    assert any("runtime.yaml" in violation and "docs_baseline_ref" in violation for violation in violations)
    assert any(
        "runtime.yaml" in violation and "review_approval_status" in violation for violation in violations
    )
    assert any(
        "resume-pack.yaml" in violation and "docs_baseline_ref" in violation for violation in violations
    )
    assert any(
        "resume-pack.yaml" in violation and "review_approved_by" in violation for violation in violations
    )


def test_validate_work_item_lifecycle_flags_cross_file_drift(tmp_path: Path) -> None:
    reconciliation = _load_reconciliation_module()
    wi_root = (
        tmp_path / ".ai-sdlc/work-items/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair"
    )

    _write(
        wi_root / "runtime.yaml",
        """
        current_stage: verify
        current_batch: 2
        current_task: T472
        last_committed_task: T471
        current_branch: codex/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair
        docs_baseline_ref: baseline-047
        docs_baseline_at: '2026-04-16T06:51:02Z'
        review_approval_status: approved
        review_approved_by:
        - Anthropic Manager Expert
        - Hermes Agent Expert
        """,
    )
    _write(
        wi_root / "execution-plan.yaml",
        """
        current_batch: 3
        tasks:
        - task_id: T471
          status: completed
        - task_id: T472
          status: pending
        batches:
        - batch_id: 2
          tasks:
          - T472
          status: pending
        - batch_id: 3
          tasks:
          - T473
          status: in_progress
        """,
    )
    _write(
        wi_root / "resume-pack.yaml",
        """
        current_stage: verify
        current_batch: 2
        last_committed_task: T470
        current_branch: codex/046-session-event-gate-payload-write-contract
        docs_baseline_ref: baseline-047
        docs_baseline_at: '2026-04-16T06:51:02Z'
        review_approval_status: approved
        review_approved_by:
        - Anthropic Manager Expert
        - Hermes Agent Expert
        timestamp: '2026-04-16T06:51:02Z'
        """,
    )
    _write(
        wi_root / "latest-summary.md",
        """
        # Development Summary

        Status: active
        Last Committed Task: T470

        ## Handoff
        - 当前下一执行入口固定为 `T473`
        """,
    )

    violations = reconciliation.validate_work_item_lifecycle(wi_root)

    assert any("current_branch" in violation for violation in violations)
    assert any("last_committed_task" in violation and "resume-pack.yaml" in violation for violation in violations)
    assert any("execution-plan.yaml" in violation and "current_batch" in violation for violation in violations)
    assert any("execution-plan.yaml" in violation and "T472" in violation for violation in violations)
    assert any("latest-summary.md" in violation and "T470" in violation for violation in violations)


def test_build_owner_ledger_assigns_unique_owner_by_priority() -> None:
    reconciliation = _load_reconciliation_module()

    rows = (
        reconciliation.MatrixGapRow(
            stable_id="row-047",
            summary="state truth drift blocks downstream work",
            gap_type="状态真值不一致 + 无验证",
            source="matrix:1",
            state_unstable=True,
        ),
        reconciliation.MatrixGapRow(
            stable_id="row-048",
            summary="runtime behavior is still missing",
            gap_type="无实现、无验证、无入口",
            source="matrix:2",
        ),
        reconciliation.MatrixGapRow(
            stable_id="row-049",
            summary="runtime exists but no formal entry",
            gap_type="无入口 + 无验证",
            source="matrix:3",
        ),
        reconciliation.MatrixGapRow(
            stable_id="row-050",
            summary="only validation is missing",
            gap_type="无验证/重启验证缺失",
            source="matrix:4",
        ),
        reconciliation.MatrixGapRow(
            stable_id="row-051",
            summary="explicit backlog hardening handoff",
            gap_type="测试强化残项",
            source="matrix:5",
            backlog_handoff=True,
        ),
    )

    ledger = reconciliation.build_owner_ledger(rows)
    owners = {entry.stable_id: entry.owner for entry in ledger}

    assert owners == {
        "row-047": "WI-047",
        "row-048": "WI-048",
        "row-049": "WI-049",
        "row-050": "WI-050",
        "row-051": "WI-051",
    }
    assert len({entry.stable_id for entry in ledger}) == len(rows)
    assert all(len(entry.non_owners) == 4 for entry in ledger)


def test_parse_unlanded_matrix_rows_projects_markdown_rows_into_stable_inputs() -> None:
    reconciliation = _load_reconciliation_module()

    markdown = """
    # matrix

    | 来源 | 条款摘要 | 实现 | 验证 | 入口 | 缺口类型 | 结论 |
    | --- | --- | --- | --- | --- | --- | --- |
    | `a.md:1` | 条款 A | impl | test |  | 无入口 | 未落地 |
    | `b.md:2` | 条款 B |  |  |  | 无实现、无验证、无入口 | 未落地 |
    | `c.md:3` | 条款 C | impl | test | route | 无 | 已落地 |
    """

    rows = reconciliation.parse_unlanded_matrix_rows(markdown)

    assert [(row.stable_id, row.summary, row.gap_type, row.source) for row in rows] == [
        ("matrix-row-0001", "条款 A", "无入口", "`a.md:1`"),
        ("matrix-row-0002", "条款 B", "无实现、无验证、无入口", "`b.md:2`"),
    ]


def test_validate_work_item_lifecycle_allows_completed_runtime_to_finish_cleanly(
    tmp_path: Path,
) -> None:
    reconciliation = _load_reconciliation_module()
    wi_root = (
        tmp_path / ".ai-sdlc/work-items/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair"
    )

    _write(
        wi_root / "runtime.yaml",
        """
        current_stage: completed
        current_batch: 5
        current_task: ''
        last_committed_task: T475
        current_branch: codex/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair
        docs_baseline_ref: baseline-047
        docs_baseline_at: '2026-04-16T06:51:02Z'
        review_approval_status: approved
        review_approved_by:
        - Anthropic Manager Expert
        - Hermes Agent Expert
        """,
    )
    _write(
        wi_root / "execution-plan.yaml",
        """
        current_batch: 5
        tasks:
        - task_id: T475
          status: completed
        batches:
        - batch_id: 5
          tasks:
          - T475
          status: completed
        """,
    )
    _write(
        wi_root / "resume-pack.yaml",
        """
        current_stage: completed
        current_batch: 5
        last_committed_task: T475
        current_branch: codex/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair
        docs_baseline_ref: baseline-047
        docs_baseline_at: '2026-04-16T06:51:02Z'
        review_approval_status: approved
        review_approved_by:
        - Anthropic Manager Expert
        - Hermes Agent Expert
        timestamp: '2026-04-16T07:04:03Z'
        """,
    )
    _write(
        wi_root / "latest-summary.md",
        """
        # Development Summary

        Status: completed
        Last Committed Task: T475

        ## Handoff
        - 当前下一执行入口固定为 `WI-048`
        """,
    )

    assert reconciliation.validate_work_item_lifecycle(wi_root) == []


def test_validate_completed_review_gate_mirror_drift_flags_pending_review_metadata(
    tmp_path: Path,
) -> None:
    reconciliation = _load_reconciliation_module()
    wi_root = tmp_path / ".ai-sdlc/work-items/049-feishu-and-openclaw-entrypoint-closure"

    _write(
        wi_root / "runtime.yaml",
        """
        current_stage: completed
        current_batch: 5
        current_task: ''
        last_committed_task: T495
        current_branch: codex/049-feishu-and-openclaw-entrypoint-closure
        review_approval_status: pending
        """,
    )
    _write(
        wi_root / "resume-pack.yaml",
        """
        current_stage: completed
        current_batch: 5
        current_task: ''
        last_committed_task: T495
        current_branch: codex/049-feishu-and-openclaw-entrypoint-closure
        review_approval_status: pending
        timestamp: '2026-04-18T00:00:00Z'
        """,
    )

    violations = reconciliation.validate_completed_review_gate_mirror_drift(tmp_path)

    assert violations == [
        "completed work-item review gate mirror "
        "(049-feishu-and-openclaw-entrypoint-closure): "
        "runtime.yaml: review_approval_status must be removed once current_stage=completed",
        "completed work-item review gate mirror "
        "(049-feishu-and-openclaw-entrypoint-closure): "
        "resume-pack.yaml: review_approval_status must be removed once current_stage=completed",
    ]


def test_collect_reconciliation_inventory_prefers_checkpoint_truth_over_older_open_runtime(
    tmp_path: Path,
) -> None:
    reconciliation = _load_reconciliation_module()

    _write(
        tmp_path / "specs/037-autonomy-golden-path-and-release-gate-e2e/spec.md",
        "# 037\n",
    )
    _write(
        tmp_path / "specs/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/spec.md",
        "# 047\n",
    )
    _write(
        tmp_path / ".ai-sdlc/work-items/037-autonomy-golden-path-and-release-gate-e2e/runtime.yaml",
        """
        current_stage: verify
        current_batch: 1
        current_task: ''
        last_committed_task: T371
        current_branch: codex/037-autonomy-golden-path-and-release-gate-e2e
        """,
    )
    _write(
        tmp_path
        / ".ai-sdlc/work-items/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/runtime.yaml",
        """
        current_stage: completed
        current_batch: 5
        current_task: ''
        last_committed_task: T475
        current_branch: codex/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair
        """,
    )
    _write(
        tmp_path / ".ai-sdlc/state/checkpoint.yml",
        """
        current_stage: completed
        feature:
          id: 047-ai-sdlc-state-reconciliation-and-canonical-gate-repair
        linked_wi_id: 047-ai-sdlc-state-reconciliation-and-canonical-gate-repair
        """,
    )
    _write(
        tmp_path / ".ai-sdlc/project/config/project-state.yaml",
        """
        status: initialized
        next_work_item_seq: 48
        """,
    )

    inventory = reconciliation.collect_reconciliation_inventory(tmp_path)

    assert inventory.active_work_item_id == "047-ai-sdlc-state-reconciliation-and-canonical-gate-repair"
    assert inventory.stale_pointers == ()


def test_collect_reconciliation_inventory_flags_top_level_state_resume_pack_drift(
    tmp_path: Path,
) -> None:
    reconciliation = _load_reconciliation_module()

    _write(
        tmp_path / "specs/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/spec.md",
        "# 047\n",
    )
    _write(
        tmp_path / ".ai-sdlc/work-items/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/runtime.yaml",
        """
        work_item_id: 047-ai-sdlc-state-reconciliation-and-canonical-gate-repair
        current_stage: verify
        current_batch: 2
        current_task: T472
        last_committed_task: T471
        current_branch: codex/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair
        """,
    )
    _write(
        tmp_path / ".ai-sdlc/state/checkpoint.yml",
        """
        current_stage: verify
        feature:
          id: 047-ai-sdlc-state-reconciliation-and-canonical-gate-repair
          current_branch: codex/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair
        linked_wi_id: 047-ai-sdlc-state-reconciliation-and-canonical-gate-repair
        """,
    )
    _write(
        tmp_path / ".ai-sdlc/project/config/project-state.yaml",
        """
        status: initialized
        next_work_item_seq: 48
        """,
    )
    _write(
        tmp_path / ".ai-sdlc/state/resume-pack.yaml",
        """
        current_stage: execute
        current_branch: codex/023-codex-client-openclaw-route-template
        working_set_snapshot:
          spec_path: specs/023-codex-client-openclaw-route-template/spec.md
          plan_path: specs/023-codex-client-openclaw-route-template/plan.md
          tasks_path: specs/023-codex-client-openclaw-route-template/tasks.md
        checkpoint_path: .ai-sdlc/state/checkpoint.yml
        checkpoint_last_updated: '2026-04-14T16:16:19+08:00'
        """,
    )

    inventory = reconciliation.collect_reconciliation_inventory(tmp_path)

    assert inventory.active_work_item_id == "047-ai-sdlc-state-reconciliation-and-canonical-gate-repair"
    assert any(
        ".ai-sdlc/state/resume-pack.yaml" in violation
        and "current_stage=execute" in violation
        and "verify" in violation
        for violation in inventory.stale_pointers
    )
    assert any(
        ".ai-sdlc/state/resume-pack.yaml" in violation
        and "current_branch=codex/023-codex-client-openclaw-route-template" in violation
        and "codex/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair" in violation
        for violation in inventory.stale_pointers
    )
    assert any(
        ".ai-sdlc/state/resume-pack.yaml" in violation
        and "spec_path=specs/023-codex-client-openclaw-route-template/spec.md" in violation
        and "specs/047-ai-sdlc-state-reconciliation-and-canonical-gate-repair/spec.md" in violation
        for violation in inventory.stale_pointers
    )
