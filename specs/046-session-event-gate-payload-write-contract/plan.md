---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/046-session-event-gate-payload-write-contract/spec.md"
---

# 实施计划：046-session-event-gate-payload-write-contract

## 目标

把 session event 中的 gate payload fragment 写侧组装收口到 shared contract，确保 `decision_validated` 与 `_command_terminal_payload()` 不再直接手工拼装 `validator_verdict` / `release_gate_verdict` / `release_gate_evidence_bundle`。

## 架构摘要

- **One gate fragment seam**：session event 通过 shared helper 统一组装 gate payload fragment。
- **Scope stays narrow**：shared helper 只覆盖 gate fragment，不接管其他 event payload 字段。
- **Payload shape stays fixed**：本 work item 只收敛写侧 fragment，保持现有 event payload surface 不变。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Formal docs / task plan | `specs/046-session-event-gate-payload-write-contract/*` | 冻结 046 正式边界、任务拆解与 handoff |
| Shared event gate helper | `src/watchdog/services/session_spine/event_gate_payload_contract.py` | 统一组装 session event 中的 gate payload fragment |
| Resident runtime events | `src/watchdog/services/session_spine/orchestrator.py` | `decision_validated` 与 `_command_terminal_payload()` 复用 shared helper |
| Contract tests | `tests/test_watchdog_session_spine_runtime.py` | 锁定两处 event payload 都通过 shared helper |

## 边界纪律

- 046 不得新增新的 policy、schema、persistence、manifest、archive metadata 或 query facade。
- 046 不得把参数命名整理、fixture helper、e2e 改造拔高成主目标。
- 046 只收敛 session event gate payload fragment，不回到 decision evidence write-side 或通用 event 平台设计面。

## 测试计划

- `tests/test_watchdog_session_spine_runtime.py`
- `tests/test_long_running_autonomy_doc_contracts.py`
