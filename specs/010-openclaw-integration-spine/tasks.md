# 任务分解：010-openclaw-integration-spine

> 对应规格：`specs/010-openclaw-integration-spine/spec.md`
>
> 对应总设计：`docs/architecture/openclaw-codex-watchdog-g0-and-v010-design.md`

## Batch 1

### Task 10.1 中立 contract 包与版本语义

- **任务编号**：T101
- **状态**：未开始
- **依赖**：无
- **文件**：`src/watchdog/contracts/session_spine/__init__.py`, `src/watchdog/contracts/session_spine/enums.py`, `src/watchdog/contracts/session_spine/models.py`, `src/watchdog/contracts/session_spine/versioning.py`, `tests/test_watchdog_session_spine_contracts.py`
- **可并行**：否
- **验收标准**：
  1. 存在 `SessionProjection`、`TaskProgressView`、`FactRecord`、`ApprovalProjection`、`WatchdogAction`、`WatchdogActionResult`、`ReplyModel`；
  2. 所有 stable contract 都携带 `contract_version` 与 `schema_version`；
  3. `thread_id` 与 `native_thread_id` 被正式区分；
  4. `reply_code`、`action_code`、`action_status`、`effect`、`session_state`、`activity_phase`、`attention_state` 的受控枚举被冻结；
  5. contract 包中不出现 `openclaw` 渠道语义命名。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_contracts.py`

### Task 10.2 L2 稳定投影层与事实构建

- **任务编号**：T102
- **状态**：未开始
- **依赖**：T101
- **文件**：`src/watchdog/services/session_spine/facts.py`, `src/watchdog/services/session_spine/projection.py`, `src/watchdog/services/status_analyzer/stuck.py`, `src/watchdog/services/a_client/client.py`, `tests/test_watchdog_session_spine_projection.py`
- **可并行**：否
- **验收标准**：
  1. raw task / approval / link state 能稳定映射到 `SessionProjection`、`TaskProgressView`、`FactRecord[]`、`ApprovalProjection[]`；
  2. `why_stuck` 与 `explain_blocker` 所需说明可完全从 `FactRecord` 推导；
  3. pending approval、control link error、context critical、stuck no progress 等关键事实都有稳定 `fact_code`；
  4. L2 不出现 OpenClaw 渠道语义与 adapter 逻辑。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_projection.py`

### Task 10.3 Canonical 动作模型与幂等收据

- **任务编号**：T103
- **状态**：未开始
- **依赖**：T101, T102
- **文件**：`src/watchdog/services/session_spine/actions.py`, `src/watchdog/storage/__init__.py`, `src/watchdog/storage/action_receipts.py`, `tests/test_watchdog_action_idempotency.py`
- **可并行**：否
- **验收标准**：
  1. 存在统一 `WatchdogAction` 执行入口；
  2. `continue_session`、`request_recovery`、`approve_approval`、`reject_approval` 都返回 `WatchdogActionResult`；
  3. `request_recovery` 只返回 `effect=advisory_only` 与 `reply_code=recovery_availability`；
  4. 相同 `(action_code, project_id, approval_id, idempotency_key)` 重试不会重复执行 side effect；
  5. 幂等收据存储位于 Watchdog 自身，不下沉到 adapter。
- **验证**：`uv run pytest -q tests/test_watchdog_action_idempotency.py`

## Batch 2

### Task 10.4 Stable API Surface

- **任务编号**：T104
- **状态**：未开始
- **依赖**：T102, T103
- **文件**：`src/watchdog/api/session_spine_queries.py`, `src/watchdog/api/session_spine_actions.py`, `src/watchdog/main.py`, `tests/test_watchdog_session_spine_api.py`
- **可并行**：否
- **验收标准**：
  1. 提供 `GET /api/v1/watchdog/sessions/{project_id}`；
  2. 提供 `GET /api/v1/watchdog/sessions/{project_id}/progress`；
  3. 提供 `GET /api/v1/watchdog/sessions/{project_id}/pending-approvals`；
  4. 提供 canonical `POST /api/v1/watchdog/actions`；
  5. 若提供 continue / request-recovery / approve / reject 的路径级 alias route，它们必须内部统一转同一 canonical action handler；
  6. read 接口 `data` 返回 `ReplyModel`，write 接口 `data` 返回 `WatchdogActionResult`；
  7. session spine 路由接入不得破坏现有 `progress / evaluate / approvals / recover / events` 这五类 raw / legacy 接口的注册与基础行为兼容。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_api.py`

### Task 10.5 L3 OpenClaw adapter spine

- **任务编号**：T105
- **状态**：未开始
- **依赖**：T104
- **文件**：`src/watchdog/services/adapters/openclaw/__init__.py`, `src/watchdog/services/adapters/openclaw/intents.py`, `src/watchdog/services/adapters/openclaw/reply_model.py`, `src/watchdog/services/adapters/openclaw/adapter.py`, `tests/test_watchdog_openclaw_adapter.py`
- **可并行**：否
- **验收标准**：
  1. adapter 支持完整冻结 intent 集：`get_session`、`get_progress`、`why_stuck`、`explain_blocker`、`list_pending_approvals`、`continue_session`、`request_recovery`、`approve_approval`、`reject_approval`；
  2. adapter 只消费 stable contract / stable API，不直连 A-Control-Agent，不读 raw route，不接 SSE；
  3. adapter 输出统一 `ReplyModel`，且 `reply_code` 正确区分 `stuck_explanation`、`blocker_explanation`、`approval_queue`、`recovery_availability` 等语义；
  4. `why_stuck` 与 `explain_blocker` 必须仅基于 `FactRecord` 与 stable read model 生成 explanation reply，不得新增 raw route 旁路实现；
  5. 未知 intent 返回稳定 `unsupported_intent`；
  6. adapter 不包含飞书或其他渠道运行时代码。
- **验证**：`uv run pytest -q tests/test_watchdog_openclaw_adapter.py`

### Task 10.6 最小闭环集成与文档收口

- **任务编号**：T106
- **状态**：未开始
- **依赖**：T105
- **文件**：`tests/integration/test_openclaw_integration_spine.py`, `README.md`, `docs/getting-started.zh-CN.md`, `docs/openapi/watchdog.json`, `specs/010-openclaw-integration-spine/spec.md`
- **可并行**：否
- **验收标准**：
  1. 最小集成测试覆盖 `continue_session` 成功 / 阻塞 / 链路错误三类路径；
  2. 最小集成测试覆盖 `request_recovery` 的 advisory-only 行为，不触发真实恢复执行；
  3. 最小集成测试覆盖 `approve_approval` 与 `reject_approval`；
  4. legacy `progress / evaluate / approvals / recover / events` 五类接口的注册与基础行为存在显式非回归验证；
  5. 文档明确区分 010 stable contract 与现有 raw / legacy API；
  6. OpenAPI 明确 canonical `POST /api/v1/watchdog/actions` 为主动作面，并标注 alias route 仅为 wrapper；
  7. 文档明确 010 不包含完整实时事件覆盖、常驻 supervisor、全量自动恢复闭环与渠道 runtime。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_contracts.py tests/test_watchdog_session_spine_projection.py tests/test_watchdog_action_idempotency.py tests/test_watchdog_session_spine_api.py tests/test_watchdog_openclaw_adapter.py tests/integration/test_openclaw_integration_spine.py`

## 预期结果

- OpenClaw 获得一套稳定、受控、可版本化的会话监管骨架。
- Watchdog 对外明确区分中立 stable contract 与 raw / legacy API。
- `request_recovery`、`why_stuck`、`explain_blocker` 回到 010 的正式最小闭环，而不是在实现时被静默降级。
- 后续实时流、真实恢复编排、渠道模板都可在不破坏 010 契约层的前提下继续演进。
