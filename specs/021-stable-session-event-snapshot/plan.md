---
related_doc:
  - "codex-watchdog-prd.md"
  - "docs/architecture/codex-watchdog-g0-and-v010-design.md"
  - "specs/021-stable-session-event-snapshot/spec.md"
---

# 实施计划：021-stable-session-event-snapshot

## 目标

把 stable session events 从单一 SSE transport 扩展为一个额外的 stable JSON snapshot read surface，让 `list_session_events` 可以正式进入 `intent -> ReplyModel` 主闭环，同时保持 011 的 SSE route 与事件 contract 不变。

## 架构摘要

- **Reply surface only**：021 只扩 `ReplyModel` 和 stable JSON route，不改 `SessionEvent` 模型本体。
- **Projection reuse**：JSON snapshot 与 SSE 都必须复用 `src/watchdog/services/session_spine/events.py` 里的既有 `SessionEvent` 投影。
- **Stable vs transport split**：稳定语义继续由 `SessionEvent` 承载；021 只是新增 JSON snapshot transport，011 的 SSE transport 保持原样。
- **Adapter symmetry**：Feishu adapter 继续保留直读 helper，但 `handle_intent("list_session_events")` 必须回到主 `ReplyModel` 闭环。
- **Schema bump scope**：只推进 session spine reply schema 到 `2026-04-05.021`；event schema version 保持 `2026-04-05.011`。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Contract | `src/watchdog/contracts/session_spine/enums.py`, `src/watchdog/contracts/session_spine/models.py`, `src/watchdog/contracts/session_spine/versioning.py` | 新增 `ReplyKind.EVENTS`、`ReplyCode.SESSION_EVENT_SNAPSHOT`、`ReplyModel.events`，推进 session spine schema version |
| L2 Reply Builder | `src/watchdog/services/session_spine/replies.py` | 新增 stable event snapshot reply builder，输入 `SessionEvent[]`，输出 `ReplyModel(events=...)` |
| Stable API Surface | `src/watchdog/api/session_spine_queries.py` | 暴露 `GET /api/v1/watchdog/sessions/{project_id}/event-snapshot`，复用既有 event projection |
| L3 Adapter | `src/watchdog/services/adapters/feishu/intents.py`, `src/watchdog/services/adapters/feishu/reply_model.py`, `src/watchdog/services/adapters/feishu/adapter.py` | 把 `list_session_events` 纳入 `handle_intent -> ReplyModel`，并复用同一 reply builder |
| 验证与文档 | `tests/test_watchdog_session_spine_contracts.py`, `tests/test_watchdog_session_spine_api.py`, `tests/test_watchdog_feishu_adapter.py`, `tests/integration/test_feishu_integration_spine.py`, `tests/test_watchdog_session_events_api.py`, `README.md`, `docs/getting-started.zh-CN.md`, `docs/openapi/watchdog.json`, `.ai-sdlc/project/config/project-state.yaml` | 锁定 contract、JSON route、adapter、integration、011 SSE 非回归与对外口径 |

## 依赖顺序

1. **先冻结 021 contract 与文档**
   - 定稿 route、reply kind/code、`ReplyModel.events` 与版本边界。
2. **再补失败测试**
   - 先锁住 schema version、JSON route、adapter intent 与 011 SSE 非回归。
3. **再实现 reply builder、API route 与 adapter wiring**
   - 只复用既有 `list_session_events(...)` 投影，不复制解析逻辑。
4. **最后更新对外文档、OpenAPI 与项目状态**
   - 把 JSON snapshot vs SSE 的边界写入 README / getting-started / OpenAPI，并推进 `.ai-sdlc`。

## 分阶段计划

### Phase 1：冻结 stable JSON event snapshot contract

交付内容：

- `specs/021-stable-session-event-snapshot/*`
- `ReplyKind.EVENTS`
- `ReplyCode.SESSION_EVENT_SNAPSHOT`
- `ReplyModel.events`
- `SESSION_SPINE_SCHEMA_VERSION=2026-04-05.021`

关键原则：

- 不推进 `SessionEvent` schema version
- `events[]` 继续承载独立事件 version
- transport 扩展不能反向污染 event contract

### Phase 2：先补测试，再实现 reply builder

交付内容：

- contract failing tests
- JSON route failing tests
- adapter/integration failing tests
- `build_session_event_snapshot_reply(...)`

关键原则：

- builder 只接收已投影好的 `SessionEvent[]`
- message 保持最小、可预测，例如 `N event(s)`
- 不在 builder 里重新做 raw 解析

### Phase 3：接入 stable API route 与 Feishu intent

交付内容：

- `GET /api/v1/watchdog/sessions/{project_id}/event-snapshot`
- `list_session_events` intent

关键原则：

- API route 只拉取 snapshot，不引入 `follow` 参数
- adapter `handle_intent` 与 HTTP route 共用同一 builder
- 原有 helper `list_session_events()` / `iter_session_events()` 保持可用

### Phase 4：文档、OpenAPI、state 与 011 非回归收口

交付内容：

- README / getting-started / OpenAPI
- `.ai-sdlc/project/config/project-state.yaml`
- 011 SSE regression verification

关键原则：

- 文档明确 JSON snapshot 与 SSE 的角色分工
- 不把 021 扩成稳定实时事件项目

## 回滚锚点

- **Phase 1 完成后**：021 scope、route 与 reply contract 可先冻结，不影响现有实现。
- **Phase 2 完成后**：JSON snapshot 语义已被测试锁住，即使 route / adapter 尚未接入也不会漂移。
- **Phase 3 完成后**：HTTP 与 adapter 已打通，可独立验证；文档与状态可随后补齐。

## 测试计划

### 契约测试

- 验证 `SESSION_SPINE_SCHEMA_VERSION` 推进到 `2026-04-05.021`
- 验证 `ReplyKind.EVENTS` 与 `ReplyCode.SESSION_EVENT_SNAPSHOT` 已冻结
- 验证 `ReplyModel.events` 存在且承载 `SessionEvent[]`

### Stable API 测试

- `GET /api/v1/watchdog/sessions/{project_id}/event-snapshot` 返回 `ReplyModel(events=...)`
- route 返回的 `events[]` 使用稳定 `SessionEvent`
- route 失败时继续走统一 control-link error 语义

### Adapter / Integration 测试

- Feishu adapter 支持 `list_session_events`
- `handle_intent("list_session_events")` 返回与 HTTP route 同源的 stable reply
- 原有 direct helper `list_session_events()` / `iter_session_events()` 不回归

### 011 SSE 非回归测试

- `GET /api/v1/watchdog/sessions/{project_id}/events` 继续返回 `text/event-stream`
- `SESSION_EVENTS_SCHEMA_VERSION` 仍是 `2026-04-05.011`

## 主要风险与应对

### 风险 1：为了做 JSON snapshot，再复制一份 raw SSE 解析逻辑

应对：

- 统一复用 `list_session_events(...)`
- 测试显式锁住 API 与 adapter 共用同一 `SessionEvent` 结果

### 风险 2：把 021 错做成另一个 SSE 变体，导致 transport 语义混乱

应对：

- route 固定为 `event-snapshot`
- 不支持 `follow`
- README / OpenAPI 明确 JSON snapshot 与 SSE 的边界

### 风险 3：推进了 event schema version，导致 011 contract 漂移

应对：

- 只 bump `SESSION_SPINE_SCHEMA_VERSION`
- 显式保留 `SESSION_EVENTS_SCHEMA_VERSION == 2026-04-05.011`

## 验收口径

只有当以下条件同时满足，021 才算达标：

1. 存在稳定 reply `ReplyKind.EVENTS / ReplyCode.SESSION_EVENT_SNAPSHOT`。
2. `ReplyModel` 已支持 `events: list[SessionEvent]`。
3. 存在 `GET /api/v1/watchdog/sessions/{project_id}/event-snapshot`。
4. Feishu adapter 已支持 `handle_intent("list_session_events") -> ReplyModel`。
5. `SESSION_SPINE_SCHEMA_VERSION` 已推进到 `2026-04-05.021`，但 `SESSION_EVENTS_SCHEMA_VERSION` 未改变。
6. 011 stable SSE route 已有显式非回归验证。
7. README、getting-started、OpenAPI 与 `.ai-sdlc` 已同步到 021。
