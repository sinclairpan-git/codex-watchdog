# 任务分解：032-goal-contract-persistence-and-governance

> 对应规格：`specs/032-goal-contract-persistence-and-governance/spec.md`
>
> 对应计划：`specs/032-goal-contract-persistence-and-governance/plan.md`

## Task 32.1 冻结 032 formal docs 与 Goal Contract 执行边界

- **任务编号**：T321
- **状态**：已完成（2026-04-13）
- **目标**：把总实施计划中的 `Task 3` 正式拆成 canonical execution work item，并写清 Goal Contract 的范围与非目标。
- **文件**：
  - `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
  - `specs/032-goal-contract-persistence-and-governance/spec.md`
  - `specs/032-goal-contract-persistence-and-governance/plan.md`
  - `specs/032-goal-contract-persistence-and-governance/tasks.md`
- **可并行**：否
- **验收标准**：
  1. 已明确 032 只做 Goal Contract 持久化与治理，不提前实现 Recovery / Brain；
  2. 已明确 Goal Contract 只能由 Session events replay 得出，而不是新 snapshot truth；
  3. 已明确 `AI_AutoSDLC.stage / active_goal` 只作为 context input，不得覆盖当前 contract。
- **验证**：人工审阅 formal docs 与总实施计划的 Task 3 边界一致。
- **完成情况**：032 已正式建为独立 work item，下一执行入口固定为 `T322`。

## Task 32.2 写失败测试锁定 Goal Contract 生命周期与阶段边界

- **任务编号**：T322
- **状态**：已完成（2026-04-13）
- **目标**：用失败测试锁定 Goal Contract 的 bootstrap、revision、adopt 与 stage conflict 规则。
- **文件**：
  - `tests/test_watchdog_goal_contract.py`
  - `tests/test_watchdog_goal_contract_stage_boundary.py`
  - `tests/test_watchdog_session_service.py`
- **可并行**：否
- **验收标准**：
  1. 覆盖 `goal_contract_created / revised / adopted_by_child_session` 的 version 语义；
  2. 覆盖缺失 `explicit_deliverables / completion_signals` 时只能停在 `observe-only` 或 `suggest-only`；
  3. 覆盖 `AI_AutoSDLC.stage / active_goal` 与当前 contract 冲突时必须记录冲突并阻断自动推进。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_goal_contract.py tests/test_watchdog_goal_contract_stage_boundary.py`
- **完成情况**：
  1. 新增 red test，锁定“未显式提供 `explicit_deliverables / completion_signals` 时不得靠默认值进入 `autonomous_ready`”；
  2. 已去除 `bootstrap_contract()` 对 deliverables 与 completion signals 的隐式兜底；
  3. 验证结果：`5 passed in 0.19s`，下一执行入口切换为 `T323`。

## Task 32.3 实现 Goal Contract canonical events 与 query facade

- **任务编号**：T323
- **状态**：未开始
- **目标**：在 `Session Service` 与 `goal_contract` 服务层实现 Goal Contract 的持久化、replay 与治理 facade。
- **文件**：
  - `src/watchdog/services/session_service/models.py`
  - `src/watchdog/services/session_service/service.py`
  - `src/watchdog/services/goal_contract/models.py`
  - `src/watchdog/services/goal_contract/service.py`
- **可并行**：否
- **验收标准**：
  1. 当前 Goal Contract 只由 Session events replay 得出；
  2. bootstrap、revision、child adoption 都有 canonical event；
  3. Goal Contract facade 不会成为独立真相层。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_goal_contract.py`

## Task 32.4 重接 context bridge、policy 与 orchestrator 的目标治理读口径

- **任务编号**：T324
- **状态**：未开始
- **目标**：让 tasks store、policy 与 runtime 消费 Goal Contract facade，并把不完整或冲突 contract 降级为受控建议态。
- **文件**：
  - `src/a_control_agent/storage/tasks_store.py`
  - `src/watchdog/services/session_spine/orchestrator.py`
  - `src/watchdog/services/policy/engine.py`
  - `tests/test_watchdog_policy_engine.py`
  - `tests/test_watchdog_session_spine_runtime.py`
- **可并行**：否
- **验收标准**：
  1. policy / orchestrator 已显式读取当前 Goal Contract；
  2. `AI_AutoSDLC.stage / active_goal` 不再直接覆盖当前目标；
  3. contract 缺失关键字段或发生冲突时，系统会 fail-closed 或降级到建议态。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_goal_contract_stage_boundary.py tests/test_watchdog_policy_engine.py tests/test_watchdog_session_spine_runtime.py`

## Task 32.5 完成 032 验证并交接到 Recovery work item

- **任务编号**：T325
- **状态**：未开始
- **目标**：跑完整体验证并写清 handoff，使后续 Recovery work item 直接消费 Goal Contract version 与 adopt lineage。
- **文件**：
  - `tests/test_watchdog_goal_contract.py`
  - `tests/test_watchdog_goal_contract_stage_boundary.py`
  - `tests/test_watchdog_policy_engine.py`
  - `tests/test_watchdog_session_spine_runtime.py`
  - `specs/032-goal-contract-persistence-and-governance/task-execution-log.md`
- **可并行**：否
- **验收标准**：
  1. 032 所需测试全部通过；
  2. formal docs 与执行日志已更新到最终状态；
  3. handoff 明确后续 Recovery 只消费 Goal Contract version / adoption，不再把 stage 文本当真相。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_goal_contract.py tests/test_watchdog_goal_contract_stage_boundary.py tests/test_watchdog_policy_engine.py tests/test_watchdog_session_spine_runtime.py`

## 整体验收

- 032 是长时运行自治一期的“Task 3”，只负责把阶段目标治理收敛到 Goal Contract。
- 032 完成后，policy / orchestrator / Recovery 前置条件应优先消费 Goal Contract facade，而不是继续依赖 `AI_AutoSDLC.stage / active_goal` 文本。
- 032 不实现 Recovery Transaction、Brain、Memory Hub、Feishu 正式能力或 release gate。
