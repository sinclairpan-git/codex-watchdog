---
related_doc:
  - "codex-watchdog-prd.md"
---

# 研究记录：009-task-events-stream

## 取舍

- 先选 **SSE**，不选 WebSocket：PRD 允许二选一；当前需求是 watchdog 侧更实时感知状态变化，单向推送足够。
- 先复用 `task_events.jsonl`，不引入额外 broker：仓库当前已经有文件型 store 与 JSONL 审计，保持一致性更重要。
- 先交付 `follow=true|false`，不做 `Last-Event-ID` / 断点续传：当前规模下先满足“可实时看见变化”，后续再补重连语义。

## 边界

- 009 当前只覆盖任务级事件，不覆盖完整 Codex transcript。
- bridge 内部更细粒度 server event 仍可后续再映射到 `task_events.jsonl`。
