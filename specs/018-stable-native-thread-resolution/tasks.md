# 任务分解：018-stable-native-thread-resolution

> 对应规格：`specs/018-stable-native-thread-resolution/spec.md`

## Task 18.1 A-client 与共享 native-thread resolution builder

- **目标**：补齐 `/by-thread` A-client 读取，并在 L2 建立共享 session-read bundle builder。
- **涉及文件**：
  - `src/watchdog/services/a_client/client.py`
  - `src/watchdog/services/session_spine/service.py`
  - `src/watchdog/services/session_spine/replies.py`
  - `tests/test_watchdog_session_spine_contracts.py`
- **完成标准**：
  1. `AControlAgentClient` 存在最小 `/api/v1/tasks/by-thread/{thread_id}` 读取方法；
  2. L2 存在 `build_session_read_bundle_by_native_thread(...)`；
  3. session reply builder 可产出 `intent_code=get_session_by_native_thread`；
  4. 018 明确不推进 session spine schema version。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_contracts.py -k native_thread`

## Task 18.2 Stable API Surface

- **目标**：暴露 canonical native-thread resolution route，并保持稳定错误语义。
- **涉及文件**：
  - `src/watchdog/api/session_spine_queries.py`
  - `tests/test_watchdog_session_spine_api.py`
- **完成标准**：
  1. 存在 `GET /api/v1/watchdog/sessions/by-native-thread/{native_thread_id}`；
  2. route 返回 `ReplyModel(reply_code=session_projection)`；
  3. 路由顺序不会被 `/sessions/{project_id}` 吞掉；
  4. lookup miss / control-link error 继续走稳定 envelope。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_api.py -k native_thread`

## Task 18.3 OpenClaw Adapter Intent

- **目标**：让 adapter 在无 `project_id` 时也能基于 `native_thread_id` 解回稳定 session reply。
- **涉及文件**：
  - `src/watchdog/services/adapters/openclaw/intents.py`
  - `src/watchdog/services/adapters/openclaw/adapter.py`
  - `tests/test_watchdog_openclaw_adapter.py`
  - `tests/integration/test_openclaw_integration_spine.py`
- **完成标准**：
  1. adapter 支持 `get_session_by_native_thread`；
  2. 该 intent 要求 `arguments.native_thread_id`，不要求 `project_id`；
  3. adapter 与 HTTP stable route 复用同一共享 builder；
  4. 对同一 `native_thread_id`，HTTP 与 adapter 返回同源 session reply。
- **验证**：`uv run pytest -q tests/test_watchdog_openclaw_adapter.py tests/integration/test_openclaw_integration_spine.py -k native_thread`

## Task 18.4 Raw 非回归、文档与项目状态收口

- **目标**：锁住 `/by-thread` raw 行为不回归，并同步对外口径。
- **涉及文件**：
  - `tests/test_a_control_agent.py`
  - `README.md`
  - `docs/getting-started.zh-CN.md`
  - `docs/openapi/watchdog.json`
  - `.ai-sdlc/project/config/project-state.yaml`
- **完成标准**：
  1. raw `/api/v1/tasks/by-thread/{thread_id}` 继续工作且基础行为不变；
  2. README 与 getting-started 已写清 stable native-thread resolution vs raw `/by-thread`；
  3. OpenAPI 暴露 018 stable route；
  4. `.ai-sdlc` 推进到 `019`。
- **验证**：`uv run pytest -q tests/test_a_control_agent.py -k by_thread`

## 整体验收

- 调用方在只有 `native_thread_id` 时，已经可以不扫描 session directory、也不直连 raw `/by-thread`，直接得到稳定 `SessionProjection` reply。
- 018 没有新增 reply code、action code、平行 DTO 或 schema bump。
- stable route、adapter intent、raw 非回归与对外文档口径一致。
