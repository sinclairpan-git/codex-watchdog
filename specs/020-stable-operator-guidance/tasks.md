# 任务分解：020-stable-operator-guidance

> 对应规格：`specs/020-stable-operator-guidance/spec.md`

## Task 20.1 Contract 与版本语义

- **任务编号**：T201
- **状态**：已完成（2026-04-06 回填）
- **目标**：冻结 stable operator-guidance action code 与 020 schema version。
- **涉及文件**：
  - `src/watchdog/contracts/session_spine/enums.py`
  - `src/watchdog/contracts/session_spine/versioning.py`
  - `tests/test_watchdog_session_spine_contracts.py`
- **完成标准**：
  1. 存在 `ActionCode.POST_OPERATOR_GUIDANCE`；
  2. `SESSION_SPINE_SCHEMA_VERSION` 推进到 `2026-04-05.020`；
  3. 文档明确 operator guidance 仍走 canonical `WatchdogAction -> WatchdogActionResult`。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_contracts.py -k operator_guidance`

## Task 20.2 L2 动作执行与幂等

- **任务编号**：T202
- **状态**：已完成（2026-04-06 回填）
- **目标**：在统一 action executor 中落地 operator guidance。
- **涉及文件**：
  - `src/watchdog/services/session_spine/actions.py`
  - `tests/test_watchdog_action_idempotency.py`
- **完成标准**：
  1. `execute_watchdog_action(...)` 支持 `post_operator_guidance`；
  2. 复用既有 `post_steer(...)`，不新增平行执行器；
  3. `arguments.message` 必填，`reason_code` 默认 `operator_guidance`，`stuck_level` 校验为 `0..4`；
  4. 相同 `idempotency_key` 只会下发一次 steer。
- **验证**：`uv run pytest -q tests/test_watchdog_action_idempotency.py -k operator_guidance`

## Task 20.3 Stable API Surface

- **任务编号**：T203
- **状态**：已完成（2026-04-06 回填）
- **目标**：暴露 operator-guidance alias route，并保持 canonical route 为主。
- **涉及文件**：
  - `src/watchdog/api/session_spine_actions.py`
  - `tests/test_watchdog_session_spine_api.py`
- **完成标准**：
  1. 存在 `POST /api/v1/watchdog/sessions/{project_id}/actions/post-guidance`；
  2. alias route 只做 payload 映射并复用 canonical handler；
  3. alias route 支持 top-level `message / reason_code / stuck_level`；
  4. canonical 与 alias 返回同源 `WatchdogActionResult`。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_api.py -k operator_guidance`

## Task 20.4 OpenClaw Adapter Intent

- **任务编号**：T204
- **状态**：已完成（2026-04-06 回填）
- **目标**：让 OpenClaw 通过 stable contract 提交 operator guidance。
- **涉及文件**：
  - `src/watchdog/services/adapters/openclaw/intents.py`
  - `src/watchdog/services/adapters/openclaw/adapter.py`
  - `tests/test_watchdog_openclaw_adapter.py`
  - `tests/integration/test_openclaw_integration_spine.py`
- **完成标准**：
  1. adapter 支持 `post_operator_guidance`；
  2. 该 intent 映射到 `ActionCode.POST_OPERATOR_GUIDANCE`；
  3. adapter 与 HTTP canonical/alias 复用同一 action executor；
  4. OpenClaw 可稳定消费 `ReplyModel(reply_code=action_result)`。
- **验证**：`uv run pytest -q tests/test_watchdog_openclaw_adapter.py tests/integration/test_openclaw_integration_spine.py -k operator_guidance`

## Task 20.5 Legacy 非回归、文档与项目状态收口

- **任务编号**：T205
- **状态**：已完成（2026-04-06 回填）
- **目标**：锁住 raw `/steer` 不回归，并同步对外口径。
- **涉及文件**：
  - `tests/test_m2_steer.py`
  - `README.md`
  - `docs/getting-started.zh-CN.md`
  - `docs/openapi/watchdog.json`
  - `.ai-sdlc/project/config/project-state.yaml`
- **完成标准**：
  1. raw `/api/v1/tasks/{project_id}/steer` 继续工作；
  2. README 与 getting-started 已写清 stable operator guidance vs raw steer；
  3. OpenAPI 暴露 020 alias route 与 canonical action 扩展；
  4. `.ai-sdlc` 推进到 `021`。
- **验证**：`uv run pytest -q tests/test_m2_steer.py`

## 整体验收

- 调用方已经可以通过 stable `WatchdogAction(action_code=post_operator_guidance)` 提交人工指导，而不必绑定 raw `/steer`。
- canonical route、alias route 与 OpenClaw adapter 共享同一稳定结果模型与幂等语义。
- 020 只补 stable operator-guidance seam，不改变既有 recovery / supervision / approvals / events contract。
- raw `/api/v1/tasks/{project_id}/steer` 继续存在，并有显式非回归覆盖。
