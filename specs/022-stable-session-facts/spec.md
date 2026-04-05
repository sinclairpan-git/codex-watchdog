---
related_doc:
  - "openclaw-codex-watchdog-prd.md"
  - "docs/architecture/openclaw-codex-watchdog-g0-and-v010-design.md"
  - "specs/010-openclaw-integration-spine/spec.md"
  - "specs/015-stable-session-explanations/spec.md"
  - "specs/021-stable-session-event-snapshot/spec.md"
---

# Stable Session Facts — 功能规格说明

## 概述

在 `010-021` 已经建立 stable session spine、stable explanations、stable events、stable receipts 与主要 stable action surfaces 之后，当前还剩一个明显缺口：

- `FactRecord` 在 `010` 就已经被冻结为核心稳定契约对象；
- `why_stuck`、`explain_blocker`、`request_recovery` 都依赖它作为解释真值；
- 但 OpenClaw 与其他上层调用方还没有一个独立、直接、稳定的 facts read surface，只能通过 session / progress / explanation 的附带字段间接读取。

022 的唯一目标固定为：

> 建立 stable session-facts read surface，让 OpenClaw 与其他上层调用方可以通过 `list_session_facts -> ReplyModel(facts=FactRecord[])` 直接稳定消费事实真值，而不是继续从 explanation 或其他 read model 的附带字段里拆取。

## 功能需求

- **FR-2201**：022 必须新增稳定 reply kind：
  - `ReplyKind.FACTS`
- **FR-2202**：022 必须新增稳定 reply code：
  - `ReplyCode.SESSION_FACTS`
- **FR-2203**：022 不新增新的 DTO 字段；`ReplyModel.facts` 继续复用 `010` 已冻结的 `FactRecord[]`。
- **FR-2204**：022 必须新增 canonical stable read route：
  - `GET /api/v1/watchdog/sessions/{project_id}/facts`
- **FR-2205**：该 route 成功时必须返回版本化 `ReplyModel`：
  - `reply_kind=facts`
  - `reply_code=session_facts`
  - `intent_code=list_session_facts`
  - `facts` 内元素必须继续使用 `010` 已冻结的 `FactRecord`
- **FR-2206**：022 的 facts route 必须复用既有稳定 `SessionReadBundle + FactRecord` 构建链路，不得新增 raw `task / approvals / evaluate / recover / events` 旁路拼装。
- **FR-2207**：OpenClaw adapter 必须正式支持 `list_session_facts` intent，并把它纳入 `handle_intent(...) -> ReplyModel` 主闭环。
- **FR-2208**：adapter `handle_intent("list_session_facts", project_id=...)` 必须返回与 HTTP route 同源的 stable `ReplyModel(reply_code=session_facts)`。
- **FR-2209**：022 必须保持 explanation contract 不变：
  - `why_stuck` 与 `explain_blocker` 继续复用既有 explanation builder
  - 022 不得改写 explanation reply_code、message 语义或 HTTP 路由
- **FR-2210**：022 只推进 session spine reply schema，因此：
  - `SESSION_SPINE_SCHEMA_VERSION` 必须从 `2026-04-05.021` 推进到 `2026-04-05.022`
  - `SESSION_EVENTS_SCHEMA_VERSION` 必须保持 `2026-04-05.011`
- **FR-2211**：README、getting-started 与 OpenAPI 必须明确写清：
  - `GET /api/v1/watchdog/sessions/{project_id}/facts` 是 stable fact surface
  - 它返回的是 `ReplyModel(reply_code=session_facts, facts=FactRecord[])`
  - 它与 `why_stuck` / `explain_blocker` 的关系是“真值层 vs 解释层”，而不是替代关系
- **FR-2212**：022 必须补齐契约测试、API 测试、adapter 测试与最小 integration 测试；同时显式验证 explanation read route 不回归。

### 用户故事 1：上层可以直接读取事实真值

OpenClaw 或其他上层系统需要独立读取某个 session 当前的稳定 facts，而不是只拿解释文案。

场景 1：调用 `GET /api/v1/watchdog/sessions/{project_id}/facts`，返回 `ReplyModel(reply_code=session_facts, facts=FactRecord[])`。

场景 2：返回的 `facts[]` 与 session / progress / explanation 已携带的 `FactRecord[]` 同源。

### 用户故事 2：OpenClaw adapter 把 facts 纳入统一意图闭环

OpenClaw 希望直接请求 `list_session_facts`，而不是先取 stuck explanation 再拆 supporting facts。

场景 1：adapter `handle_intent("list_session_facts", project_id="repo-a")` 返回 `ReplyModel(reply_code=session_facts)`。

场景 2：adapter 与 HTTP route 返回的 `facts[]` 同源，且不会走 raw 旁路。

### 用户故事 3：解释层继续存在，但与真值层角色分离

已有调用方仍需要 `why_stuck` 或 `explain_blocker` 这样的解释语义。

场景 1：`GET /api/v1/watchdog/sessions/{project_id}/stuck-explanation` 继续返回 explanation reply，不因 022 而改变。

场景 2：`GET /api/v1/watchdog/sessions/{project_id}/facts` 提供 facts truth source；调用方可自行渲染、审计或二次推理。

## 非目标

- 不新增 `FactRecord` 字段、事实枚举体系或新的 fact-specific DTO。
- 不新增 facts filter、fact history、分页、severity 查询参数或时间窗口语义。
- 不把 `facts` route 扩成 explanation route 的替代品。
- 不新增新的动作面、receipt 语义或事件流。
- 不允许 adapter 或 API 直接读取 raw/legacy route 来拼事实结果。
