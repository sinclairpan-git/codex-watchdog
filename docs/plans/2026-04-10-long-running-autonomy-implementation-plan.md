# 长时运行自治架构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 以最小迁移风险把当前 `watchdog + a-control-agent` 逐步收敛到 `Session Service -> Projection Cache -> Goal Contract -> Brain/Recovery -> Feishu` 的单控制面架构，同时把 `Memory Hub` 收敛成可独立开发的能力层，通过统一 contract 同时服务 Codex 长时自动开发与 `AI_AutoSDLC` 调用，并停止 `OpenClaw` 继续充当主链路。

**Architecture:** 先建立新的事件真源与双写桥，再把现有 `session_spine`、审批视图和审计查询改成从事件投影读取，之后补齐 `Goal Contract`、恢复事务、`Brain + Provider certification + replay` 决策闭环和飞书控制面，并把 `Memory Hub` 收敛成受 `Session Service + Goal Contract` 约束的 retrieval/provider 能力层，通过受控 packet inputs、session search、skills metadata 和安全降级同时服务 Codex 主路径与后续兼容入口。整个过程坚持 fail-closed、真源前置写入、低风险先迁移，不在第一阶段引入新的自动高危能力。

**Tech Stack:** Python, FastAPI, Pydantic, JSON file stores, SQLite/FTS or equivalent local index for `Memory Hub`, pytest, existing `watchdog`/`a_control_agent` service layers

---

## 目标文件结构

- `src/watchdog/services/session_service/`
  - 新建事件真源、single-writer append-only writer、approval/notification/human-override truth 与 lineage/recovery transaction primitives。
- `src/watchdog/services/session_spine/`
  - 保留现有 stable read surface，但把 `store.py`、`projection.py`、`service.py` 收敛为事件投影消费层。
- `src/watchdog/services/policy/`
  - 保留硬边界与风险策略，但要求先写 Session events，再允许命令进入执行面。
- `src/watchdog/services/approvals/`
  - 降级为 Session projection 的兼容外观与 inbox cache，不再作为独立审批真源。
- `src/watchdog/services/delivery/`
  - 保留兼容 envelope 和 worker；后续只作为 side effect consumer，不再承担业务真相。
- `src/watchdog/services/goal_contract/`
  - 新建 Goal Contract bootstrap、revision、inheritance 逻辑。
- `src/watchdog/services/brain/`
  - 新建 packet builder、goal closure judge、decision validator、provider certification 与 replay harness。
- `src/watchdog/services/memory_hub/`
  - 新建独立 contract、resident facade、session search archive、基线扫描、增量索引、skill registry、packet input retrieval facade。
- `src/watchdog/api/`
  - 增加 Session query / Feishu control / Goal Contract 读取接口，逐步退役 OpenClaw 专属入口。
- `tests/`
  - 为每个迁移阶段补充事件写入屏障、命令租约恢复、通知投递恢复、projection 兼容、recovery lineage、Goal Contract 治理、Brain 决策回放、Memory Hub 降级策略、Feishu ACL 和端到端 release gate 的失败/成功用例。

### Task 1: 建立 Session Service 事件真源与写入闸门

**Canonical execution work item:** `specs/030-session-service-event-truth-write-barrier/`

**Files:**
- Create: `src/watchdog/services/session_service/models.py`
- Create: `src/watchdog/services/session_service/store.py`
- Create: `src/watchdog/services/session_service/service.py`
- Modify: `src/watchdog/services/policy/engine.py`
- Modify: `src/watchdog/services/policy/decisions.py`
- Modify: `src/watchdog/services/session_spine/orchestrator.py`
- Modify: `src/watchdog/services/approvals/service.py`
- Test: `tests/test_watchdog_session_service.py`
- Create: `tests/test_watchdog_session_service_atomicity.py`
- Modify: `tests/test_watchdog_approval_loop.py`
- Create: `tests/test_watchdog_command_leases.py`

- [ ] **Step 1: 写失败测试，冻结事件写入契约**
  - 新增测试覆盖 `decision_proposed -> decision_validated -> command_created` 的前置顺序。
  - 新增测试覆盖 `approval_requested -> approval_approved|approval_rejected|approval_expired` 的前置顺序。
  - 新增测试覆盖 `memory_unavailable_degraded`、`memory_conflict_detected` 必须作为 `Session Service` 事件落账，不能只停留在 `Memory Hub` 内部日志或指标。
  - 新增测试覆盖 `notification_announced -> notification_receipt_recorded -> human_override_recorded` 的状态推进顺序。
  - 新增测试覆盖 `command_claimed -> command_lease_renewed -> command_claim_expired -> command_requeued` 的中间态恢复顺序。
  - 新增测试覆盖“真相事件写入失败时不得执行命令”的 fail-closed 行为。
  - 新增测试覆盖单 writer、写锁丢失、原子追加失败与崩溃恢复后的幂等去重。

- [ ] **Step 2: 运行测试确认正确失败**
  - Run: `uv run pytest tests/test_watchdog_session_service.py tests/test_watchdog_session_service_atomicity.py tests/test_watchdog_approval_loop.py tests/test_watchdog_command_leases.py -q`
  - Expected: 因 `session_service` 尚不存在、审批/通知仍绕过事件真源、命令租约恢复未定义或 writer 尚不具备原子性而失败。

- [ ] **Step 3: 实现 append-only 事件模型与 writer**
  - 新增 `SessionEventRecord`、`SessionLineageRecord`、`RecoveryTransactionRecord`。
  - 实现本地 JSON store 版本的 append-only writer、单 writer 锁和崩溃恢复后的幂等索引。
  - 在 policy/orchestrator 中先写入事件，再允许产生执行命令。
  - 为 `memory_unavailable_degraded`、`memory_conflict_detected` 补齐 schema、writer 与 query facade，使记忆异常成为可重放、可审计的 canonical event。
  - 为 `command_claimed` 冻结 `worker_id/lease_expires_at`，并实现 claim 过期、requeue 与晚到结果拒绝策略。
  - 审批、通知、人工覆盖只从 `Session Service` 写入与派生，不再维护独立真源状态。

- [ ] **Step 4: 运行测试确认通过**
  - Run: `uv run pytest tests/test_watchdog_session_service.py tests/test_watchdog_session_service_atomicity.py tests/test_watchdog_approval_loop.py tests/test_watchdog_command_leases.py tests/test_watchdog_policy_engine.py tests/test_watchdog_session_spine_runtime.py -q`
  - Expected: 新增事件真源、审批链路、记忆异常 canonical event、命令租约恢复和 writer 原子性测试通过，既有 policy/runtime 行为不回退。

- [ ] **Step 5: 提交**
  - `git add src/watchdog/services/session_service src/watchdog/services/policy src/watchdog/services/session_spine src/watchdog/services/approvals/service.py tests/test_watchdog_session_service.py tests/test_watchdog_session_service_atomicity.py tests/test_watchdog_approval_loop.py tests/test_watchdog_command_leases.py tests/test_watchdog_policy_engine.py tests/test_watchdog_session_spine_runtime.py`
  - `git commit -m "feat: add session service event writer"`

### Task 2: 把 session_spine 降级为 Session events projection

**Canonical execution work item:** `specs/031-session-spine-events-projection-read-surface/`

**Files:**
- Modify: `src/watchdog/services/session_spine/store.py`
- Modify: `src/watchdog/services/session_spine/projection.py`
- Modify: `src/watchdog/services/session_spine/service.py`
- Modify: `src/watchdog/services/audit/service.py`
- Modify: `src/watchdog/api/session_spine_queries.py`
- Test: `tests/test_watchdog_session_spine_projection.py`
- Test: `tests/test_watchdog_session_spine_api.py`

- [ ] **Step 1: 写失败测试，冻结 projection 来源优先级**
  - 覆盖 projection 优先读 Session events。
  - 覆盖旧 `store` 仅在迁移缺口时作为兼容回填。
  - 覆盖 approval inbox、notification status、human override status 全部由 Session projection 派生。
  - 覆盖 `memory_unavailable_degraded`、`memory_conflict_detected` 的当前状态与最近原因也由 Session projection/query 派生，而不是读 Memory Hub 私有状态。

- [ ] **Step 2: 运行测试确认正确失败**
  - Run: `uv run pytest tests/test_watchdog_session_spine_projection.py tests/test_watchdog_session_spine_api.py -q`
  - Expected: 因读取顺序和字段来源仍基于旧 store 而失败。

- [ ] **Step 3: 最小实现 projection reader**
  - 从 `Session Service` 派生 session/progress/facts/approval inbox。
  - 从 `Session Service` 派生 notification status、human override status，并把 approvals store 降级为兼容 facade。
  - 从 `Session Service` 派生当前 memory degradation/conflict 状态，供 packet builder、audit query 和 release gate evidence 直接读取。
  - 明确 stable `session_id` 与 projection `thread_id` 的分离。
  - `audit/service` 改为优先读 Session query facade。

- [ ] **Step 4: 运行测试确认通过**
  - Run: `uv run pytest tests/test_watchdog_session_spine_projection.py tests/test_watchdog_session_spine_api.py tests/test_watchdog_ops.py -q`
  - Expected: stable read surface 保持兼容，同时数据优先级切换到事件投影。

- [ ] **Step 5: 提交**
  - `git add src/watchdog/services/session_spine src/watchdog/services/audit/service.py src/watchdog/api/session_spine_queries.py tests/test_watchdog_session_spine_projection.py tests/test_watchdog_session_spine_api.py tests/test_watchdog_ops.py`
  - `git commit -m "refactor: read session spine from session events"`

### Task 3: 引入 Goal Contract 一等持久化对象

**Canonical execution work item:** `specs/032-goal-contract-persistence-and-governance/`

**Files:**
- Modify: `src/watchdog/services/session_service/models.py`
- Modify: `src/watchdog/services/session_service/service.py`
- Create: `src/watchdog/services/goal_contract/models.py`
- Create: `src/watchdog/services/goal_contract/service.py`
- Modify: `src/a_control_agent/storage/tasks_store.py`
- Modify: `src/watchdog/services/session_spine/orchestrator.py`
- Modify: `src/watchdog/services/policy/engine.py`
- Modify: `tests/test_watchdog_session_service.py`
- Test: `tests/test_watchdog_goal_contract.py`
- Create: `tests/test_watchdog_goal_contract_stage_boundary.py`

- [ ] **Step 1: 写失败测试，冻结 Goal Contract 生命周期**
  - 覆盖 bootstrap、revision、child session adopt。
  - 覆盖 `goal_contract_created|revised|adopted_by_child_session` 必须作为 `Session Service` 事件存在，任何物化快照都不能越过最新 event version 生效。
  - 覆盖 `explicit_deliverables` / `completion_signals` 缺失时只能停在 `observe-only` 或 `suggest-only`。
  - 覆盖 `AI_AutoSDLC.stage/active_goal` 只能作为 bootstrap context，不得覆盖当前 `Goal Contract.current_phase_goal`。
  - 覆盖 `stage/active_goal` 与现有 contract 冲突时必须记录冲突并阻断自动推进。

- [ ] **Step 2: 运行测试确认正确失败**
  - Run: `uv run pytest tests/test_watchdog_goal_contract.py tests/test_watchdog_goal_contract_stage_boundary.py -q`
  - Expected: 因 Goal Contract 尚不存在、生命周期事件尚未进入 `Session Service`，或阶段边界仍可被上游静默覆盖而失败。

- [ ] **Step 3: 实现最小 Goal Contract 存储与治理**
  - 在 `Session Service` 中补齐 `goal_contract_created|revised|adopted_by_child_session` 与冲突事件 schema，并把 version 切换纳入 write barrier。
  - 从任务标题、用户最近指令、稳定摘要生成初始 contract。
  - 将 `goal_contract/service.py` 实现为治理与查询 facade；其物化快照只能从 Session events 重建，不得成为独立真源。
  - 在决策环节只允许模型建议补全，不允许自由覆盖核心字段。
  - 将 `AI_AutoSDLC.stage/active_goal` 收敛为 request context / deterministic-derived input，而非运行时真相。
  - 子会话恢复必须显式继承 `goal_contract_version`。
  - 发现阶段冲突时写入冲突事件、返回差异摘要，并要求人工确认或显式修订。

- [ ] **Step 4: 运行测试确认通过**
  - Run: `uv run pytest tests/test_watchdog_goal_contract.py tests/test_watchdog_goal_contract_stage_boundary.py tests/test_watchdog_policy_engine.py tests/test_watchdog_session_spine_runtime.py -q`
  - Expected: Goal Contract 成为自动决策的显式输入和治理对象，当前有效 version 只来源于 `Session Service` 事件，`AI_AutoSDLC` 阶段信息只作为上下文与模板来源。

- [ ] **Step 5: 提交**
  - `git add src/watchdog/services/session_service src/watchdog/services/goal_contract src/a_control_agent/storage/tasks_store.py src/watchdog/services/session_spine/orchestrator.py src/watchdog/services/policy/engine.py tests/test_watchdog_session_service.py tests/test_watchdog_goal_contract.py tests/test_watchdog_goal_contract_stage_boundary.py`
  - `git commit -m "feat: persist and govern goal contracts"`

### Task 4: 把恢复流程改成 Recovery Transaction + lineage

**Canonical execution work item:** `specs/033-recovery-transaction-lineage/`

**Files:**
- Modify: `src/watchdog/services/session_spine/recovery.py`
- Modify: `src/watchdog/services/session_spine/orchestrator.py`
- Modify: `src/watchdog/services/session_spine/actions.py`
- Modify: `src/watchdog/services/approvals/service.py`
- Create: `tests/test_watchdog_recovery_transaction.py`
- Modify: `tests/test_watchdog_session_spine_runtime.py`

- [ ] **Step 1: 写失败测试，冻结恢复事务步骤**
  - 覆盖 `recovery_tx_started -> handoff_packet_frozen -> child_session_created -> lineage_committed -> recovery_tx_completed`。
  - 覆盖在 `lineage_committed` 前 parent session 不得标记为已接续完成。

- [ ] **Step 2: 运行测试确认正确失败**
  - Run: `uv run pytest tests/test_watchdog_recovery_transaction.py tests/test_watchdog_session_spine_runtime.py -q`
  - Expected: 因当前恢复模型仍偏单步动作而失败。

- [ ] **Step 3: 实现最小 recovery transaction**
  - 为高频 `session_continuity_failure` 建立固定事务记录。
  - 在 approval/decision/delivery 层统一识别同一 `recovery_key`，防止重复恢复。
  - 子会话创建后先提交 lineage，再决定是否自动继续。

- [ ] **Step 4: 运行测试确认通过**
  - Run: `uv run pytest tests/test_watchdog_recovery_transaction.py tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_delivery_worker.py -q`
  - Expected: 中断恢复从“动作”变成“事务”，审批和 delivery 不再把恢复当自由重复按钮。

- [ ] **Step 5: 提交**
  - `git add src/watchdog/services/session_spine/recovery.py src/watchdog/services/session_spine/orchestrator.py src/watchdog/services/session_spine/actions.py src/watchdog/services/approvals/service.py tests/test_watchdog_recovery_transaction.py tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_delivery_worker.py`
  - `git commit -m "feat: add recovery transactions and lineage"`

### Task 5: 建独立 Memory Hub 能力层的 Codex-critical 切片（正式 work item：`specs/034-memory-hub-codex-critical/`）

**Files:**
- Create: `src/watchdog/services/memory_hub/models.py`
- Create: `src/watchdog/services/memory_hub/service.py`
- Create: `src/watchdog/services/memory_hub/indexer.py`
- Create: `src/watchdog/services/memory_hub/contracts.py`
- Create: `src/watchdog/services/memory_hub/packets.py`
- Create: `src/watchdog/services/memory_hub/skills.py`
- Modify: `src/watchdog/services/session_service/service.py`
- Modify: `src/watchdog/services/session_spine/orchestrator.py`
- Modify: `src/watchdog/services/delivery/store.py`
- Create: `tests/test_watchdog_memory_hub.py`
- Create: `tests/test_watchdog_memory_packets.py`
- Create: `tests/test_watchdog_memory_degradation.py`

- [ ] **Step 1: 写失败测试，冻结受约束的 retrieval/provider contract**
  - 覆盖 `Session Service + Goal Contract` 仍是运行时真源，`Memory Hub` 只输出 advisory retrieval、skills metadata 与 packet inputs。
  - 覆盖 `resident` 受硬预算约束，并且进入当前 turn 后保持 frozen，不被当轮 memory update 回改。
  - 覆盖 resident write surface 具备 `add|replace|remove` 或等价语义，容量压力下必须显式 consolidate，而不是静默追加。
  - 覆盖 `session search archive` 只返回摘要、引用与 expansion handles，不返回整段原始 transcript / log / blob 进入热路径。
  - 覆盖 `skill registry` 默认只暴露名称、短描述、trust/security/update 元数据，全文按需展开。
  - 覆盖 `Session Service` 提供事件切片读取能力，summary/packet input 不得替代 raw event replayability；compaction 后仍可通过 cursor/range/anchor 恢复关键 raw events。
  - 覆盖 `security_verdict` 是注入前强制门禁，正式枚举至少包括 `pass|caution|warn|dangerous|quarantine`；其中 `dangerous` 不可 override、只能 quarantine，`caution|warn` 也只能在人工 override 留痕后降级为 reference-only。
  - 覆盖 `Memory Hub` 不可用时必须退化为 `Session Service + runtime snapshot`，并以 `Session Service` 事件显式记录降级事实。
  - 覆盖 `memory_conflict_detected`、TTL 过期、skill 技术栈不匹配与 security verdict 失败时必须降级为参考信息，其中 conflict/degrade 事实必须带 `reason_code` 与 `source_ref`，并能从 Session query 读回。
  - 覆盖 provider lifecycle 只作为 compatibility adapter，provider memory ops 只允许 `search|store|manage` 类受控操作，不能接管 final packet policy。
  - 覆盖 retrieval 质量指标：`key_fact_recall`、`irrelevant_summary_precision`、`token_budget_utilization`、`expansion_miss_rate`。
  - 覆盖 `AI_AutoSDLC`、`Cursor/受控聊天`、`User Model`、`Periodic Nudge` 只冻结 disabled-by-default preview contract，不作为一期 release blocker。

- [ ] **Step 2: 运行测试确认正确失败**
  - Run: `uv run pytest tests/test_watchdog_memory_hub.py tests/test_watchdog_memory_packets.py tests/test_watchdog_memory_degradation.py -q`
  - Expected: 因 `Memory Hub` contract、session replay/JIT expansion、安全门禁、packet input 组装或降级逻辑尚未实现而失败。

- [ ] **Step 3: 实现第一期完整可用但受约束的垂直切片**
  - 建立 `Project Registrar`、`Workspace Baseline Scanner`、`Incremental Workspace Indexer`。
  - 实现 `resident memory facade`，冻结预算、裁剪和 provenance/security 规则。
  - 实现 resident 的受控写语义与容量治理，禁止绕过 frozen packet block 的直连注入。
  - 实现 `session search archive` 的索引、检索、摘要与 expansion handles。
  - 实现 `skill registry facade` 与 trust/security/update 元数据，一期只要求 metadata、按需展开与安全降级，preview promotion 不进入正式主路径；skill body 继续由 source-of-truth 提供，Memory Hub 只持有 metadata/reference。
  - 冻结 `User Model`、`Periodic Nudge`、`AI_AutoSDLC`、`Cursor/受控聊天` 的 preview schema 与调用边界；它们缺省 disabled，不进入一期 release gate。
  - 实现统一 `ingest + packet input contract`，其中 `watchdog/Codex` 为一期主路径；final packet policy 仍由调用侧 harness 决定。
  - provider lifecycle 只作为 compatibility adapter 落地，provider memory ops 限定在受控 memory record 范围内，不获得 shell/toolchain/credential 通道。
  - transcript、artifact、retrieval packet 只建索引和 blob 引用，不进入热路径真源表。
  - 所有条目必须带 provenance；project/archive 条目强制 `project_id`，user/global 条目允许 project/task 为空，但必须显式标明 scope、source、timestamp、hash、freshness 与 security verdict。
  - `Memory Hub` 不可用或与 Session facts 冲突时，必须先写入 `memory_unavailable_degraded` / `memory_conflict_detected` 到 `Session Service`，再执行 packet 降级；Memory 本地日志不得替代 canonical event。
  - 一期 release gate 只要求 `Codex` 主路径、resident/search/skills packet inputs、安全门禁与降级闭环，不先做通用知识平台能力。
  - `Memory Hub` 不可用、冲突、TTL 失效或 security verdict 不通过时，必须保证 Codex 仍可依靠 `Session Service + runtime snapshot` 接续。

- [ ] **Step 4: 运行测试确认通过**
  - Run: `uv run pytest tests/test_watchdog_memory_hub.py tests/test_watchdog_memory_packets.py tests/test_watchdog_memory_degradation.py tests/test_watchdog_session_spine_runtime.py -q`
  - Expected: `Memory Hub` 既满足“基线建档 + 增量摄取 + provenance”，又能对 `Codex` 主路径返回可用 packet，并在异常时通过 `Session Service` 事件安全降级；`AI_AutoSDLC/User Model/Periodic Nudge/Cursor` 等 preview contract 即使只冻结边界、不落完整实现，也不影响一期放行。

- [ ] **Step 5: 提交**
  - `git add src/watchdog/services/memory_hub src/watchdog/services/session_service/service.py src/watchdog/services/session_spine/orchestrator.py src/watchdog/services/delivery/store.py tests/test_watchdog_memory_hub.py tests/test_watchdog_memory_packets.py tests/test_watchdog_memory_degradation.py`
  - `git commit -m "feat: add independent memory hub capability layer"`

### Task 6: 补齐 Brain / Provider certification / replay / 低风险自动决策闭环

**Canonical execution work item:** `specs/035-brain-decision-boundary-and-release-gate/`

**Files:**
- Create: `src/watchdog/services/brain/models.py`
- Create: `src/watchdog/services/brain/decision_input_builder.py`
- Create: `src/watchdog/services/brain/service.py`
- Create: `src/watchdog/services/brain/validator.py`
- Create: `src/watchdog/services/brain/provider_certification.py`
- Create: `src/watchdog/services/brain/replay.py`
- Create: `src/watchdog/services/brain/release_gate.py`
- Create: `src/watchdog/services/brain/release_gate_evidence.py`
- Create: `scripts/generate_release_gate_report.py`
- Create: `docs/operations/release-gate-runbook.md`
- Modify: `src/watchdog/services/policy/engine.py`
- Modify: `src/watchdog/services/session_spine/orchestrator.py`
- Test: `tests/test_watchdog_brain_decision_loop.py`
- Test: `tests/test_watchdog_provider_certification.py`
- Test: `tests/test_watchdog_decision_replay.py`
- Create: `tests/test_watchdog_release_gate.py`
- Create: `tests/test_watchdog_release_gate_evidence.py`
- Create: `tests/fixtures/release_gate_packets.jsonl`
- Create: `tests/fixtures/release_gate_shadow_runs.jsonl`
- Create: `tests/fixtures/release_gate_expected_report.json`
- Create: `tests/fixtures/release_gate_label_manifest.json`

- [x] **Step 1: 写失败测试，冻结决策闭环能力**
  - 覆盖 `Policy Gate -> Decision Input Builder -> Goal Closure Judge -> Recovery Planner -> Decision Validator` 的最小顺序闭环。
  - 覆盖 `Brain` 只能产出声明式 `DecisionIntent`，不得直接执行工具、claim lease、写完成态或修改 approval state。
  - 覆盖 `DecisionInputBuilder` 只生成 versioned `decision_packet_input`，不拥有最终 prompt/messages/tool schema 组装权。
  - 覆盖 provider 未通过 certification 时只能停留在 `observe-only` 或 `suggest-only`。
  - 覆盖低风险自动决策必须同时满足 `Goal Contract` 完整、provider 合格、risk band 允许、decision input freshness 合格、当前有效 approval 存在且未过期。
  - 覆盖历史 `packet_replay`、`session_semantic_replay`、provider 对比和决策漂移记录。
  - 覆盖 release gate 的量化门槛：样本规模、schema 成功率、安全失败率、漂移率、错误完成率和 shadow override 率。
  - 覆盖 release gate 证据生产闭环：`certification_packet_corpus`、`shadow_decision_ledger`、`release_gate_report` 三类产物缺一不可，没有有效报告时不得切入 `low-risk auto-decision`。
  - 覆盖 `memory degrade/conflict` 样本必须优先从 `Session Service` 的 canonical event 语料进入认证集，不能只靠 Memory Hub 内部夹具凑数。
  - 覆盖 `release_gate_report` 必须引用冻结窗口、`label_manifest`、`generated_by`、`approved_by` 与归档地址；缺任一字段不得视为可放行报告。
  - 覆盖 provider/model/prompt/schema/risk-policy/tool-schema/memory-adapter 任一变化都会使既有 `release_gate_report` 失效，必须重新认证。

- [x] **Step 2: 运行测试确认正确失败**
  - Run: `uv run pytest tests/test_watchdog_brain_decision_loop.py tests/test_watchdog_provider_certification.py tests/test_watchdog_decision_replay.py tests/test_watchdog_release_gate.py tests/test_watchdog_release_gate_evidence.py -q`
  - Expected: 因 `Brain` 闭环、provider 准入、replay harness、release gate 证据包或量化放行报告尚未实现而失败。

- [x] **Step 3: 实现最小 Brain 决策闭环**
  - 实现 `Decision Input Builder`、`Goal Closure Judge`、`Recovery Planner`、`Decision Validator` 的最小服务编排。
  - 实现 provider certification、模式分级和结构化输出校验，并明确区分 inference provider certification 与 memory provider adapter certification。
  - 实现历史 `packet_replay` 与 `session_semantic_replay`，输出漂移、缺口原因和失败分类。
  - 实现 `release_gate_evidence`，把历史 packet、人工标注和 shadow mode 候选决策冻结为 `certification_packet_corpus` 与 `shadow_decision_ledger`，并产出可追溯哈希。
  - 在证据构建时优先消费 `memory_unavailable_degraded`、`memory_conflict_detected` 的 Session event 语料，保证 memory 场景覆盖来自 canonical truth 而非旁路日志。
  - 实现固定脚本/运行规程，产出 `label_manifest`、冻结窗口、报告归档路径和责任人元数据；禁止靠人工拼接放行材料。
  - 实现 release gate evaluator，基于证据包生成唯一有效的 `release_gate_report`；未达门槛、报告缺失、报告过期、输入哈希不一致或当前 approval 不满足时自动停留在 `observe-only/suggest-only`，门槛回归失败时自动降级。
  - 仅在低风险前提满足时允许 orchestrator 消费 `propose_execute` 进入执行面，否则退化为 `suggest_only`、`require_approval` 或 `reject`。

- [x] **Step 4: 运行测试确认通过**
  - Run: `uv run pytest tests/test_watchdog_brain_decision_loop.py tests/test_watchdog_provider_certification.py tests/test_watchdog_decision_replay.py tests/test_watchdog_release_gate.py tests/test_watchdog_release_gate_evidence.py tests/test_watchdog_policy_engine.py tests/test_watchdog_session_spine_runtime.py -q`
  - Expected: 自治主链路具备可评估、可回放、可降级的低风险自动决策能力，并且 low-risk 模式受“量化门槛 + 证据包 + 放行报告 + runtime 校验”四重约束。

- [x] **Step 5: 提交**
  - `git add src/watchdog/services/brain scripts/generate_release_gate_report.py docs/operations/release-gate-runbook.md src/watchdog/services/policy/engine.py src/watchdog/services/session_spine/orchestrator.py tests/test_watchdog_brain_decision_loop.py tests/test_watchdog_provider_certification.py tests/test_watchdog_decision_replay.py tests/test_watchdog_release_gate.py tests/test_watchdog_release_gate_evidence.py tests/fixtures/release_gate_packets.jsonl tests/fixtures/release_gate_shadow_runs.jsonl tests/fixtures/release_gate_expected_report.json tests/fixtures/release_gate_label_manifest.json`
  - `git commit -m "feat: add brain decision loop and provider certification"`

### Task 7: 迁移到 Feishu 主控制面并退役 OpenClaw 主链路

**Canonical execution work item:** `specs/036-feishu-control-plane-and-openclaw-retirement/`

**Files:**
- Create: `src/watchdog/services/feishu_control/service.py`
- Create: `src/watchdog/api/feishu_control.py`
- Modify: `src/watchdog/main.py`
- Modify: `src/watchdog/api/openclaw_bootstrap.py`
- Modify: `src/watchdog/api/openclaw_callbacks.py`
- Modify: `src/watchdog/services/adapters/openclaw/adapter.py`
- Modify: `src/watchdog/services/delivery/store.py`
- Modify: `src/watchdog/services/delivery/worker.py`
- Modify: `src/watchdog/services/session_service/models.py`
- Modify: `src/watchdog/services/session_spine/projection.py`
- Test: `tests/test_watchdog_feishu_control.py`
- Test: `tests/test_openclaw_contracts.py`
- Create: `tests/test_watchdog_notification_delivery.py`

- [x] **Step 1: 写失败测试，冻结 Feishu 控制语义**
  - 覆盖 DM 才允许高风险确认。
  - 覆盖 `interaction_context_id`、`interaction_family_id`、actor binding、过期、replay protection。
  - 覆盖审批确认、通知回执与人工覆盖都必须先落 `Session Service` 事件，再映射为控制动作。
  - 覆盖 `notification_delivery_succeeded|failed|requeued`、`interaction_context_superseded`、过期窗口拒绝、stale interaction 和重新生成交互上下文。
  - 覆盖同一 `interaction_family_id` 任意时刻只允许一个有效上下文，旧上下文晚到送达/回复只能记审计不能双生效。
  - 覆盖 OpenClaw 入口退为兼容层而非主执行入口。

- [x] **Step 2: 运行测试确认正确失败**
  - Run: `uv run pytest tests/test_watchdog_feishu_control.py tests/test_watchdog_notification_delivery.py tests/test_openclaw_contracts.py -q`
  - Expected: 因 Feishu 控制面缺失、通知投递中间态未建模、上下文 supersede 语义未冻结或 OpenClaw 仍承担主职责而失败。

- [x] **Step 3: 实现最小控制面切换**
  - 新增 Feishu command gateway 与 ACL。
  - 把审批确认、通知回执、人工覆盖统一映射为 `Session Service` 事件与 projection 更新。
  - 把通知送达成功、发送失败、重试排队、上下文 supersede、窗口过期与 stale/audit 的状态面明确收口到 `delivery/store.py`、`delivery/worker.py` 与 `session_service/models.py` / `session_spine/projection.py`，避免 handler 自行分叉记状态。
  - 为通知投递增加送达成功、发送失败、重试排队、上下文 supersede 与窗口过期的真相事件，并在需要时生成新的交互上下文。
  - 为同一交互族冻结单活跃上下文规则与 notification attempt 幂等键，晚到送达/回复只能进入审计。
  - `main.py` 中把新控制面注册为主入口。
  - OpenClaw bootstrap/callbacks 仅保留迁移期兼容协议，并标记退役边界。

- [x] **Step 4: 运行测试确认通过**
  - Run: `uv run pytest tests/test_watchdog_feishu_control.py tests/test_watchdog_notification_delivery.py tests/test_openclaw_contracts.py tests/test_watchdog_ops.py -q`
  - Expected: 主控制面切到 Feishu，通知/审批的中间态故障可恢复，补发后的旧上下文不会双生效，OpenClaw 只剩兼容读写接口。

- [x] **Step 5: 提交**
  - `git add src/watchdog/services/feishu_control src/watchdog/api/feishu_control.py src/watchdog/main.py src/watchdog/api/openclaw_bootstrap.py src/watchdog/api/openclaw_callbacks.py src/watchdog/services/adapters/openclaw/adapter.py src/watchdog/services/delivery/store.py src/watchdog/services/delivery/worker.py src/watchdog/services/session_service/models.py src/watchdog/services/session_spine/projection.py tests/test_watchdog_feishu_control.py tests/test_watchdog_notification_delivery.py tests/test_openclaw_contracts.py tests/test_watchdog_ops.py`
  - `git commit -m "feat: switch primary control plane to feishu"`

### Task 8: 固化一期通关验收与端到端 release gate

**Canonical execution work item:** `specs/037-autonomy-golden-path-and-release-gate-e2e/`

**Files:**
- Create: `tests/e2e/test_watchdog_autonomy_golden_path.py`
- Create: `tests/e2e/test_watchdog_midstate_recovery.py`
- Create: `tests/e2e/test_watchdog_release_gate_e2e.py`
- Modify: `src/watchdog/services/brain/release_gate.py`
- Modify: `src/watchdog/services/brain/release_gate_evidence.py`
- Modify: `src/watchdog/services/feishu_control/service.py`
- Modify: `src/watchdog/services/session_service/service.py`

- [x] **Step 1: 写失败测试，冻结一期通关场景**
  - 覆盖 `Feishu DM -> Goal Contract -> Brain 决策 -> Session write barrier -> command lease -> 执行/审批 -> continuity recovery -> 完成判定 -> replay/指标落账` 的单一主链路。
  - 覆盖 worker crash、claim timeout、通知发送失败、旧交互上下文 supersede、stale interaction、人工 override 与 `remote compact` 后子会话接续。
  - 覆盖全流程不得依赖手工改库、手工补事件或绕过 release gate。
  - 覆盖 `certification_packet_corpus + shadow_decision_ledger -> release_gate_report -> low-risk auto-decision` 的通关链路；没有有效报告或报告与当前输入哈希不一致时，e2e 必须阻断自动执行。
  - 覆盖放行前必须先通过固定 runbook/脚本冻结样本窗口、标注清单和归档报告，不能通过临时人工操作直接放行。

- [x] **Step 2: 运行测试确认正确失败**
  - Run: `uv run pytest tests/e2e/test_watchdog_autonomy_golden_path.py tests/e2e/test_watchdog_midstate_recovery.py tests/e2e/test_watchdog_release_gate_e2e.py -q`
  - Expected: 因跨模块 glue、端到端状态恢复或 release gate 仍未完全收口而失败。

- [x] **Step 3: 补齐通关所需的跨模块 glue**
  - 在前述模块中补齐命令租约恢复、通知投递恢复、人工接管、child session 接续、release gate 证据归档与放行报告汇总。
  - 保证 golden path 在进入 `low-risk auto-decision` 前，已经完成样本冻结、shadow 决策记账和 `release_gate_report` 生成/校验，而不是在上线后再补证据。
  - 保证 `release_gate_runbook` 与生成脚本成为正式阻断门输入，而不是可选运维说明。
  - 保证单一 golden path 在不手工修状态的前提下可重复通过。
  - 将该 e2e 通关用例定义为一期放行的阻断门，而不是可选演示脚本。

- [x] **Step 4: 运行测试确认通过**
  - Run: `uv run pytest tests/e2e/test_watchdog_autonomy_golden_path.py tests/e2e/test_watchdog_midstate_recovery.py tests/e2e/test_watchdog_release_gate_e2e.py tests/test_watchdog_ops.py -q`
  - Expected: 一期存在单一、可重复、可审计的自治主链路通关标准，且 release gate 的证据包与放行报告能在端到端链路中被生成、校验并阻断不合格配置。

- [x] **Step 5: 提交**
  - `git add tests/e2e/test_watchdog_autonomy_golden_path.py tests/e2e/test_watchdog_midstate_recovery.py tests/e2e/test_watchdog_release_gate_e2e.py src/watchdog/services/brain/release_gate.py src/watchdog/services/brain/release_gate_evidence.py src/watchdog/services/feishu_control/service.py src/watchdog/services/session_service/service.py tests/test_watchdog_ops.py`
  - `git commit -m "test: add autonomy golden path release gate"`

## 验收顺序

- [ ] 完成 Task 1 后，确认所有 side effect 都经过 Session event write barrier。
- [ ] 完成 Task 1 后，确认审批、通知、人工覆盖也不再拥有独立业务真源，writer 具备单写者与原子追加保证，命令 claim 具备 lease/expire/requeue 恢复协议。
- [ ] 完成 Task 2 后，确认 `session_spine` / approval inbox / notification status / audit query 都优先读事件投影。
- [ ] 完成 Task 3 后，确认 Goal Contract 成为显式持久化对象，不再只是 prompt 片段，当前有效 version 只来源于 `Session Service` 事件，`AI_AutoSDLC.stage/active_goal` 只能作为上下文与模板来源。
- [ ] 完成 Task 4 后，确认 `remote compact` 一类问题走 recovery transaction，而不是重复旧会话重试。
- [x] 完成 Task 5 后，确认 `Memory Hub` 以独立 contract 对外提供 `resident/session-search/skills/packet-inputs` 能力；`user-model/periodic-nudge` 如存在也仅为 assistive-only preview contract，且不覆盖 Session truth / Goal Contract。
- [x] 完成 Task 5 后，确认长期记忆写入遵循“基线建档 + 增量摄取 + provenance + security verdict”，`watchdog/Codex` 主路径已接入，`AI_AutoSDLC` 仅保留 disabled-by-default preview compatibility contract，preview 入口不阻塞一期放行，且 `Memory Hub` 不可用或冲突时会写入 `memory_unavailable_degraded` / `memory_conflict_detected` canonical event 后再安全降级。
- [x] 完成 Task 6 后，确认 `Brain` 具备 provider certification、replay、decision validation 和低风险自动决策闭环，且受明确量化 release gate、证据包和放行报告约束。
- [x] 完成 Task 6 后，确认 release gate 的样本冻结、人工标注、报告归档均有脚本化产物与责任人元数据，不能靠临时人工流程替代。
- [x] 完成 Task 7 后，确认 Feishu 成为唯一主控制面，OpenClaw 不再承担主链路职责，通知/审批的中间态故障具备恢复协议，补发后的旧上下文不会双生效。
- [x] 完成 Task 8 后，确认至少一条 `Feishu DM -> Goal Contract -> Brain -> Session write barrier -> command execution -> interruption recovery -> human approval/override -> completion -> replay/metrics` 主链路可在无手工补状态前提下重复打通，并且 low-risk 放行前已经产出并校验对应的 `release_gate_report`。
- [x] 完成 Task 9 后，确认 future worker / sub-agent 只以 canonical execution contract 存在，lifecycle 与 result consume/reject 全部进入 `Session Service` truth，worker 输出只有在 parent canonical consume 后才真正生效。
- [x] 完成 Task 9 后，确认 declarative worker request、same-trace replay/consume、late-result rejection 与 recovery supersede 都已 fail-closed，并能从 runtime / recovery / ops/read-side 回看。

### Task 9: 把 future worker / sub-agent 收敛为 canonical execution contract

**Canonical execution work item:** `specs/038-future-worker-canonical-execution-and-governance/`

**Files:**
- Create: `src/watchdog/services/future_worker/models.py`
- Create: `src/watchdog/services/future_worker/service.py`
- Modify: `src/watchdog/services/session_service/models.py`
- Modify: `src/watchdog/services/session_service/service.py`
- Modify: `src/watchdog/services/brain/models.py`
- Modify: `src/watchdog/services/session_spine/orchestrator.py`
- Modify: `src/watchdog/services/session_spine/recovery.py`
- Modify: `src/watchdog/services/memory_hub/models.py`
- Create: `tests/test_watchdog_future_worker_contract.py`
- Create: `tests/test_watchdog_future_worker_runtime.py`
- Create: `tests/e2e/test_watchdog_future_worker_execution.py`

- [x] **Step 1: 写失败测试，冻结 worker/sub-agent canonical execution 边界**
  - 覆盖 `FutureWorkerTraceRef` 从声明式 schema 升格为正式 worker execution contract，但 worker 仍不得直接写 Goal Contract、approval、risk band 或 completion truth。
  - 覆盖 `worker_started -> worker_heartbeat -> worker_summary_published -> worker_completed|worker_failed|worker_cancelled` 必须作为 `Session Service` canonical events 落账。
  - 覆盖 worker 只允许消费冻结的 `decision_trace_ref`、`input_packet_refs`、`retrieval_handles` 与 `distilled_summary_ref`，不得绕过到 Memory Hub 私有状态或 live provider memory。
  - 覆盖 worker crash、stale completion、duplicate worker start、result late arrival 与 parent session supersede 时必须 fail closed。
  - 覆盖 parent session 只通过 canonical worker result envelope 消费 worker 输出，而不是隐式把 worker side effects 当成已完成真相。

- [x] **Step 2: 运行测试确认正确失败**
  - Run: `uv run pytest tests/test_watchdog_future_worker_contract.py tests/test_watchdog_future_worker_runtime.py tests/e2e/test_watchdog_future_worker_execution.py -q`
  - Expected: 因 worker/sub-agent 仍只有声明式 schema、缺少 canonical events 与 runtime/recovery glue 而失败。

- [x] **Step 3: 实现最小 canonical worker execution contract**
  - 新增 `future_worker` 服务层，收口 worker execution request、result envelope、budget/scope 与 canonical refs。
  - 在 `Session Service` 中补齐 worker lifecycle events、stale result rejection、supersede/cancel 记录与 parent-child worker lineage。
  - 让 orchestrator / recovery 只消费 canonical worker records，不直接信任 worker 进程本地状态。
  - 保证 worker 输出必须经 parent-side canonical consumption 才能影响后续决策或 completion judgment。
  - 保证 worker scope / allowed hands / retrieval refs / distilled summary 仍沿用 034/035 已冻结的 contract，而不是定义第二套上下文协议。

- [x] **Step 4: 运行测试确认通过**
  - Run: `uv run pytest tests/test_watchdog_future_worker_contract.py tests/test_watchdog_future_worker_runtime.py tests/e2e/test_watchdog_future_worker_execution.py tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_recovery_execution.py tests/test_watchdog_ops.py -q`
  - Expected: worker/sub-agent 已进入 canonical truth、runtime/recovery/ops 都能看见其 lifecycle 与阻断原因，且不会越权修改 parent session 真相。

- [x] **Step 5: 提交**
  - `git add src/watchdog/services/future_worker src/watchdog/services/session_service src/watchdog/services/brain/models.py src/watchdog/services/session_spine/orchestrator.py src/watchdog/services/session_spine/recovery.py src/watchdog/services/memory_hub/models.py tests/test_watchdog_future_worker_contract.py tests/test_watchdog_future_worker_runtime.py tests/e2e/test_watchdog_future_worker_execution.py tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_recovery_execution.py tests/test_watchdog_ops.py`
  - `git commit -m "feat: add canonical future worker execution contract"`

## 风险控制

- 所有阶段都必须维持现有 stable read contract，不允许一次性拆掉全部兼容层。
- 任何自动高风险动作继续强制人工确认，直到 Feishu ACL、Goal Contract 和 replay protection 全部落地。
- `Session Service` 在文件存储阶段必须坚持单 writer、写锁、原子追加与崩溃恢复，不满足前提时直接 fail closed。
- 命令 claim 超时、worker crash、通知投递失败和过期交互都必须显式进入恢复或人工接管，禁止停留在假 pending 状态。
- 如果某阶段需要引入网络侧新依赖，先在 `observe-only` 模式接入，再决定是否进入主链路。
- `Memory Hub` 即使独立开发，也不得绕开 `Session Service` 与 `Goal Contract` 直接成为自治真源。
- `Memory Hub` 的 preview 接入能力可以提前铺 contract，但不得作为一期 release blocker 反向拖慢 Codex 主链路闭环。
- `memory_unavailable_degraded`、`memory_conflict_detected` 必须是 `Session Service` canonical event，而不是 `Memory Hub` 私有日志；release gate 认证优先消费这些事件语料。
- `stage_goal_conflict_detected` 必须进入基础事件 schema 与 query facade，不能只存在于 Memory Hub 适配器内部。
- `AI_AutoSDLC.stage/active_goal` 与当前 `Goal Contract` 冲突时，禁止自动推进，必须先修订 contract 或人工确认。
- 未通过量化 release gate 的 Provider 不得进入 `low-risk auto-decision`，门槛不得在实现阶段临时放宽。
- 没有当前有效且证据哈希匹配的 `release_gate_report` 时，任何 Provider 都不得进入 `low-risk auto-decision`。
- 跨项目共享技能默认 fail-closed，没有验证元数据、技术栈适配和回滚信息时，最多作为建议参考。
