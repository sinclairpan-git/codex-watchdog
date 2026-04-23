---
related_doc:
  - "codex-watchdog-prd.md"
  - "docs/architecture/codex-watchdog-g0-and-v010-design.md"
  - "specs/011-stable-session-events/spec.md"
---

# 实施计划：011-stable-session-events

## 目标

在不改变 raw SSE 透传语义、不引入动作回执事件融合的前提下，交付一套 **稳定、版本化、只读** 的 session event surface，让 Feishu 与其他上层调用方消费 `SessionEvent`，而不是直接消费 Codex runtime service raw SSE payload。

## 架构摘要

- **Contract-first**：先冻结 `SessionEvent`、`EventCode`、`EventKind` 与事件版本语义。
- **Projection / Codec 分离**：L2 负责 raw event -> stable event projection 与 SSE parse/encode；API 层只负责 transport。
- **Stable vs Legacy 明确分离**：`/watchdog/sessions/{project_id}/events` 是 canonical stable route；`/watchdog/tasks/{project_id}/events` 继续作为 legacy pass-through。
- **Adapter 只读接入**：Feishu adapter 新增只读事件入口，不把事件面塞回 010 的 intent/reply write loop。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Contract | `src/watchdog/contracts/session_spine/enums.py`, `models.py`, `versioning.py`, `__init__.py` | 定义 `SessionEvent`、事件枚举、独立版本常量 |
| L2 Event Projection | `src/watchdog/services/session_spine/events.py` | raw SSE block 解析、raw event -> `SessionEvent` 投影、stable SSE 编码 |
| Stable API Surface | `src/watchdog/api/session_spine_events.py`, `src/watchdog/main.py` | 暴露 canonical stable event route |
| L3 Adapter | `src/watchdog/services/adapters/feishu/adapter.py` | 暴露 Feishu 只读事件消费入口 |
| Legacy 保持不动为主 | `src/watchdog/api/events_proxy.py` | 原样保留 raw SSE proxy |
| 验证与文档 | `tests/test_watchdog_session_events_*.py`, `tests/integration/test_stable_session_events.py`, `README.md`, `docs/getting-started.zh-CN.md`, `docs/openapi/watchdog.json` | 锁定行为与接入文档 |

## 依赖顺序

1. **先冻结事件契约**
   - 没有稳定事件对象与事件码，后续 route 只会变成另一个 raw proxy。
   - 先把 `SessionEvent`、`EventCode`、`EventKind` 与事件版本常量钉死。
2. **再做 L2 projection / codec**
   - 先把 raw SSE 解析和 stable SSE 输出做稳，再接 API。
   - 这里同时处理未知 raw 事件的稳定降级路径。
3. **再接 Stable API Surface**
   - canonical route 只依赖 projection / codec 层。
   - raw route 不做侵入式改造，只做非回归保护。
4. **最后补 L3 adapter 与文档**
   - adapter 只读消费 `SessionEvent`。
   - 文档与 OpenAPI 统一强调 stable/legacy 双面共存。

## 分阶段计划

### Phase 1：冻结稳定事件契约

交付内容：

- `EventCode`
- `EventKind`
- `SessionEvent`
- `SESSION_EVENTS_CONTRACT_VERSION`
- `SESSION_EVENTS_SCHEMA_VERSION`

关键原则：

- 事件契约保持中立，不带 `feishu` 命名
- `thread_id` 继续表示 stable session id
- `native_thread_id` 只表达底层原生线程
- 011 事件版本独立于 010 session spine read/write schema 版本

风险点：

- 若直接复用 raw `event_type` / `payload_json`，contract 会再次漂移
- 若沿用 010 全局 schema 版本，011 事件对象会和 010 冻结文档混淆

### Phase 2：建立 L2 事件投影与 SSE codec

交付内容：

- raw SSE block parser
- raw event decoder
- raw event -> `SessionEvent` 映射器
- stable SSE encoder
- snapshot / streaming 统一转换路径

关键原则：

- projection 与 HTTP transport 分离
- 未知 raw event 退化为 `session_updated`
- stable output 不透出 raw `payload_json`

风险点：

- `iter_events()` 返回的是 text chunk，不保证与 SSE event block 对齐
- snapshot body 可能包含多条 SSE 记录，需要逐条 parse 而不是字符串替换

### Phase 3：暴露 Stable API Surface

交付内容：

- `GET /api/v1/watchdog/sessions/{project_id}/events`
- `follow=true|false`
- `poll_interval`
- 成功时返回 stable SSE；失败时继续返回统一错误 envelope

关键原则：

- `event:` 行使用 `event_code`
- `data:` 行是 `SessionEvent` JSON
- raw proxy 路由继续保持 legacy 行为

### Phase 4：接入 L3 Feishu adapter

交付内容：

- adapter snapshot 读取入口
- adapter streaming 读取入口

关键原则：

- adapter 不绕回 raw proxy route
- adapter 不把 `SessionEvent` 伪装成 `ReplyModel`
- adapter 不混入动作回执事件

### Phase 5：文档、OpenAPI 与验收收口

交付内容：

- 011 spec / plan / tasks
- README 与 getting-started 新增 stable event surface
- OpenAPI 标注 stable event route 与 raw legacy route
- 最小集成与非回归测试

关键原则：

- 明确 stable route 是 `/watchdog/sessions/.../events`
- 明确 raw route 仍在，但只是 pass-through
- 明确 011 不包含 action receipt events 与 cursor/backfill redesign

## 测试计划

### 契约测试

- 验证 `SessionEvent` 携带独立事件 contract/schema version
- 验证 `event_code`、`event_kind` 枚举域冻结
- 验证 `thread_id / native_thread_id` 分层仍成立

### 投影 / Codec 测试

- 验证 raw `task_created`、`resume`、`approval_decided` 等被稳定映射
- 验证未知 raw 事件退化为 `session_updated`
- 验证 snapshot text 可被 parse 成多条 stable SSE
- 验证流式 chunk 可被正确组块并转换

### API 测试

- 验证 canonical stable route 返回 `text/event-stream`
- 验证 `event:` 行使用 stable `event_code`
- 验证错误时仍返回统一 envelope
- 验证 raw legacy route 行为非回归

### Adapter 测试

- 验证 adapter snapshot 返回 `SessionEvent[]`
- 验证 adapter stream 返回 `SessionEvent` 迭代器
- 验证 adapter 不暴露 raw `payload_json`

### 最小集成测试

- 用 fake A client 走通 stable snapshot
- 用 fake A client 走通 stable follow stream
- 验证 raw `/watchdog/tasks/{project_id}/events` 与 stable `/watchdog/sessions/{project_id}/events` 并存

## 主要风险与应对

### 风险 1：stable route 退化成 raw proxy 的字段改名版

应对：

- 用独立 `SessionEvent` 模型锁字段
- 测试明确断言 output 不含 `payload_json`

### 风险 2：SSE chunk 边界处理错误导致丢事件

应对：

- 单独写 codec 测试，覆盖多 chunk 拼接
- API 层只消费 codec，不重复实现解析逻辑

### 风险 3：011 范围再次膨胀到动作回执融合

应对：

- spec/tasks 写死 read-only
- adapter 与 API 都不新增 action-result event synthesis

## 验收口径

只有当以下条件同时满足，011 才算达标：

1. 存在独立稳定 `SessionEvent` 契约与事件版本语义。
2. canonical stable route 已是 `/api/v1/watchdog/sessions/{project_id}/events`。
3. raw `/api/v1/watchdog/tasks/{project_id}/events` 仍存在且不承担 stable contract 角色。
4. Feishu adapter 已具备只读稳定事件消费入口，但未把事件面混回动作 reply 模型。
5. 文档、OpenAPI、测试都明确 011 是 read-only stable event stream，不含 action receipt events。
