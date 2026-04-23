---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/035-brain-decision-boundary-and-release-gate/spec.md"
  - "specs/030-session-service-event-truth-write-barrier/spec.md"
  - "specs/031-session-spine-events-projection-read-surface/spec.md"
  - "specs/032-goal-contract-persistence-and-governance/spec.md"
  - "specs/033-recovery-transaction-lineage/spec.md"
  - "specs/034-memory-hub-codex-critical/spec.md"
---

# 实施计划：035-brain-decision-boundary-and-release-gate

## 目标

把当前 `policy -> canonical decision -> orchestrator auto execute` 的直连路径收敛成受 `Session Service`、`Goal Contract`、`Memory Hub` 与 `Policy rules` 约束的 `Brain` 决策层，并补齐 `DecisionTrace`、provider certification、只读 replay、release gate evidence 与 runtime enforced 的低风险自动决策资格校验。

## 架构摘要

- **Brain derives, never owns truth**：`Brain` 只读取 canonical events、Goal Contract、policy rules 和 bounded memory inputs，输出声明式 `DecisionIntent` 与 `DecisionTrace`；审批、完成态、恢复态、执行态仍由现有真相层负责。
- **Intent is explicit, runtime disposition stays compatible**：035 不直接把现有 `CanonicalDecisionRecord.decision_result` 改写成 `propose_execute` 一类新值；它先在 `policy/decisions.py` 中冻结显式 `brain_intent` 与兼容的 runtime disposition/adapter 规则，再逐步让下游从旧 `decision_result` 迁到新的声明式 contract。
- **Decision inputs, not prompt assembly**：`DecisionInputBuilder` 只产出 versioned `decision_packet_input`，沿用 034 已冻结的 `refs / quality / expansion handles / worker_scope` contract，不接管最终 prompt/messages/tool schema 组装。
- **Brain runs before action selection**：runtime 不再以 `_select_action_ref()` 作为 Brain 的唯一入口；它先为活跃 session 构建 Brain 输入并得到 intent/trace，再只在 `propose_execute / propose_recovery` 等需要 hands 的场景映射出可执行 `action_ref`。
- **Intent before execution**：runtime 先冻结 `DecisionIntent + DecisionTrace + validator / release gate verdict`，再决定是 `suggest_only`、`require_approval`、`propose_execute`、`propose_recovery` 还是 `candidate_closure`；`Brain` 自身不 claim lease、不执行命令，`candidate_closure` 也必须再经过 `Goal Contract + Policy Gate + Session truth` 二次确认。
- **Replay and release are evidence-driven**：`packet_replay` 与 `session_semantic_replay` 都必须回到 canonical truth；release gate 只约束低风险自动决策资格，并以脚本产出的 evidence/report 为唯一放行材料。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Brain contracts | `src/watchdog/services/brain/__init__.py`, `src/watchdog/services/brain/models.py` | 定义 `DecisionIntent`、`DecisionTrace`、`DecisionPacketInput`、validator verdict、provider certification、replay/report schema、approval read contract 与 future worker trace refs |
| Decision input assembly | `src/watchdog/services/brain/decision_input_builder.py` | 从 `SessionService.get_events(...)`、`GoalContractService`、`MemoryHubService` 组装 versioned `decision_packet_input`，记录 provenance/freshness/context quality，不组装最终 prompt |
| Decision orchestration | `src/watchdog/services/brain/service.py` | 编排 Goal Closure Judge、Recovery Planner、Decision Validator，输出声明式 intent/result，不触发 hands，并替代旧的 action-first 入口 |
| Validation and certification | `src/watchdog/services/brain/validator.py`, `src/watchdog/services/brain/provider_certification.py` | 校验 `DecisionIntent` 是否符合 action approval freshness、risk/goal readiness/release gate 条件，并拆分 inference provider certification 与 memory provider adapter certification |
| Replay and release gate | `src/watchdog/services/brain/replay.py`, `src/watchdog/services/brain/release_gate_evidence.py`, `src/watchdog/services/brain/release_gate.py`, `scripts/generate_release_gate_report.py`, `docs/operations/release-gate-runbook.md` | 只读 replay、冻结 evidence corpus、生成/校验 `release_gate_report`、提供 runbook 与脚本入口 |
| Runtime wiring | `src/watchdog/services/policy/engine.py`, `src/watchdog/services/policy/decisions.py`, `src/watchdog/services/session_spine/orchestrator.py`, `src/watchdog/services/session_service/models.py`, `src/watchdog/services/session_service/service.py` | 把 Brain 结果接入现有 canonical decision/event 路径，冻结 `brain_intent -> runtime disposition` adapter，并要求每次 validator/release gate pass/fail/degrade 都先写 canonical Session decision event |
| Verification | `tests/test_watchdog_brain_decision_loop.py`, `tests/test_watchdog_provider_certification.py`, `tests/test_watchdog_decision_replay.py`, `tests/test_watchdog_release_gate.py`, `tests/test_watchdog_release_gate_evidence.py`, `tests/test_watchdog_policy_engine.py`, `tests/test_watchdog_session_spine_runtime.py` | 锁定决策边界、DecisionTrace、replay、release gate、runtime degrade 与现有热路径不回退 |

## 边界纪律

- 035 不把 `Brain` 做成新的 prompt harness、session truth、tool runtime 或 command lease owner。
- 035 不让 `DecisionInputBuilder` 直接读取/写入 provider memory，也不默认把 raw transcript、artifact blob、skill body 或 Memory Hub 私有状态内联进热路径。
- 035 不改变 034 已冻结的 retrieval/input/fallback contract；只消费 `Memory Hub` 输出的 bounded refs、metadata、quality 与 expansion handles。
- 035 必须把 trace/release gate 所需 hash 来源写清：`memory_packet_input_hashes` 来自冻结的 `decision_packet_input` 派生哈希；provider/model/prompt/schema/tool schema/policy engine 等版本哈希来自 harness/runtime config；`memory_provider_adapter_hash` 来自 Memory Hub adapter contract，而不是让 Brain 偷拿 source-of-truth。
- 035 不正式实现 worker/sub-agent orchestration；只冻结 future trace/schema，后续 work item 再把 worker start/complete/fail 写回 Session events。
- 035 必须区分 `action approval` 与 `release report approved_by/report_approved_by`：前者决定某次动作是否能越过 human gate，后者只是 report 治理元数据，不能替代当前动作审批。
- 035 不把 release gate 扩成全平台总闸门；没有有效 report 时，系统必须退回建议态/审批态，而不是阻断 observe-only、session search 或基础 runtime 能力。

## 依赖顺序

1. **先冻结 formal docs 与 035 work item 元数据**
   - 把 035 从总实施计划的 `Task 6` 正式拆成 canonical execution work item；
   - 明确当前实现断点是 `policy.engine` 与 `ResidentOrchestrator` 直连，而不是从零设计一套新 runtime。
2. **再写失败测试锁定 Brain contract**
   - 先证明当前仓库缺少 `DecisionIntent` / `DecisionTrace` / provider certification / replay / release gate modules；
   - 先证明当前 auto-execute 路径还没有 runtime-enforced 的 release gate、approval freshness 与 canonical release verdict 事件校验。
3. **再实现最小 Brain 决策面与 trace**
   - 先交付 Brain contracts、decision input builder、validator、certification 和 replay；
   - 同步冻结 `brain_intent -> runtime disposition` adapter，避免直接改坏现有 `decision_result` 下游。
4. **再接 runtime wiring 与 release gate**
   - 让 `policy/engine.py` 与 `session_spine/orchestrator.py` 改为先跑 Brain，再消费声明式 Brain 结果；
   - 只允许 `propose_execute` 在低风险资格满足且 release verdict 已落 canonical event 时进入执行面。
5. **最后运行验证并更新 handoff**
   - 固定后续 work item 只消费 `DecisionTrace`、release evidence/report 与 future worker contract；
   - 不回头把 `Brain` 重新长成中心化 harness。

## 分阶段计划

### Phase 1：冻结 035 formal docs、任务分解与执行元数据

交付内容：

- `specs/035-brain-decision-boundary-and-release-gate/spec.md`
- `specs/035-brain-decision-boundary-and-release-gate/plan.md`
- `specs/035-brain-decision-boundary-and-release-gate/tasks.md`
- `specs/035-brain-decision-boundary-and-release-gate/task-execution-log.md`
- `.ai-sdlc/work-items/035-brain-decision-boundary-and-release-gate/*`

关键原则：

- 先把 035 收紧为 Brain decision boundary + release gate；
- 明确它只消费 030-034 已冻结的 truth / projection / goal / recovery / memory contracts。

### Phase 2：写失败测试锁定 Brain、DecisionTrace、replay 与 release gate contract

交付内容：

- `tests/test_watchdog_brain_decision_loop.py`
- `tests/test_watchdog_provider_certification.py`
- `tests/test_watchdog_decision_replay.py`
- `tests/test_watchdog_release_gate.py`
- `tests/test_watchdog_release_gate_evidence.py`

关键原则：

- 红测优先锁定 `DecisionIntent` 只允许声明式结果；
- 红测优先锁定 `DecisionTrace` 必须引用 canonical truth 与 approval freshness；
- 红测优先锁定 release gate report 缺失/漂移/过期时只能 degrade，且每次 PASS/FAIL/degrade 都要先写 canonical event；
- 红测优先锁定 future worker trace refs 只允许声明式引用，不允许越权字段。

### Phase 3：实现最小 Brain contracts、decision input builder 与 validator/certification/replay

交付内容：

- `src/watchdog/services/brain/__init__.py`
- `src/watchdog/services/brain/models.py`
- `src/watchdog/services/brain/decision_input_builder.py`
- `src/watchdog/services/brain/service.py`
- `src/watchdog/services/brain/validator.py`
- `src/watchdog/services/brain/provider_certification.py`
- `src/watchdog/services/brain/replay.py`
- `src/watchdog/services/policy/decisions.py`
- `src/watchdog/services/session_service/models.py`
- `src/watchdog/services/session_service/service.py`

关键原则：

- 先把 `DecisionTrace` 与 `decision_packet_input` 做成稳定 contract；
- provider certification 和 replay 必须只读、可审计、可比较 drift，不触发 live execution 或 live recall 补洞。

### Phase 4：接入 release gate evidence/runtime wiring，并验证低风险自动决策资格门禁

交付内容：

- `src/watchdog/services/brain/release_gate_evidence.py`
- `src/watchdog/services/brain/release_gate.py`
- `scripts/generate_release_gate_report.py`
- `docs/operations/release-gate-runbook.md`
- `src/watchdog/services/policy/engine.py`
- `src/watchdog/services/policy/decisions.py`
- `src/watchdog/services/session_spine/orchestrator.py`
- `src/watchdog/services/session_service/models.py`
- `src/watchdog/services/session_service/service.py`
- `tests/fixtures/release_gate_packets.jsonl`
- `tests/fixtures/release_gate_shadow_runs.jsonl`
- `tests/fixtures/release_gate_expected_report.json`
- `tests/fixtures/release_gate_label_manifest.json`
- `tests/test_watchdog_policy_engine.py`
- `tests/test_watchdog_session_spine_runtime.py`

关键原则：

- release gate 必须是 runtime enforced 的资格门禁，而不是文档约定；
- orchestrator 只能消费 validator/release gate 放行后的声明式结果，不能重新把 Brain 内联成自由逻辑；
- release gate 的 PASS/FAIL/degrade、report hash、input hash、approval read ref 必须先进入 canonical Session decision event，再允许创建 command。

### Phase 5：运行验证并交接到 Feishu/control-plane 与 e2e work item

交付内容：

- `specs/035-brain-decision-boundary-and-release-gate/task-execution-log.md`
- `.ai-sdlc/work-items/035-brain-decision-boundary-and-release-gate/latest-summary.md`

关键原则：

- handoff 必须说明 035 已冻结 Brain trace/replay/release gate 输入输出边界；
- 后续 Feishu/e2e work item 只消费这些边界，不回退到旧的 policy-only auto-execute。

## 测试计划

- `tests/test_watchdog_brain_decision_loop.py`
  - `DecisionInputBuilder` 只产出 versioned `decision_packet_input`
  - `Brain` 只输出声明式 `DecisionIntent`
  - `brain_intent -> runtime disposition` adapter 规则被显式冻结，不直接拿旧 `decision_result` 充当 Brain intent
  - Brain 不再被旧 `_select_action_ref()` 的 action-first 入口短路
  - `candidate_closure` 与 `propose_recovery` 都要经过 validator/policy/Session truth 二次校验
- `tests/test_watchdog_provider_certification.py`
  - inference provider certification 与 memory provider adapter certification 分离
  - provider/model/prompt/schema/risk-policy/tool-schema/memory-adapter 任一变化会使旧 certification / report 失效
- `tests/test_watchdog_decision_replay.py`
  - `packet_replay` 复现冻结输入
  - `session_semantic_replay` 从 canonical event slice 重建输入
  - 缺失输入时显式标记 `replay_incomplete`
- `tests/test_watchdog_release_gate.py`
  - release gate report 缺字段、过期、漂移、approval stale 时只能 degrade
  - 漂移矩阵覆盖 `decision_input_builder_version`、`policy_engine_version`、`risk_policy_version`、provider/model/prompt/schema、`tool_schema_hash`、`memory_provider_adapter_hash`
  - release gate verdict / degrade reason / report hash / input hash / approval read ref 必须先落 canonical event
  - observe-only 与 suggest-only 不被 release gate 阻断
- `tests/test_watchdog_release_gate_evidence.py`
  - `certification_packet_corpus`、`shadow_decision_ledger`、`release_gate_report` 必须同时存在
  - memory degrade/conflict 样本优先来自 canonical Session events
  - 固定 evidence fixture/artifact 可重放，不退化成 inline fixture
- `tests/test_watchdog_policy_engine.py`
  - policy 不再直接决定 auto execute，而是消费 Brain/validator/release gate verdict
- `tests/test_watchdog_session_spine_runtime.py`
  - orchestrator 只在 low-risk 条件满足时执行 `propose_execute`
  - approval stale、report drift、memory conflict 等场景会自动降级为 `suggest_only` 或 `require_approval`
  - Session event 写入失败时不得创建 command、claim lease 或执行

## 主要风险与应对

### 风险 1：Brain 重新变成新的 runtime 中枢

应对：

- 把输入、intent、trace、validator、release gate 拆成小模块；
- orchestrator 只拿声明式结果，不拿 Brain 内部 prompt/runtime 细节。

### 风险 2：DecisionTrace 只是日志，不足以回放或审计

应对：

- 强制 trace 记录 `session_event_range/cursor`、goal version、policy hash、memory refs/hashes、provider/schema、approval read 与 degrade reason；
- replay 测试必须覆盖 drift、missing context 和人工 override 差异。

### 风险 3：release gate 退化成“有报告就放行”的软约束

应对：

- runtime 必须实时校验 report hash、TTL、版本与当前输入一致性；
- 没有有效 report 时只允许建议态或审批态。

### 风险 4：035 顺手把 034 的 packet/memory contract 改坏

应对：

- `DecisionInputBuilder` 只消费 `MemoryHubService.packet_inputs()` 的现有 contract；
- 不在 035 修改 final packet policy 或 provider memory lifecycle。

### 风险 5：future worker/sub-agent contract 提前侵入当前主路径

应对：

- 只在 `DecisionTrace` / model schema 中冻结 future refs；
- 不在 035 创建正式 worker runtime 或额外执行通道。

## 验收口径

只有当以下条件同时满足，035 才算完成：

1. `Brain` 已被收紧为声明式决策层，不能直接执行命令、修改审批或写完成态；
2. `DecisionInputBuilder` 只输出 versioned `decision_packet_input`，不接管最终 prompt/messages/tool schema；
3. `DecisionTrace` 已能把每次决策追溯到 canonical truth，并支撑 `packet_replay` 与 `session_semantic_replay`；
4. provider certification、release gate evidence 与 `release_gate_report` 已形成脚本化、可校验、可过期的资格门禁闭环，且漂移矩阵覆盖 `decision_input_builder_version`、`policy_engine_version` 与 approval freshness；
5. `policy/engine.py` 与 `session_spine/orchestrator.py` 已改为消费声明式 Brain 结果与 trace，low-risk auto-decision 只能在 runtime 校验通过后执行；
6. release gate 的 PASS/FAIL/degrade 与 future worker trace refs 都已以 canonical event / schema 形式冻结，后续 work item 只消费 Brain trace/replay/release gate/future worker contract，不把 Brain 升级成新的中心化 harness。
