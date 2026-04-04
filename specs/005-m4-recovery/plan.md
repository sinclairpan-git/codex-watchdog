---
related_doc:
  - "openclaw-codex-watchdog-prd.md"
---

# 实施计划：M4 恢复能力

## 目标

A 侧 handoff/resume HTTP API、文件型 handoff 目录、Watchdog `recover` 编排；测试覆盖鉴权与链路错误。

## 模块

| 路径 | 职责 |
|------|------|
| `storage/handoff_manager.py` | 写 markdown、登记路径 |
| `api/recovery.py` | handoff / resume 路由 |
| `api/recover_watchdog.py` | Watchdog recover |

## 宪章

行为与审计可追溯；不伪造 A 侧可达性。
