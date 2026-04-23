# 任务分解：009-task-events-stream

> 对应规格：`specs/009-task-events-stream/spec.md`

## Batch 1

### Task 9.1 Codex runtime service SSE 事件流

- **任务编号**：T91
- **状态**：已完成（2026-04-05）
- **依赖**：无
- **文件**：`src/a_control_agent/storage/tasks_store.py`, `src/a_control_agent/api/tasks.py`, `tests/test_a_control_agent.py`
- **可并行**：否
- **验收标准**：
  1. `GET /api/v1/tasks/{project_id}/events` 返回 `text/event-stream`；
  2. `follow=false` 时可回放当前事件快照；
  3. `task_created`、`native_thread_registered`、`steer` 会落入 `task_events.jsonl`；
  4. 相关 `pytest` 通过。
- **验证**：`uv run pytest tests/test_a_control_agent.py::test_task_events_endpoint_returns_sse_snapshot -q`

### Task 9.2 文档、OpenAPI 与回归校验

- **任务编号**：T92
- **状态**：已完成（2026-04-05）
- **依赖**：T91
- **文件**：`README.md`, `docs/getting-started.zh-CN.md`, `docs/openapi/a-control-agent.json`
- **可并行**：否
- **验收标准**：
  1. README 与接入文档标明 SSE 已可用；
  2. OpenAPI 导出物包含 `GET /api/v1/tasks/{project_id}/events`；
  3. `uv run pytest -q`、`uv run ruff check src tests examples` 通过。
- **验证**：`uv run pytest -q`

### Task 9.3 控制流关键动作接入任务事件流

- **任务编号**：T93
- **状态**：已完成（2026-04-05）
- **依赖**：T91
- **文件**：`src/a_control_agent/storage/tasks_store.py`, `src/a_control_agent/api/recovery.py`, `src/a_control_agent/api/approvals.py`, `tests/test_a_control_agent_control_flow.py`, `README.md`, `docs/getting-started.zh-CN.md`
- **可并行**：否
- **验收标准**：
  1. `handoff`、`resume`、`approval_decided` 成功路径会追加到 `task_events.jsonl`；
  2. SSE 快照会暴露上述事件；
  3. 相关控制流测试与全量回归通过。
- **验证**：`uv run pytest -q tests/test_a_control_agent_control_flow.py -k 'handoff_event or resume_event or approval_decided_event'`

### Task 9.4 Watchdog 代理消费任务事件流

- **任务编号**：T94
- **状态**：已完成（2026-04-05）
- **依赖**：T91, T93
- **文件**：`src/watchdog/services/a_client/client.py`, `src/watchdog/api/events_proxy.py`, `src/watchdog/main.py`, `tests/test_watchdog.py`, `README.md`, `docs/getting-started.zh-CN.md`, `docs/openapi/watchdog.json`
- **可并行**：否
- **验收标准**：
  1. Watchdog 提供 `GET /api/v1/watchdog/tasks/{project_id}/events`；
  2. `follow=false` 可返回 SSE 快照，`follow=true` 可透传 runtime 侧事件流；
  3. runtime 侧业务错误与链路错误在 Watchdog 侧语义正确；
  4. 文档与 OpenAPI 同步。
- **验证**：`uv run pytest -q tests/test_watchdog.py`

## 执行结果

- T91：Codex runtime service 已提供基础 SSE 事件流，并复用 `task_events.jsonl` 作为回放来源。
- T92：README、接入文档与 OpenAPI 已同步，回归测试和静态检查通过。
- T93：`handoff`、`resume`、`approval_decided` 已写入任务事件流，SSE 可直接消费这些控制流动作。
- T94：Watchdog 已可代理 runtime 侧任务事件流，Feishu 不必直连 runtime 机器也能读取 SSE。
