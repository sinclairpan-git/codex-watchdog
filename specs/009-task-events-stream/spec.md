---
related_doc:
  - "codex-watchdog-prd.md"
---

# Task Events Stream — 功能规格说明

## 概述

在 008 已完成 live control plane 的基础上，补齐 **Codex runtime service → Watchdog / Feishu** 的最小实时事件面。009 先交付 `GET /api/v1/tasks/{project_id}/events` 的 **SSE** 只读流，复用现有 `task_events.jsonl` 落盘事件，为 watchdog 侧提供比轮询 `progress` 更及时的状态感知。

## 功能需求

- **FR-901**：Codex runtime service 提供 `GET /api/v1/tasks/{project_id}/events`，响应类型为 `text/event-stream`。
- **FR-902**：事件流至少支持回放指定 `project_id` 已落盘事件，并可按 `follow=true|false` 选择持续跟随或一次性快照返回。
- **FR-903**：流内每条事件至少包含 `event_id`、`project_id`、`thread_id`、`event_type`、`event_source`、`payload_json`、`created_at`。
- **FR-904**：Codex runtime service 至少为 `task_created`、`native_thread_registered`、`steer` 写入 `task_events.jsonl`，供 SSE 回放。
- **FR-905**：未知 `project_id` 请求不得悬挂；应返回现有统一错误 envelope。
- **FR-906**：OpenAPI、README 与接入文档同步更新，明确 009 当前只交付 SSE，不交付 WebSocket。

### 用户故事 1：watchdog 侧订阅任务事件

Watchdog 或 Feishu 需要更实时地知道任务是否刚创建、刚被 steer，或是否有新的本地线程登记。

场景 1：调用 `GET /api/v1/tasks/{project_id}/events?follow=false`，快速拿到当前事件快照。

场景 2：调用 `GET /api/v1/tasks/{project_id}/events`，保持连接并持续接收后续事件。

## 非目标

- 不实现 WebSocket 版本事件流。
- 不输出完整 transcript、token 流或 Codex 内部原始 event stream。
- 不引入独立消息中间件、数据库订阅或跨机广播总线。
