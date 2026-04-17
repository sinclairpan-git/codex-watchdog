# Plan：075-external-integration-smoke-harness-closeout

## 目标

把已经交付的外部集成烟测能力正式并入 `ai_sdlc` 真值，消除 `WI-074` 与仓库现状之间的状态滞后。

## 实施边界

1. 先为外部集成烟测 closeout 建立正式 `spec / plan / tasks / execution log`。
2. 再补 `WI-075` 的 `runtime / execution-plan / resume-pack / latest-summary`，使工作项状态可被框架直接消费。
3. 最后更新 `checkpoint` 与 `project-state`，并以测试、约束校验和双对抗评审完成收口。

## 验证

- `uv run pytest -q tests/test_ai_sdlc_repo_cli.py tests/test_ai_sdlc_reconciliation.py`
- `uv run pytest -q`
- `uv run python -m ai_sdlc verify constraints`
- `uv run python -m ai_sdlc status`
