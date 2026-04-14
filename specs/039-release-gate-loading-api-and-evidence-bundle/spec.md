---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/035-brain-decision-boundary-and-release-gate/spec.md"
  - "specs/037-autonomy-golden-path-and-release-gate-e2e/spec.md"
  - "specs/038-future-worker-canonical-execution-and-governance/spec.md"
---

# Release Gate Shared Loading API 与 Evidence Bundle — 功能规格说明

## 概述

`039-release-gate-loading-api-and-evidence-bundle` 是在 `WI-035`、`WI-037` 与 `WI-038` 完成后追加的第十个正式执行 work item。它不再扩新的 release gate 分支，而是把 035 handoff 中唯一明确保留的扩展点正式化：把 `release_gate_report` 的加载、校验、hash exactness、runtime contract drift 判定与 evidence bundle 回读，从局部 helper 提升为正式 shared contract。

039 的目标不是重新设计 release gate，而是消除“每个入口各自理解 report/evidence”的风险：

> `artifact report -> shared loading API -> canonical evidence bundle -> runtime / ops / future consumers`

它只消费已经冻结的边界：

- `035` 的 `DecisionTrace`、runtime contract surface、report governance metadata 与 `report_load_failed` fail-closed；
- `037` 的 formal blocking inputs、`release_gate_evidence_bundle` 与 release blocker read-side；
- `038` 的 future worker / parent consume contract，保证后续 worker 或新 runtime 入口只能复用同一套 release gate loading surface。

它同时吸收两组外部约束：

- **Hermes Agent 专家边界**：任何后续入口只要消费 `release_gate_report`，都必须通过同一套 canonical parse/validate/hash contract，不能各自拼自己的“看起来一样”的校验逻辑。
- **Anthropic Manager 专家边界**：运行时必须区分“报告文件存在”“shared loader 认定它是当前有效 canonical report”“evidence bundle 足以支撑 blocker/放行解释”这三个层次；缺任何一层都不能视为可放行。

因此，039 的首要目标不是新增行为，而是收口 shared API，防止 release gate contract 再次分叉。

## 功能需求

- **FR-3901**：系统必须存在单一 shared loading API 负责 `release_gate_report` 的读取、JSON object 校验、canonical hash exactness、governance metadata 校验、runtime contract drift 判定与 TTL/expiry 检查。后续任何 runtime/ops/e2e/future worker 入口不得再各自手写 parse/validate 逻辑。
- **FR-3902**：shared loading API 的输出必须是结构化 canonical surface，而不是裸布尔值。最小输出至少包括：validated report、raw payload hash、`input_hash`、runtime contract snapshot、`decision_trace_ref`、artifact refs 与当前 fail/degrade reason。
- **FR-3903**：系统必须提供 formal `release_gate_evidence_bundle` 读取面，用单一结构暴露 `certification_packet_corpus`、`shadow_decision_ledger`、`label_manifest`、`artifact_ref`、`generated_by`、`approved_by`、冻结窗口与报告引用；不能让 orchestrator、ops 或新入口各自去拼 evidence metadata。
- **FR-3904**：shared loading API 必须沿用 035 已冻结的 fail-closed 语义。报告缺失、过期、hash drift、runtime contract drift、非对象 JSON、默认值补全漂移、Python 宽松相等等路径都必须稳定收敛到 `report_load_failed` 或等价 canonical degrade reason，不得引入“部分有效”的软通过语义。
- **FR-3905**：ops/read-side 与 metrics 只允许消费 shared loader / evidence bundle 输出的 canonical blocker metadata，不得自行重新计算 report 是否有效，避免 read-side 与 runtime 出现第二真相。
- **FR-3906**：039 不得重新定义 release gate blocker taxonomy、样本窗口、label manifest、report schema 或 low-risk auto-decision 门槛。它只收口加载与回读 contract，不扩大 policy surface。
- **FR-3907**：后续 future worker、Feishu/control-plane 或新的 runtime 入口若需要解释 release gate 状态，必须只消费 shared loading API / evidence bundle 的 canonical surface，而不是直接访问 report JSON 或复制 helper 逻辑。
- **FR-3908**：shared loading API 与 evidence bundle 必须保留 provenance，至少覆盖 `report_id`、`report_hash`、`input_hash`、runtime contract version/hash、artifact refs 与生成/审批责任人元数据，使审计与 handoff 可以直接引用。

### 用户故事 1：runtime 需要单一 release gate 解释面

runtime 需要确认“当前报告能不能被正式消费”只有一个答案，而不是 orchestrator、ops 和后续入口各自算一遍。

场景 1：orchestrator 加载报告时，shared loader 判断 `report_load_failed`，ops/read-side 看到的 blocker reason 必须与 runtime 一致。

场景 2：报告存在但 evidence bundle 缺失 `label_manifest` 或 artifact ref 时，shared loader 与 bundle surface 都只能 fail closed。

### 用户故事 2：后续 work item 不能再复制 report 解析逻辑

operator 需要确保后续扩展不会把 release gate 规则重新分散到多个 helper。

场景 1：future worker 或新的 runtime 入口需要知道 release gate 是否有效，只能调用 shared loading API。

场景 2：ops/read-side 需要解释 blocker metadata，只能读 canonical bundle，而不是自己拼 JSON 字段。

## 非目标

- 不在 039 中新增新的 release gate policy、风险分层或放行门槛。
- 不在 039 中重写 035/037 已冻结的 report schema、runbook、样本窗口或 artifact 生成流程。
- 不在 039 中新增第二条 runtime gate 状态机、旁路配置或“只给 read-side 用”的影子解析器。
