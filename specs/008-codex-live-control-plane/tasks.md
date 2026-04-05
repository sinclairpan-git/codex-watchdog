# 任务分解：008-codex-live-control-plane

> 对应规格：`specs/008-codex-live-control-plane/spec.md`

## Batch 1

### Task 8.1 Codex bridge 协议与生命周期

- **任务编号**：T81
- **状态**：已完成（2026-04-04）
- **依赖**：无
- **文件**：`src/a_control_agent/services/codex/protocol.py`, `src/a_control_agent/services/codex/app_server_bridge.py`, `src/a_control_agent/services/codex/client.py`, `src/a_control_agent/main.py`, `src/a_control_agent/settings.py`, `tests/test_codex_app_server_bridge.py`
- **可并行**：否
- **验收标准**：
  1. A-Control-Agent 可按配置启动并关闭本地 Codex bridge；
  2. bridge 支持 `thread/resume`、`thread/read`、`turn/start`、`turn/steer` 的最小调用面；
  3. 断线、启动超时、请求超时有稳定错误返回；
  4. 相关 `pytest` 通过。
- **验证**：`uv run pytest tests/test_codex_app_server_bridge.py -q`

### Task 8.2 审批请求映射与决策回写

- **任务编号**：T82
- **状态**：已完成（2026-04-04）
- **依赖**：T81
- **文件**：`src/a_control_agent/api/approvals.py`, `src/a_control_agent/storage/approvals_store.py`, `src/a_control_agent/storage/tasks_store.py`, `src/a_control_agent/services/codex/app_server_bridge.py`, `tests/test_a_control_agent_control_flow.py`
- **可并行**：否
- **验收标准**：
  1. bridge 收到审批请求后能创建 pending approval 并记录 request id 映射；
  2. 决策接口可把 approve / reject 回写至 live bridge；
  3. 任务 `pending_approval`、`approval_risk`、`phase` 与审计同步更新。
- **验证**：`uv run pytest tests/test_a_control_agent_control_flow.py -q`

### Task 8.3 steer / resume 打进 live session

- **任务编号**：T83
- **状态**：已完成（2026-04-04）
- **依赖**：T82
- **文件**：`src/a_control_agent/api/tasks.py`, `src/a_control_agent/api/recovery.py`, `src/a_control_agent/main.py`, `src/watchdog/services/a_client/client.py`, `tests/test_a_control_agent.py`, `tests/test_m2_watchdog_supervision.py`, `tests/test_a_control_agent_control_flow.py`
- **可并行**：否
- **验收标准**：
  1. `POST steer` 能根据线程活跃状态调用 `turn/start` 或 `turn/steer`；
  2. `POST resume` 能真实恢复 thread，并在传入 `handoff_summary` 时继续注入续跑内容；
  3. 失败路径不会把任务错误标记为成功恢复。
- **验证**：`uv run pytest tests/test_a_control_agent.py tests/test_m2_watchdog_supervision.py tests/test_a_control_agent_control_flow.py -q`

### Task 8.4 文档、OpenAPI 与回归校验

- **任务编号**：T84
- **状态**：已完成（2026-04-04）
- **依赖**：T83
- **文件**：`README.md`, `config/examples/a-agent.env.example`, `docs/getting-started.zh-CN.md`, `docs/openapi/a-control-agent.json`, `tests/test_codex_local_client.py`, `tests/test_a_control_agent_sync_loop.py`
- **可并行**：否
- **验收标准**：
  1. 接入文档明确区分 008 live control plane 与 009 event stream；
  2. OpenAPI 与环境变量示例同步更新；
  3. `uv run python -m ai_sdlc verify constraints`、`uv run pytest`、`uv run ruff check src tests examples` 通过。
- **验证**：`uv run python -m ai_sdlc verify constraints`

## 执行结果

- T81：bridge 已支持 `thread/resume`、`thread/read`、`turn/start`、`turn/steer`，并缓存 thread snapshot / active turn。
- T82：审批请求可登记到 `ApprovalsStore`，决策接口失败时保留 `pending`，成功时回写 live bridge。
- T83：`steer`/`resume` 已真正调用 bridge，`resume` 失败不会再误标任务为 `running`。
- T84：`uv run pytest -q`、`uv run ruff check src tests examples`、`uv run python -m ai_sdlc verify constraints` 已通过。
