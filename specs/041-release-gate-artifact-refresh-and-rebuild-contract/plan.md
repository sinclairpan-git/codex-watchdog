---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/039-release-gate-loading-api-and-evidence-bundle/spec.md"
  - "specs/040-release-gate-report-material-contract-and-hash-unification/spec.md"
  - "specs/041-release-gate-artifact-refresh-and-rebuild-contract/spec.md"
---

# 实施计划：041-release-gate-artifact-refresh-and-rebuild-contract

## 目标

把 `release_gate_report` 的 refresh、archive rebuild 与 fixture regeneration 收口成单一正式命令入口，确保整个 refresh 路径只复用既有 shared material / loader contract。

## 架构摘要

- **One refresh command**：operator 只通过一个正式命令完成 refresh / rebuild / regeneration。
- **Reuse, don’t redefine**：refresh 命令只能委托现有 generator、shared material helper 与 shared loader。
- **No metadata platform**：041 只正式化 refresh contract，不新增 manifest、archive model 或新的审计层。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Formal docs / task plan | `specs/041-release-gate-artifact-refresh-and-rebuild-contract/*` | 冻结 041 正式边界、任务拆解与 handoff |
| Refresh command | `scripts/refresh_release_gate_artifacts.py` | 单一 operator 入口，委托 generator + loader 完成 refresh |
| Existing generation/validation | `scripts/generate_release_gate_report.py`, `src/watchdog/services/brain/release_gate_report_material.py`, `src/watchdog/services/brain/release_gate_loading.py` | 保持既有 canonical generation / validation contract |
| Runbook + contract tests | `docs/operations/release-gate-runbook.md`, `tests/test_watchdog_release_gate.py` | 锁定 refresh 输入/输出/成功态与 fail-closed 纪律 |

## 边界纪律

- 041 不得新增新的 release gate blocker taxonomy、policy gate 或放行门槛。
- 041 不得修改 `release_gate_report` schema、evidence bundle 字段或 ops/read-side surface。
- 041 不得新增 refresh manifest、archive metadata store、query facade 或元数据平台。
- 041 只正式化单一 refresh 命令入口与 runbook/contract test，不回退到人工编辑 JSON 或散落脚本步骤。

## 依赖顺序

1. **先冻结 formal docs 与 041 work item 元数据**
   - 明确 041 只做 refresh / rebuild contract；
   - 明确它不扩 metadata model 或 policy surface。
2. **再写失败测试锁定 refresh contract**
   - 先证明当前缺少单一 refresh 命令入口；
   - 先锁定 refresh 输出必须由 shared helper 和 shared loader 一致约束。
3. **再补 refresh 命令与 runbook**
   - 新增单一 refresh 入口；
   - 更新 runbook，明确输入、输出、成功态与 fail-closed 条件。
4. **最后更新 handoff**
   - 固定后续任何 report refresh / archive rebuild / fixture regeneration 都必须复用该入口。

## 分阶段计划

### Phase 1：冻结 041 formal docs、任务分解与执行元数据

交付内容：

- `specs/041-release-gate-artifact-refresh-and-rebuild-contract/spec.md`
- `specs/041-release-gate-artifact-refresh-and-rebuild-contract/plan.md`
- `specs/041-release-gate-artifact-refresh-and-rebuild-contract/tasks.md`
- `specs/041-release-gate-artifact-refresh-and-rebuild-contract/task-execution-log.md`
- `.ai-sdlc/work-items/041-release-gate-artifact-refresh-and-rebuild-contract/*`

### Phase 2：写失败测试锁定 refresh / rebuild contract

交付内容：

- `tests/test_watchdog_release_gate.py`

### Phase 3：补齐 refresh 命令与 runbook

交付内容：

- `scripts/refresh_release_gate_artifacts.py`
- `scripts/generate_release_gate_report.py`
- `docs/operations/release-gate-runbook.md`
- `tests/test_watchdog_release_gate.py`

### Phase 4：更新执行日志与 handoff 摘要

交付内容：

- `specs/041-release-gate-artifact-refresh-and-rebuild-contract/task-execution-log.md`
- `.ai-sdlc/work-items/041-release-gate-artifact-refresh-and-rebuild-contract/execution-plan.yaml`
- `.ai-sdlc/work-items/041-release-gate-artifact-refresh-and-rebuild-contract/runtime.yaml`
- `.ai-sdlc/work-items/041-release-gate-artifact-refresh-and-rebuild-contract/resume-pack.yaml`
- `.ai-sdlc/work-items/041-release-gate-artifact-refresh-and-rebuild-contract/latest-summary.md`

## 测试计划

- `tests/test_watchdog_release_gate.py`
  - 锁定 refresh 命令 module/CLI surface、shared helper 复用与 loader-valid output
- `tests/test_watchdog_release_gate_evidence.py`
  - 锁定 runbook 已正式记录 refresh 输入/输出/纪律
- `tests/test_long_running_autonomy_doc_contracts.py`
  - 锁定总实施计划与 canonical work item 元数据同步

## 主要风险与应对

### 风险 1：refresh 命令退化成又一层本地 helper

应对：

- 命令只做 orchestration，不得重写 report material/hash 逻辑；
- 用红测锁定它必须委托现有 generator + loader。

### 风险 2：scope 滑向 metadata/manifest 设计

应对：

- 明确把 manifest、archive metadata store 和 query 语义列为非目标；
- 只交付单一命令、runbook 与 contract tests。

## 验收口径

只有当以下条件同时满足，041 才算完成：

1. `release_gate_report` refresh / rebuild / regeneration 已有唯一正式命令入口；
2. refresh 命令只复用既有 generator、shared material helper 与 shared loader；
3. runbook 已正式记录输入、输出、成功态与 fail-closed 条件；
4. 未引入 manifest、schema 变化、policy 变化或新的第二真相。
