---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/033-recovery-transaction-lineage/spec.md"
  - "specs/032-goal-contract-persistence-and-governance/spec.md"
---

# 实施计划：033-recovery-transaction-lineage

## 目标

把 interruption recovery 收敛成由 `Session Service` canonical truth 驱动的恢复事务，保证 frozen handoff packet、child session、lineage commit 与 parent cooling 之间的顺序、幂等和去重边界可验证。

## 架构摘要

- **Transaction before action**：恢复不再只是调用 handoff/resume，而是显式记录 `recovery_tx_started -> ... -> recovery_tx_completed` 的事务链。
- **One active transaction per recovery key**：同一个 `recovery_key` 任何时刻只能有一个活跃事务，避免重复恢复制造多个 child session。
- **Lineage before closure**：child session 创建后先进入 `lineage_pending`，只有 lineage commit 成功后才允许 parent cooling 与 completed。
- **Goal Contract is inherited truth**：恢复事务直接消费 `WI-032` 产出的 `goal_contract_version / contract_id / provenance`，不回退到 stage 文本判断恢复目标。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Recovery truth writer | `src/watchdog/services/session_service/service.py` | 持久化 recovery canonical event 顺序、状态机与 active transaction guard |
| Recovery executor | `src/watchdog/services/session_spine/recovery.py` | 以事务语义驱动 handoff / resume，并把结果落回 `Session Service` |
| Runtime wiring | `src/watchdog/services/session_spine/orchestrator.py`, `src/watchdog/services/session_spine/actions.py` | 在 runtime / action 入口消费 recovery truth，而不是把恢复当成自由动作 |
| Compatibility facade | `src/watchdog/services/approvals/service.py` | 识别同一 `recovery_key` 的活跃事务，阻止重复恢复入口 |
| Verification | `tests/test_watchdog_recovery_transaction.py`, `tests/test_watchdog_session_service.py`, `tests/test_watchdog_session_spine_runtime.py`, `tests/test_watchdog_delivery_worker.py` | 锁定状态机顺序、active transaction guard、runtime 兼容与 delivery 幂等 |

## 边界纪律

- 033 只收敛 Recovery Transaction 与 lineage，不把 Brain、Memory Hub、Feishu 一并混入。
- 033 不重写 `Goal Contract` 逻辑，只消费其 version / provenance 作为恢复事务输入。
- 033 不把恢复结果存成新的 snapshot truth；所有当前态都必须可由 Session events 与 recovery records 重放。
- 033 只做最小必要修改，优先沿用当前 `session_service` 里已经存在的 recovery primitives。

## 依赖顺序

1. **先冻结 formal docs 与 033 work item 元数据**
   - 把总实施计划中的 `Task 4` 正式回链到 `WI-033`；
   - 明确活跃事务去重、lineage pending 和 parent cooling 是正式验收边界。
2. **再写失败测试锁定事务状态机**
   - 先证明当前实现没有把 `lineage_pending` / `parent_cooling` 真正持久化到 recovery 状态序列；
   - 先证明同一 `recovery_key` 的活跃事务还没有被阻止。
3. **再补最小实现收紧事务顺序与去重**
   - 在 `SessionService.record_recovery_execution()` 中补 active transaction guard；
   - 补齐 `lineage_pending`、`parent_cooling` 的 recovery status 持久化顺序。
4. **再验证 runtime / delivery 兼容面**
   - 确认 recovery executor、runtime 和 delivery 仍能沿同一 truth 工作；
   - 确认不引入新的重复 child session 或 lineage 漏洞。
5. **最后写交接与验证摘要**
   - 固定 handoff：下一 work item 直接消费 recovery truth 与 lineage，而不是再回头猜恢复状态。

## 分阶段计划

### Phase 1：冻结 033 formal docs 与执行元数据

交付内容：

- `specs/033-recovery-transaction-lineage/spec.md`
- `specs/033-recovery-transaction-lineage/plan.md`
- `specs/033-recovery-transaction-lineage/tasks.md`
- `.ai-sdlc/work-items/033-recovery-transaction-lineage/*`

关键原则：

- 先把 033 的范围限制在 Recovery Transaction + lineage；
- 明确下一实现从现有 `session_service` recovery primitives 继续，而不是另起炉灶。

### Phase 2：写失败测试锁事务顺序与 active transaction guard

交付内容：

- `tests/test_watchdog_recovery_transaction.py`
- `tests/test_watchdog_session_service.py`

关键原则：

- 红测优先锁定 `lineage_pending` 与 `parent_cooling`；
- 红测优先锁定“同一 recovery_key 只能有一个活跃事务”。

### Phase 3：实现最小 recovery transaction 收口

交付内容：

- `src/watchdog/services/session_service/service.py`
- `src/watchdog/services/session_spine/recovery.py`
- `src/watchdog/services/session_spine/orchestrator.py`
- `src/watchdog/services/session_spine/actions.py`
- `src/watchdog/services/approvals/service.py`

关键原则：

- 先收紧 canonical writer，再决定 runtime wiring 是否需要最小补线；
- 保持 child creation、lineage commit 与 parent cooling 的顺序可重放。

### Phase 4：运行验证并确认兼容面不回退

交付内容：

- `tests/test_watchdog_recovery_transaction.py`
- `tests/test_watchdog_recovery_execution.py`
- `tests/test_watchdog_session_spine_runtime.py`
- `tests/test_watchdog_delivery_worker.py`

关键原则：

- recovery 成为事务后，既有 recovery executor 和 delivery 仍然可用；
- 不允许新增重复恢复或 parent 提前关闭的问题。

### Phase 5：交接到后续 Brain / Memory Hub work item

交付内容：

- `specs/033-recovery-transaction-lineage/task-execution-log.md`
- `.ai-sdlc/work-items/033-recovery-transaction-lineage/latest-summary.md`

关键原则：

- handoff 必须说明 recovery 已统一到 canonical truth；
- 后续 work item 只消费 recovery truth / lineage / Goal Contract facade。

## 测试计划

- `tests/test_watchdog_recovery_transaction.py`
  - recovery status 序列必须包含 `lineage_pending` 与 `parent_cooling`
  - 同一 `recovery_key` 的活跃事务必须阻止第二次 child creation
- `tests/test_watchdog_session_service.py`
  - canonical event 顺序与 recovery status 顺序保持一致
- `tests/test_watchdog_recovery_execution.py`
  - Goal Contract version / source packet / child adoption 继续沿 recovery transaction 保持稳定
- `tests/test_watchdog_session_spine_runtime.py`
  - runtime 相关入口继续消费 recovery truth，不发生行为回退
- `tests/test_watchdog_delivery_worker.py`
  - delivery / side effect 层不会把恢复当成可无限重复的自由按钮

## 主要风险与应对

### 风险 1：已经存在 child session，但 lineage 还没 commit 就被当成恢复完成

应对：

- 明确 `lineage_pending` 为正式状态；
- 只有 `lineage_committed` 之后才允许 `parent_cooling` 和 `completed`。

### 风险 2：同一故障反复触发，产生多个 child session

应对：

- 在 canonical writer 层按 `recovery_key` 检查活跃事务；
- 对非终态事务直接 fail-closed，避免继续创建新的 child session。

### 风险 3：恢复又回退到 `stage / active_goal` 文本驱动

应对：

- lineage 与 recovery records 继续保留 `goal_contract_version`；
- runtime / audit 读取恢复状态时只看 recovery truth 与 Goal Contract facade。

## 验收口径

只有当以下条件同时满足，033 才算完成：

1. recovery status 序列已显式包含 `lineage_pending` 与 `parent_cooling`；
2. 同一 `recovery_key` 的活跃事务会阻止第二次 child session 创建；
3. child session、lineage commit、parent cooling 与 completed 的顺序可由 canonical records 重放；
4. recovery executor、runtime 与 delivery 相关验证通过且不回退；
5. 后续 work item 可以直接基于 recovery truth、lineage 与 Goal Contract facade 继续推进。
