# Plan：081-autonomous-next-step-recovery

## 目标

把已提交的 autonomous next-step / context-critical recovery 主补丁纳入 formal AI-SDLC owner，并以最小增量继续收口 runtime acceptance 证据。

## 实施边界

1. 先把 `.ai-sdlc` checkpoint、resume-pack、project-state 与分支对齐到 `WI-081`，结束 `WI-080` 已完成却仍被复用的状态漂移。
2. 冻结本轮已经提交的运行时代码语义：`propose_recovery` 自动执行、`continue_session` 人工闸门、多项目 progress summary 覆盖。
3. 保持验证入口聚焦在 policy、session spine、brain runtime 与 Feishu delivery 的 targeted 回归，不扩展到新的外部依赖。
4. 在 state 就位后，为下一轮 live runtime acceptance 留出明确任务入口，而不是继续在已完成工单上累计隐性改动。

## 验证

- `uv run pytest tests/test_watchdog_brain_provider_runtime.py tests/test_watchdog_policy_engine.py tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_session_spine_api.py tests/test_watchdog_feishu_delivery.py -q`
- `uv run python -m ai_sdlc verify constraints`
- `uv run python -m ai_sdlc status`
