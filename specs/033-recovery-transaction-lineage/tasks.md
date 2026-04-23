# 任务分解：033-recovery-transaction-lineage

> 对应规格：`specs/033-recovery-transaction-lineage/spec.md`
>
> 对应计划：`specs/033-recovery-transaction-lineage/plan.md`

## Task 33.1 冻结 033 formal docs 与 Recovery Transaction 边界

- **任务编号**：T331
- **状态**：已完成（2026-04-13）
- **目标**：把总实施计划中的 `Task 4` 正式拆成 canonical execution work item，并冻结恢复事务与 lineage 的边界。
- **文件**：
  - `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
  - `specs/033-recovery-transaction-lineage/spec.md`
  - `specs/033-recovery-transaction-lineage/plan.md`
  - `specs/033-recovery-transaction-lineage/tasks.md`
- **可并行**：否
- **验收标准**：
  1. 已明确 033 只做 Recovery Transaction + lineage，不提前实现 Brain / Memory Hub / Feishu；
  2. 已明确同一 `recovery_key` 只能有一个活跃事务；
  3. 已明确 `lineage_pending` 与 `parent_cooling` 是正式事务状态，不只是预留枚举。
- **验证**：人工审阅 formal docs 与总实施计划中的 Task 4 边界一致。
- **完成情况**：
  1. 已将总实施计划中的 `Task 4` 回链到 `specs/033-recovery-transaction-lineage/`；
  2. 已补齐 `spec.md`、`plan.md`、`tasks.md` 与 `.ai-sdlc/work-items/033-*` 元数据；
  3. 已冻结 033 只负责 Recovery Transaction + lineage，后续只消费 Goal Contract facade 与 Session projection。

## Task 33.2 写失败测试锁定恢复事务状态机与活跃事务去重

- **任务编号**：T332
- **状态**：已完成（2026-04-13）
- **目标**：用失败测试锁定恢复事务的 canonical status 顺序和 active transaction guard。
- **文件**：
  - `tests/test_watchdog_recovery_transaction.py`
  - `tests/test_watchdog_session_service.py`
- **可并行**：否
- **验收标准**：
  1. 覆盖 `started -> packet_frozen -> child_created -> lineage_pending -> lineage_committed -> parent_cooling -> completed`；
  2. 覆盖同一 `recovery_key` 已存在非终态事务时，新的恢复调用会被拒绝；
  3. 覆盖 parent 不会在 `lineage_committed` 前被视为已接续完成。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_recovery_transaction.py`
- **完成情况**：
  1. 新增 `tests/test_watchdog_recovery_transaction.py`，锁定 recovery status 序列必须包含 `lineage_pending` 与 `parent_cooling`；
  2. 新增 red test，锁定同一 `recovery_key` 已存在非终态事务时必须拒绝第二次恢复；
  3. 初次验证结果为 `2 failed in 0.45s`，失败点准确暴露当前实现缺少中间态持久化与 active transaction guard。

## Task 33.3 实现最小 Recovery Transaction canonical writer 与 guard

- **任务编号**：T333
- **状态**：已完成（2026-04-13）
- **目标**：在 `Session Service` 中补齐 recovery status 顺序与 active transaction guard，并按最小需要补 runtime 接线。
- **文件**：
  - `src/watchdog/services/session_service/service.py`
  - `src/watchdog/services/session_spine/recovery.py`
  - `src/watchdog/services/session_spine/orchestrator.py`
  - `src/watchdog/services/session_spine/actions.py`
  - `src/watchdog/services/approvals/service.py`
- **可并行**：否
- **验收标准**：
  1. canonical recovery writer 会写入 `lineage_pending` 与 `parent_cooling`；
  2. 同一 `recovery_key` 的非终态事务会阻止第二次 child creation；
  3. runtime / approvals 相关入口继续沿 recovery truth 工作，不引入第二真相层。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_recovery_transaction.py tests/test_watchdog_session_service.py`
- **完成情况**：
  1. `SessionService.record_recovery_execution()` 已补齐 `lineage_pending` 与 `parent_cooling` 的 canonical recovery status；
  2. 已新增按 `recovery_key` 检查非终态事务的 fail-closed guard，只允许同一事务幂等重放，不允许新事务重复创建 child session；
  3. 更新后的局部验证结果为 `7 passed in 0.20s`。

## Task 33.4 运行 Recovery / runtime / delivery 相关验证

- **任务编号**：T334
- **状态**：已完成（2026-04-13）
- **目标**：确认 Recovery Transaction 收口后，既有 recovery executor、runtime 与 delivery 行为不回退。
- **文件**：
  - `tests/test_watchdog_recovery_transaction.py`
  - `tests/test_watchdog_recovery_execution.py`
  - `tests/test_watchdog_action_execution.py`
  - `tests/test_watchdog_session_spine_runtime.py`
  - `tests/test_watchdog_delivery_worker.py`
- **可并行**：否
- **验收标准**：
  1. recovery 相关测试通过；
  2. runtime / delivery 没有因为新增事务边界产生行为回退；
  3. 仍能保留 Goal Contract version、source packet 与 child adoption truth。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_recovery_transaction.py tests/test_watchdog_recovery_execution.py tests/test_watchdog_action_execution.py tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_delivery_worker.py`
- **完成情况**：
  1. 已同步旧测试对 recovery status 序列的断言，使其与新的 canonical 状态机一致；
  2. 验证结果为 `61 passed in 3.43s`；
  3. 额外验证 `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`，结果为 `3 passed in 0.03s`。

## Task 33.5 更新执行日志与 handoff 摘要

- **任务编号**：T335
- **状态**：已完成（2026-04-13）
- **目标**：同步 formal docs、task execution log 与 `.ai-sdlc` 元数据，固定后续 handoff。
- **文件**：
  - `specs/033-recovery-transaction-lineage/task-execution-log.md`
  - `.ai-sdlc/work-items/033-recovery-transaction-lineage/execution-plan.yaml`
  - `.ai-sdlc/work-items/033-recovery-transaction-lineage/runtime.yaml`
  - `.ai-sdlc/work-items/033-recovery-transaction-lineage/resume-pack.yaml`
  - `.ai-sdlc/work-items/033-recovery-transaction-lineage/latest-summary.md`
- **可并行**：否
- **验收标准**：
  1. 执行日志已记录 red/green 验证与关键设计决策；
  2. `.ai-sdlc` 元数据能准确恢复到下一执行入口；
  3. handoff 明确后续工作项只消费 recovery truth / lineage / Goal Contract facade。
- **验证**：人工审阅执行日志与 `.ai-sdlc` 元数据一致。
- **完成情况**：
  1. 已更新 `task-execution-log.md` 记录 red/green 闭环与实现决策；
  2. `.ai-sdlc/work-items/033-*` 元数据已同步到完成态；
  3. handoff 已固定为：后续 Brain / Memory Hub 等 work item 只消费 recovery truth、lineage 与 Goal Contract facade。

## 整体验收

- 033 是长时运行自治一期的“Task 4”，只负责把恢复从单步动作收敛成 Recovery Transaction + lineage。
- 033 完成后，恢复、审批、runtime 与 delivery 的相关路径都应把 `recovery_key` 识别和 lineage commit 当成 canonical truth。
- 033 不实现 Brain、Memory Hub、Feishu 控制面或 release gate。
