---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/031-session-spine-events-projection-read-surface/spec.md"
  - "specs/032-goal-contract-persistence-and-governance/spec.md"
---

# Recovery Transaction 与 lineage 边界 — 功能规格说明

## 概述

`033-recovery-transaction-lineage` 是长时运行自治一期的第四个正式执行 work item。它从总实施计划中拆出“Task 4”，只负责把 interruption recovery 从“触发一次 handoff/resume 动作”收敛成由 `Session Service` canonical truth 驱动的恢复事务。

033 的目标不是扩写一个新的总控层，而是把已有恢复路径补齐到事务语义：

> 同一类 continuity failure 必须围绕固定 `recovery_key` 冻结 handoff packet、创建 child session、提交 parent/child lineage，并且在 lineage 真正确认前禁止把 parent session 当成已接续完成。

033 必须直接消费 `WI-032` 交付的 `Goal Contract` version / contract identity / provenance 与 Session projection；它不再把 `AI_AutoSDLC.stage / active_goal` 文本当成恢复期的真相来源。

## 功能需求

- **FR-3301**：033 必须把 `recovery_tx_started`、`handoff_packet_frozen`、`child_session_created`、`lineage_committed`、`parent_session_closed_or_cooled`、`recovery_tx_completed` 定义为恢复事务的 canonical event 顺序。
- **FR-3302**：033 必须把 `started`、`packet_frozen`、`child_created`、`lineage_pending`、`lineage_committed`、`parent_cooling`、`completed`、`failed_retryable`、`failed_manual` 作为恢复事务状态集合，并要求实际持久化顺序与事务步骤一致。
- **FR-3303**：同一个 `recovery_key` 在任意时刻只能有一个活跃恢复事务；如果先前事务停留在非终态，后续 approval / orchestrator / delivery 路径必须识别并拒绝创建第二个 child session。
- **FR-3304**：`source_packet_id` 必须在 child session 创建前冻结；若恢复被重放或重复调用，系统必须复用同一 frozen packet identity，而不是为相同失败上下文制造新的 packet 真相。
- **FR-3305**：当 child session 已创建但 lineage 尚未提交时，系统必须持久化 `lineage_pending`，明确表示“child 已存在，但 parent/child 关系尚未完成 canonical commit”。
- **FR-3306**：只有在 `lineage_committed` 成功后，系统才允许记录 `parent_session_closed_or_cooled` 与 `parent_cooling`；在此之前 parent session 只能保持可恢复的 cooling / pending 状态，不得被视为已被 child 接续完成。
- **FR-3307**：恢复事务必须显式携带 `goal_contract_version` 与 lineage identity，使 child session 的 adopt / replay / audit 只依赖 Session events 与 Goal Contract facade。
- **FR-3308**：若 resume 失败或人工接管，系统仍必须保留 replayable frozen handoff packet 与 recovery transaction record，并用 `failed_retryable` 或 `failed_manual` 标记终态，而不是把恢复过程留在不可审计的半完成动作中。
- **FR-3309**：033 完成后，`session_spine.recovery`、`orchestrator`、`actions` 与 approvals 相关兼容层都必须把恢复当作事务读取面，而不是自由重复触发按钮。

### 用户故事 1：同一故障不会触发多个并行 child session

operator 需要在 continuity failure 发生时只看到一个正在进行的恢复事务，而不是因为重复重试、审批回放或 delivery 晚到信号又拉起第二个 child session。

场景 1：同一个 `recovery_key` 的恢复事务已经停在 `packet_frozen` 或 `lineage_pending` 时，新的恢复调用必须被拒绝并提示已有活跃事务。

场景 2：同一个事务被幂等重放时，系统只能返回已有 truth，不得追加第二套 lineage 或 child session event。

### 用户故事 2：lineage commit 是 parent 完成接续前的硬前置

operator 需要知道 parent session 是否真的被 child 接续，而不是只看到“resume 调了”就默认恢复完成。

场景 1：child session 创建成功后，系统先记录 `lineage_pending`，再提交 canonical lineage。

场景 2：只有在 `lineage_committed` 成功后，才允许把 parent 标记为 `parent_cooling`，并最终进入 `completed`。

### 用户故事 3：恢复期只消费 Goal Contract 与 Session projection 真相

恢复事务不能重新回退到 `stage` 文本驱动，否则 child session 可能在错误目标版本上继续自动推进。

场景 1：handoff 提供 `goal_contract_version` 时，lineage 与 child adoption 必须保留这个 version。

场景 2：后续审批、delivery 或 runtime audit 读取恢复状态时，只通过 recovery records、Session events 与 Goal Contract facade 判断是否允许继续。

## 非目标

- 不在 033 中实现 Brain、Goal Closure Judge、provider certification、replay harness 或 release gate。
- 不在 033 中引入新的恢复数据库或第二真相层；恢复事务仍然只通过 `Session Service` canonical records 与 projection replay 得出。
- 不在 033 中扩张恢复能力到任意高风险自动操作；033 只冻结 continuity failure 的事务语义、幂等和 lineage 边界。
- 不在 033 中实现 Feishu 控制面、Memory Hub 正式能力或新的 UI 流程。
