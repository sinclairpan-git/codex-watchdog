# Plan：079-state-resume-pack-canonical-sync

## 目标

把顶层 `.ai-sdlc/state/resume-pack.yaml` 从“长期游离的历史快照”收口为当前 active work item 的 canonical resume entry，并让 repo-local `verify constraints` 能直接阻断同类漂移。

## 实施边界

1. 先 formalize `WI-079`，冻结顶层 state resume pack drift 的范围、约束与验证入口。
2. 先写失败测试，锁定两类行为：reconciliation 能识别顶层 state resume pack stale pointer；CLI constraints 主入口会把该漂移作为 blocker。
3. 再最小实现顶层 state resume pack validator，并把它接入 `ai_sdlc verify constraints`。
4. 最后把当前仓库的顶层 state resume pack 与 active checkpoint / branch / `WI-079` 文档路径同步，跑 targeted verification，完成 closeout。

## 验证

- `uv run pytest -q tests/test_ai_sdlc_reconciliation.py tests/test_ai_sdlc_repo_cli.py`
- `uv run python -m ai_sdlc verify constraints`
- `uv run python -m ai_sdlc status`
