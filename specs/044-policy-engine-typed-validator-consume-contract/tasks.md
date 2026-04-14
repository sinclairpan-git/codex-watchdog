# 任务分解：044-policy-engine-typed-validator-consume-contract

> 对应规格：`specs/044-policy-engine-typed-validator-consume-contract/spec.md`
>
> 对应计划：`specs/044-policy-engine-typed-validator-consume-contract/plan.md`

## Task 44.1 冻结 044 formal docs 与 validator seam 边界

- **任务编号**：T441
- **状态**：已完成（2026-04-14）
- **目标**：把总实施计划中的 `Task 15` 正式拆成 canonical execution work item，并把 044 收紧为 validator typed consume contract。
- **文件**：
  - `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
  - `specs/044-policy-engine-typed-validator-consume-contract/spec.md`
  - `specs/044-policy-engine-typed-validator-consume-contract/plan.md`
  - `specs/044-policy-engine-typed-validator-consume-contract/tasks.md`
  - `specs/044-policy-engine-typed-validator-consume-contract/task-execution-log.md`
  - `.ai-sdlc/work-items/044-policy-engine-typed-validator-consume-contract/*`
- **可并行**：否
- **验收标准**：
  1. 已明确 044 只做 typed validator consume seam；
  2. 已明确 044 只消费既有 `DecisionValidationVerdict` typed model；
  3. 已明确 044 不引入新的 policy、schema、测试平台、manifest、archive metadata 或 release-gate write helper；
  4. Hermes Agent 专家与 Anthropic Manager 专家复核后无 blocking/P1。
- **验证**：
  - `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`
  - 人工审阅 `spec.md / plan.md / tasks.md / .ai-sdlc` 元数据与 Task 15 边界一致
- **完成情况**：
  1. 已新增 `Task 15` 到总实施计划，并挂到 `specs/044-policy-engine-typed-validator-consume-contract/`；
  2. 已创建 `spec.md / plan.md / tasks.md / task-execution-log.md` 与 `.ai-sdlc/work-items/044-*` 基线；
  3. 已把 044 收紧为 `policy engine + resident runtime` 的 validator consume seam，而不是 release-gate write-side 或测试整理；
  4. Hermes Agent 专家与 Anthropic Manager 专家复核均无 blocking/P1。

## Task 44.2 写失败测试锁定 typed validator consume contract

- **任务编号**：T442
- **状态**：未开始
- **目标**：用失败测试先锁定 `policy engine` 与 resident runtime 对 validator evidence 的唯一 consume surface。
- **文件**：
  - `tests/test_watchdog_policy_engine.py`
  - `tests/test_watchdog_session_spine_runtime.py`
- **可并行**：否
- **验收标准**：
  1. 覆盖 consumer 不得继续手工消费 raw validator dict；
  2. 覆盖 missing / malformed / partial validator evidence 必须 fail closed；
  3. 覆盖合法 typed pass verdict 保持当前 allow path。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_policy_engine.py tests/test_watchdog_session_spine_runtime.py`

## Task 44.3 实现最小 typed validator helper 与 consumer 收口

- **任务编号**：T443
- **状态**：未开始
- **目标**：让 `policy engine` 与 resident runtime 只通过 shared typed validator contract 解释 validator state。
- **文件**：
  - `src/watchdog/services/brain/validator_read_contract.py`
  - `src/watchdog/services/policy/engine.py`
  - `src/watchdog/services/session_spine/orchestrator.py`
  - `tests/test_watchdog_policy_engine.py`
  - `tests/test_watchdog_session_spine_runtime.py`
- **可并行**：否
- **验收标准**：
  1. `evaluate_persisted_session_policy(...)` 与 `_runtime_gate_override(...)` 已改为消费 typed validator contract；
  2. resident runtime 的 auto-execute/runtime-gate 判断已复用同一 typed helper；
  3. missing / malformed / partial validator evidence 继续 fail closed；
  4. 不引入 policy surface、schema、persistence、manifest 或 release-gate write-side 变化。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_policy_engine.py tests/test_watchdog_session_spine_runtime.py tests/test_long_running_autonomy_doc_contracts.py`

## Task 44.4 更新执行日志与 handoff 摘要

- **任务编号**：T444
- **状态**：未开始
- **目标**：同步 formal docs、执行日志与 `.ai-sdlc` 元数据，固定后续 handoff。
- **文件**：
  - `specs/044-policy-engine-typed-validator-consume-contract/task-execution-log.md`
  - `.ai-sdlc/work-items/044-policy-engine-typed-validator-consume-contract/execution-plan.yaml`
  - `.ai-sdlc/work-items/044-policy-engine-typed-validator-consume-contract/runtime.yaml`
  - `.ai-sdlc/work-items/044-policy-engine-typed-validator-consume-contract/resume-pack.yaml`
  - `.ai-sdlc/work-items/044-policy-engine-typed-validator-consume-contract/latest-summary.md`
- **可并行**：否
- **验收标准**：
  1. 执行日志已记录方案选择、red/green/review 闭环与 seam 收口；
  2. `.ai-sdlc` 元数据能准确恢复到下一执行入口；
  3. handoff 明确后续 validator consumer 只能复用 typed contract。
- **验证**：
  - `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`
  - 人工审阅执行日志与 `.ai-sdlc` 元数据一致

## Task 44.5 完成 044 整体验证并交接后续 work item

- **任务编号**：T445
- **状态**：未开始
- **目标**：完成 044 的整体验证，并把 typed validator consume contract 作为后续 work item 的正式依赖写回 handoff。
- **文件**：
  - `specs/044-policy-engine-typed-validator-consume-contract/task-execution-log.md`
  - `.ai-sdlc/work-items/044-policy-engine-typed-validator-consume-contract/latest-summary.md`
  - `.ai-sdlc/work-items/044-policy-engine-typed-validator-consume-contract/resume-pack.yaml`
- **可并行**：否
- **验收标准**：
  1. 044 的 typed validator consume contract 已被明确为唯一正式 consumer seam；
  2. handoff 明确后续 validator consumer 不得再复制 raw validator dict 逻辑；
  3. 最后一轮 Hermes Agent 专家与 Anthropic Manager 专家复核均无 blocking/P1。
- **验证**：
  - `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`
  - 人工审阅 handoff 与总实施计划一致

## 整体验收

- 044 只负责把 policy engine 与 resident runtime 的 validator consume path 正式化成单一 typed contract。
- 044 完成后，后续任何 validator consumer 都只能复用 shared typed contract，不得再手工消费 raw validator dict。
- 044 不得新增 policy、schema、persistence、manifest 或新的第二真相。
