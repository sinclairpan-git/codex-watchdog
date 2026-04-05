---
related_doc:
  - "openclaw-codex-watchdog-prd.md"
  - "docs/architecture/openclaw-codex-watchdog-g0-and-v010-design.md"
  - "specs/009-task-events-stream/spec.md"
---

# Stable Session Events — 功能规格说明

## 概述

在 `010-openclaw-integration-spine` 已冻结 stable read/write spine 之后，`011-stable-session-events` 的目标是继续补齐 **可稳定消费的只读事件面**：让 OpenClaw 与其他上层调用方可以订阅 **版本化、受控字段集、不中断演进** 的会话事件流，而不再直接消费 raw `task_events.jsonl` SSE 透传。

011 的唯一目标固定为：

> 建立与 `session_spine` 并列的稳定、只读、版本化 session event surface，使 OpenClaw 可消费 `GET /api/v1/watchdog/sessions/{project_id}/events`，而不是继续绑定 raw SSE payload。

## 功能需求

- **FR-1101**：011 必须定义中立稳定事件契约；事件对象与受控枚举不得落在 `openclaw` 命名空间下，也不得复用 raw `event_type` / `payload_json` 作为对外稳定字段。
- **FR-1102**：011 至少冻结以下稳定事件对象与枚举：`SessionEvent`、`EventCode`、`EventKind`。
- **FR-1103**：`SessionEvent` 必须显式携带 `contract_version` 与 `schema_version`，并继续区分 `thread_id` 与 `native_thread_id`。
- **FR-1104**：`SessionEvent` 至少包含以下稳定字段：`event_id`、`event_code`、`event_kind`、`project_id`、`thread_id`、`native_thread_id`、`source`、`observed_at`、`summary`、`related_ids`、`attributes`。
- **FR-1105**：Watchdog 必须提供 canonical stable event route：`GET /api/v1/watchdog/sessions/{project_id}/events`。
- **FR-1106**：上述 stable event route 必须继续支持 `follow=true|false` 与 `poll_interval`，以保持与当前 raw SSE 使用方式的最小迁移成本。
- **FR-1107**：stable event route 成功时必须返回 `text/event-stream`；每条 SSE 事件的 `id` 必须使用稳定 `event_id`，`event` 必须使用稳定 `event_code`，`data` 必须是 `SessionEvent` JSON。
- **FR-1108**：Watchdog 必须把当前 raw 事件类型稳定投影为以下最小事件码：
  - `task_created -> session_created`
  - `native_thread_registered -> native_thread_bound`
  - `steer -> guidance_posted`
  - `handoff -> handoff_requested`
  - `resume -> session_resumed`
  - `approval_decided -> approval_resolved`
- **FR-1109**：若遇到当前稳定映射表外的 raw 事件，Watchdog 必须退化为稳定 `event_code=session_updated`，而不是把未知 raw 类型直接泄漏给上层。
- **FR-1110**：stable event route 的 `data` 不得直接暴露 raw `event_type`、`payload_json`、raw task DTO 或 A-Control-Agent 专有 envelope 结构。
- **FR-1111**：legacy raw route `GET /api/v1/watchdog/tasks/{project_id}/events` 必须继续保留为 pass-through，不承担 stable contract 角色。
- **FR-1112**：OpenClaw adapter spine 必须提供只读事件消费入口，但不得把事件流强行塞回 010 的 `intent -> ReplyModel` 闭环，也不得把动作结果回执伪装成 stable session event。
- **FR-1113**：011 必须明确保持 “read-only stable event stream” 范围；不得在本工作项中引入 action-result receipt events、cursor/backfill 协议重做、WebSocket、常驻 supervisor 或渠道 runtime。
- **FR-1114**：011 必须补齐稳定事件契约测试、投影 / SSE codec 测试、stable API 测试、adapter 测试与最小集成测试。

### 用户故事 1：OpenClaw 订阅稳定会话事件

OpenClaw 需要实时知道会话创建、原生线程绑定、人工 guidance、handoff、resume 与审批完成，但不希望理解 raw SSE payload。

场景 1：调用 `GET /api/v1/watchdog/sessions/{project_id}/events?follow=false`，获得稳定 SSE 快照。

场景 2：调用 `GET /api/v1/watchdog/sessions/{project_id}/events`，持续接收稳定 `SessionEvent`。

### 用户故事 2：消费方基于稳定字段而不是 raw event schema 编程

上层消费方需要围绕受控 `event_code` 与版本字段开发，而不是围绕 `payload_json` 的偶发字段拼接逻辑。

场景 1：消费方只依赖 `event_code=session_resumed`，不依赖 raw `resume` payload 的字段顺序。

场景 2：审批事件只消费 `approval_resolved + related_ids.approval_id + attributes.decision`，而不是 raw `approval_decided` 结构。

### 用户故事 3：旧接口继续存在但不再是 stable contract

现有 raw 透传接口不能因为 011 而被打断，但新接入方也不应继续绑定它。

场景 1：原有 `/api/v1/watchdog/tasks/{project_id}/events` 继续可用。

场景 2：新文档与 OpenAPI 明确标注 `/api/v1/watchdog/sessions/{project_id}/events` 为 stable route，raw route 为 legacy/pass-through。

## 非目标

- 不把 `WatchdogActionResult` 或动作回执事件并入 011 stable event model。
- 不重做 cursor、offset、Last-Event-ID、事件回补协议。
- 不引入 WebSocket、消息总线或跨进程广播。
- 不让 adapter 直连 raw SSE route 或 A-Control-Agent。
- 不把 stable event route 扩成完整会话快照替代物；完整状态仍由 010 stable read API 提供。
