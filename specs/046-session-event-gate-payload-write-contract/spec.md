---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/045-resident-runtime-release-gate-evidence-write-contract/spec.md"
---

# Session Event Gate Payload Write Contract — 功能规格说明

## 概述

`046-session-event-gate-payload-write-contract` 是在 `WI-045` 完成后追加的第十七个正式执行 work item。它不再扩新的 decision evidence write-side、policy/read-side、参数命名整理或 e2e 平台，而是把 session event 中 gate 子 payload 的写侧组装收口成 shared contract。

046 要解决的是当前仍停留在 orchestrator 内联组装层的 event payload seam：

> `decision evidence -> shared gate payload fragment contract -> session events`

它只消费已经存在且冻结的边界：

- `043` / `044` 的 typed gate consume contract；
- `045` 的 resident runtime decision evidence write-side contract；
- 当前 session event payload shape。

它同时吸收两组对抗约束：

- **Hermes Agent 专家边界**：046 必须只收口两个 gate payload fragment，不滑向通用 event serializer 或参数重命名工程。
- **Anthropic Manager 专家边界**：046 必须只覆盖 `decision_validated` 与 `_command_terminal_payload()` 中的 gate 子 payload；`decision_trace`、`completion_judgment`、`replay_summary`、`metrics_summary` 继续留在 orchestrator。

因此，046 的首要目标不是重写事件平台，而是让 session event 的 gate payload fragment 不再在 orchestrator 里各自维护第二真相。

## 功能需求

- **FR-4601**：session event gate payload 必须通过 shared contract 组装 `validator_verdict`、`release_gate_verdict`、`release_gate_evidence_bundle` fragment；orchestrator 不得继续直接手工拼装这些 gate 字段。
- **FR-4602**：`decision_validated` 与 `_command_terminal_payload()` 必须复用同一 gate payload helper。
- **FR-4603**：046 不得改变现有 session event payload 字段名、结构、decision evidence surface、read-side/policy semantics；它只收敛 gate fragment 写侧组装。
- **FR-4604**：046 不得新增新的 schema、manifest、archive metadata、query facade、parameter rename campaign、event platform 或测试平台层。
- **FR-4605**：shared helper 只负责 gate payload fragment，不得顺手接管 `decision_trace`、`completion_judgment`、`replay_summary`、`metrics_summary` 或其他事件字段。

## 非目标

- 不在 046 中修改 decision evidence、policy engine、read-side、future-worker schema 或 e2e/golden-path。
- 不在 046 中做参数命名整理、通用 event serializer 或新的 workflow。
