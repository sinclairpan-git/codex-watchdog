# 任务分解：013-stable-action-receipts

> 对应规格：`specs/013-stable-action-receipts/spec.md`
>
> 对应总设计：`docs/architecture/openclaw-codex-watchdog-g0-and-v010-design.md`

## Batch 1

### Task 13.1 稳定 receipt 契约与版本推进

- **任务编号**：T131
- **状态**：已完成（2026-04-06 回填）
- **依赖**：无
- **文件**：`src/watchdog/contracts/session_spine/enums.py`, `src/watchdog/contracts/session_spine/models.py`, `src/watchdog/contracts/session_spine/versioning.py`, `tests/test_watchdog_session_spine_contracts.py`
- **可并行**：否
- **验收标准**：
  1. 存在 `ActionReceiptQuery`；
  2. 存在 `ReplyCode.action_receipt` 与 `ReplyCode.action_receipt_not_found`；
  3. `ReplyModel` 可稳定承载 `action_result`；
  4. session spine `schema_version` 明确推进到 `2026-04-05.013`。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_contracts.py`

### Task 13.2 L2 receipt lookup 内核

- **任务编号**：T132
- **状态**：已完成（2026-04-06 回填）
- **依赖**：T131
- **文件**：`src/watchdog/storage/action_receipts.py`, `src/watchdog/services/session_spine/receipts.py`, `tests/test_watchdog_action_receipts.py`
- **可并行**：否
- **验收标准**：
  1. receipt 查询复用既有幂等 key 语义；
  2. receipt 命中时返回稳定 `action_receipt` reply；
  3. receipt 缺失时返回稳定 `action_receipt_not_found` reply；
  4. lookup 过程中不访问 A-Control-Agent，不执行 side effect。
- **验证**：`uv run pytest -q tests/test_watchdog_action_receipts.py`

### Task 13.3 Stable Receipt API Surface

- **任务编号**：T133
- **状态**：已完成（2026-04-06 回填）
- **依赖**：T132
- **文件**：`src/watchdog/api/session_spine_queries.py`, `tests/test_watchdog_session_spine_api.py`
- **可并行**：否
- **验收标准**：
  1. 存在 canonical route `GET /api/v1/watchdog/action-receipts`；
  2. 存在 alias route `GET /api/v1/watchdog/sessions/{project_id}/action-receipts/{action_code}/{idempotency_key}`；
  3. canonical 与 alias 对同一 lookup 返回相同 payload；
  4. receipt 查询不会重新执行动作。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_api.py`

## Batch 2

### Task 13.4 OpenClaw adapter 接入 receipt 查询

- **任务编号**：T134
- **状态**：已完成（2026-04-06 回填）
- **依赖**：T133
- **文件**：`src/watchdog/services/adapters/openclaw/intents.py`, `src/watchdog/services/adapters/openclaw/adapter.py`, `src/watchdog/services/adapters/openclaw/reply_model.py`, `tests/test_watchdog_openclaw_adapter.py`
- **可并行**：否
- **验收标准**：
  1. adapter 支持 `get_action_receipt` intent；
  2. adapter 返回 `ReplyModel(reply_code=action_receipt|action_receipt_not_found)`；
  3. adapter 不直读本地 receipt 文件；
  4. adapter 不重新执行对应动作。
- **验证**：`uv run pytest -q tests/test_watchdog_openclaw_adapter.py`

### Task 13.5 文档与 OpenAPI 收口

- **任务编号**：T135
- **状态**：已完成（2026-04-06 回填）
- **依赖**：T133
- **文件**：`README.md`, `docs/getting-started.zh-CN.md`, `docs/openapi/watchdog.json`, `specs/013-stable-action-receipts/spec.md`
- **可并行**：是
- **验收标准**：
  1. 文档明确 stable receipt query surface 与 canonical route；
  2. 文档明确 receipt 查询不会重新执行动作；
  3. OpenAPI 暴露 canonical 与 alias receipt query route；
  4. 文档明确该能力建立在既有幂等收据存储之上。
- **验证**：人工核对 + `rg -n "action-receipts|action_receipt|action_receipt_not_found|get_action_receipt" README.md docs/getting-started.zh-CN.md docs/openapi/watchdog.json`

### Task 13.6 最小集成与非回归收口

- **任务编号**：T136
- **状态**：已完成（2026-04-06 回填）
- **依赖**：T134, T135
- **文件**：`tests/integration/test_openclaw_integration_spine.py`, `tests/test_watchdog_action_idempotency.py`
- **可并行**：否
- **验收标准**：
  1. stable action 执行后可通过 receipt query 读取相同结果；
  2. `execute_recovery` 的 receipt 可稳定查询；
  3. receipt 查询不会新增 side effect；
  4. 010-012 既有 stable action/write 行为不回归。
- **验证**：`uv run pytest -q tests/integration/test_openclaw_integration_spine.py tests/test_watchdog_action_idempotency.py`
