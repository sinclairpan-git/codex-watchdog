# 执行日志：033-recovery-transaction-lineage

> 对应规格：`specs/033-recovery-transaction-lineage/spec.md`
>
> 对应任务：`specs/033-recovery-transaction-lineage/tasks.md`

## 2026-04-13

- 完成 `T331`：已把总实施计划中的 `Task 4` 正式回链到 `specs/033-recovery-transaction-lineage/`，不再让 Recovery Transaction 只停留在总计划条目里。
- 已冻结 033 的 formal docs 边界：
  - 033 只负责 Recovery Transaction + lineage；
  - 必须消费 `WI-032` 交付的 `goal_contract_version / contract_id / provenance` 与 Session projection；
  - 同一 `recovery_key` 只能有一个活跃事务；
  - `lineage_pending` 与 `parent_cooling` 是正式事务状态，不只是模型枚举中的预留值。
- 已确认现状断点：
  - `SessionService.record_recovery_execution()` 已能写入 `recovery_tx_started`、`handoff_packet_frozen`、`child_session_created`、`lineage_committed`、`parent_session_closed_or_cooled`、`recovery_tx_completed`；
  - 但当前 recovery status 序列仍缺少实际持久化的 `lineage_pending` 与 `parent_cooling`；
  - 当前尚未对同一 `recovery_key` 的非终态事务做 fail-closed 去重。
- 完成 `T332`：新增 `tests/test_watchdog_recovery_transaction.py`，先用 red test 锁定两个关键缺口：
  - recovery status 序列必须包含 `lineage_pending` 与 `parent_cooling`；
  - 同一 `recovery_key` 若已有非终态事务，新的恢复调用必须报错，不能再创建第二个 child session。
- red test 验证记录：
  - `uv run pytest -q tests/test_watchdog_recovery_transaction.py` -> `2 failed in 0.45s`
- 完成 `T333`：在 `src/watchdog/services/session_service/service.py` 中做最小实现收口：
  - 增加 `_assert_no_conflicting_active_recovery_transaction()`，按 `recovery_key` 检查同 parent 的最新恢复记录；若最新事务非终态且 transaction id 不同，则 fail-closed 报错；
  - 在 `child_created` 之后、lineage commit 之前持久化 `lineage_pending`；
  - 在 `parent_session_closed_or_cooled` 事件之后、`completed` 之前持久化 `parent_cooling`；
  - 保留对同一事务 id 的幂等重放能力，不阻止稳定 transaction identity 的 replay。
- `T333` 局部验证记录：
  - `uv run pytest -q tests/test_watchdog_recovery_transaction.py tests/test_watchdog_session_service.py` -> `7 passed in 0.20s`
- 完成 `T334`：同步旧测试到新的 canonical status 序列，并跑通 recovery/runtime/delivery 相关回归。
- `T334` 验证记录：
  - `uv run pytest -q tests/test_watchdog_recovery_transaction.py tests/test_watchdog_recovery_execution.py tests/test_watchdog_action_execution.py tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_delivery_worker.py` -> `61 passed in 3.43s`
  - `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py` -> `3 passed in 0.03s`
- 完成 `T335`：已更新 formal docs、执行日志与 `.ai-sdlc/work-items/033-*` 元数据到完成态。
- 当前结论：
  - `WI-033` 已完成，恢复路径现在是显式的 Recovery Transaction，而不是松散的 handoff/resume 动作串；
  - recovery status 已与架构文档一致，包含 `lineage_pending` 与 `parent_cooling`；
  - 同一 `recovery_key` 的非终态事务会阻止第二个 child session，被迫沿既有 frozen packet / lineage 继续；
  - 后续 work item 应直接消费 recovery truth、lineage 与 Goal Contract facade，而不是重新回退到 `AI_AutoSDLC.stage / active_goal` 文本驱动。
