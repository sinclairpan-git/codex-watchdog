---
related_doc:
  - "codex-watchdog-prd.md"
---

# 实施计划：M3 审批能力

## 目标

交付审批存储、风险分级模块、runtime 侧 API、Watchdog 代理与测试；不实现飞书机器人（PRD §3.2）。

## 技术栈

沿用 `.ai-sdlc/profiles/tech-stack.yml`：Python 3.11+、FastAPI；持久化为 JSON 文件。

## 模块划分

| 组件 | 职责 |
|------|------|
| `risk_classifier` | 基于关键词与规则将 `command` 映射到 L0–L3 |
| `approvals_store` | `approval_id` 索引的读写 |
| `api/approvals` | runtime 侧 REST |
| `api/approvals_watchdog` | Watchdog 代理路由 |

## 宪章响应

契约与测试校验后再合并；决策与审计可追溯至 PRD §7。
