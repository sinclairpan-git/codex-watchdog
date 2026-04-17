# Task Execution Log：078-completed-review-gate-drift

- 2026-04-18：在 `WI-077` 关闭后继续扫描 formal backlog，确认 canonical residual ledger、framework defect backlog 与 product backlog 均已收口。
- 2026-04-18：发现多个已完成 historical work item 仍保留 `review_approval_status: pending`，但 repo-local CLI 目前只校验 active/highest WI，导致 completed review gate drift 未被发现。
- 2026-04-18：已将当前工作切换到 `codex/078-completed-review-gate-drift`，准备以新的 framework closeout 工单处理该类漂移。
- 2026-04-18：已补充失败测试，锁定 completed historical work item 的 `review_approval_status: pending` 必须被 repo-local `ai_sdlc verify constraints` 识别。
- 2026-04-18：已新增 completed review gate mirror drift validator，并把它接入 `ai_sdlc/cli.py` 的 constraints 收集路径；active work item 继续复用既有 `validate_work_item_lifecycle()` 语义。
- 2026-04-18：已清理 `WI-049` 至 `WI-064` completed mirrors 中悬空的 `review_approval_status: pending` 与空 `review_approved_by` 字段，不伪造历史 reviewer。
- 2026-04-18：已跑完 `tests/test_ai_sdlc_reconciliation.py`、`tests/test_ai_sdlc_repo_cli.py`、`uv run python -m ai_sdlc verify constraints` 与 `uv run python -m ai_sdlc status`，并同步 `WI-078` closeout 状态。
