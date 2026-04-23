---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/030-session-service-event-truth-write-barrier/spec.md"
  - "specs/031-session-spine-events-projection-read-surface/spec.md"
  - "specs/032-goal-contract-persistence-and-governance/spec.md"
  - "specs/033-recovery-transaction-lineage/spec.md"
  - "specs/035-brain-decision-boundary-and-release-gate/spec.md"
  - "specs/036-feishu-control-plane-primary-surface/spec.md"
---

# 一期自治通关与端到端 Release Gate 验收 — 功能规格说明

## 概述

`037-autonomy-golden-path-and-release-gate-e2e` 是长时运行自治一期的第八个正式执行 work item。它把总实施计划中的 `Task 8` 从“补几条 e2e 测试”收紧成“一条可重复、可审计、可阻断放行的自治主链路验收标准”。

037 不再新增新的真相层或旁路工具，而是把 030-036 已冻结的 contract 串成单一通关主链：

> `Feishu DM -> Goal Contract -> Brain decision -> Session write barrier -> command lease -> execution / approval -> recovery transaction -> completion judgment -> replay / metrics / release gate evidence`

这条链路必须在没有手工改库、手工补事件、手工跳过审批或手工绕过 release gate 的前提下重复打通。

037 同时吸收两组外部约束：

- **Hermes Agent 专家边界**：golden path 必须是正式 release blocker，而不是演示脚本；child session continuation、remote compact、lease recovery、notification recovery 都必须走已冻结 contract，不能临时拼装旁路状态。
- **Anthropic Manager 专家边界**：运行时要明确区分“系统生成了决策/证据”“系统具备低风险自动决策资格”“系统真的执行了动作”；任何 release gate 报告缺失、漂移、过期或与当前输入不一致，都必须阻断自动执行，而不是事后补材料。

因此，037 的首要目标不是“把测试补齐”，而是正式冻结一期的通关口径与放行纪律。

## 功能需求

- **FR-3701**：系统必须存在且只存在一条一期正式自治主链路，至少覆盖 `Feishu DM -> Goal Contract -> Brain decision -> Session write barrier -> command lease -> execution / approval -> continuity recovery -> completion judgment -> replay / metrics`。该主链路必须通过端到端测试固定下来，而不是仅停留在设计说明或手工演示。
- **FR-3702**：037 的 e2e 验收必须只消费 030-036 已冻结的 canonical truth / projection / goal / recovery / brain / release gate / Feishu control contracts，不得在 e2e 阶段重新引入旁路状态机、手工注入脚本、临时 DB patch 或“先改 store 再补 event”的旧路径。
- **FR-3703**：系统必须为 golden path 的每个关键阶段保留 canonical evidence，至少包括 `goal_contract_version`、`decision_trace_ref`、`approval_read_ref`、`release_gate_report`、`interaction_context_id`、`command lease`、`recovery_tx`、完成态判定依据与 replay/metrics ref。e2e 断言必须能从这些 canonical artifacts 复盘主链路，而不是只检查表面返回码。
- **FR-3704**：037 必须覆盖中间态恢复与接续场景，至少包括 worker crash、claim timeout、notification send failure、`interaction_context_superseded`、stale interaction、人工 override，以及 `remote compact` 后 child session continuation。以上任一场景都不得要求人工修改状态后才恢复到主链路。
- **FR-3705**：一期低风险自动决策只能在当前输入与当前 runtime contract 对应的有效 `release_gate_report` 存在时发生。至少要校验 `report_id/report_hash`、`sample_window`、`shadow_window`、`label_manifest`、`generated_by`、`approved_by`、`artifact_ref`、TTL/expiry、provider/model/prompt/schema、`risk_policy_version`、`decision_input_builder_version`、`policy_engine_version`、`tool_schema_hash`、`memory_provider_adapter_hash` 与当前 `input_hash` 一致性。
- **FR-3706**：当 `release_gate_report` 缺失、过期、输入哈希不一致、provider/runtime contract 漂移、approval stale、memory conflict 或 report 解析失败时，系统必须阻断 low-risk auto-decision，并显式降级到 `suggest_only`、`require_approval` 或等价人工路径；不得以旧报告、默认配置或手工确认字段绕过阻断。
- **FR-3707**：`certification_packet_corpus`、`shadow_decision_ledger`、`label_manifest`、样本冻结窗口、runbook 与报告归档必须构成 formal blocking inputs。固定脚本与 runbook 产物是 release blocker 的一部分，而不是可选运维附件。
- **FR-3708**：golden path e2e 测试必须是可重复、无外网依赖的 hermetic 夹具。Feishu、provider、delivery 与 recovery 交互可通过本地 fake/fixture 复现，但断言的业务 contract 必须与正式 runtime 一致，不得为测试再造独立协议。
- **FR-3709**：一期完成判定必须仍由 `Goal Contract + Session truth + Policy Gate` 确认；Brain 的 `candidate_closure` 只能作为候选信号。e2e 必须覆盖 completion 只能在 canonical truth 足够时落终态，且终态之后 replay/metrics 会补齐对应 evidence。
- **FR-3710**：037 必须把“无手工补状态即可重复通过”的约束冻结为 release gate 的一部分。任何需要手工补事件、手工修 pending、手工替换 report 或手工重置 interaction context 才能成功的路径，都视为一期未通关。
- **FR-3711**：037 必须把 `tests/e2e/test_watchdog_autonomy_golden_path.py`、`tests/e2e/test_watchdog_midstate_recovery.py` 与 `tests/e2e/test_watchdog_release_gate_e2e.py` 定义为正式 release blocker；其失败不能被“已知 flaky”“线下手动验证通过”或临时跳过替代。

### 用户故事 1：operator 需要一条真正可复跑的自治主链

operator 需要确认系统不是“局部功能都能跑”，而是整条主链在统一 contract 下可重复通过。

场景 1：Feishu DM 触发 Goal Contract 建档，Brain 给出决策，runtime 在 release gate 放行后执行低风险动作，并把 replay/metrics evidence 落账。

场景 2：相同 golden path 在不改数据库、不补事件、不跳过审批的情况下重复运行，仍能得到一致的通关结果。

### 用户故事 2：中间态故障必须可恢复，不能靠人工补状态

operator 需要在 worker crash、claim timeout、通知失败或 child session 接续后继续同一条主链，而不是开新流程或手动修状态。

场景 1：notification send failure 后，系统写 canonical requeue/supersede 事件并生成新的有效 interaction context，旧上下文晚到消息只进审计。

场景 2：remote compact 后系统通过 recovery transaction 与 child session continuation 恢复主链，旧 session 不会被误当成仍在执行。

### 用户故事 3：release gate 是硬阻断，不是文档承诺

operator 需要确保 low-risk auto-decision 的放行条件由 runtime 强制执行，而不是依靠口头流程。

场景 1：`release_gate_report` 与当前输入哈希不一致时，系统自动降级并拒绝 auto execute。

场景 2：runbook、样本窗口、label manifest 或 report archive 缺失时，e2e 直接失败，不能靠人工补说明继续放行。

## 非目标

- 不在 037 中重新设计 030-036 已冻结的 canonical contracts；037 只把这些 contract 串成正式一期通关主链。
- 不在 037 中引入真实外网 Feishu/provider 调用；e2e 以 hermetic fake/fixture 固化行为边界。
- 不在 037 中把 release gate 扩成全平台总闸门；037 只冻结一期 low-risk auto-decision 的正式通关与阻断标准。
- 不在 037 中通过跳过 flaky、人工修状态、手工补 report 或直写数据库来“证明”系统可用。
