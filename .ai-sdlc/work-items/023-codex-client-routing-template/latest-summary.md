# Development Summary

Status: completed
Total Tasks: 4
Completed Tasks: 4
Halted Tasks: 0
Total Batches: 4
Completed Batches: 4
Last Committed Task: T234

## Notes
- 已完成 `T234`，新增 `WatchdogTemplateClient`，把 Feishu 常见消息模板收敛到 stable Watchdog routes。
- 模板覆盖查询进展、查询卡点、继续推进、审批 inbox 与审批决策，并支持 `WATCHDOG_DEFAULT_PROJECT_ID` 的显式/缺省路由策略。
- `README.md`、`docs/getting-started.zh-CN.md` 与 `config/examples/watchdog.env.example` 已写清模板输入项与“本仓库不包含飞书/Feishu runtime”的边界。
- 已通过 `uv run pytest -q tests/integration/test_feishu_integration_spine.py`。
- 当前环境的 `ai-sdlc workitem init` 失败根因已复现：`WorkitemScaffolder` 把模板目录错误解析到 `.venv/lib/python3.11/templates`，随后报错 `template not found: /Users/sinclairpan/project/codex-watchdog/.venv/lib/python3.11/templates/spec-template.md`。
- 因此 023 继续采用与 canonical direct-formal 一致的目录边界维护 formal docs 与状态文件，并把失败原因保留在本摘要与 `specs/023-codex-client-routing-template/task-execution-log.md`。
