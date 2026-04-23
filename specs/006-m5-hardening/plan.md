---
related_doc:
  - "codex-watchdog-prd.md"
---

# 实施计划：006-m5-hardening

## 目标

补齐 M5 与 §22 中不依赖飞书/Feishu 渠道的部分：可观测性、resume 状态、工作区摘要、Codex 占位、集成测试与 API/示例交付物。

## 步骤

1. 审计聚合 + 双服务 `/metrics`。
2. `recovery.resume` 两阶段状态；必要时补充单测。
3. `repo_activity` 模块 + `GET /api/v1/tasks/{project_id}/workspace-activity`。
4. `codex/client.py` Protocol + 默认实现；`app.state` 挂载（可选）。
5. `tests/integration/`、`scripts/export_openapi.py`、`examples/codex_watchdog_client.py`、`README` 增补 M5 说明。

## 风险与缓解

- 大仓库扫描耗时：限制深度、文件数、超时。
- 指标读审计文件：大文件时仅顺序扫描单行 JSON，可接受 M5 规模；后续可加 rotate。
