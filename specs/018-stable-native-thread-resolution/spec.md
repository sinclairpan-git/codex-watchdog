---
related_doc:
  - "codex-watchdog-prd.md"
  - "docs/architecture/codex-watchdog-g0-and-v010-design.md"
  - "specs/010-runtime-integration-spine/spec.md"
  - "specs/017-stable-session-directory/spec.md"
---

# Stable Native Thread Resolution — 功能规格说明

## 概述

在 `010-017` 完成 stable session spine、events、recovery、receipt、supervision、explanation、approval inbox 与 session directory 之后，当前 stable surface 还剩一个明显缺口：

- `SessionProjection`、`ApprovalProjection`、`SessionEvent` 都已经正式区分 `thread_id` 与 `native_thread_id`；
- 上层现在可以稳定拿到 `native_thread_id`；
- 但一旦调用方手里只有 `native_thread_id`，仍然只能回退到 Codex runtime service raw `/api/v1/tasks/by-thread/{thread_id}`，而不是继续走 Watchdog stable contract。

017 的 session directory 虽然能靠全量枚举再扫描解决一部分问题，但它不是“给一个 native thread 直接解回 stable session”这一条明确契约。

018 的唯一目标固定为：

> 建立 stable native-thread resolution read surface，让 Feishu 与其他调用方能够在仅持有 `native_thread_id` 时，直接解析出同源的稳定 `SessionProjection` reply，而不是扫描 session directory 或直接绑定 Codex runtime service raw `/by-thread` payload。

## 功能需求

- **FR-1801**：018 必须补一个独立 stable native-thread resolution read surface；不得把稳定语义直接塞回 Codex runtime service raw `/api/v1/tasks/by-thread/{thread_id}`。
- **FR-1802**：018 的 canonical stable route 固定为：
  - `GET /api/v1/watchdog/sessions/by-native-thread/{native_thread_id}`
- **FR-1803**：该 route 返回稳定 `ReplyModel`，其中：
  - `reply_kind=session`
  - `reply_code=session_projection`
  - `intent_code=get_session_by_native_thread`
  - `session` 为稳定 `SessionProjection`
  - `facts` 为与该解析结果同源的稳定 `FactRecord[]`
- **FR-1804**：018 必须继续复用既有 `SessionProjection` 与 `ReplyModel`；不得新增 `ThreadResolutionView`、`NativeThreadLookupReply` 或任何平行 DTO。
- **FR-1805**：native-thread resolution 必须先通过 Codex runtime service 的 `/api/v1/tasks/by-thread/{thread_id}` 获得目标 task row，再在 Watchdog L2 内把该 row 投影为稳定 `SessionProjection`；adapter 与 HTTP route 均不得自己拼 raw payload。
- **FR-1806**：018 不新增 `ReplyCode`、`ActionCode`、contract object 字段或 schema 字段；`contract_version` 与 session spine `schema_version` 保持 `017` 的值，不因 018 单独推进。
- **FR-1807**：native-thread resolution 只覆盖“由一个明确 `native_thread_id` 解出稳定 session reply”；不引入搜索、模糊匹配、批量 lookup、分页、history 或 archive 语义。
- **FR-1808**：Feishu adapter 必须新增 `get_session_by_native_thread` intent，并通过 stable builder 返回与 HTTP route 同源的 `ReplyModel`；该 intent 不要求 `project_id`，但必须要求 `arguments.native_thread_id`。
- **FR-1809**：当 `native_thread_id` 不存在或 control-link 不可达时，018 必须继续复用稳定错误 envelope；不得把 raw upstream body 或内部异常栈暴露为 stable payload。
- **FR-1810**：README、getting-started 与 OpenAPI 必须明确把 native-thread resolution 纳入 stable read surface，并说明：
  - `/watchdog/sessions/by-native-thread/{native_thread_id}`：稳定 native-thread resolution route
  - `/api/v1/tasks/by-thread/{thread_id}`：Codex runtime service raw lookup route，继续存在但不承担 stable contract 角色
- **FR-1811**：018 必须补齐 API 测试、adapter 测试、最小 integration 测试，以及 raw `/api/v1/tasks/by-thread/{thread_id}` 非回归测试。

### 用户故事 1：Feishu 手里只有 native thread，也能直接回到 stable session

Feishu 可能从事件流、审批投影或外部上下文中拿到 `native_thread_id`，但当下并不知道 `project_id`。

场景 1：调用 `GET /api/v1/watchdog/sessions/by-native-thread/thr_native_1`，返回稳定 `ReplyModel(reply_code=session_projection)`。

场景 2：返回体中的 `session.project_id`、`thread_id` 与 `native_thread_id` 足以让上层继续跳转到单 session 读面、解释面或动作面。

### 用户故事 2：HTTP 与 adapter 使用同一套 resolution 语义

同一个 `native_thread_id` 在 HTTP stable route 与 Feishu adapter 上应该得到同源 session reply，而不是两套 lookup 逻辑。

场景 1：adapter `get_session_by_native_thread(arguments.native_thread_id=...)` 与 HTTP route 返回相同 `reply_code`。

场景 2：两者返回的 `project_id`、`thread_id`、`native_thread_id` 与关键信息一致。

### 用户故事 3：raw `/by-thread` 继续存在，但不再是稳定接入面

已有脚本或测试可能仍依赖 Codex runtime service raw `/api/v1/tasks/by-thread/{thread_id}`。

场景 1：018 落地后，raw `/by-thread` 继续工作且基础行为不回归。

场景 2：README / OpenAPI 明确 stable native-thread resolution 与 raw `/by-thread` 的角色边界。

## 非目标

- 不新增新的 stable write action、receipt、event、approval 或 supervision 语义。
- 不引入 thread 搜索、prefix lookup、multi-thread batch 查询或 archive/history。
- 不把 018 扩成“按 thread_id 读取完整历史线程视图”。
- 不改变既有 `GET /api/v1/watchdog/sessions/{project_id}`、`GET /api/v1/watchdog/sessions`、`GET /api/v1/watchdog/approval-inbox` 的 contract。
