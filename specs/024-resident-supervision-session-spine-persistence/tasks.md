# 任务分解：024-resident-supervision-session-spine-persistence

> 对应规格：`specs/024-resident-supervision-session-spine-persistence/spec.md`

## Task 24.1 冻结 canonical snapshot 与 resident runtime 边界

- **任务编号**：T241
- **状态**：已完成
- **目标**：把 resident projection runtime、persisted spine、`fact_snapshot_version` 与 `session_seq` 的边界收敛为可执行文档与模块职责。
- **涉及文件**：
  - `docs/architecture/codex-watchdog-full-product-loop-design.md`
  - `specs/024-resident-supervision-session-spine-persistence/spec.md`
  - `specs/024-resident-supervision-session-spine-persistence/plan.md`
  - `specs/024-resident-supervision-session-spine-persistence/tasks.md`
- **完成标准**：
  1. 明确 resident runtime 与 persisted spine 的职责；
  2. 明确 `fact_snapshot_version` 与 `session_seq` 的单调规则；
  3. 明确 `024` 的非目标，不混入 policy / delivery / host runtime。
- **验证**：人工审阅 formal docs 是否与总设计 Section 5 的 WI-1 边界一致。
- **完成情况**：resident runtime、persisted spine、fresh/stale read 语义与非目标边界已回写 formal docs。

## Task 24.2 新增 resident runtime 与 persisted spine store

- **任务编号**：T242
- **状态**：已完成
- **目标**：新增 resident projection loop 与 canonical spine 持久化层，支撑可恢复的事实快照读取。
- **涉及文件**：
  - `src/watchdog/services/session_spine/runtime.py`
  - `src/watchdog/services/session_spine/store.py`
  - `src/watchdog/services/session_spine/projection.py`
  - `src/watchdog/services/session_spine/facts.py`
  - `src/watchdog/main.py`
- **完成标准**：
  1. resident loop 可持续刷新；
  2. store 能保存 snapshot、`fact_snapshot_version`、`session_seq`；
  3. 无事实变化时不伪造新快照。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_runtime.py`
- **完成情况**：已交付 resident refresh loop、`session_spine.json` 持久化 store 与 snapshot 单调语义。

## Task 24.3 重接 stable query surfaces 与恢复链路

- **任务编号**：T243
- **状态**：已完成
- **目标**：让 stable query read bundle 改为优先消费 persisted spine，并补齐 restart / replay / restore 语义。
- **涉及文件**：
  - `src/watchdog/services/session_spine/service.py`
  - `src/watchdog/api/session_spine_queries.py`
  - `src/watchdog/api/supervision.py`
  - `src/watchdog/main.py`
  - `tests/test_watchdog_session_spine_api.py`
- **完成标准**：
  1. `get_session / progress / why_stuck / explain_blocker / facts` 读取 persisted spine；
  2. query 层有 freshness/staleness 语义；
  3. 重启后 resident runtime 能恢复并继续推进顺序语义。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_api.py`
- **完成情况**：stable query surfaces 已优先消费 persisted spine，并提供 freshness/source 语义。

## Task 24.4 锁住集成回归与最小运维说明

- **任务编号**：T244
- **状态**：已完成
- **目标**：补齐最小 integration 回归与 operator notes，确认 resident runtime 引入后 stable route contract 不回归。
- **涉及文件**：
  - `tests/integration/test_feishu_integration_spine.py`
  - `docs/getting-started.zh-CN.md`
  - `README.md`
- **完成标准**：
  1. Feishu 模板继续复用 stable route，不受底层 persisted spine 切换影响；
  2. 文档写清 fresh/stale/read semantics 与 resident runtime 的基本运维注意事项；
  3. 不引入 delivery / webhook / policy 运行时说明。
- **验证**：`uv run pytest -q tests/integration/test_feishu_integration_spine.py`
- **完成情况**：已补齐 integration 回归与最小运维说明，并保持 stable route contract 不回归。

## 整体验收

- `024` 是完整产品闭环中的 `WI-1`，只负责 resident supervision 与 canonical session spine persistence。
- `024` 完成后，后续 `WI-2` 可以直接基于 persisted snapshot 做策略判定，而不再依赖 query 时临时拼装。
- `024` 不引入策略引擎、自动执行、ApprovalEnvelope/DecisionEnvelope/NotificationEnvelope 投递链，也不实现 Feishu runtime。
