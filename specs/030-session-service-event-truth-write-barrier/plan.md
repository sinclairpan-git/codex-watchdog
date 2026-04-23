---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/030-session-service-event-truth-write-barrier/spec.md"
---

# 实施计划：030-session-service-event-truth-write-barrier

## 目标

把 `Session Service` 立成长时运行自治一期的 canonical 写入真源，并在 `policy -> command execution` 之间建立 fail-closed 写入闸门，使审批、通知、人工接管、命令租约、记忆降级与目标冲突都有统一可回放的 Session events 作为真相来源。

## 架构摘要

- **Write truth first**：先冻结 append-only Session events writer，再谈 projection、Goal Contract、Brain 与 Memory Hub 的上层能力。
- **Fail-closed before side effects**：任何需要落入执行面的命令、审批、通知与人工接管，都必须先写 canonical event；写入失败就中止，不允许“动作先发生、真相后补”。
- **Read surface stays compatible in 030**：030 只接管写面，不在本 work item 中重写 `session_spine` 读面；下一 work item 再做 projection 替换。
- **Future hooks, current scope**：030 只冻结 `memory_*` 与 `stage_goal_conflict_detected` 的事件位点和 query facade，不把完整 `Memory Hub` / `Goal Contract` 检测逻辑一并做完。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Canonical event contract | `src/watchdog/services/session_service/models.py` | `SessionEventRecord`、`SessionLineageRecord`、`RecoveryTransactionRecord` 与受控事件类型 |
| Append-only writer | `src/watchdog/services/session_service/store.py` | single-writer、原子追加、锁与幂等去重 |
| Session service orchestration | `src/watchdog/services/session_service/service.py` | 事件写入门面、最小 query facade、事件序列约束 |
| Policy write barrier | `src/watchdog/services/policy/engine.py`, `src/watchdog/services/policy/decisions.py` | 决策落账与 `command_created` 前置写入屏障 |
| Runtime integration | `src/watchdog/services/session_spine/orchestrator.py`, `src/watchdog/services/approvals/service.py` | 审批、通知、人工接管与命令租约热路径接入 Session Service |
| Verification | `tests/test_watchdog_session_service.py`, `tests/test_watchdog_session_service_atomicity.py`, `tests/test_watchdog_approval_loop.py`, `tests/test_watchdog_command_leases.py`, `tests/test_watchdog_policy_engine.py`, `tests/test_watchdog_session_spine_runtime.py` | 锁定事件顺序、fail-closed、租约恢复与非回归 |

## 边界纪律

- `030` 只拥有 canonical 写面、写入闸门和最小 query facade。
- `030` 不替换 `session_spine` 读面，不重写 projection / audit 查询。
- `030` 不实现完整 `Goal Contract`、`Memory Hub`、`Brain`、`Recovery orchestrator` 或 `Feishu`。
- `030` 只冻结 `stage_goal_conflict_detected` 的事件位点，不在本工作项中承诺完整自动冲突治理。

## 依赖顺序

1. **先冻结 formal docs 与事件边界**
   - 没有明确 work item 边界，后续实现会再次把 `Task 1` 漫射成“顺手改很多地方”。
   - 先把 030 从总实施计划中拆成 formal `spec / plan / tasks`。
2. **再冻结事件契约与失败测试**
   - 先把事件顺序、fail-closed、memory / goal conflict canonicalization 写成失败测试。
   - 没有失败测试，writer 容易退化成旁路日志。
3. **再做 writer / store**
   - append-only、single-writer、幂等恢复是整个写面地基。
   - 如果这里不稳，后面的 policy barrier 只会把不稳定点前移。
4. **再接 policy / orchestrator 热路径**
   - 把 `decision -> command`、`approval`、`notification`、`human override` 写前置。
   - 审批与运行时组件只保留兼容 facade，不再自建真源。
5. **最后补 lease / requeue 与整体验证**
   - 030 结束时只要求写面成立和热路径接通。
   - 读面替换、Goal Contract、Brain、Feishu 都留给后续 work item。

## 分阶段计划

### Phase 1：冻结 030 formal docs 与事件契约

交付内容：

- `specs/030-session-service-event-truth-write-barrier/spec.md`
- `specs/030-session-service-event-truth-write-barrier/plan.md`
- `specs/030-session-service-event-truth-write-barrier/tasks.md`
- `SessionEventRecord` / `SessionLineageRecord` / `RecoveryTransactionRecord` 契约草案

关键原则：

- 总设计继续留在 `docs/architecture/`
- 总执行蓝图继续留在 `docs/plans/`
- 真正要执行的 030 只在 `specs/030-.../` 维护

### Phase 2：建立 append-only writer 与原子性保证

交付内容：

- `session_service/models.py`
- `session_service/store.py`
- 原子追加、锁与幂等索引

关键原则：

- single-writer 是硬约束，不是“最好如此”
- 写锁丢失、落盘失败、恢复重试都必须有测试锁住

### Phase 3：接入 pre-command write barrier

交付内容：

- `policy` 与 `orchestrator` 在 `command_created` 前的写入闸门
- `decision_proposed -> decision_validated -> command_created` 顺序保证

关键原则：

- 先写真相，后放 side effect
- 失败路径必须 fail-closed

### Phase 4：收敛 approval / notification / human override / memory anomalies

交付内容：

- 审批 lifecycle canonical events
- 通知与人工接管 canonical events
- `memory_unavailable_degraded`
- `memory_conflict_detected`
- `stage_goal_conflict_detected` schema / query facade support

关键原则：

- 外部动作已发生，就必须能在 Session events 找到真相
- `stage_goal_conflict_detected` 先冻结位点，再由后续 work item 生产更完整的冲突治理

### Phase 5：命令租约、恢复位点与 030 收口验证

交付内容：

- claim / renew / expire / requeue canonical events
- `worker_id / lease_expires_at` 冻结
- 晚到结果拒绝
- 030 整体测试与 handoff 记录

关键原则：

- 030 结束时“写面可信”必须先成立
- 030 不把读面替换和 Goal Contract 顺手带入

## 测试计划

- `tests/test_watchdog_session_service.py`
  - 事件顺序、memory / goal conflict canonicalization、fail-closed
- `tests/test_watchdog_session_service_atomicity.py`
  - 单写者、原子追加、锁丢失、崩溃恢复与幂等去重
- `tests/test_watchdog_approval_loop.py`
  - 审批 lifecycle 必须由 Session events 驱动
- `tests/test_watchdog_command_leases.py`
  - command claim / lease renew / expire / requeue 与晚到结果拒绝
- `tests/test_watchdog_policy_engine.py`
  - policy 决策不会绕过写入闸门
- `tests/test_watchdog_session_spine_runtime.py`
  - runtime 热路径接入后无行为回退

## 主要风险与应对

### 风险 1：writer 被实现成“附带记录日志”，而不是硬闸门

应对：

- 用失败测试先锁 `decision_proposed -> decision_validated -> command_created`
- 明确断言写入失败时命令不能进入执行面

### 风险 2：030 范围膨胀，顺手把 projection / Goal Contract 也做掉

应对：

- `tasks.md` 明确只做写面与闸门
- 验收口径写死“读面替换不属于 030”

### 风险 3：记忆降级与目标冲突再次退化成私有日志

应对：

- 在 030 就把 `memory_*` 与 `stage_goal_conflict_detected` 写入基础 schema / query facade
- 让后续 release gate 与 projection 直接消费 canonical event，而不是重新拼接解释

### 风险 4：当前工作区已有未完成改动，030 容易被脏状态带偏

应对：

- 先以 formal docs 收敛边界
- 执行时按 `tasks.md` 单任务推进，不在 030 中顺手处理无关 runtime 改动

## 验收口径

只有当以下条件同时满足，030 才算完成：

1. `Session Service` 已具备 append-only、single-writer、原子追加与恢复幂等能力；
2. `policy -> command execution` 之间已建立 fail-closed 写入闸门；
3. 审批、通知、人工接管、命令租约、记忆降级与目标冲突位点都已进入 canonical Session events；
4. 030 没有提前把 `session_spine` 读面替换、`Goal Contract`、`Brain / Recovery`、`Feishu` 或 `Memory Hub` 检索逻辑塞进来；
5. 030 的测试与 handoff 足以让下一 work item 专注于 projection 替换，而不是回头补写真源。
