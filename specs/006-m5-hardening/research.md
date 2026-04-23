---
related_doc:
  - "codex-watchdog-prd.md"
---

# 研究记录：006-m5-hardening

| 主题 | 结论 |
|------|------|
| PRD §14.3 指标 | 任务数来自 store；steer/handoff/resume/审批从 `audit.jsonl` 的 `action` 聚合 |
| Codex | 仅 Protocol 占位，与 PRD §19.1「再接 app-server」一致 |
| Feishu | 示例脚本仅演示 HTTP 调用 Watchdog，无飞书依赖 |
