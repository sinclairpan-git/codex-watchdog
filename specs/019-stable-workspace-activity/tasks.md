# 任务分解：019-stable-workspace-activity

> 对应规格：`specs/019-stable-workspace-activity/spec.md`

## Task 19.1 Contract 与版本语义

- **目标**：冻结 `WorkspaceActivityView`、reply code 与 019 schema version。
- **涉及文件**：
  - `src/watchdog/contracts/session_spine/enums.py`
  - `src/watchdog/contracts/session_spine/models.py`
  - `src/watchdog/contracts/session_spine/versioning.py`
  - `tests/test_watchdog_session_spine_contracts.py`
- **完成标准**：
  1. 存在 `WorkspaceActivityView`；
  2. `ReplyModel` 挂载 `workspace_activity`；
  3. `ReplyCode` 存在 `workspace_activity_view`；
  4. `SESSION_SPINE_SCHEMA_VERSION` 推进到 `2026-04-05.019`。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_contracts.py -k workspace_activity`

## Task 19.2 A-client 与共享 L2 builder

- **目标**：收拢 raw `/workspace-activity` 读取，并在 L2 形成共享稳定 builder。
- **涉及文件**：
  - `src/watchdog/services/a_client/client.py`
  - `src/watchdog/services/session_spine/service.py`
  - `src/watchdog/services/session_spine/projection.py`
  - `src/watchdog/services/session_spine/replies.py`
  - `tests/test_watchdog_session_spine_contracts.py`
- **完成标准**：
  1. `AControlAgentClient` 存在 `/api/v1/tasks/{project_id}/workspace-activity` 读取方法；
  2. L2 存在 workspace-activity read bundle；
  3. `WorkspaceActivityView` 由共享 builder 产出，而不是在 API/adapter 临时拼装；
  4. `recent_minutes` 默认 15，可显式透传。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_contracts.py -k workspace_activity`

## Task 19.3 Stable API Surface

- **目标**：暴露 canonical stable workspace activity route。
- **涉及文件**：
  - `src/watchdog/api/session_spine_queries.py`
  - `tests/test_watchdog_session_spine_api.py`
- **完成标准**：
  1. 存在 `GET /api/v1/watchdog/sessions/{project_id}/workspace-activity`；
  2. route 返回 `ReplyModel(reply_code=workspace_activity_view)`；
  3. `recent_minutes` 透传有效；
  4. 上游 miss / control-link error 继续走稳定 envelope。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_api.py -k workspace_activity`

## Task 19.4 OpenClaw Adapter Intent

- **目标**：让 OpenClaw 通过 stable contract 消费 workspace activity。
- **涉及文件**：
  - `src/watchdog/services/adapters/openclaw/intents.py`
  - `src/watchdog/services/adapters/openclaw/adapter.py`
  - `src/watchdog/services/adapters/openclaw/reply_model.py`
  - `tests/test_watchdog_openclaw_adapter.py`
  - `tests/integration/test_openclaw_integration_spine.py`
- **完成标准**：
  1. adapter 支持 `get_workspace_activity`；
  2. 该 intent 要求 `project_id`，`arguments.recent_minutes` 可选；
  3. adapter 与 HTTP stable route 复用同一 reply builder；
  4. OpenClaw 可稳定消费 `workspace_activity_view`。
- **验证**：`uv run pytest -q tests/test_watchdog_openclaw_adapter.py tests/integration/test_openclaw_integration_spine.py -k workspace_activity`

## Task 19.5 Raw 非回归、文档与项目状态收口

- **目标**：锁住 raw `/workspace-activity` 不回归，并同步对外口径。
- **涉及文件**：
  - `tests/test_a_control_agent.py`
  - `README.md`
  - `docs/getting-started.zh-CN.md`
  - `docs/openapi/watchdog.json`
  - `.ai-sdlc/project/config/project-state.yaml`
- **完成标准**：
  1. raw `/api/v1/tasks/{project_id}/workspace-activity` 继续工作；
  2. README 与 getting-started 已写清 stable workspace activity vs raw route；
  3. OpenAPI 暴露 019 stable route；
  4. `.ai-sdlc` 推进到 `020`。
- **验证**：`uv run pytest -q tests/test_a_control_agent.py -k workspace_activity`

## 整体验收

- 调用方已经可以通过 stable contract 获取 workspace activity，而不必绑定 raw A payload。
- 019 引入了独立 `WorkspaceActivityView` 与 `workspace_activity_view` reply code，并完成 schema bump。
- stable route、adapter intent、raw 非回归与对外文档口径一致。
