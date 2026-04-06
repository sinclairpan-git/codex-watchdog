# 任务分解：012-stable-recovery-execution

> 对应规格：`specs/012-stable-recovery-execution/spec.md`
>
> 对应总设计：`docs/architecture/openclaw-codex-watchdog-g0-and-v010-design.md`

## Batch 1

### Task 12.1 稳定恢复动作契约与版本推进

- **任务编号**：T121
- **状态**：已完成（2026-04-06 回填）
- **依赖**：无
- **文件**：`src/watchdog/contracts/session_spine/enums.py`, `src/watchdog/contracts/session_spine/versioning.py`, `tests/test_watchdog_session_spine_contracts.py`
- **可并行**：否
- **验收标准**：
  1. 存在 `ActionCode.execute_recovery`；
  2. 存在 `ReplyCode.recovery_execution_result`；
  3. 存在 `Effect.handoff_triggered` 与 `Effect.handoff_and_resume`；
  4. session spine `schema_version` 明确推进到 `2026-04-05.012`；
  5. `request_recovery` 的 advisory-only 枚举值未被改写。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_contracts.py`

### Task 12.2 L2 recovery execution 内核

- **任务编号**：T122
- **状态**：已完成（2026-04-06 回填）
- **依赖**：T121
- **文件**：`src/watchdog/services/session_spine/recovery.py`, `src/watchdog/services/a_client/client.py`, `src/watchdog/services/session_spine/actions.py`, `tests/test_watchdog_recovery_execution.py`, `tests/test_watchdog_action_idempotency.py`
- **可并行**：否
- **验收标准**：
  1. 非 critical task 返回稳定 noop 结果；
  2. critical task 触发 handoff 并返回 `effect=handoff_triggered`；
  3. `recover_auto_resume=true` 时可返回 `effect=handoff_and_resume`；
  4. resume 失败时保留 handoff 成功语义，并返回稳定降级 message；
  5. 相同幂等键重试不会重复触发 handoff / resume。
- **验证**：`uv run pytest -q tests/test_watchdog_recovery_execution.py tests/test_watchdog_action_idempotency.py`

### Task 12.3 Stable Action API 与 legacy recover 非回归

- **任务编号**：T123
- **状态**：已完成（2026-04-06 回填）
- **依赖**：T122
- **文件**：`src/watchdog/api/session_spine_actions.py`, `src/watchdog/api/recover_watchdog.py`, `src/watchdog/main.py`, `tests/test_watchdog_session_spine_api.py`, `tests/test_m4_watchdog_recover.py`
- **可并行**：否
- **验收标准**：
  1. `POST /api/v1/watchdog/actions` 支持 `action_code=execute_recovery`；
  2. 存在 alias route `/api/v1/watchdog/sessions/{project_id}/actions/execute-recovery`；
  3. alias route 与 canonical route 返回同一 `WatchdogActionResult`；
  4. legacy `/watchdog/tasks/{project_id}/recover` 继续输出 `action=noop|handoff_triggered|handoff_and_resume`；
  5. legacy 路由不会绕开共享 recovery execution 内核。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_api.py tests/test_m4_watchdog_recover.py`

## Batch 2

### Task 12.4 OpenClaw adapter 接入真实恢复动作

- **任务编号**：T124
- **状态**：已完成（2026-04-06 回填）
- **依赖**：T123
- **文件**：`src/watchdog/services/adapters/openclaw/intents.py`, `src/watchdog/services/adapters/openclaw/adapter.py`, `src/watchdog/services/adapters/openclaw/reply_model.py`, `tests/test_watchdog_openclaw_adapter.py`
- **可并行**：否
- **验收标准**：
  1. adapter 支持 `execute_recovery` intent；
  2. adapter 将 stable action result 映射为 `ReplyModel(reply_code=recovery_execution_result)`；
  3. adapter 不直连 legacy recover route；
  4. `request_recovery` 仍返回 advisory-only reply，不被新动作覆盖。
- **验证**：`uv run pytest -q tests/test_watchdog_openclaw_adapter.py`

### Task 12.5 文档与 OpenAPI 收口

- **任务编号**：T125
- **状态**：已完成（2026-04-06 回填）
- **依赖**：T123
- **文件**：`README.md`, `docs/getting-started.zh-CN.md`, `docs/openapi/watchdog.json`, `specs/012-stable-recovery-execution/spec.md`
- **可并行**：是
- **验收标准**：
  1. 文档明确 `request_recovery` 与 `execute_recovery` 的分工；
  2. 文档明确 canonical stable route 仍是 `POST /api/v1/watchdog/actions`；
  3. OpenAPI 暴露 alias route `/sessions/{project_id}/actions/execute-recovery`；
  4. 文档明确 legacy `/watchdog/tasks/{project_id}/recover` 仍存在但只是兼容面。
- **验证**：人工核对 + `rg -n "execute_recovery|request_recovery|/watchdog/actions|/watchdog/tasks/\\{project_id\\}/recover" README.md docs/getting-started.zh-CN.md docs/openapi/watchdog.json`

### Task 12.6 最小集成与 legacy 非回归收口

- **任务编号**：T126
- **状态**：已完成（2026-04-06 回填）
- **依赖**：T124, T125
- **文件**：`tests/integration/test_stable_recovery_execution.py`, `tests/integration/test_openclaw_integration_spine.py`
- **可并行**：否
- **验收标准**：
  1. fake A client 可走通 `critical -> handoff`；
  2. fake A client 可走通 `critical -> handoff_and_resume`；
  3. OpenClaw adapter 的 `execute_recovery` 与 stable API 结果一致；
  4. `request_recovery` 仍保持 advisory-only；
  5. legacy recover 与 stable `execute_recovery` 并存，不互相覆盖。
- **验证**：`uv run pytest -q tests/integration/test_openclaw_integration_spine.py tests/integration/test_stable_recovery_execution.py`

## 预期结果

- Watchdog 对外同时具备 advisory-only recovery 与真实 recovery execution 两类稳定动作。
- OpenClaw 能在不依赖 legacy recover payload 的前提下执行最小恢复闭环。
- 012 在保持 legacy 非回归的同时，把真实恢复执行拉回 canonical `WatchdogAction -> WatchdogActionResult` 契约。
