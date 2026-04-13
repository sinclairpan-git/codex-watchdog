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

- 完成 `T323`：修正 `GoalContractService` 对新 `GoalContractSnapshot` 结构的构造与演进逻辑，补齐 deterministic `contract_id`、`status`、`constraints` 与 `provenance` 的 bootstrap / revision / adoption 全路径保持。
- Goal Contract canonical events 现在把 `contract_id` 写入 `related_ids`，后续 Recovery / audit 可以沿 Session events 直接追溯当前 contract 与 lineage，而不需要额外 snapshot truth。
- 完成 `T324`：`tasks_store`、policy 与 runtime 相关路径已经切到 Goal Contract 治理口径；不完整 contract 不再被直接视为可自动推进，而是降级为受控建议或人工决策。
- 完成 `T325`：已将 032 work item 收口，并明确 handoff 约束为“后续 Recovery 只消费 Goal Contract version / contract identity / provenance 与 Session projection”。
- 补充验证记录：
  - `uv run pytest -q tests/test_watchdog_goal_contract.py tests/test_watchdog_goal_contract_stage_boundary.py` -> `6 passed in 0.40s`
  - `uv run pytest -q tests/test_watchdog_policy_engine.py tests/test_watchdog_session_spine_runtime.py -k goal_contract` -> `3 passed, 26 deselected in 1.49s`
  - `uv run pytest -q tests/test_watchdog_goal_contract.py tests/test_watchdog_goal_contract_stage_boundary.py tests/test_watchdog_policy_engine.py tests/test_watchdog_session_spine_runtime.py` -> `35 passed in 3.15s`
- 当前结论：
  - `WI-032` 已完成，Goal Contract 已成为 session-event-first 的治理读面；
  - `AI_AutoSDLC.stage / active_goal` 继续保留为 bootstrap context / compatibility input，但不能覆盖当前 contract；
  - 后续 Recovery work item 应直接消费 Goal Contract version、child adoption lineage 与 Session projection，而不是重新回退到 stage 文本驱动。
