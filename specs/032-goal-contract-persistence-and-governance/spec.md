---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/030-session-service-event-truth-write-barrier/spec.md"
  - "specs/031-session-spine-events-projection-read-surface/spec.md"
---

# Goal Contract 一等持久化与治理边界 — 功能规格说明

## 概述

`032-goal-contract-persistence-and-governance` 是长时运行自治一期的第三个正式执行 work item。它从总实施计划中拆出“Task 3”，只负责一件事：

> 把当前 session 的阶段目标、交付物约束与完成信号，从 prompt / stage 字段 / 临时摘要中的隐式文本，收敛成由 `Session Service` canonical events 驱动的 `Goal Contract` 一等持久化对象。

032 的边界依然必须收紧。它只负责 Goal Contract 的持久化、版本治理、阶段边界冲突处理，以及给 policy / orchestrator 提供稳定读取入口；它不在本 work item 中把 Recovery Transaction、Brain、Feishu 控制面或 Memory Hub 一并实现。

## 功能需求

- **FR-3201**：032 必须定义可被持久化与回放的 `Goal Contract` 结构，至少稳定包含 `contract_id`、`session_id`、`version`、`current_phase_goal`、`explicit_deliverables`、`completion_signals`、`constraints`、`status` 与 provenance 信息。
- **FR-3202**：032 必须让 `goal_contract_created`、`goal_contract_revised`、`goal_contract_adopted_by_child_session` 成为 `Session Service` canonical events；当前有效 contract version 只能通过重放 session events 得出，不得由独立 snapshot store 直接覆盖。
- **FR-3203**：`src/watchdog/services/goal_contract/service.py` 必须作为治理与查询 facade 存在，但它物化出的当前 contract 只能来源于 Session events projection，不得成为第二真源。
- **FR-3204**：系统必须支持从任务标题、用户最近指令、稳定摘要与受控上下文派生 bootstrap contract；当 `explicit_deliverables` 或 `completion_signals` 缺失时，contract 只能把自动推进能力降级到 `observe-only` 或 `suggest-only`。
- **FR-3205**：`AI_AutoSDLC.stage` 与 `active_goal` 在 032 中只能作为 bootstrap context / deterministic-derived input，不得在运行时静默覆盖当前 `Goal Contract.current_phase_goal`。
- **FR-3206**：当 `stage / active_goal` 与当前 Goal Contract 冲突时，系统必须记录 `stage_goal_conflict_detected` 或等价冲突事实，返回差异摘要，并阻断自动推进，直到人工确认或显式 revision。
- **FR-3207**：子会话恢复、handoff 或 adopt 路径必须显式继承 `goal_contract_version`；若 child session 未声明 adopt event，则不得假定其沿用 parent 的 contract。
- **FR-3208**：policy / orchestrator 的自动决策入口必须能够读取当前 Goal Contract 与其能力边界；当 contract 不完整、冲突或缺失关键 deliverables / completion signals 时，系统只能建议补全，不得自由自动推进。
- **FR-3209**：032 完成后，后续 Recovery、Brain、Feishu 与 release gate work items 必须能只依赖 Goal Contract facade + Session projection 读取目标边界，而不需要再回头把 `AI_AutoSDLC.stage/active_goal` 当作运行时真相。

### 用户故事 1：当前目标不再只是 prompt 文本片段

operator 需要知道系统当前到底在追哪个阶段目标、交付物和完成信号，而不是从 prompt、handoff 文本和 `AI_AutoSDLC.stage` 里人工猜测。

场景 1：session 首次进入自治时，系统从稳定上下文生成 bootstrap Goal Contract，并记录 `goal_contract_created`。

场景 2：后续目标被修订时，系统记录新的 revision event；任何读取方都只能看到最新 version 生效。

### 用户故事 2：阶段边界冲突必须显式暴露并阻断自动推进

长期运行系统不能让 `stage/active_goal` 与当前 contract 发生冲突时仍然静默继续执行。

场景 1：上游传入新的 `active_goal`，但与当前 contract 的 `current_phase_goal` 不一致时，系统记录冲突事实并要求人工确认或显式修订。

场景 2：contract 缺失明确交付物或完成信号时，policy 只能给出 observe-only / suggest-only 建议，而不是直接继续自动动作。

### 用户故事 3：子会话恢复必须显式继承 contract 版本

Recovery / handoff 不能只复制文本摘要，否则子会话可能在不同目标版本上继续自动推进。

场景 1：child session 创建时显式记录 adopt event，并绑定 parent 的 contract version。

场景 2：若 child session 需要切换目标边界，必须先产生 revision，再允许后续恢复或决策继续。

## 非目标

- 不在 032 中实现 `Recovery Transaction`、lineage orchestration 或完整 interruption recovery 事务。
- 不在 032 中实现 Brain、Goal Closure Judge、Decision Validator、Feishu control plane 或 release gate。
- 不在 032 中把 Goal Contract 做成独立数据库或新的真相层；032 只允许从 Session events projection 重建当前 contract。
- 不在 032 中新增任意高风险自动执行能力；032 只治理目标边界与自动推进门槛。
