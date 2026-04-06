# 任务分解：016-stable-approval-inbox

> 对应规格：`specs/016-stable-approval-inbox/spec.md`
>
> 对应总设计：`docs/architecture/openclaw-codex-watchdog-g0-and-v010-design.md`

## Batch 1

### Task 16.1 Contract delta 与版本推进

- **任务编号**：T161
- **状态**：已完成（2026-04-06 回填）
- **依赖**：无
- **文件**：`src/watchdog/contracts/session_spine/enums.py`, `src/watchdog/contracts/session_spine/versioning.py`, `tests/test_watchdog_session_spine_contracts.py`
- **可并行**：否
- **验收标准**：
  1. 新增 `ReplyCode.APPROVAL_INBOX`；
  2. `SESSION_SPINE_SCHEMA_VERSION` 推进到 `2026-04-05.016`；
  3. 不新增新的审批 DTO。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_contracts.py`

### Task 16.2 共享 approval inbox builder

- **任务编号**：T162
- **状态**：已完成（2026-04-06 回填）
- **依赖**：T161
- **文件**：`src/watchdog/services/session_spine/service.py`, `src/watchdog/services/session_spine/replies.py`, `tests/test_watchdog_session_spine_api.py`, `tests/test_watchdog_openclaw_adapter.py`
- **可并行**：否
- **验收标准**：
  1. 存在共享 approval inbox builder；
  2. 默认仅返回全局 pending approvals；
  3. 可选 `project_id` 过滤生效；
  4. builder 输出稳定 `ReplyModel(reply_code=approval_inbox)`。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_api.py tests/test_watchdog_openclaw_adapter.py -k approval_inbox`

## Batch 2

### Task 16.3 Stable inbox route 与 adapter intent

- **任务编号**：T163
- **状态**：已完成（2026-04-06 回填）
- **依赖**：T162
- **文件**：`src/watchdog/api/session_spine_queries.py`, `src/watchdog/services/adapters/openclaw/intents.py`, `src/watchdog/services/adapters/openclaw/adapter.py`, `tests/test_watchdog_session_spine_api.py`, `tests/test_watchdog_openclaw_adapter.py`, `tests/integration/test_openclaw_integration_spine.py`
- **可并行**：否
- **验收标准**：
  1. 存在 `GET /api/v1/watchdog/approval-inbox`；
  2. adapter 支持 `list_approval_inbox`；
  3. HTTP 与 adapter 复用同一 stable inbox builder；
  4. session 级 `pending-approvals` 与 approve/reject 动作不回归。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_api.py tests/test_watchdog_openclaw_adapter.py tests/integration/test_openclaw_integration_spine.py -k approval`

### Task 16.4 Legacy 非回归、文档与项目状态收口

- **任务编号**：T164
- **状态**：已完成（2026-04-06 回填）
- **依赖**：T163
- **文件**：`tests/test_m3_watchdog_approvals.py`, `README.md`, `docs/getting-started.zh-CN.md`, `docs/openapi/watchdog.json`, `.ai-sdlc/project/config/project-state.yaml`
- **可并行**：是
- **验收标准**：
  1. `/watchdog/approvals` 与 `/decision` legacy proxy 行为不变；
  2. README 与 getting-started 已写清 global inbox vs session queue 的区别；
  3. OpenAPI 暴露 stable inbox route；
  4. `.ai-sdlc` 推进到下一个 work item 序号。
- **验证**：`uv run pytest -q tests/test_m3_watchdog_approvals.py tests/test_watchdog_session_spine_api.py tests/test_watchdog_openclaw_adapter.py`
