---
related_doc:
  - "openclaw-codex-watchdog-prd.md"
---

# 数据与行为补充：007-prd-alignment

## steer 请求体（增量）

- `stuck_level`：可选 int，范围建议 0–4，与 PRD §6.5 一致。

## Watchdog 配置

- `recover_auto_resume`：bool，默认 `false`，环境变量 `WATCHDOG_RECOVER_AUTO_RESUME`。
