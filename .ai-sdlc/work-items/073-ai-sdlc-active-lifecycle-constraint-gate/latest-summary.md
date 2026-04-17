# Development Summary

Status: completed
Total Tasks: 5
Completed Tasks: 5
Halted Tasks: 0
Total Batches: 5
Completed Batches: 5
Last Committed Task: T735

## Notes

- `WI-073` 目标是把 active work item lifecycle validator 接回 `ai_sdlc verify constraints` 主入口，并修复 repo-local `status` 测试对旧 checkpoint 的硬编码依赖。
- 当前已完成：
  - `ai_sdlc/cli.py` 已新增 `_collect_constraint_violations()`，并对 `collect_reconciliation_inventory()` 选出的 active work item 执行 `validate_work_item_lifecycle()`；
  - lifecycle violations 现在会以 `work-item lifecycle (<wi-id>): ...` 形式并入 `Constraint violations` 输出；
  - `tests/test_ai_sdlc_repo_cli.py` 已改为动态读取 checkpoint / project-state 真值，并新增 lifecycle gate 接线回归测试。
- 双专家最终复核结论：
  - Hilbert：认定这是 `P1` framework truth gap，建议以 `WI-073` 独立关闭；
  - Gauss：认定这是 `P1` 正式闭环缺口，status 测试漂移属于已实红症状，lifecycle gate 缺失属于主问题。

## Verification

- `uv run pytest -q tests/test_ai_sdlc_repo_cli.py tests/test_ai_sdlc_reconciliation.py` -> `11 passed in 0.25s`
- `uv run python -m ai_sdlc verify constraints` -> `Constraints OK`
- `uv run python -m ai_sdlc status` -> `linked_wi_id=073-ai-sdlc-active-lifecycle-constraint-gate`, `current_stage=completed`, `current_branch=codex/073-ai-sdlc-active-lifecycle-constraint-gate`, `next_work_item_seq=74`

## Handoff

- `WI-073` 只补 framework gate 与 repo-local truth test，不重写 lifecycle rule 本身，也不扩展 `ai_sdlc status` 的输出面。
