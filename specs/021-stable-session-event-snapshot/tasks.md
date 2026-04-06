# 任务分解：021-stable-session-event-snapshot

> 对应规格：`specs/021-stable-session-event-snapshot/spec.md`

## Task 21.1 Contract 与版本语义

- **任务编号**：T211
- **状态**：已完成（2026-04-06 回填）
- **目标**：冻结 stable JSON event snapshot reply contract 与 021 schema version。
- **涉及文件**：
  - `src/watchdog/contracts/session_spine/enums.py`
  - `src/watchdog/contracts/session_spine/models.py`
  - `src/watchdog/contracts/session_spine/versioning.py`
  - `tests/test_watchdog_session_spine_contracts.py`
- **完成标准**：
  1. 存在 `ReplyKind.EVENTS`；
  2. 存在 `ReplyCode.SESSION_EVENT_SNAPSHOT`；
  3. `ReplyModel` 暴露 `events` 字段；
  4. `SESSION_SPINE_SCHEMA_VERSION` 推进到 `2026-04-05.021`；
  5. `SESSION_EVENTS_SCHEMA_VERSION` 仍保持 `2026-04-05.011`。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_contracts.py -k event_snapshot`

## Task 21.2 L2 Reply Builder

- **任务编号**：T212
- **状态**：已完成（2026-04-06 回填）
- **目标**：把稳定 `SessionEvent[]` 收敛为统一 JSON snapshot reply。
- **涉及文件**：
  - `src/watchdog/services/session_spine/replies.py`
  - `tests/test_watchdog_session_spine_contracts.py`
- **完成标准**：
  1. 存在 `build_session_event_snapshot_reply(...)`；
  2. builder 输入是既有 `SessionEvent[]`，不重新解析 raw SSE；
  3. 输出 `ReplyModel(reply_code=session_event_snapshot, events=...)`。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_contracts.py -k session_event_snapshot`

## Task 21.3 Stable API Surface

- **任务编号**：T213
- **状态**：已完成（2026-04-06 回填）
- **目标**：暴露 canonical stable JSON event snapshot route。
- **涉及文件**：
  - `src/watchdog/api/session_spine_queries.py`
  - `tests/test_watchdog_session_spine_api.py`
  - `tests/test_watchdog_session_events_api.py`
- **完成标准**：
  1. 存在 `GET /api/v1/watchdog/sessions/{project_id}/event-snapshot`；
  2. route 复用既有 `list_session_events(...)` 投影；
  3. route 返回稳定 `ReplyModel(events=SessionEvent[])`；
  4. 011 的 `GET /api/v1/watchdog/sessions/{project_id}/events` 不回归。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_api.py tests/test_watchdog_session_events_api.py -k event`

## Task 21.4 OpenClaw Adapter Intent

- **任务编号**：T214
- **状态**：已完成（2026-04-06 回填）
- **目标**：让 OpenClaw 通过主 `intent -> ReplyModel` 闭环消费事件快照。
- **涉及文件**：
  - `src/watchdog/services/adapters/openclaw/intents.py`
  - `src/watchdog/services/adapters/openclaw/reply_model.py`
  - `src/watchdog/services/adapters/openclaw/adapter.py`
  - `tests/test_watchdog_openclaw_adapter.py`
  - `tests/integration/test_openclaw_integration_spine.py`
- **完成标准**：
  1. adapter 支持 `list_session_events`；
  2. `handle_intent("list_session_events")` 返回稳定 `ReplyModel(reply_code=session_event_snapshot)`；
  3. adapter 与 HTTP route 共用同一 `SessionEvent` reply builder；
  4. direct helper `list_session_events()` / `iter_session_events()` 不回归。
- **验证**：`uv run pytest -q tests/test_watchdog_openclaw_adapter.py tests/integration/test_openclaw_integration_spine.py -k session_events`

## Task 21.5 文档、OpenAPI 与项目状态收口

- **任务编号**：T215
- **状态**：已完成（2026-04-06 回填）
- **目标**：同步 021 对外口径，并推进 work item state。
- **涉及文件**：
  - `README.md`
  - `docs/getting-started.zh-CN.md`
  - `docs/openapi/watchdog.json`
  - `.ai-sdlc/project/config/project-state.yaml`
- **完成标准**：
  1. README 与 getting-started 已写清 JSON snapshot vs SSE 的区别；
  2. OpenAPI 暴露 `GET /api/v1/watchdog/sessions/{project_id}/event-snapshot`；
  3. `.ai-sdlc` 推进到 `022`。
- **验证**：`uv run python scripts/export_openapi.py`

## 整体验收

- 调用方已经可以通过 stable JSON `ReplyModel(events=SessionEvent[])` 一次性获取事件快照，而不必只能走 SSE。
- OpenClaw adapter 已将 `list_session_events` 纳入主 `handle_intent -> ReplyModel` 闭环。
- 021 只补 stable JSON event snapshot seam，不改变 011 的 stable SSE contract，也不扩成 cursor/backfill/实时事件系统。
