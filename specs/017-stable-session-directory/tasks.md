# 任务分解：017-stable-session-directory

> 对应规格：`specs/017-stable-session-directory/spec.md`
>
> 对应总设计：`docs/architecture/openclaw-codex-watchdog-g0-and-v010-design.md`

## Batch 1

### Task 17.1 Contract delta 与版本推进

- **任务编号**：T171
- **状态**：已完成（2026-04-06 回填）
- **依赖**：无
- **文件**：`src/watchdog/contracts/session_spine/enums.py`, `src/watchdog/contracts/session_spine/models.py`, `src/watchdog/contracts/session_spine/versioning.py`, `tests/test_watchdog_session_spine_contracts.py`
- **可并行**：否
- **验收标准**：
  1. 新增 `ReplyCode.SESSION_DIRECTORY`；
  2. `ReplyModel` 新增稳定 `sessions` 字段；
  3. `SESSION_SPINE_SCHEMA_VERSION` 推进到 `2026-04-05.017`；
  4. 不新增新的 session DTO。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_contracts.py`

### Task 17.2 共享 session directory builder

- **任务编号**：T172
- **状态**：已完成（2026-04-06 回填）
- **依赖**：T171
- **文件**：`src/watchdog/services/session_spine/service.py`, `src/watchdog/services/session_spine/projection.py`, `src/watchdog/services/session_spine/replies.py`, `tests/test_watchdog_session_spine_api.py`, `tests/test_watchdog_openclaw_adapter.py`
- **可并行**：否
- **验收标准**：
  1. 存在共享 session directory builder；
  2. 能基于 raw task list 与 pending approvals 构建 `SessionProjection[]`；
  3. `pending_approval_count` 与 `available_intents` 与单 session 口径一致；
  4. builder 输出稳定 `ReplyModel(reply_code=session_directory)`。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_api.py tests/test_watchdog_openclaw_adapter.py -k session_directory`

## Batch 2

### Task 17.3 Stable directory route 与 adapter intent

- **任务编号**：T173
- **状态**：已完成（2026-04-06 回填）
- **依赖**：T172
- **文件**：`src/watchdog/api/session_spine_queries.py`, `src/watchdog/services/adapters/openclaw/intents.py`, `src/watchdog/services/adapters/openclaw/adapter.py`, `src/watchdog/services/adapters/openclaw/reply_model.py`, `tests/test_watchdog_session_spine_api.py`, `tests/test_watchdog_openclaw_adapter.py`, `tests/integration/test_openclaw_integration_spine.py`
- **可并行**：否
- **验收标准**：
  1. 存在 `GET /api/v1/watchdog/sessions`；
  2. adapter 支持 `list_sessions`；
  3. HTTP 与 adapter 复用同一 stable directory builder；
  4. 单 session route 与既有 actions 不回归。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_api.py tests/test_watchdog_openclaw_adapter.py tests/integration/test_openclaw_integration_spine.py -k session`

### Task 17.4 Legacy 非回归、文档与项目状态收口

- **任务编号**：T174
- **状态**：已完成（2026-04-06 回填）
- **依赖**：T173
- **文件**：`tests/test_a_control_agent.py`, `README.md`, `docs/getting-started.zh-CN.md`, `docs/openapi/watchdog.json`, `.ai-sdlc/project/config/project-state.yaml`
- **可并行**：是
- **验收标准**：
  1. A-Control-Agent raw `/api/v1/tasks` 行为不变；
  2. README 与 getting-started 已写清 session directory vs single-session route vs raw tasks 的区别；
  3. OpenAPI 暴露 stable directory route；
  4. `.ai-sdlc` 推进到下一个 work item 序号。
- **验证**：`uv run pytest -q tests/test_a_control_agent.py tests/test_watchdog_session_spine_api.py tests/test_watchdog_openclaw_adapter.py tests/integration/test_openclaw_integration_spine.py`
