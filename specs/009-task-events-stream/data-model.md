---
related_doc:
  - "codex-watchdog-prd.md"
---

# 数据与行为补充：009-task-events-stream

## task_events 记录

- `event_id`：事件唯一标识
- `project_id`：任务所属项目
- `thread_id`：对应线程
- `event_type`：如 `task_created`、`native_thread_registered`、`steer`
- `event_source`：事件来源，如 `a_control_agent`、`watchdog`
- `payload_json`：事件附加字段
- `created_at`：事件创建时间
- `ts`：兼容既有时间字段

## SSE 输出格式

- `id: <event_id>`
- `event: <event_type>`
- `data: <compact-json>`

`data` 内直接序列化完整事件对象，避免 watchdog 侧再拼装字段。
