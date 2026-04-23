# 任务分解：023-codex-client-routing-template

> 对应规格：`specs/023-codex-client-routing-template/spec.md`

## Task 23.1 冻结接入边界与模板输入项

- **任务编号**：T231
- **状态**：已完成（2026-04-06 手工补齐）
- **目标**：把真实 Codex 客户端、Feishu 路由模板与外部前提清单收敛到 formal docs。
- **涉及文件**：
  - `specs/023-codex-client-routing-template/spec.md`
  - `specs/023-codex-client-routing-template/plan.md`
  - `specs/023-codex-client-routing-template/tasks.md`
  - `specs/023-codex-client-routing-template/task-execution-log.md`
  - `docs/getting-started.zh-CN.md`
- **完成标准**：
  1. 023 scope 明确限定为“真实 Codex 客户端接缝 + Feishu 路由模板”；
  2. 已列出网络地址、Token 策略、Codex/Feishu 接口样例等外部前提；
  3. 已明确说明不覆盖飞书/Feishu 运行时代码。
  4. 已记录 `workitem init` 在当前环境中的模板路径故障与手工补齐原因。
- **验证**：人工审阅 formal docs、`task-execution-log.md` 与 getting-started 是否边界一致。

## Task 23.2 收敛真实 Codex client / bridge 接缝

- **任务编号**：T232
- **状态**：已完成（2026-04-06）
- **目标**：把真实 Codex 客户端能力明确挂到既有 bridge / transport / protocol 上，并保持 fallback 可用。
- **涉及文件**：
  - `src/a_control_agent/services/codex/client.py`
  - `src/a_control_agent/services/codex/app_server_bridge.py`
  - `src/a_control_agent/services/codex/protocol.py`
  - `src/a_control_agent/services/codex/stdio_transport.py`
  - `tests/test_codex_local_client.py`
  - `tests/test_codex_app_server_bridge.py`
- **完成标准**：
  1. 真实 bridge 能力边界明确覆盖 `thread/read`、`turn/start`、`turn/steer` 与审批回写；
  2. `LocalCodexClient` / `NoOpCodexClient` 继续保留且降级语义稳定；
  3. 不新增第二套并行控制链路。
- **验证**：`uv run pytest -q tests/test_codex_local_client.py tests/test_codex_app_server_bridge.py`

## Task 23.3 接 Codex runtime service API 与审计语义

- **任务编号**：T233
- **状态**：已完成（2026-04-06）
- **目标**：把 tasks / recovery / approvals API 显式绑定到新的 client / bridge 配置，并统一错误与审计。
- **涉及文件**：
  - `src/a_control_agent/main.py`
  - `src/a_control_agent/api/tasks.py`
  - `src/a_control_agent/api/recovery.py`
  - `src/a_control_agent/api/approvals.py`
  - `tests/test_a_control_agent.py`
- **完成标准**：
  1. 相关 API 都通过同一 bridge/client seam 与 Codex 交互；
  2. bridge 不可用时返回稳定降级结果，而不是 500 或静默失败；
  3. 审批请求登记、审批回写与审计日志保持一致。
- **验证**：`uv run pytest -q tests/test_a_control_agent.py`

## Task 23.4 交付 Feishu 路由模板与接入说明

- **任务编号**：T234
- **状态**：已完成（2026-04-06）
- **目标**：提供可直接给 Feishu 集成方复用的查询/控制/审批路由模板与环境变量说明。
- **涉及文件**：
  - `examples/codex_watchdog_client.py`
  - `README.md`
  - `docs/getting-started.zh-CN.md`
  - `config/examples/watchdog.env.example`
  - `tests/integration/test_feishu_integration_spine.py`
- **完成标准**：
  1. 模板至少覆盖“查询进展 / 查询卡点 / 继续 / 审批”四类消息；
  2. 已明确 `WATCHDOG_BASE_URL`、`WATCHDOG_API_TOKEN` 与 `project_id` 路由策略；
  3. 示例与文档明确说明本仓库不包含飞书/Feishu runtime，但已提供可复用模板。
- **验证**：`uv run pytest -q tests/integration/test_feishu_integration_spine.py`

## 整体验收

- 当前仓库已经从“023 前仅有 stable API 与最小 HTTP 示例”推进到“有真实 Codex 客户端接缝、有 Feishu 路由模板、可直接指导现场集成”。
- 023 不改写 010-022 已冻结的 stable contract，只补真实接入层与模板化配置。
- `.ai-sdlc` 顶层 state、checkpoint 与 formal docs 已统一指向 `023-codex-client-routing-template`。
