# 任务分解：046-session-event-gate-payload-write-contract

> 对应规格：`specs/046-session-event-gate-payload-write-contract/spec.md`
>
> 对应计划：`specs/046-session-event-gate-payload-write-contract/plan.md`

## Task 46.1 冻结 046 formal docs 与 session event gate payload seam 边界

- **任务编号**：T461
- **状态**：未开始
- **目标**：把总实施计划中的 `Task 17` 正式拆成 canonical execution work item，并把 046 收紧为 session event gate payload write contract。
- **文件**：
  - `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
  - `specs/046-session-event-gate-payload-write-contract/spec.md`
  - `specs/046-session-event-gate-payload-write-contract/plan.md`
  - `specs/046-session-event-gate-payload-write-contract/tasks.md`
  - `specs/046-session-event-gate-payload-write-contract/task-execution-log.md`
  - `.ai-sdlc/work-items/046-session-event-gate-payload-write-contract/*`
- **可并行**：否
- **验收标准**：
  1. 已明确 046 只做 session event gate payload seam；
  2. 已明确 046 只覆盖 `decision_validated` 与 `_command_terminal_payload()` 两处 gate fragment；
  3. 已明确 046 不引入新的 policy、schema、测试平台、manifest、archive metadata 或 parameter rename campaign；
  4. Hermes Agent 专家与 Anthropic Manager 专家复核后无 blocking/P1。
- **验证**：
  - `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`

## Task 46.2 写失败测试锁定 session event gate payload contract

- **任务编号**：T462
- **状态**：未开始
- **目标**：用失败测试先锁定 session event 中 gate payload 的唯一 write-side surface。
- **文件**：
  - `tests/test_watchdog_session_spine_runtime.py`
- **可并行**：否
- **验收标准**：
  1. 覆盖 `decision_validated` 与 `_command_terminal_payload()` 不得继续各自手工拼 gate fragment；
  2. 覆盖 shared helper 不得接管其他 event payload 字段；
  3. 覆盖现有 gate payload shape 保持不变。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_session_spine_runtime.py`

## Task 46.3 实现最小 shared event gate helper 与 orchestrator 收口

- **任务编号**：T463
- **状态**：未开始
- **目标**：让 session event gate payload 只通过 shared contract 组装。
- **文件**：
  - `src/watchdog/services/session_spine/event_gate_payload_contract.py`
  - `src/watchdog/services/session_spine/orchestrator.py`
  - `tests/test_watchdog_session_spine_runtime.py`
- **可并行**：否
- **验收标准**：
  1. `decision_validated` 与 `_command_terminal_payload()` 已改为复用同一 shared helper；
  2. helper 只组装 gate fragment；
  3. 现有 event payload shape 保持不变。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_session_spine_runtime.py tests/test_long_running_autonomy_doc_contracts.py`

## Task 46.4 更新执行日志与 handoff 摘要

- **任务编号**：T464
- **状态**：未开始

## Task 46.5 完成 046 整体验证并交接后续 work item

- **任务编号**：T465
- **状态**：未开始
