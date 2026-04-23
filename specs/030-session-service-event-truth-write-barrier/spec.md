---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
---

# Session Service 事件真源与写入闸门 — 功能规格说明

## 概述

`030-session-service-event-truth-write-barrier` 是长时运行自治一期的首个正式执行 work item。它从总实施计划中拆出“Task 1”，只负责一件事：

> 把 `Session Service` 建成唯一可审计的写入真源，并在任何命令进入执行面之前建立 fail-closed 的事件写入闸门。

030 的边界非常明确。它先冻结“写前记账”地基，让后续 `session_spine projection`、`Goal Contract`、`Brain / Recovery`、`Feishu control plane` 与 `Memory Hub` 都有统一可回放的 canonical 写面可依赖；但 030 本身不负责完成这些后续能力。

## 功能需求

- **FR-3001**：030 必须定义 `SessionEventRecord`、`SessionLineageRecord`、`RecoveryTransactionRecord` 三类 canonical 持久化模型，作为后续回放、恢复与审计的基础真相。
- **FR-3002**：030 必须提供 append-only、single-writer 的 `Session Service` 本地持久化能力，至少稳定记录：
  - `event_id`
  - `session_id`
  - `event_type`
  - `occurred_at`
  - `causation_id`
  - `correlation_id`
  - 与事件相关的受控 payload
- **FR-3003**：writer 必须具备单写者锁、原子追加与崩溃恢复后的幂等去重能力；若锁丢失、追加失败或 writer 不可用，系统必须 fail-closed，而不是继续放行命令。
- **FR-3004**：policy 决策链路必须先把 `decision_proposed -> decision_validated -> command_created` 写入 `Session Service`，之后命令才允许进入执行面；任一前置事件写入失败时，不得继续创建或投递命令。
- **FR-3005**：审批链路必须以 `approval_requested -> approval_approved | approval_rejected | approval_expired` 的 canonical 事件序列落账；`approvals` 服务只能保留兼容 facade / inbox cache 角色，不得继续维护独立真源状态。
- **FR-3006**：通知与人工接管链路必须以 `notification_announced -> notification_receipt_recorded -> human_override_recorded` 的 canonical 事件序列落账，不得只保留在 side-effect store、日志或瞬时状态中。
- **FR-3007**：命令租约链路必须以 `command_claimed -> command_lease_renewed -> command_claim_expired -> command_requeued` 的 canonical 事件序列落账，并冻结 `worker_id` 与 `lease_expires_at`；命令被重新入队后，晚到结果必须被拒绝，而不是覆盖当前状态。
- **FR-3008**：`memory_unavailable_degraded` 与 `memory_conflict_detected` 必须成为 `Session Service` 的 canonical 事件，不得只停留在 `Memory Hub` 私有日志、指标或临时内存状态中。
- **FR-3009**：`stage_goal_conflict_detected` 必须进入 030 的基础事件 schema 与 query facade，允许现有调用方在发现 stage / active goal 冲突时落账；冲突路径必须退化为 reference / human-handled，而不是静默自动继续。030 只冻结该事件位点，不负责实现完整 `Goal Contract` 冲突检测器。
- **FR-3010**：030 必须提供最小 query facade，允许按 `session_id`、事件类型与相关标识读取 canonical 事件，供测试、后续 projection 与审计层消费。
- **FR-3011**：030 必须把写入闸门接到现有 `policy` 与 `session_spine/orchestrator` 热路径上，但不得在本工作项中把 `session_spine` 读面整体替换为 events projection；读面替换属于下一 work item。
- **FR-3012**：030 必须确保一旦命令、审批、通知、人工接管、记忆降级等动作已经对外发生，就一定能在 `Session Service` 中找到对应 canonical 事件；不得出现“外部动作发生了，但 canonical 真相缺失”的状态漂移。

### 用户故事 1：决策与命令执行必须先有可回放真相

operator 需要确认一条命令是如何被提出、验证并放行的，而不是从多个服务日志里拼接过程。

场景 1：策略引擎生成一个低风险决策时，系统先写 `decision_proposed` 与 `decision_validated`，随后才允许 `command_created`。

场景 2：若 `command_created` 前的任何写入失败，命令不会进入执行面，operator 在审计时也能直接看到失败发生在 writer 闸门。

### 用户故事 2：审批、通知与人工接管必须能从 Session events 重放

长期运行系统不能依赖独立审批状态或通知 side effect 作为真相来源。

场景 1：审批被请求后，operator 能在 `Session Service` 中看到 `approval_requested` 与最终 `approval_approved | approval_rejected | approval_expired`。

场景 2：通知已经发出且人工接管发生后，系统能按 `notification_announced -> notification_receipt_recorded -> human_override_recorded` 重放事实，而不是只在外部消息平台留痕。

### 用户故事 3：命令租约与恢复必须可审计

worker 崩溃或 lease 过期时，系统需要有可重放的中间态，而不是依赖“当前内存里还记得什么”。

场景 1：worker 成功 claim 命令后，`worker_id` 与 `lease_expires_at` 被写入 canonical event。

场景 2：lease 过期后，系统生成 `command_claim_expired` 与 `command_requeued`，晚到结果不会把已重排队的命令覆盖回旧状态。

### 用户故事 4：记忆降级与目标冲突必须从第一期开始入账

后续 `Memory Hub` 与 `Goal Contract` 即使还在分阶段实现，也不能让降级与冲突只停留在隐式日志里。

场景 1：`Memory Hub` 不可用时，系统记录 `memory_unavailable_degraded`，后续 release gate 与审计都能引用它。

场景 2：调用方发现 stage 与 active goal 不一致时，可以写入 `stage_goal_conflict_detected`，并把执行退化到 reference / human-handled。

## 非目标

- 不在 030 中把 `session_spine` 全面替换成 Session events projection；这属于下一 work item。
- 不在 030 中引入完整 `Goal Contract` 持久化、revision 语义或自动冲突治理器。
- 不在 030 中交付 `Brain`、`Recovery` 编排器、`Feishu control plane`、`release gate` 或 `Memory Hub` 检索 / skill 生命周期。
- 不在 030 中新增任何自动高风险执行能力；030 只负责把已有决策与执行链路先收进 canonical 写面。
