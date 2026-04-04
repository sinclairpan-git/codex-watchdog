# Task Execution Log: 009-task-events-stream

## 2026-04-05

- 新增 `tests/test_a_control_agent.py::test_task_events_endpoint_returns_sse_snapshot`，先观察到 `404` 红测。
- 在 `TaskStore` 增加统一事件落盘与按 `project_id` 读取能力。
- 在 `src/a_control_agent/api/tasks.py` 新增 `GET /api/v1/tasks/{project_id}/events` SSE 输出。
- 新增 `tests/test_a_control_agent_control_flow.py` 中针对 `handoff`、`resume`、`approval_decided` 的事件流红测。
- 在 `src/a_control_agent/api/recovery.py` 与 `src/a_control_agent/api/approvals.py` 补齐控制流关键动作的 `task_events` 追加。
- 新增 Watchdog 侧 `GET /api/v1/watchdog/tasks/{project_id}/events`，通过 A client 透传 SSE 快照与持续流。
- 新增 `tests/test_watchdog.py` 覆盖代理快照、代理流、A 侧业务错误与链路错误。
- 重新导出 OpenAPI，并同步 README / 接入文档。
- 验证通过：`uv run pytest -q`、`uv run ruff check src tests examples`。
