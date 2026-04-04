---
related_doc:
  - "openclaw-codex-watchdog-prd.md"
---

# 实施计划：008-codex-live-control-plane

## 步骤

1. 定义 Codex app-server 协议封装与配置面，新增 bridge 生命周期管理与错误模型。
2. 将 bridge 接入 A-Control-Agent 生命周期，补线程恢复、活跃 turn 跟踪与失联回退。
3. 打通审批请求 ingest / decision callback，统一更新 `ApprovalsStore`、`TaskStore` 与审计。
4. 将 `POST steer` 与 `POST resume` 改为真实 control-plane 调用，同时保持现有 Watchdog HTTP 边界兼容。
5. 新增 bridge / approval / control API 单测，更新 OpenAPI 与接入文档；SSE 明确留给 009。
