---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/032-goal-contract-persistence-and-governance/spec.md"
  - "specs/031-session-spine-events-projection-read-surface/spec.md"
---

# 实施计划：032-goal-contract-persistence-and-governance

## 目标

把阶段目标与完成判定收敛成由 `Session Service` canonical events 驱动的 `Goal Contract` 持久化对象，并给 policy / orchestrator 提供稳定治理入口。

## 架构摘要

- **Contract as event-governed truth**：当前 Goal Contract 只通过 `goal_contract_created / revised / adopted_by_child_session` 等 Session events 物化，不额外引入新的真相层。
- **Govern before autonomy**：先把 bootstrap、revision、stage conflict 与 child adoption 的边界冻结，再让 policy / orchestrator 把 contract 当成自动推进的显式门槛。
- **Context is input, not truth**：`AI_AutoSDLC.stage / active_goal`、任务标题与最近用户指令都只作为受控输入，不能直接覆盖当前 contract version。
- **Recovery comes later**：032 只把 Recovery 所需的 contract version inheritance 钩子补齐，不在本 work item 中实现完整 recovery transaction。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Canonical event contract | `src/watchdog/services/session_service/models.py`, `src/watchdog/services/session_service/service.py` | 冻结 Goal Contract 相关事件类型、payload 与写入屏障 |
| Goal contract facade | `src/watchdog/services/goal_contract/models.py`, `src/watchdog/services/goal_contract/service.py` | 定义 contract 结构、version replay、bootstrap / revision / adopt 查询与治理 |
| Upstream context bridge | `src/a_control_agent/storage/tasks_store.py` | 把 `AI_AutoSDLC.stage / active_goal` 收敛为 bootstrap context，而不是运行时真相 |
| Runtime consumers | `src/watchdog/services/session_spine/orchestrator.py`, `src/watchdog/services/policy/engine.py` | 把当前 Goal Contract 纳入自动决策输入与 fail-closed 门槛 |
| Verification | `tests/test_watchdog_goal_contract.py`, `tests/test_watchdog_goal_contract_stage_boundary.py`, `tests/test_watchdog_policy_engine.py`, `tests/test_watchdog_session_spine_runtime.py` | 锁定 lifecycle、stage conflict、治理降级与 runtime 接入 |

## 边界纪律

- 032 只做 Goal Contract 持久化与治理，不把 Recovery Transaction 顺手实现。
- 032 不把 `goal_contract` 做成独立 snapshot truth；projection 只能从 Session events 重放。
- 032 不允许 `AI_AutoSDLC.stage / active_goal` 越过 Goal Contract 直接成为运行时真相。
- 032 不把 Goal Closure Judge、Brain、Feishu 或 release gate 提前混入当前 work item。

## 依赖顺序

1. **先冻结 formal docs 与 Goal Contract 治理边界**
   - 把 lifecycle、stage conflict、child adoption 与 degrade-to-suggest-only 的规则写进 formal docs；
   - 明确 032 只提供 Goal Contract truth，不实现 Recovery / Brain。
2. **再写失败测试锁生命周期与阶段边界**
   - 先证明当前系统仍没有 Goal Contract canonical object；
   - 锁住 stage / active_goal 不能静默覆盖当前目标。
3. **再实现 Goal Contract 持久化与 facade**
   - 在 Session Service 中补齐 create / revise / adopt event；
   - 让 `goal_contract/service.py` 从 Session events 物化最新 contract。
4. **再重接 policy / orchestrator / context bridge**
   - 把 policy 与 runtime 读口径切到 Goal Contract facade；
   - 把不完整 contract 自动降级到 observe-only / suggest-only。
5. **最后跑回归并交接给 Recovery work item**
   - 确认后续 Recovery 只需消费显式 contract version 与 adopt lineage；
   - handoff 明确不再把 stage / active_goal 当成真相层。

## 分阶段计划

### Phase 1：冻结 032 formal docs 与 Goal Contract 边界

交付内容：

- `specs/032-goal-contract-persistence-and-governance/spec.md`
- `specs/032-goal-contract-persistence-and-governance/plan.md`
- `specs/032-goal-contract-persistence-and-governance/tasks.md`

关键原则：

- 先把 Goal Contract 作为 event-governed truth 写死；
- 明确 stage conflict 与 child adoption 也是 032 的正式范围。

### Phase 2：写失败测试锁生命周期与 stage boundary

交付内容：

- `tests/test_watchdog_goal_contract.py`
- `tests/test_watchdog_goal_contract_stage_boundary.py`

关键原则：

- 先锁 bootstrap / revision / adopt 的 version 语义；
- 再锁 `AI_AutoSDLC.stage / active_goal` 只能作为 context。

### Phase 3：实现 Goal Contract facade 与 canonical events

交付内容：

- `src/watchdog/services/session_service/models.py`
- `src/watchdog/services/session_service/service.py`
- `src/watchdog/services/goal_contract/models.py`
- `src/watchdog/services/goal_contract/service.py`

关键原则：

- current contract 只能从 events 重建；
- version 切换必须经过 canonical write barrier。

### Phase 4：切换 policy / orchestrator 的目标治理读口径

交付内容：

- `src/a_control_agent/storage/tasks_store.py`
- `src/watchdog/services/session_spine/orchestrator.py`
- `src/watchdog/services/policy/engine.py`
- `tests/test_watchdog_policy_engine.py`
- `tests/test_watchdog_session_spine_runtime.py`

关键原则：

- runtime 只消费当前 Goal Contract；
- contract 缺失或冲突时必须 fail-closed 或降级到建议态。

### Phase 5：整体验证与 Recovery handoff

交付内容：

- `tests/test_watchdog_goal_contract.py`
- `tests/test_watchdog_goal_contract_stage_boundary.py`
- `tests/test_watchdog_policy_engine.py`
- `tests/test_watchdog_session_spine_runtime.py`
- `specs/032-goal-contract-persistence-and-governance/task-execution-log.md`

关键原则：

- 032 结束时 Goal Contract 必须成为显式治理对象；
- 下一 work item 可以专注 Recovery Transaction，而不是继续猜当前目标版本。

## 测试计划

- `tests/test_watchdog_goal_contract.py`
  - bootstrap、revision、child adoption、event replay 与缺失字段降级
- `tests/test_watchdog_goal_contract_stage_boundary.py`
  - `stage / active_goal` 冲突检测、静默覆盖阻断与人工确认前门槛
- `tests/test_watchdog_policy_engine.py`
  - policy 决策读取 Goal Contract，并在 contract 不完整时降级
- `tests/test_watchdog_session_spine_runtime.py`
  - orchestrator / recovery entrypoint 只通过 Goal Contract version 继续

## 主要风险与应对

### 风险 1：Goal Contract 又退化成新的 snapshot truth

应对：

- current version 只能由 Session events replay 得出；
- service facade 只提供 projection，不单独持久化当前态。

### 风险 2：`AI_AutoSDLC.stage / active_goal` 仍然能静默覆盖当前目标

应对：

- 先写 stage boundary 失败测试；
- 任何冲突都必须写入冲突事实并阻断自动推进。

### 风险 3：child session 恢复时目标版本丢失

应对：

- adopt event 明确记录继承的 contract version；
- handoff / recovery 只消费显式 version，不猜测 parent 当前摘要。

## 验收口径

只有当以下条件同时满足，032 才算完成：

1. Goal Contract 已成为 `Session Service` canonical events 驱动的一等持久化对象；
2. 当前有效 contract version 只能由 Session events replay 得出；
3. `AI_AutoSDLC.stage / active_goal` 已收敛为 context input，不再静默覆盖当前目标；
4. policy / orchestrator 已把 Goal Contract 当成自动推进的显式门槛；
5. 下一 work item 可以直接基于 Goal Contract version + Session projection 推进 Recovery Transaction。
