# Plan：078-completed-review-gate-drift

## 目标

把 completed historical work items 上悬空的 `review_approval_status: pending` 从“未被发现的历史噪音”收口成正式可校验的 repo-local contract，并清理当前仓库里的已确认漂移。

## 实施边界

1. 先 formalize 一个新的 `WI-078`，明确这是 framework drift closeout，而不是产品功能工单。
2. 先写失败测试，锁定两类行为：repo-local CLI 能发现 completed review gate drift；历史 completed work item 的悬空 `pending` 元数据不能继续存在。
3. 再最小实现 completed drift validator，并让 `ai_sdlc verify constraints` 在 active WI lifecycle 之外也覆盖它。
4. 最后清理当前仓库里已确认受影响的 historical mirrors，跑 targeted verification，完成 formal closeout。

## 验证

- `uv run pytest -q tests/test_ai_sdlc_reconciliation.py tests/test_ai_sdlc_repo_cli.py`
- `uv run python -m ai_sdlc verify constraints`
- `uv run python -m ai_sdlc status`
