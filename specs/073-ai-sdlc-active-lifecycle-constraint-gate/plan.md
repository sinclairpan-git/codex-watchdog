# Plan：073-ai-sdlc-active-lifecycle-constraint-gate

## 目标

把 active work item lifecycle validator 接回 `ai_sdlc verify constraints` 主入口，并移除 repo-local status 测试中的硬编码 checkpoint 漂移。

## 实施边界

1. 先写/更新回归测试，锁定 status 动态真值与 lifecycle gate 接线要求。
2. 再在 `ai_sdlc/cli.py` 中追加 active work item lifecycle blocker 聚合逻辑。
3. 最后同步 `ai_sdlc` 元数据，完成对抗评审与 closeout。

## 验证

- `uv run pytest -q tests/test_ai_sdlc_repo_cli.py tests/test_ai_sdlc_reconciliation.py`
- `uv run python -m ai_sdlc verify constraints`
- `uv run python -m ai_sdlc status`
