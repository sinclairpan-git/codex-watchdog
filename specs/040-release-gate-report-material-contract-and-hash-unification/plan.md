---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/035-brain-decision-boundary-and-release-gate/spec.md"
  - "specs/039-release-gate-loading-api-and-evidence-bundle/spec.md"
  - "specs/040-release-gate-report-material-contract-and-hash-unification/spec.md"
---

# 实施计划：040-release-gate-report-material-contract-and-hash-unification

## 目标

把 `release_gate_report` 的 canonical material、`report_id` seed 与 `report_hash` 计算收口到共享 helper，避免 generator / loader / fixture refresh 再次分叉。

## 架构摘要

- **One report material contract**：`release_gate_report` 的 canonical JSON material 与 hash/id 计算只允许存在一个共享定义。
- **Generator and loader stay aligned**：script 与 loader 通过同一 helper 对齐，而不是各自维护看起来等价的局部算法。
- **No policy changes**：040 只收口 report generation contract，不改 release gate policy、evidence bundle 或 read-side 语义。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Formal docs / task plan | `specs/040-release-gate-report-material-contract-and-hash-unification/*` | 冻结 040 正式边界、任务拆解与 handoff |
| Shared report material contract | `src/watchdog/services/brain/release_gate_report_material.py` | 统一 canonical material、`report_id` seed 与 `report_hash` 计算 |
| Generator / loader integration | `scripts/generate_release_gate_report.py`, `src/watchdog/services/brain/release_gate_loading.py` | 改为只复用 shared helper |
| Contract tests | `tests/test_watchdog_release_gate.py` | 锁定 script/loader/fixture 通过同一 report material contract 对齐 |

## 边界纪律

- 040 不得新增新的 release gate blocker taxonomy、policy gate 或放行门槛。
- 040 不得修改 `release_gate_report` 外部 schema、evidence bundle 字段或 ops surfacing。
- 040 不得重新发明第二套 fixture refresh helper、test-only hash helper 或 script-only seed 逻辑。
- 040 只收口 report generation / hash material contract，不回退到手写 JSON 再猜 hash 的路径。

## 依赖顺序

1. **先冻结 formal docs 与 040 work item 元数据**
   - 明确 040 只做 shared report material/hash contract；
   - 明确它不改 policy、schema 或 evidence bundle。
2. **再写失败测试锁定 shared material/hash contract**
   - 先证明当前 script 与 loader 仍有局部 helper；
   - 先锁定 `report_id` / `report_hash` 计算只能来自单一 shared helper。
3. **再补 shared helper 并收口 generator / loader**
   - 在 brain 层新增共享 report material helper；
   - 让 script 与 loader 都只复用它。
4. **最后更新 handoff**
   - 固定后续任何 report refresh / validation 都必须复用 shared material contract。

## 分阶段计划

### Phase 1：冻结 040 formal docs、任务分解与执行元数据

交付内容：

- `specs/040-release-gate-report-material-contract-and-hash-unification/spec.md`
- `specs/040-release-gate-report-material-contract-and-hash-unification/plan.md`
- `specs/040-release-gate-report-material-contract-and-hash-unification/tasks.md`
- `specs/040-release-gate-report-material-contract-and-hash-unification/task-execution-log.md`
- `.ai-sdlc/work-items/040-release-gate-report-material-contract-and-hash-unification/*`

### Phase 2：写失败测试锁定 shared report material/hash contract

交付内容：

- `tests/test_watchdog_release_gate.py`

### Phase 3：补齐 shared report material/hash helper

交付内容：

- `src/watchdog/services/brain/release_gate_report_material.py`
- `src/watchdog/services/brain/release_gate_loading.py`
- `scripts/generate_release_gate_report.py`

### Phase 4：更新执行日志与 handoff 摘要

交付内容：

- `specs/040-release-gate-report-material-contract-and-hash-unification/task-execution-log.md`
- `.ai-sdlc/work-items/040-release-gate-report-material-contract-and-hash-unification/execution-plan.yaml`
- `.ai-sdlc/work-items/040-release-gate-report-material-contract-and-hash-unification/runtime.yaml`
- `.ai-sdlc/work-items/040-release-gate-report-material-contract-and-hash-unification/resume-pack.yaml`
- `.ai-sdlc/work-items/040-release-gate-report-material-contract-and-hash-unification/latest-summary.md`

## 测试计划

- `tests/test_watchdog_release_gate.py`
  - 锁定 shared helper 的 module surface、`report_id` / `report_hash` material contract 与 generator/loader 一致性
- `tests/test_long_running_autonomy_doc_contracts.py`
  - 锁定总实施计划与 canonical work item 元数据同步

## 主要风险与应对

### 风险 1：script / loader 继续各自维护 hash helper

应对：

- 用单一 shared helper 明确唯一入口；
- 用红测锁定 generator 与 loader 必须通过同一 contract 对齐。

### 风险 2：future fixture refresh 重新引入 hash/material 漂移

应对：

- 把 `report_id` seed 与 `report_hash` material 都写成共享 helper；
- 禁止 test-only 或 script-only 本地算法继续存在。

## 验收口径

只有当以下条件同时满足，040 才算完成：

1. `release_gate_report` 的 canonical material、`report_id` seed 与 `report_hash` 计算已有唯一 shared helper；
2. generator script 与 loader 都只消费 shared helper；
3. fixture refresh / tests 不再维护第二套本地 hash/material 逻辑；
4. 既有 report schema、evidence bundle 与 fail-closed 语义未被改变。
