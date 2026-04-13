# 执行日志：032-goal-contract-persistence-and-governance

> 对应规格：`specs/032-goal-contract-persistence-and-governance/spec.md`
>
> 对应任务：`specs/032-goal-contract-persistence-and-governance/tasks.md`

## 2026-04-13

- 完成 `T321`：已把总实施计划中的 `Task 3` 正式拆成 `WI-032`，并补齐 canonical `spec.md`、`plan.md`、`tasks.md`。
- 已将总实施计划回链到 `specs/032-goal-contract-persistence-and-governance/`，避免继续把 Task 3 只保留在总计划中。
- 当前边界已冻结为：
  - Goal Contract 只由 `Session Service` canonical events 驱动，不引入新的真相层；
  - `AI_AutoSDLC.stage / active_goal` 只保留 bootstrap context / deterministic-derived input 角色；
  - stage conflict、revision 与 child adoption 一并纳入 032 范围；
  - 不提前实现 Recovery Transaction、Brain、Feishu 或 release gate。
- 完成 `T322`：新增 red test 锁定“未显式提供 `explicit_deliverables / completion_signals` 时只能停在 `observe_only`”，确认旧实现会错误地产生 `autonomous_ready`。
- 为通过上述 red test，已去除 `GoalContractService.bootstrap_contract()` 对 deliverables 与 completion signals 的隐式默认填充，只保留显式输入。
- 验证记录：
  - `uv run pytest -q tests/test_watchdog_goal_contract.py::test_goal_contract_bootstrap_without_explicit_evidence_stays_observe_only` -> `1 passed in 0.16s`
  - `uv run pytest -q tests/test_watchdog_goal_contract.py tests/test_watchdog_goal_contract_stage_boundary.py` -> `5 passed in 0.19s`
  - `uv run pytest -q tests/test_watchdog_policy_engine.py tests/test_watchdog_session_spine_runtime.py -k goal_contract` -> `3 passed, 26 deselected in 0.68s`
- 下一执行入口切换为 `T323`，继续收敛 Goal Contract canonical events 与 query facade 的实现与验收。
