---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/030-session-service-event-truth-write-barrier/spec.md"
  - "specs/031-session-spine-events-projection-read-surface/spec.md"
  - "specs/032-goal-contract-persistence-and-governance/spec.md"
  - "specs/033-recovery-transaction-lineage/spec.md"
---

# Memory Hub Codex-critical 切片边界 — 功能规格说明

## 概述

`034-memory-hub-codex-critical` 是长时运行自治一期的第五个正式执行 work item。它从总实施计划中的 `Task 5` 拆出 `Memory Hub` 的一期最小闭环，但这次不再把它定义成“统一记忆平台”，而是收紧成：

> 一个受 `Session Service + Goal Contract` 约束、可降级、可审计、不可夺权的 memory/provider facade，与其相邻的检索/索引能力。

034 的核心不是“做更多 memory 功能”，而是把记忆相关能力整理成对 `Codex/watchdog` 主路径真正有用且不会越权的边界：

- `Session Service + Goal Contract` 继续是唯一运行时真相源；
- `Memory Hub` 只返回 bounded context、search refs、skill metadata 与 packet inputs；
- final prompt / final packet 的装配策略仍由调用侧 harness 决定，`Memory Hub` 不拥有最终上下文裁剪权；
- `Memory Hub` 不可用、冲突、过期或命中安全问题时，必须先写 canonical event，再安全降级。

034 会同时吸收两组外部设计约束，但不会假装它们是同一套原生模型：

- **Hermes 对齐边界**：persistent memory target、session search、external provider lifecycle、skills progressive disclosure、安全扫描；
- **Anthropic 对齐边界**：session 不是 context window、durable event log 可回放、just-in-time context expansion、brain/hands/sandbox 解耦。

因此，034 中常说的 `resident / session search archive / skills / user-model preview` 只是**项目内部实现分区**，不是 Hermes 官方 memory 原生层级，也不是 Anthropic 官方分类。

## 功能需求

- **FR-3401**：`Session Service + Goal Contract` 必须继续作为唯一运行时真相源；`Memory Hub` 不得直接成为决策真相、审批真相、风险真相或完成态真相。
- **FR-3402**：034 对外正式能力只包括 `resident memory facade`、`session search archive`、`skill registry facade` 与 `packet input retrieval facade`；`user-model`、`periodic-nudge`、`AI_AutoSDLC/Cursor` 只允许以 disabled-by-default 的 preview contract 存在。
- **FR-3403**：`resident memory facade` 必须显式映射到项目约束/稳定事实与用户画像等价目标，具有硬预算；一旦进入当前 turn 的 frozen packet block，当轮后续 memory update 不得回改已冻结内容。resident write surface 必须至少支持 `add|replace|remove` 或等价语义；容量压力必须触发显式 replace/consolidate，而不是静默追加，也不得提供绕过 frozen prompt block 的直接注入读路径。
- **FR-3404**：`session search archive` 必须按 search/retrieval 语义工作，只返回摘要、引用与 expansion handles；raw transcript、日志、大代码块、artifact blob 不得默认进入热路径。
- **FR-3405**：`skill registry facade` 必须与 persistent memory 分离；默认只暴露 `name / short description / trust_level / security_verdict / content_hash / installed_version / last_scanned_at` 等元数据，全文按需展开。`Memory Hub` 对 skill 只保存 index/metadata/reference，不得把 skill body 复制成 resident memory；skill 正文必须来自 registry/source directory/controlled blob reference 等 source-of-truth，且更新必须以 `source_ref + content_hash` 识别。local source 优先级高于 shared/external source，shared/external source 默认 read-only。
- **FR-3406**：034 中的 `resident / session search archive / skill registry / user-model preview` 只是内部实现分区；规格文本不得把这四类表述成 Hermes 官方原生记忆层级。
- **FR-3407**：`Memory Hub` 只返回 versioned packet inputs，不拥有 final packet / final prompt 的装配权；final packet 必须由调用侧 harness 根据模型版本、风险带和 token budget 决定。
- **FR-3408**：`Session Service` 必须提供可回放的事件切片读取能力，支持按 `session_id + cursor/range/anchor` 读取事件；任何 compaction、summary 或 packet input 都不得替代 raw event 的可重放性。
- **FR-3409**：`Memory Hub` 返回的 archive、artifact、skill 结果必须同时给出“预注入摘要”和“按需展开句柄”；调用侧 agent 必须能够在运行时逐步扩展引用，而不是只能消费服务端预裁剪结果。
- **FR-3410**：所有可注入项都必须携带 provenance，至少包括 `source_runtime`、`source_kind`、`source_scope`、`source_ref`、`captured_at`、`content_hash`、`freshness_ttl`、`last_verified_at`；其中 project/archive 条目必须带 `project_id`，user/global 条目允许 `project_id/session_id/task_id` 为空，但必须显式标明 `scope=user_profile|global`。
- **FR-3411**：所有可注入项都必须先通过安全门禁；`security_verdict` 的正式枚举至少包括 `pass | caution | warn | dangerous | quarantine`。其中 `dangerous` 为不可 override 的阻断级别，只允许进入 `quarantine`；community/shared/external source 的非 `pass` 内容默认不得进入 hot path，其中 `caution|warn` 只有在人工 override 并留下审计事件后才能以 `reference-only` 形式暴露，且 override 不得把内容提升为 resident block。
- **FR-3412**：`Memory Hub` 必须提供 Hermes-compatible provider lifecycle，但该生命周期在 034 中只能作为 compatibility adapter contract 存在：pre-turn 非阻塞 prefetch、post-response sync、session-end extraction、built-in write mirror 必须幂等、不可阻塞当前 turn 的 frozen packet、失败不得改写已冻结上下文，并且同一时刻只允许一个 active provider facade 参与正式主路径。provider-specific memory operation surface 必须限制在 `search|store|manage` 或等价 memory 操作内，不得扩张成 final context policy、tool execution 或权限决策。
- **FR-3413**：`Memory Hub` 不得直接执行工具，不得持有执行凭证，不得直接读取 sandbox secrets；任何 workspace/archive/skill ingest 都必须来自 `Session Service` canonical events、受控索引过程或受限 blob 引用。provider memory operations 可以存在，但只允许处理受控 memory records，不得获得 shell/toolchain/credential 通道；命中 secret-like payload 或 sandbox-only reference 的内容必须只保留 metadata/quarantine handle，不得进入 resident block、packet hot path 或 provider sync payload。
- **FR-3414**：`Memory Hub` 不可用、结果冲突、TTL 过期、skill 技术栈不匹配或 security verdict 不通过时，系统必须先写入 `memory_unavailable_degraded` 或 `memory_conflict_detected` 到 `Session Service`，再降级到 `Session Service + runtime snapshot` 可支撑的最小 packet path。所有 degrade/conflict 事件都必须带 `reason_code=outage|conflict|ttl_expired|security_blocked|skill_incompatible` 与对应 `source_ref`。
- **FR-3415**：`User Model`、`skills`、preview adapters 与任何 memory/provider recall 都不得影响审批、权限、风险带和完成判定；这些判定继续只由 `Session Service`、`Goal Contract` 与后续 `Brain`/policy 链路决定。
- **FR-3416**：034 必须为复杂 coding 场景保留 future-compatible 的 `scoped packet input` 与 `distilled summary` 边界，但一期不实现 sub-agent orchestration 正式能力；若后续 worker/sub-agent 接入，必须消费同一 retrieval/ref contract，而不是直接绕过到 Memory Hub 私有状态。预留的最小 future schema 至少包括 `scope`、`parent_session_id`、`worker_task_ref`、`retrieval_handles`、`distilled_summary_ref`。
- **FR-3417**：034 的 replayability 验收必须覆盖语义级回放，而不只是接口存在性；在 compaction 之后，调用侧仍必须能够通过 `Session Service` 的 cursor/range/anchor 从 canonical event log 重新取回至少 `raw tool result`、`user instruction`、`decision event` 等关键事件，且 harness 重启后可以从同一 cursor 继续恢复。summary 或 packet input 不能成为唯一恢复来源。
- **FR-3418**：034 必须建立最小 context quality evaluation contract，用于持续评估 packet input/retrieval 质量，至少包含 `key_fact_recall`、`irrelevant_summary_precision`、`token_budget_utilization`、`expansion_miss_rate` 四项指标；该评估只用于质量回归和后续 release evidence，不得反向篡改当前 turn 的 frozen packet。

### 用户故事 1：Memory Hub 故障时，Codex 主路径仍能接续

operator 需要在 memory/provider 层出故障时仍能推进会话，而不是让主路径被检索子系统反向卡死。

场景 1：external provider 超时或不可用时，系统先写 `memory_unavailable_degraded`，再回退到 `Session Service + runtime snapshot` 的最小 packet path。

场景 2：archive 命中安全风险或 TTL 失效时，结果只能作为 `reference-only`，不得继续污染 resident block。

### 用户故事 2：Session history 必须可回放，不被摘要系统吞掉

agent 需要在长时 coding 里重新查看过去的关键事件，而不是只能依赖服务端提前压好的摘要。

场景 1：packet 里只包含事件摘要与 expansion handles，agent 可以再按 cursor/range 回读关键事件。

场景 2：compaction 发生后，operator 仍能从 `Session Service` 事件切片接口取回原始关键事件用于审计和恢复。

### 用户故事 3：skills 与 memory 必须分开治理

operator 需要知道一个技能是否可信、是否适配当前技术栈，而不是把技能文本当成与 resident memory 同级的默认注入内容。

场景 1：默认 packet 只拿 skill metadata，不拿 skill 全文。

场景 2：skill 未通过安全扫描或技术栈不匹配时，系统写 degrade/conflict 事件并把该结果降级为引用信息。

## 非目标

- 不在 034 中把 `Memory Hub` 做成新的自治真相层、统一 packet orchestrator 或通用知识平台。
- 不在 034 中把“四层记忆”宣称为 Hermes 官方 memory 原生模型；它只作为本仓库内部实现分区存在。
- 不在 034 中正式实现 `User Model`、`Periodic Nudge`、自动 shared promotion、`AI_AutoSDLC/Cursor` 实时接入或 sub-agent orchestration。
- 不在 034 中让 `Memory Hub` 持有执行凭证、直接执行工具或直接读取 sandbox secrets。
- 不在 034 中替代 `Session Service` 的事件读写能力；session replayability 必须继续来自 canonical event log。
