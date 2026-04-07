---
related_doc:
  - "docs/architecture/openclaw-codex-watchdog-full-product-loop-design.md"
  - "specs/024-resident-supervision-session-spine-persistence/spec.md"
  - "src/watchdog/services/session_spine/projection.py"
  - "src/watchdog/services/session_spine/service.py"
  - "src/watchdog/api/supervision.py"
  - "src/watchdog/main.py"
---

# 实施计划：024-resident-supervision-session-spine-persistence

## 目标

把当前“查询时临时构建 session 视图 + 启动时一次性 supervision”的形态，推进到“resident projection runtime + persisted canonical session spine”，为后续策略、执行与投递 work items 建立统一事实面。

## 架构摘要

- **Resident projection first**：024 的核心是常驻投影与持久化，不是策略判定，也不是自动执行。
- **Persisted spine as truth**：稳定查询面应优先读取 canonical 持久化 spine，而不是在 API 层直接向 A 拉 raw 事实重新拼装。
- **Replay-safe sequencing**：`fact_snapshot_version` 与 `session_seq` 必须成为后续策略层可直接复用的单调顺序语义。
- **No policy / delivery leakage**：024 不引入 envelope、delivery outbox、webhook、人工升级或自动执行判定。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Resident Runtime | `src/watchdog/services/session_spine/runtime.py` | 常驻 projection loop、刷新调度、停止/恢复生命周期 |
| Persistence | `src/watchdog/services/session_spine/store.py` | canonical spine 快照、`fact_snapshot_version`、`session_seq`、restore/replay 读取 |
| Snapshot Builder | `src/watchdog/services/session_spine/projection.py`, `src/watchdog/services/session_spine/facts.py` | 从 A-side read model 构建 canonical snapshot，并决定“是否产生新快照版本” |
| Read Service | `src/watchdog/services/session_spine/service.py` | 从 persisted spine 组装 `SessionReadBundle` 等稳定 read bundle |
| Query API | `src/watchdog/api/session_spine_queries.py`, `src/watchdog/api/supervision.py` | 把既有 stable query route 改为消费 persisted spine 与 freshness 语义 |
| App Lifecycle | `src/watchdog/main.py` | 挂接 resident runtime 的启动、停止与 restore/replay |
| 验证 | `tests/test_watchdog_session_spine_api.py`, `tests/test_watchdog_session_spine_runtime.py`, `tests/integration/test_openclaw_integration_spine.py` | 锁住 runtime、排序、恢复与 stable query contract 不回归 |

## 边界纪律

- `024` 只拥有 canonical session spine 的 resident runtime 与 persistence 语义。
- `024` 不拥有策略判定逻辑；`human_gate / hard_block / decision_key` 只允许在文档中保留为后续接口前提，不进入本工作项实现。
- `024` 不拥有 delivery / retry / receipt / webhook 逻辑。
- `024` 不拥有 OpenClaw 宿主渲染与 Feishu 渠道语义。

## 依赖顺序

1. **先冻结状态与持久化模型**
   - 明确 canonical session snapshot 需要保存哪些字段；
   - 明确 `fact_snapshot_version` 与 `session_seq` 的单调规则。
2. **再补 resident runtime 与 store**
   - 新增 runtime loop；
   - 新增 persisted spine store；
   - 打通 restore / replay。
3. **再重接 stable query surfaces**
   - 让 `SessionReadBundle` 等读取 persisted spine；
   - 保持 stable query contract 不变。
4. **最后补测试与最小文档**
   - 锁住 resident refresh、版本稳定性、重启恢复与 API 不回归。

## 分阶段计划

### Phase 1：冻结 canonical snapshot 与顺序语义

交付内容：

- persisted spine 模型边界；
- `fact_snapshot_version` 规则；
- `session_seq` 规则；
- resident runtime 的启动/停止/恢复生命周期约束。

关键原则：

- 不把 policy / delivery 的字段提前混进 snapshot；
- 顺序字段必须面向 replay / restore 可重用；
- `created_at` 不能作为稳定排序基准。

### Phase 2：补 resident runtime 与 store

交付内容：

- `runtime.py`
- `store.py`
- 与现有 `projection.py / facts.py` 的接缝

关键原则：

- resident runtime 负责刷新和恢复；
- store 负责快照、版本和顺序语义；
- 同一 session 的重复刷新不应伪造新快照。

### Phase 3：重接 stable query surfaces

交付内容：

- `service.py` 改为以 persisted spine 为主要读取源；
- `session_spine_queries.py` 与相关 query builder 对 freshness 有稳定解释；
- 最小 integration 继续保证 OpenClaw 模板看到的 contract 不变。

关键原则：

- read surface 改底层，不改 stable contract；
- 不允许在 query API 内保留新的 raw/legacy 旁路。

### Phase 4：恢复验证与最小文档

交付内容：

- runtime / API / integration tests；
- 最小 operator notes，说明 resident runtime 的 fresh/stale/read semantics。

关键原则：

- 验证重点放在单调性、恢复性、contract continuity；
- 不在本阶段引入 delivery / policy / OpenClaw runtime 说明。

## 测试计划

### Runtime / Persistence

- `tests/test_watchdog_session_spine_runtime.py`

覆盖：

- resident loop 周期刷新；
- `session_seq` 单调递增；
- 无事实变化时 `fact_snapshot_version` 保持不变；
- restart / replay 后顺序继续推进。

### API / Read Bundle

- `tests/test_watchdog_session_spine_api.py`

覆盖：

- persisted spine 作为 query 主读取源；
- freshness/staleness 解释；
- `get_session / progress / stuck-explanation / blocker-explanation / facts` 不回归。

### Integration

- `tests/integration/test_openclaw_integration_spine.py`

覆盖：

- OpenClaw 模板继续通过 stable route 读取同源 session snapshot；
- resident runtime 引入后，OpenClaw 可见 contract 不变。

## 主要风险与应对

### 风险 1：把 resident supervision 做成半个策略引擎

应对：

- 024 只做 projection 与 persistence；
- 不实现 `auto_execute_and_notify / require_user_decision / block_and_alert`；
- 所有策略字段只允许作为后续 work item 依赖占位。

### 风险 2：刷新逻辑制造假快照或顺序回退

应对：

- `fact_snapshot_version` 只在 canonical 事实面变化时推进；
- `session_seq` 单调递增并持久化；
- restart / replay 测试必须锁住该语义。

### 风险 3：查询层偷留 raw 旁路

应对：

- 明确要求 `service.py` 与 query API 以 persisted spine 为主；
- 测试要验证读取来源与 fresh/stale 语义，而不是只验证最终文案。

## 验收口径

只有当以下条件同时满足，024 才算完成：

1. `Watchdog(B)` 已具备 resident projection runtime，而不是启动时一次性监督；
2. canonical session spine 已持久化，并具有 `fact_snapshot_version` 与 `session_seq`；
3. stable query surfaces 已优先读取 persisted spine；
4. restart / replay / restore 语义已被验证；
5. 本工作项仍未引入策略、执行、投递或宿主 runtime 逻辑。
