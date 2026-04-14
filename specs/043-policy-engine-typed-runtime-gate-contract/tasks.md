# 任务分解：043-policy-engine-typed-runtime-gate-contract

> 对应规格：`specs/043-policy-engine-typed-runtime-gate-contract/spec.md`
>
> 对应计划：`specs/043-policy-engine-typed-runtime-gate-contract/plan.md`

## Task 43.1 冻结 043 formal docs 与 policy-engine seam 边界

- **任务编号**：T431
- **状态**：已完成（2026-04-14）
- **目标**：把总实施计划中的 `Task 14` 正式拆成 canonical execution work item，并把 043 收紧为 policy engine typed runtime-gate contract。
- **文件**：
  - `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
  - `specs/043-policy-engine-typed-runtime-gate-contract/spec.md`
  - `specs/043-policy-engine-typed-runtime-gate-contract/plan.md`
  - `specs/043-policy-engine-typed-runtime-gate-contract/tasks.md`
  - `specs/043-policy-engine-typed-runtime-gate-contract/task-execution-log.md`
  - `.ai-sdlc/work-items/043-policy-engine-typed-runtime-gate-contract/*`
- **可并行**：否
- **验收标准**：
  1. 已明确 043 只做 typed runtime-gate policy consume seam；
  2. 已明确 043 只消费 042 已冻结的 shared read contract；
  3. 已明确 043 不引入新的 policy、schema、测试平台、manifest、archive metadata 或 read facade；
  4. Hermes Agent 专家与 Anthropic Manager 专家复核后无 blocking/P1。
- **验证**：
  - `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`
  - 人工审阅 `spec.md / plan.md / tasks.md / .ai-sdlc` 元数据与 Task 14 边界一致
- **完成情况**：
  1. 已新增 `Task 14` 到总实施计划，并挂到 `specs/043-policy-engine-typed-runtime-gate-contract/`；
  2. 已创建 `spec.md / plan.md / tasks.md / task-execution-log.md` 与 `.ai-sdlc/work-items/043-*` 基线；
  3. 已把 043 收紧为 policy-engine typed runtime-gate consume seam，而不是测试平台或 e2e 改造；
  4. Hermes Agent 专家与 Anthropic Manager 专家复核均无 blocking/P1。

## Task 43.2 写失败测试锁定 typed runtime-gate policy contract

- **任务编号**：T432
- **状态**：未开始
- **目标**：用失败测试先锁定 `policy engine` 对 runtime-gate evidence 的唯一 consume surface。
- **文件**：
  - `tests/test_watchdog_policy_engine.py`
- **可并行**：否
- **验收标准**：
  1. 覆盖 policy engine 不得继续手工消费 raw verdict dict；
  2. 覆盖 formal report pass verdict 在缺 bundle、partial bundle 或 malformed evidence 下必须 fail closed；
  3. 覆盖 `report:resident_default` 默认态不应被误伤成 formal report drift/blocker。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_policy_engine.py`

## Task 43.3 实现最小 typed runtime-gate helper 与 policy engine 收口

- **任务编号**：T433
- **状态**：未开始
- **目标**：让 `policy engine` 只通过 shared typed runtime-gate contract 解释 release-gate state。
- **文件**：
  - `src/watchdog/services/policy/engine.py`
  - `src/watchdog/services/brain/release_gate_read_contract.py`
  - `tests/test_watchdog_policy_engine.py`
- **可并行**：否
- **验收标准**：
  1. `evaluate_persisted_session_policy(...)` 与 `_runtime_gate_override(...)` 已改为消费 typed contract；
  2. missing / malformed / partial runtime-gate evidence 继续 fail closed；
  3. `report:resident_default` 默认态保持现有语义；
  4. 不引入 policy surface、schema、persistence、manifest 或测试平台变化。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_policy_engine.py tests/test_long_running_autonomy_doc_contracts.py`

## Task 43.4 更新执行日志与 handoff 摘要

- **任务编号**：T434
- **状态**：未开始
- **目标**：同步 formal docs、执行日志与 `.ai-sdlc` 元数据，固定后续 handoff。
- **文件**：
  - `specs/043-policy-engine-typed-runtime-gate-contract/task-execution-log.md`
  - `.ai-sdlc/work-items/043-policy-engine-typed-runtime-gate-contract/execution-plan.yaml`
  - `.ai-sdlc/work-items/043-policy-engine-typed-runtime-gate-contract/runtime.yaml`
  - `.ai-sdlc/work-items/043-policy-engine-typed-runtime-gate-contract/resume-pack.yaml`
  - `.ai-sdlc/work-items/043-policy-engine-typed-runtime-gate-contract/latest-summary.md`
- **可并行**：否
- **验收标准**：
  1. 执行日志已记录方案选择、red/green/review 闭环与 seam 收口；
  2. `.ai-sdlc` 元数据能准确恢复到下一执行入口；
  3. handoff 明确后续 policy/runtime gate consumer 只能复用 typed contract。
- **验证**：
  - `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`
  - 人工审阅执行日志与 `.ai-sdlc` 元数据一致

## Task 43.5 完成 043 整体验证并交接后续 work item

- **任务编号**：T435
- **状态**：未开始
- **目标**：完成 043 的整体验证，并把 typed runtime-gate policy contract 作为后续 work item 的正式依赖写回 handoff。
- **文件**：
  - `specs/043-policy-engine-typed-runtime-gate-contract/task-execution-log.md`
  - `.ai-sdlc/work-items/043-policy-engine-typed-runtime-gate-contract/latest-summary.md`
  - `.ai-sdlc/work-items/043-policy-engine-typed-runtime-gate-contract/resume-pack.yaml`
- **可并行**：否
- **验收标准**：
  1. 043 的 typed runtime-gate policy contract 已被明确为唯一正式 policy consume seam；
  2. handoff 明确后续 policy/runtime gate consumer 不得再复制 raw verdict dict 逻辑；
  3. 最后一轮 Hermes Agent 专家与 Anthropic Manager 专家复核均无 blocking/P1。
- **验证**：
  - `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`
  - 人工审阅 handoff 与总实施计划一致

## 整体验收

- 043 只负责把 policy engine 的 runtime-gate consume path 正式化成单一 typed contract。
- 043 完成后，后续任何 policy/runtime gate consumer 都只能复用 shared typed contract，不得再手工消费 raw verdict dict。
- 043 不得新增 policy、schema、persistence、manifest 或新的第二真相。
