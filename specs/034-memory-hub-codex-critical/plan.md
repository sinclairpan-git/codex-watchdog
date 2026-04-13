---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/034-memory-hub-codex-critical/spec.md"
  - "specs/030-session-service-event-truth-write-barrier/spec.md"
  - "specs/031-session-spine-events-projection-read-surface/spec.md"
  - "specs/032-goal-contract-persistence-and-governance/spec.md"
  - "specs/033-recovery-transaction-lineage/spec.md"
---

# 实施计划：034-memory-hub-codex-critical

## 目标

把 `Memory Hub` 收敛成一个对 `Codex/watchdog` 主路径可用、可降级、可审计、不可夺权的 memory/provider facade，并补齐 session replay、JIT expansion、安全门禁与 provider lifecycle。

## 架构摘要

- **Truth stays outside**：`Session Service + Goal Contract` 继续做唯一运行时真相；`Memory Hub` 只提供 advisory retrieval 与 packet inputs。
- **Search, not hidden compaction**：session history 继续保留在 canonical event log；archive 只负责 search/retrieval，不能取代 raw event replay。
- **Packet inputs, not final packet**：`Memory Hub` 输出 versioned packet inputs、summaries 与 expansion handles；final packet 仍由调用侧 harness 按模型/风险/预算装配，provider lifecycle 和 provider memory ops 不得偷偷接管这一层。
- **Security before injection**：provenance 不是注入许可；所有 recall 和 skill 内容都要先通过 `security_verdict`，且 shared/external source 的 override 必须可审计。
- **Fail closed with replayable evidence**：发生 outage/conflict/TTL/security 问题时，先写 canonical event，再降级。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Memory contracts | `src/watchdog/services/memory_hub/contracts.py`, `src/watchdog/services/memory_hub/models.py` | 定义 resident facade、session search archive、skill registry、preview contracts、provenance、security verdict schema 与 future worker packet contract |
| Memory facade | `src/watchdog/services/memory_hub/service.py` | 暴露 ingest、search、provider lifecycle、provider-scoped memory ops、degrade decision 与 retrieval facade；不拥有 final packet policy |
| Indexing/search | `src/watchdog/services/memory_hub/indexer.py` | 基线扫描、增量索引、blob refs、archive summaries、expansion handles |
| Skill registry | `src/watchdog/services/memory_hub/skills.py` | 技能元数据、trust/security/update 状态、按需展开 |
| Packet input retrieval | `src/watchdog/services/memory_hub/packets.py` | 产出 versioned packet inputs 与 scoped retrieval refs，不负责最终 prompt 装配 |
| Canonical event integration | `src/watchdog/services/session_service/service.py` | 写入 `memory_unavailable_degraded`、`memory_conflict_detected` 并暴露 session event replay/read slices |
| Runtime wiring | `src/watchdog/services/session_spine/orchestrator.py`, `src/watchdog/services/delivery/store.py` | 让主路径消费 packet inputs 和 fallback path，而不是依赖 Memory Hub 私有状态 |
| Verification | `tests/test_watchdog_memory_hub.py`, `tests/test_watchdog_memory_packets.py`, `tests/test_watchdog_memory_degradation.py`, `tests/test_watchdog_session_spine_runtime.py` | 锁定边界、JIT expansion、安全门禁、provider lifecycle 与 fail-closed |

## 边界纪律

- 034 不把 `Memory Hub` 扩成新的 orchestrator；`Brain`、release gate、自动决策继续留给后续 work item。
- 034 不把 session archive、skills、user profile 混成单一信任级别的 “memory blob”；它们必须分开治理。
- 034 只在 repo 里使用“内部实现分区”表述，不把它们包装成 Hermes 或 Anthropic 的官方原生术语。
- 034 的 preview contract 必须 disabled by default，不得阻塞一期 release gate。
- 034 先锁定 `Codex/watchdog` 主路径，再考虑 `AI_AutoSDLC` 或其他 runtime 兼容层。

## 依赖顺序

1. **先冻结 formal docs 与 034 work item 元数据**
   - 改写总实施计划中的 `Task 5`，明确 `Memory Hub` 的受约束定位；
   - 冻结 session replay、JIT expansion、security verdict、provider lifecycle 与 canonical degrade event 的正式边界。
2. **再写失败测试锁定 contract**
   - 先证明当前实现没有 session event slice/read 接口；
   - 先证明当前 packet path 还没有 expansion handles、安全门禁与 provider lifecycle。
3. **再实现最小垂直切片**
   - 先做 resident facade、session search archive、skill metadata、packet inputs、degrade path；
   - preview contracts 只冻结 schema，不进入主路径装配。
4. **再验证 runtime fallback 与 replayability**
   - 确认 Memory Hub 故障、冲突、TTL/security 问题时，`Codex/watchdog` 仍可接续；
   - 确认 raw event replayability 没有被 summary/packet 取代。
5. **最后写 handoff 与验收摘要**
   - 为后续 `Brain`、provider certification、release gate 保留稳定输入边界，不提前实现。

## 分阶段计划

### Phase 1：冻结 034 formal docs 与对齐后的架构边界

交付内容：

- `specs/034-memory-hub-codex-critical/spec.md`
- `specs/034-memory-hub-codex-critical/plan.md`
- `specs/034-memory-hub-codex-critical/tasks.md`
- `specs/034-memory-hub-codex-critical/task-execution-log.md`
- `.ai-sdlc/work-items/034-memory-hub-codex-critical/*`

关键原则：

- 先把 `Memory Hub` 的职责从“中心化记忆平台”收紧成受约束的 facade；
- 明确四类内容只是内部实现分区，不是官方原生模型。

### Phase 2：写失败测试锁定 session replay、packet inputs 与安全门禁

交付内容：

- `tests/test_watchdog_memory_hub.py`
- `tests/test_watchdog_memory_packets.py`
- `tests/test_watchdog_memory_degradation.py`

关键原则：

- 红测优先锁定 `Session Service.get_events(...)` 风格接口；
- 红测优先锁定 packet inputs 只返回摘要和 expansion handles；
- 红测优先锁定 `security_verdict`、resident write semantics、provider memory ops 与 canonical degrade event。

### Phase 3：实现一期最小可用垂直切片

交付内容：

- `src/watchdog/services/memory_hub/models.py`
- `src/watchdog/services/memory_hub/contracts.py`
- `src/watchdog/services/memory_hub/service.py`
- `src/watchdog/services/memory_hub/indexer.py`
- `src/watchdog/services/memory_hub/skills.py`
- `src/watchdog/services/memory_hub/packets.py`
- `src/watchdog/services/session_service/service.py`
- `src/watchdog/services/session_spine/orchestrator.py`
- `src/watchdog/services/delivery/store.py`

关键原则：

- 先交付 resident facade、session search archive、skill metadata、packet inputs；
- final packet policy 继续放在调用侧；
- provider lifecycle、provider memory ops 与 fallback path 同步落地。

### Phase 4：运行验证并确认主路径不回退

交付内容：

- `tests/test_watchdog_memory_hub.py`
- `tests/test_watchdog_memory_packets.py`
- `tests/test_watchdog_memory_degradation.py`
- `tests/test_watchdog_session_spine_runtime.py`
- `tests/test_long_running_autonomy_doc_contracts.py`

关键原则：

- Codex 主路径在 Memory Hub outage/conflict/security 失效时仍可继续；
- replayability、JIT expansion、security gate 与 context quality evaluation 同时通过。

### Phase 5：更新 handoff 摘要并交给后续 Brain / release gate work item

交付内容：

- `specs/034-memory-hub-codex-critical/task-execution-log.md`
- `.ai-sdlc/work-items/034-memory-hub-codex-critical/latest-summary.md`

关键原则：

- handoff 必须说明 034 只输出稳定 retrieval/input contracts；
- 后续 work item 直接消费这些 contracts，不回头把 Memory Hub 升级成中心化 harness。

## 测试计划

- `tests/test_watchdog_memory_hub.py`
  - resident facade 有硬预算且 turn 内 frozen
  - resident write surface 具备 `add|replace|remove` 或等价语义，并在容量压力下显式 consolidate
  - `Session Service.get_events(...)` 或等价切片读取接口存在
  - provider lifecycle、provider memory ops 与 single active provider facade 受控
- `tests/test_watchdog_memory_packets.py`
  - packet inputs 默认只返回摘要、元数据、refs、expansion handles
  - final packet policy 不在 Memory Hub 内部硬编码
  - context quality evaluation 记录 `key_fact_recall`、`irrelevant_summary_precision`、`token_budget_utilization`、`expansion_miss_rate`
- `tests/test_watchdog_memory_degradation.py`
  - outage/conflict/TTL/security/tech-stack mismatch 先写 canonical event 再降级
  - `security_verdict` 不通过的内容只进 quarantine/reference-only
  - canonical degrade/conflict event 带 `reason_code` 与 `source_ref`
  - secret-like payload、sandbox-only reference、dangerous source 不会进入 provider sync 或 hot path
- `tests/test_watchdog_session_spine_runtime.py`
  - runtime 在 Memory Hub 不可用时仍依赖 `Session Service + runtime snapshot` 接续
  - compaction 后仍能从 cursor/range/anchor 恢复关键 raw events
- `tests/test_long_running_autonomy_doc_contracts.py`
  - formal docs 与总实施计划中的 Task 5 边界一致

## 主要风险与应对

### 风险 1：Memory Hub 再次长成新的中心化 orchestrator

应对：

- 在 spec 中明确它只输出 retrieval facade 和 packet inputs；
- final packet policy、Brain、release gate 都不归 034 所有。

### 风险 2：session history 被摘要系统吞掉，失去 replayability

应对：

- 强制 `Session Service` 暴露事件切片读取接口；
- 把 archive 定义成 search/retrieval，而不是替代 raw event truth。

### 风险 3：provenance 充足但内容不安全，照样进入热路径

应对：

- `security_verdict` 成为强制门禁；
- 未通过的 recall/skill 内容只能 quarantine 或 reference-only。

### 风险 4：preview contract 范围太大，拖慢一期主链路

应对：

- `User Model`、`Periodic Nudge`、`AI_AutoSDLC/Cursor` 一律 disabled by default；
- release gate 只关心 Codex-critical 主路径。

### 风险 5：provider lifecycle 变成隐式 orchestration 层

应对：

- 把 provider lifecycle 明确限制为 compatibility adapter contract；
- provider 只允许 `search|store|manage` 类 memory ops，且失败不能改写已冻结 packet。

## 验收口径

只有当以下条件同时满足，034 才算完成：

1. `Memory Hub` 已被收紧为 retrieval/provider facade，不再拥有 final packet policy；
2. `Session Service` 的 raw event replayability 仍然存在，summary/packet input 不能替代它；
3. packet inputs 默认只注入预算内摘要与 expansion handles，不默认注入 raw transcript、skill 全文或 artifact blob；
4. `security_verdict`、canonical degrade event、fallback path、provider lifecycle 与 provider memory ops 均已落地；
5. replay 语义级恢复与 context quality evaluation 已落地，summary/packet inputs 不是唯一恢复来源；
6. Codex 主路径在 Memory Hub outage/conflict/security 问题下仍可接续，preview contracts 不阻塞一期放行。
