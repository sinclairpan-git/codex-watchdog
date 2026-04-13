---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/030-session-service-event-truth-write-barrier/spec.md"
  - "specs/031-session-spine-events-projection-read-surface/spec.md"
  - "specs/032-goal-contract-persistence-and-governance/spec.md"
  - "specs/033-recovery-transaction-lineage/spec.md"
  - "specs/034-memory-hub-codex-critical/spec.md"
---

# Brain 决策层与 Release Gate 边界 — 功能规格说明

## 概述

`035-brain-decision-boundary-and-release-gate` 是长时运行自治一期的第六个正式执行 work item。它从总实施计划中的 `Task 6` 拆出“Brain / provider certification / replay / 低风险自动决策闭环”，但边界必须比旧提案更紧。

035 只负责把 `Brain` 收敛成一个可回放、可审计、可替换的决策层：

> `Brain` 只消费 `Session Service`、`Goal Contract`、`Policy rules` 与 `Memory Hub` 的受控输入，产出候选决策、校验结果和低风险自动化资格证据；它不是事实层，不是执行层，不是 prompt/runtime 中枢。

035 同时吸收两组外部约束，但不混淆它们的原生实现：

- **Hermes 对齐边界**：persistent memory 与 session search 分离、memory provider lifecycle 与 inference/runtime 分离、skills progressive disclosure、prompt assembly 归 harness；
- **Anthropic 对齐边界**：session log 是 durable truth、brain/hands 分离、decision loop 与 execution loop 分离、replay 必须回到 canonical events 而非只依赖压缩摘要。

因此，035 的首要目标不是“让 Brain 更强”，而是确保它不会偷走已有真相层与执行层的职责。

## 功能需求

- **FR-3501**：`Brain` 只能作为派生决策层存在；运行时权威真相仍只允许来自 `Session Service` canonical events、`Goal Contract` 当前版本、`Policy Gate` 风险/审批规则与 `Session Spine Orchestrator` 执行状态。`Brain` 本地记录、packet、summary、report 或 replay cache 都不得成为审批、完成态、恢复态或执行态的权威来源。
- **FR-3502**：035 必须把 `DecisionInputBuilder`、`Goal Closure Judge`、`Recovery Planner`、`Decision Validator`、`Provider Certification`、`Historical Replay`、`Release Gate Evidence` 与 `Release Gate` 收敛成独立但可组合的子能力；其中 `DecisionInputBuilder` 是 `Packet Builder` 的正式替代命名，用于强调它不是最终 prompt/message assembly owner。
- **FR-3503**：`DecisionInputBuilder` 只能产出 versioned `decision_packet_input`，内容限于预算化 summary、retrieval refs、expansion handles、hashes 与 provenance；它不得直接组装 system prompt、provider API messages 或最终 tool schema，不得读取/写入 provider memory，不得把 raw transcript、artifact blob、skill body 或 Memory Hub 私有状态默认内联为热路径上下文。
- **FR-3504**：`Brain` 的输出必须固定为声明式 `DecisionIntent`，至少包括 `observe_only`、`suggest_only`、`require_approval`、`propose_execute`、`propose_recovery`、`candidate_closure` 与 `reject`。`Brain` 不得直接 claim command lease、执行工具、修改 session history、写入完成态或变更审批状态；`candidate_closure` 只能作为候选完成判断，必须由 `Goal Contract + Policy Gate + Session truth` 二次确认后才允许落终态。
- **FR-3505**：每次 Brain 决策都必须可追溯到 canonical truth。系统必须为每次决策保留可重建的 `DecisionTrace`，至少包含 `session_event_range/cursor`、`goal_contract_version`、`policy_ruleset_hash`、`memory_packet_input_ids`、`memory_packet_input_hashes`、`provider/model/prompt/schema`、`risk_policy_version`、validator 结果、approval 读取结果与最终降级/放行原因。任何进入 runtime 的建议或决策都必须先绑定到 canonical Session decision events 或等价 event family，而不是只停留在 Brain 私有记录中。
- **FR-3506**：风险带、审批要求与完成判定只能由 `Policy rules + Session facts + Goal Contract` 决定；`Memory Hub` recall、skills、provider confidence、User Model、shadow statistics 或 release evidence 都不得降低风险等级或绕过审批。高风险或需审批动作即使 provider 已通过 certification，也必须读取当前有效的 canonical approval event；stale、superseded 或来自旧 session 的 approval 不得复用。
- **FR-3507**：`Provider Certification` 必须至少拆成 `inference_provider_certification` 与 `memory_provider_adapter_certification` 两类契约。Brain 可以认证 provider/model/prompt/schema/risk-policy/tool-schema/memory-adapter 的兼容性与证据哈希，但不得选择、切换或驱动 inference provider lifecycle，也不得触发 memory provider 的 recall、sync、extraction 或 built-in mirror；这些生命周期仍分别归运行时 harness 与 `Memory Hub` compatibility facade。
- **FR-3508**：035 必须显式区分 `persistent memory` 与 `session_search`。历史恢复、完成判定、replay 与 recovery 判断需要历史上下文时，优先消费 `Session Service` 的 `cursor/range/anchor` 读取或等价 `session_search` 结果；persistent memory 只能作为低优先级辅助上下文。若 memory recall 与 Session truth 冲突，系统必须以 canonical Session facts 为准，并把 memory 结果降级为 `reference-only`。
- **FR-3509**：skills 在 Brain 输入中必须遵守 progressive disclosure。默认只允许注入 `skill_name`、`short_description`、`trust_level`、`security_verdict`、`source_ref`、`content_hash`、`installed_version` 等 metadata；只有某个决策明确需要 procedure 时，才允许通过 expansion handle 拉取 skill 正文或受控片段，并在 `DecisionTrace` 中记录其 `source_ref/content_hash/trust_level/security_verdict`。skill body 不得被当作 resident memory 或 provider sync payload。
- **FR-3510**：035 必须同时支持两类 replay：`packet_replay` 与 `session_semantic_replay`。前者用冻结的 `decision_packet_input` 复现特定 provider/model/schema 下的决策结果；后者必须能从 canonical Session event log 的 `cursor/range/anchor`、tool result refs、memory expansion handles 与 Goal Contract version 重新构造决策输入。两类 replay 都必须输出 drift、schema failure、unsafe decision、missing context 与人工 override 差异，而不是只生成一份成功/失败报告。
- **FR-3511**：replay 必须是只读评估模式。它不得写入 provider memory、不得触发 live recall 覆盖冻结输入、不得执行工具，也不得用当前时间点的新 Memory Hub 内容补洞后仍宣称“等价回放”。若回放缺失必要输入，必须显式标记 `replay_incomplete` 并保留缺口原因。
- **FR-3512**：`Release Gate` 的定位必须收敛为“低风险自动决策资格门禁”，而不是平台运行时总闸门。没有有效报告时，系统只能把 Brain 决策降级为 `suggest_only`、`require_approval` 或等价人工路径；它不得阻断普通 observe-only 决策、session search、memory write mirror、provider fallback 或基础 agent loop 的非自动执行能力。
- **FR-3513**：运行时进入 `low-risk auto-decision` 前，`Policy Gate` 必须对 `release_gate_report` 做硬校验。至少要校验 `report_id`、`report_hash`、`sample_window`、`shadow_window`、`label_manifest`、`generated_by`、`approved_by`、`artifact_ref`、TTL/expiry、`provider/model/prompt/schema`、`risk_policy_version`、`decision_input_builder_version`、`policy_engine_version`、`tool_schema_hash`、`memory_provider_adapter_hash` 与输入哈希一致性。任一字段缺失、过期、哈希不一致或版本漂移时，系统必须自动降级并写入 canonical event。
- **FR-3514**：`release_gate_evidence` 必须至少冻结 `certification_packet_corpus`、`shadow_decision_ledger` 与 `release_gate_report` 三类产物，并要求 `memory_unavailable_degraded`、`memory_conflict_detected`、approval-required、completion-candidate、recovery-needed 等关键样本优先来自 canonical Session events 语料，而不是只由人工夹具补齐。
- **FR-3515**：035 必须把 `DecisionTrace` 与后续 worker/sub-agent 合同先冻结，但一期不实现正式 sub-agent orchestration。预留的 future schema 至少包括 `parent_session_id`、`worker_task_ref`、`scope`、`allowed_hands`、`input_packet_refs`、`retrieval_handles`、`distilled_summary_ref` 与 `decision_trace_ref`。未来 worker start/complete/fail 必须回写 Session events，且 worker 不得直接修改 Goal Contract、approval、risk band 或 completion truth。
- **FR-3516**：`DecisionInputBuilder` 必须为每个字段记录 provenance 与 freshness，并持续产出最小 context quality evaluation contract，至少覆盖 `key_fact_recall`、`irrelevant_summary_precision`、`token_budget_utilization` 与 `expansion_miss_rate`。这些指标只用于质量回归与 release evidence，不得反向改写当前 turn 已冻结的决策输入。
- **FR-3517**：035 完成后，`policy/engine.py` 与 `session_spine/orchestrator.py` 只能消费 Brain 的声明式结果与可审计 trace，不能把 Brain 重新内联成自由 prompt/runtime 逻辑；同样，Brain 也不得反向拥有 orchestrator 的租约与执行语义。

### 用户故事 1：Brain 不能成为新的真相层

operator 需要知道任何自动化建议都能追溯到当前 session 真相，而不是由某份 packet、summary 或 report 私下决定。

场景 1：Brain 提出 `candidate_closure` 时，系统只能把它记为候选判断，并继续由 `Goal Contract + Policy Gate + Session facts` 校验。

场景 2：release gate 报告存在但输入哈希已经漂移时，系统必须自动降级，而不是继续沿用旧报告执行低风险自动决策。

### 用户故事 2：历史回放必须能回到事件真源

operator 需要区分“模型在旧输入上会怎么判”和“如果按当前 canonical event slice 重新构造输入会怎么判”，而不是只有一份不可解释的 replay 结果。

场景 1：`packet_replay` 使用冻结样本比较 provider/model 变化下的 drift。

场景 2：`session_semantic_replay` 从 canonical event log 重新取回 user instruction、tool result 与 decision events，验证 compaction 后是否仍可恢复关键语义。

### 用户故事 3：低风险自动决策必须是 runtime-enforced，而不是文档约定

operator 需要在 provider、prompt、schema、risk policy 或 memory adapter 改动后自动阻断旧资格，而不是上线后再人工补报告。

场景 1：prompt contract 变化时，旧 `release_gate_report` 立即失效，系统退回 `suggest_only`。

场景 2：provider certification 通过，但当前 action 需要审批时，系统仍必须读取当前有效 approval，不能因为模型“信心高”而直接执行。

## 非目标

- 不在 035 中把 `Brain` 做成新的 session truth、prompt orchestrator、tool runtime 或平台控制总线。
- 不在 035 中让 `DecisionInputBuilder` 接管最终 prompt assembly、provider lifecycle、memory sync 或 skill source-of-truth。
- 不在 035 中引入新的执行凭证通道、直接 shell/tool 调用或独立 command lease 机制。
- 不在 035 中把 `release_gate_report` 扩张成所有 provider/runtime 行为的全局总开关；它只约束低风险自动决策资格。
- 不在 035 中提前正式实现 worker/sub-agent orchestration、Feishu 主控制面或端到端 golden path；这些仍留给后续 work item。
