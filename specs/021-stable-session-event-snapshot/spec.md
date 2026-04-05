---
related_doc:
  - "openclaw-codex-watchdog-prd.md"
  - "docs/architecture/openclaw-codex-watchdog-g0-and-v010-design.md"
  - "specs/010-openclaw-integration-spine/spec.md"
  - "specs/011-stable-session-events/spec.md"
  - "specs/020-stable-operator-guidance/spec.md"
---

# Stable Session Event Snapshot — 功能规格说明

## 概述

在 `010-020` 已经建立 stable session spine、stable session events SSE、stable receipts、stable explanations 与 stable operator guidance 之后，当前仍有一个明显的不对称点：

- `011` 已经提供 `GET /api/v1/watchdog/sessions/{project_id}/events`，但它是 `text/event-stream`；
- OpenClaw adapter 也已有 `list_session_events()` / `iter_session_events()` 辅助方法；
- 但主读取闭环 `intent -> ReplyModel` 里还没有一个稳定、版本化的 JSON event snapshot reply。

021 的唯一目标固定为：

> 建立 stable session-event snapshot read surface，让 OpenClaw 与其他上层调用方可以通过 `list_session_events -> ReplyModel(events=SessionEvent[])` 稳定消费事件快照，而不是只能单独走 SSE 或 adapter 特例方法。

## 功能需求

- **FR-2101**：021 必须新增稳定 reply kind：
  - `ReplyKind.EVENTS`
- **FR-2102**：021 必须新增稳定 reply code：
  - `ReplyCode.SESSION_EVENT_SNAPSHOT`
- **FR-2103**：`ReplyModel` 必须新增稳定字段：
  - `events: list[SessionEvent]`
- **FR-2104**：021 必须新增 canonical stable JSON read route：
  - `GET /api/v1/watchdog/sessions/{project_id}/event-snapshot`
- **FR-2105**：该 route 成功时必须返回版本化 `ReplyModel`：
  - `reply_kind=events`
  - `reply_code=session_event_snapshot`
  - `intent_code=list_session_events`
  - `events` 内元素必须继续使用 `011` 已冻结的 `SessionEvent`
- **FR-2106**：021 不得改写 `011` 的 stable SSE contract：
  - `GET /api/v1/watchdog/sessions/{project_id}/events` 继续返回 `text/event-stream`
  - `SessionEvent.contract_version / schema_version` 继续保持 `011` 口径
- **FR-2107**：021 必须把 OpenClaw adapter intent `list_session_events` 正式纳入 `handle_intent(...) -> ReplyModel` 主闭环，而不是只保留 adapter 特例方法。
- **FR-2108**：adapter `handle_intent("list_session_events", project_id=...)` 必须返回与 HTTP route 同源的 stable `ReplyModel(reply_code=session_event_snapshot)`。
- **FR-2109**：021 的 JSON snapshot 必须复用既有稳定事件投影层 `list_session_events(...)`，不得新写 raw SSE 解析分支，也不得让 adapter 或 API 自己拼 `SessionEvent`。
- **FR-2110**：021 只新增 stable JSON event snapshot，不新增 follow、cursor、backfill、分页、过滤或 action receipt event 融合能力。
- **FR-2111**：021 只推进 session spine reply schema，因此：
  - `SESSION_SPINE_SCHEMA_VERSION` 必须从 `2026-04-05.020` 推进到 `2026-04-05.021`
  - `SESSION_EVENTS_SCHEMA_VERSION` 必须保持 `2026-04-05.011`
- **FR-2112**：README、getting-started 与 OpenAPI 必须明确写清：
  - `GET /api/v1/watchdog/sessions/{project_id}/event-snapshot` 是 stable JSON snapshot
  - `GET /api/v1/watchdog/sessions/{project_id}/events` 仍是 stable SSE
  - 两者共享同一份 `SessionEvent` 投影层，但 transport 不同
- **FR-2113**：021 必须补齐契约测试、API 测试、adapter 测试与最小 integration 测试；同时显式验证 011 SSE route 不回归。

### 用户故事 1：上层可以通过稳定 JSON 一次性读取事件快照

OpenClaw 或其他上层系统需要一次性拿到一个项目的稳定事件列表，并继续使用 `ReplyModel` 作为统一读取载体。

场景 1：调用 `GET /api/v1/watchdog/sessions/{project_id}/event-snapshot`，返回 `ReplyModel(reply_code=session_event_snapshot, events=SessionEvent[])`。

场景 2：返回的 `events[]` 继续使用 `011` 已冻结的 `SessionEvent` 字段与版本语义。

### 用户故事 2：OpenClaw adapter 不再需要为事件快照走旁路方法

OpenClaw 希望把 session event snapshot 纳入现有 `handle_intent(...) -> ReplyModel` 调用方式。

场景 1：adapter `handle_intent("list_session_events", project_id="repo-a")` 返回 `ReplyModel(reply_code=session_event_snapshot)`。

场景 2：adapter 返回的 `events[]` 与 HTTP route 返回的 `events[]` 同源。

### 用户故事 3：011 的 SSE 读面继续保留，不被 JSON snapshot 替代

已有消费者可能仍需要稳定 SSE follow stream。

场景 1：`GET /api/v1/watchdog/sessions/{project_id}/events` 继续返回 `text/event-stream`。

场景 2：021 落地后，SSE 与 JSON snapshot 共享 `SessionEvent` 投影，但 transport 与消费方式保持分离。

## 非目标

- 不改变 `011` 已冻结的 `SessionEvent` 对象、事件枚举与事件 schema version。
- 不把 stable session events 扩成 cursor / since / backfill / pagination 产品。
- 不把 event stream 强塞进 `ReplyModel` follow 模式。
- 不移除 OpenClaw adapter 现有的 `list_session_events()` / `iter_session_events()` 辅助方法。
- 不引入 audit timeline、action receipt events 或实时 supervisor event 融合。
