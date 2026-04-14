---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/033-recovery-transaction-lineage/spec.md"
  - "specs/034-memory-hub-codex-critical/spec.md"
  - "specs/035-brain-decision-boundary-and-release-gate/spec.md"
  - "specs/036-feishu-control-plane-and-openclaw-retirement/spec.md"
  - "specs/037-autonomy-golden-path-and-release-gate-e2e/spec.md"
---

# Future Worker / Sub-Agent Canonical Execution Contract — 功能规格说明

## 概述

`038-future-worker-canonical-execution-and-governance` 是在 `WI-037` 通关后追加的第九个正式执行 work item。它不再讨论“是否需要 sub-agent”，而是把已经在 `034/035/037` 中冻结过的 future worker 边界，收敛成正式可执行、可恢复、可审计的 canonical contract。

038 的核心目标不是让系统“能并行跑更多 worker”，而是把 worker/sub-agent 执行纳入既有真相链：

> `parent canonical decision -> future worker contract freeze -> worker lifecycle Session events -> parent-side result consumption -> recovery / supersede / completion governance`

038 只消费已经冻结的 contract：

- `033` 的 recovery transaction / lineage；
- `034` 的 retrieval handles / distilled summary / packet input contract；
- `035` 的 `DecisionTrace`、`FutureWorkerTraceRef` 与 release gate 边界；
- `036` 的 Feishu 主控制面与 interaction governance；
- `037` 的 completion evidence / replay / metrics / release blocker 主链。

它同时吸收两组外部约束：

- **Hermes Agent 专家边界**：worker/sub-agent 不能带着私有上下文绕过 canonical truth；retrieval handles、distilled summary、resume/handoff、late result 与 supersede 都必须可审计、可回放，而不是靠隐式进程状态收口。
- **Anthropic Manager 专家边界**：必须明确区分“parent 决策允许创建 worker”“worker 进程正在执行”“worker 结果被 parent canonical consume 并真正影响后续决策/完成态”这三个层次；worker 产出本身不能自动等于真相。

因此，038 的首要目标不是编排更多 worker，而是先确保 worker/sub-agent 不会成为新的暗箱执行面。

## 功能需求

- **FR-3801**：038 必须把 `FutureWorkerTraceRef` 从声明式预留 schema 升格为正式 execution contract，但仍保持它是“受限引用集合”，而不是自由执行授权。正式 contract 至少包括 `parent_session_id`、`worker_task_ref`、`scope`、`allowed_hands`、`input_packet_refs`、`retrieval_handles`、`distilled_summary_ref`、`decision_trace_ref`、`goal_contract_version`、`execution_budget_ref` 与 `worker_contract_version`。
- **FR-3802**：worker/sub-agent lifecycle 必须进入 `Session Service` canonical events。最小事件族至少包括 `future_worker_requested`、`future_worker_started`、`future_worker_heartbeat`、`future_worker_summary_published`、`future_worker_completed`、`future_worker_failed`、`future_worker_cancelled`、`future_worker_result_consumed` 与 `future_worker_result_rejected`。
- **FR-3803**：worker 只能消费父会话在 spawn 时冻结的 refs：`decision_trace_ref`、`input_packet_refs`、`retrieval_handles`、`distilled_summary_ref`、`goal_contract_version` 与 budget/scope 元数据。worker 不得直接读取 parent live session 私有状态、Memory Hub 私有热路径、provider built-in memory、sandbox secrets 或未冻结的 raw transcript 补洞。
- **FR-3804**：worker 不得直接修改 `Goal Contract`、approval、risk band、completion truth、release gate verdict、command lease 或 operator override 状态。worker 只能产出 result envelope、summary 和引用；真正影响 parent session 的变更，必须由 parent-side canonical consumer 明确落账。
- **FR-3805**：parent-side canonical consumer 必须显式区分三层状态：
  1. parent 已批准或自动放行 worker 创建；
  2. worker 实际开始/运行/失败/完成；
  3. worker 结果被 parent canonical consume，并影响后续 decision/completion/recovery。
  任意层次缺失时，系统不得把 worker 输出误判为已生效真相。
- **FR-3806**：worker/sub-agent 结果必须带 canonical provenance，至少包括 `worker_task_ref`、`decision_trace_ref`、`result_summary_ref`、`artifact_refs`、`input_contract_hash`、`produced_at`、`worker_runtime_contract` 与 `result_hash`。如果这些字段缺失、与 parent 冻结 contract 不匹配或来自 superseded/cancelled worker，系统必须拒绝 consume。
- **FR-3807**：038 必须把 stale / late / duplicate worker 结果视作正式治理面。worker crash、duplicate start、late completion、duplicate completion、superseded worker result、scope drift、budget overrun 与 result hash mismatch 都必须有 canonical rejection/recovery 语义，不得靠日志或人工判断兜底。
- **FR-3808**：worker 恢复必须复用 `033` 的 recovery transaction 语义，而不是单独再造恢复状态机。若 worker 进程中断，系统只能通过 canonical recovery / lineage / supersede 机制恢复或替换 worker，禁止在 parent 未知情时悄悄拉起第二个活跃 worker。
- **FR-3809**：worker scope 必须 fail-closed。最小正式 scope 至少区分 `read_only`、`propose_patch`、`execute_scoped_action` 三类；scope 外的行为必须被拒绝并记录 canonical event。`allowed_hands` 只能限制“允许使用哪类 hand/runtime”，不能视作高风险操作的审批替代。
- **FR-3810**：worker 的 `distilled_summary_ref` 与 `retrieval_handles` 必须继续消费 `034` 已冻结的 retrieval/ref contract；038 不得定义第二套 worker-only context packing 协议，也不得把 worker summary 提升为新的 session truth。
- **FR-3811**：parent session 在 consume worker result 前，仍必须受当前 `Goal Contract + Policy rules + release gate / approval` 约束。即使 worker 成功完成，也不得绕过当前有效 approval、release gate blocker 或 completion judgment contract。
- **FR-3812**：ops/read-side 必须能区分 worker 处于 `requested/running/completed/failed/cancelled/rejected/consumed` 的哪一层，并暴露阻断原因、supersede 原因、budget/scope drift 与 late-result rejection 元数据；不能只暴露抽象 “worker failed”。
- **FR-3813**：038 的 e2e 必须覆盖至少一条正式 worker 主链：`parent decision -> worker requested -> worker started -> summary published -> worker completed -> parent consumes result -> follow-up decision/completion evidence updated`。同时必须覆盖 crash recovery、duplicate worker start、late stale result 与 superseded result rejection。
- **FR-3814**：Feishu/control-plane 仍是唯一主控制面。涉及高风险 worker 创建、worker result consume override、supersede/abort 等人工干预时，必须沿用 `036` 已冻结的 interaction/ACL/expiry/replay-protection contract，不得为 worker 引入第二套人工确认协议。
- **FR-3815**：038 不得把 sub-agent orchestration 扩成通用任务队列平台、通用云编排层或外部执行器抽象。它只收敛当前仓库里 future worker/sub-agent 对 parent canonical session 的执行契约与治理边界。

### 用户故事 1：operator 需要知道 worker 结果什么时候才真正生效

operator 需要区分 “worker 自己说做完了” 和 “parent session 真的接受了这份结果并推进了主链”。

场景 1：worker 发布 summary 并完成，但 parent 因当前 release gate blocker 或 approval stale 拒绝 consume，该结果必须停留在 `future_worker_result_rejected`。

场景 2：parent 明确 consume 结果后，后续 decision / completion evidence 才允许引用这份 worker 产物。

### 用户故事 2：worker 崩溃或晚到结果不能污染主链

operator 需要在 worker crash、duplicate start 或 late result 时仍维持单一 canonical truth。

场景 1：某个 worker 已被 supersede 后，旧 worker 晚到 completion 只能进入审计/rejection，不得覆盖新 worker 或 parent 当前状态。

场景 2：worker 崩溃后系统通过 recovery transaction 续接，期间不得产生第二个未治理的并行 worker 真相。

### 用户故事 3：worker 只能消费冻结上下文，不能越权取数或改真相

operator 需要确保 worker/sub-agent 只是受控执行单元，而不是新的隐式 orchestrator。

场景 1：worker 只能读取被冻结的 retrieval handles 与 distilled summary，不能直接访问 parent 未冻结上下文。

场景 2：worker 不得直接写 approval、Goal Contract 或 completion truth；即使产出 patch/result，也必须由 parent canonical consume。

## 非目标

- 不在 038 中把 worker/sub-agent 做成通用任务平台、分布式调度器或多租户执行系统。
- 不在 038 中发明新的 truth store、第二条 recovery 状态机或 worker-only context protocol。
- 不在 038 中让 worker 直接拥有 approval mutation、goal patch、completion write、risk downgrade、release gate override 或 provider credential 通道。
- 不在 038 中回退到“worker 结果到达即自动生效”或“parent 通过隐式共享内存读取 worker 状态”的旧路径。
