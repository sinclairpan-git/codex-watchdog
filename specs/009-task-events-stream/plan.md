---
related_doc:
  - "openclaw-codex-watchdog-prd.md"
---

# 实施计划：009-task-events-stream

## 步骤

1. 为 `TaskStore` 增加统一事件落盘与按 `project_id` 读取能力，先覆盖 create / native-thread / steer。
2. 在 `tasks` 路由新增 `GET /api/v1/tasks/{project_id}/events`，按 SSE 格式输出事件并支持 `follow` 控制。
3. 新增 API 红绿测试，验证 `text/event-stream`、事件回放与未知任务错误路径。
4. 重新导出 OpenAPI，并同步 README / 接入文档。
