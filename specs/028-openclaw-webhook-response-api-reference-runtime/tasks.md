# 任务分解：028-openclaw-webhook-response-api-reference-runtime

> 对应规格：`specs/028-openclaw-webhook-response-api-reference-runtime/spec.md`

## Task 28.1 冻结 OpenClaw webhook / response contract

- **任务编号**：T281
- **状态**：待开始
- **目标**：把 OpenClaw webhook、receipt 与 response API 收敛成 stable contract。
- **涉及文件**：
  - `docs/architecture/openclaw-codex-watchdog-full-product-loop-design.md`
  - `specs/028-openclaw-webhook-response-api-reference-runtime/spec.md`
  - `specs/028-openclaw-webhook-response-api-reference-runtime/plan.md`
  - `specs/028-openclaw-webhook-response-api-reference-runtime/tasks.md`
- **验证**：人工审阅 formal docs 是否与总设计 Section 4 / 5 的 WI-5 边界一致。

## Task 28.2 新增 webhook / response API surface

- **任务编号**：T282
- **状态**：待开始
- **目标**：新增 Watchdog 对 OpenClaw 的 webhook 与响应 API 接口。
- **涉及文件**：
  - `src/watchdog/api/openclaw_callbacks.py`
  - `src/watchdog/api/openclaw_responses.py`
  - `tests/test_openclaw_contracts.py`
- **验证**：`uv run pytest -q tests/test_openclaw_contracts.py`

## Task 28.3 提供最小 reference runtime

- **任务编号**：T283
- **状态**：待开始
- **目标**：提供最小宿主模板，证明 envelope / response contract 可落地。
- **涉及文件**：
  - `examples/openclaw_watchdog_client.py`
  - `examples/openclaw_webhook_runtime.py`
  - `tests/integration/test_openclaw_integration_spine.py`
- **验证**：`uv run pytest -q tests/integration/test_openclaw_integration_spine.py`

## Task 28.4 锁住宿主边界与接入文档

- **任务编号**：T284
- **状态**：待开始
- **目标**：补齐宿主边界、接入指引与最小运维说明。
- **涉及文件**：
  - `README.md`
  - `docs/getting-started.zh-CN.md`
  - `examples/openclaw_webhook_runtime.py`
- **验证**：人工审阅宿主边界是否明确且未引入第二内核。

## 整体验收

- `028` 是完整产品闭环中的 `WI-5`，只负责 OpenClaw 接入 contract 与 reference runtime。
- `028` 完成后，宿主接入不再依赖口头说明。
- `028` 不引入第二套策略引擎、第二套 session spine 或 delivery retry。
