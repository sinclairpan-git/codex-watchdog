# 任务分解：011-stable-session-events

> 对应规格：`specs/011-stable-session-events/spec.md`
>
> 对应总设计：`docs/architecture/openclaw-codex-watchdog-g0-and-v010-design.md`

## Batch 1

### Task 11.1 稳定事件契约与版本语义

- **任务编号**：T111
- **状态**：未开始
- **依赖**：无
- **文件**：`src/watchdog/contracts/session_spine/enums.py`, `src/watchdog/contracts/session_spine/models.py`, `src/watchdog/contracts/session_spine/versioning.py`, `src/watchdog/contracts/session_spine/__init__.py`, `tests/test_watchdog_session_events_contracts.py`
- **可并行**：否
- **验收标准**：
  1. 存在 `SessionEvent`、`EventCode`、`EventKind`；
  2. `SessionEvent` 携带独立事件 `contract_version` 与 `schema_version`；
  3. `thread_id` 与 `native_thread_id` 继续正式区分；
  4. 事件 contract 不复用 raw `event_type` / `payload_json` 作为稳定字段；
  5. contract 命名中不出现 `openclaw` 运行时语义。
- **验证**：`uv run pytest -q tests/test_watchdog_session_events_contracts.py`

### Task 11.2 L2 事件投影与 SSE codec

- **任务编号**：T112
- **状态**：未开始
- **依赖**：T111
- **文件**：`src/watchdog/services/session_spine/events.py`, `tests/test_watchdog_session_events_projection.py`
- **可并行**：否
- **验收标准**：
  1. raw `task_created`、`native_thread_registered`、`steer`、`handoff`、`resume`、`approval_decided` 能稳定映射到受控 `event_code`；
  2. 未知 raw event 会退化为 `session_updated`；
  3. SSE snapshot body 能被 parse 成多条 stable event；
  4. 流式 text chunk 能正确拼块后编码成 stable SSE；
  5. stable output 不暴露 raw `payload_json` 与 raw `event_type`。
- **验证**：`uv run pytest -q tests/test_watchdog_session_events_projection.py`

### Task 11.3 Stable Event API Surface

- **任务编号**：T113
- **状态**：未开始
- **依赖**：T112
- **文件**：`src/watchdog/api/session_spine_events.py`, `src/watchdog/main.py`, `tests/test_watchdog_session_events_api.py`
- **可并行**：否
- **验收标准**：
  1. 提供 `GET /api/v1/watchdog/sessions/{project_id}/events`；
  2. 支持 `follow=true|false` 与 `poll_interval`；
  3. 成功时输出 `text/event-stream`，`event:` 行使用稳定 `event_code`；
  4. upstream 失败时继续返回统一错误 envelope；
  5. `/api/v1/watchdog/tasks/{project_id}/events` 的 raw pass-through 行为不被破坏。
- **验证**：`uv run pytest -q tests/test_watchdog_session_events_api.py tests/test_watchdog.py`

## Batch 2

### Task 11.4 OpenClaw 只读事件 adapter

- **任务编号**：T114
- **状态**：未开始
- **依赖**：T113
- **文件**：`src/watchdog/services/adapters/openclaw/adapter.py`, `tests/test_watchdog_openclaw_adapter.py`
- **可并行**：否
- **验收标准**：
  1. adapter 提供 stable event snapshot / stream 消费入口；
  2. adapter 只消费 `SessionEvent`，不读取 raw proxy route；
  3. adapter 不把 `SessionEvent` 伪装成 `ReplyModel`；
  4. adapter 不合成动作回执事件。
- **验证**：`uv run pytest -q tests/test_watchdog_openclaw_adapter.py`

### Task 11.5 文档与 OpenAPI 收口

- **任务编号**：T115
- **状态**：未开始
- **依赖**：T113
- **文件**：`README.md`, `docs/getting-started.zh-CN.md`, `docs/openapi/watchdog.json`, `specs/011-stable-session-events/spec.md`
- **可并行**：是
- **验收标准**：
  1. 文档明确 stable route 与 raw legacy route 的区别；
  2. 文档明确 011 只做 read-only stable event stream；
  3. OpenAPI 标注 stable route 返回 `text/event-stream`；
  4. 文档明确 011 不包含 action receipt events。
- **验证**：人工核对 + `rg -n "stable event|session event|/watchdog/sessions/\\{project_id\\}/events|legacy" README.md docs/getting-started.zh-CN.md docs/openapi/watchdog.json`

### Task 11.6 最小集成与非回归

- **任务编号**：T116
- **状态**：未开始
- **依赖**：T114, T115
- **文件**：`tests/integration/test_stable_session_events.py`
- **可并行**：否
- **验收标准**：
  1. stable snapshot 可端到端返回稳定 `SessionEvent`；
  2. stable follow stream 可端到端输出连续 `SessionEvent`；
  3. OpenClaw adapter snapshot / stream 行为与 stable route 一致；
  4. raw `/watchdog/tasks/{project_id}/events` 与 stable `/watchdog/sessions/{project_id}/events` 可并存；
  5. action receipt 不会出现在 011 stable event stream 中。
- **验证**：`uv run pytest -q tests/test_watchdog_session_events_contracts.py tests/test_watchdog_session_events_projection.py tests/test_watchdog_session_events_api.py tests/test_watchdog_openclaw_adapter.py tests/integration/test_stable_session_events.py`

## 预期结果

- OpenClaw 与其他上层调用方获得独立于 raw SSE 的稳定 session event 面。
- Watchdog 对外明确区分 stable event surface 与 legacy raw proxy。
- 011 在不引入动作回执融合、cursor/backfill redesign、WebSocket 的前提下，为后续实时事件演进保留干净接缝。
