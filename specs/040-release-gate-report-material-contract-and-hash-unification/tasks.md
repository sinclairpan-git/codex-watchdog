# 任务分解：040-release-gate-report-material-contract-and-hash-unification

> 对应规格：`specs/040-release-gate-report-material-contract-and-hash-unification/spec.md`
>
> 对应计划：`specs/040-release-gate-report-material-contract-and-hash-unification/plan.md`

## Task 40.1 冻结 040 formal docs 与 shared report material/hash 边界

- **任务编号**：T401
- **状态**：已完成（2026-04-14）
- **目标**：把总实施计划中的 `Task 11` 正式拆成 canonical execution work item，并把 040 收紧为 `release_gate_report` canonical material / `report_id` / `report_hash` shared contract。
- **文件**：
  - `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
  - `specs/040-release-gate-report-material-contract-and-hash-unification/spec.md`
  - `specs/040-release-gate-report-material-contract-and-hash-unification/plan.md`
  - `specs/040-release-gate-report-material-contract-and-hash-unification/tasks.md`
  - `specs/040-release-gate-report-material-contract-and-hash-unification/task-execution-log.md`
  - `.ai-sdlc/work-items/040-release-gate-report-material-contract-and-hash-unification/*`
- **可并行**：否
- **验收标准**：
  1. 已明确 040 只做 shared report material/hash contract，不扩新的 release gate consume path；
  2. 已明确 040 只消费 035/037/039 已冻结的 report schema、runbook 与 shared loading contract；
  3. 已明确后续任何 report refresh / validation 都必须复用同一 shared helper；
  4. Hermes Agent 专家与 Anthropic Manager 专家复核后无 blocking/P1。
- **验证**：
  - `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`
  - 人工审阅 `spec.md / plan.md / tasks.md / .ai-sdlc` 元数据与 Task 11 边界一致
- **完成情况**：
  1. 已新增 `Task 11` 到总实施计划，并挂到 `specs/040-release-gate-report-material-contract-and-hash-unification/`；
  2. 已创建 `spec.md / plan.md / tasks.md / task-execution-log.md` 与 `.ai-sdlc/work-items/040-*` 基线；
  3. 已把 040 收紧为 report material/hash shared contract，而不是扩新的 release gate 行为；
  4. Hermes Agent 专家与 Anthropic Manager 专家复核均无 blocking/P1。

## Task 40.2 写失败测试锁定 shared report material/hash contract

- **任务编号**：T402
- **状态**：已完成（2026-04-14）
- **目标**：用失败测试先锁定 `release_gate_report` canonical material、`report_id` seed 与 `report_hash` 算法只能来自单一 shared helper。
- **文件**：
  - `tests/test_watchdog_release_gate.py`
- **可并行**：否
- **验收标准**：
  1. 覆盖 shared helper module surface 必须存在；
  2. 覆盖 generator 与 loader 必须通过同一 canonical material/hash contract 对齐；
  3. 覆盖 `report_id` seed 与 `report_hash` material 不得在 script、loader 或 test helper 各自维护；
  4. 覆盖 governance metadata、冻结窗口、artifact refs 与 `input_hash` 纳入 canonical material 的方式固定。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_release_gate.py`
- **完成情况**：
  1. 已新增 `release_gate_report_material` shared helper module surface 红测；
  2. 已锁定 fixture 里的 `report_id/report_hash` 必须能由 shared helper 重建；
  3. 已锁定 loader 的 `raw_payload_hash` 必须与 shared helper 计算结果一致；
  4. 初次红测确认当前缺口就是缺少 shared helper，generator / loader 仍各自维护本地 hash/material 逻辑。

## Task 40.3 实现最小 shared report material/hash helper

- **任务编号**：T403
- **状态**：已完成（2026-04-14）
- **目标**：交付单一 shared helper，让 generator script、loader 与 fixture refresh 共享同一份 report material/hash contract。
- **文件**：
  - `src/watchdog/services/brain/release_gate_report_material.py`
  - `src/watchdog/services/brain/release_gate_loading.py`
  - `scripts/generate_release_gate_report.py`
  - `tests/test_watchdog_release_gate.py`
- **可并行**：否
- **验收标准**：
  1. shared helper 已统一 canonical material、`report_id` seed 与 `report_hash` 计算；
  2. script 与 loader 已改为只消费 shared helper；
  3. 不引入新的 report schema、policy gate 或 evidence bundle 变化；
  4. checked-in fixture 输出保持稳定。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_release_gate.py tests/test_watchdog_release_gate_evidence.py tests/test_long_running_autonomy_doc_contracts.py`
- **完成情况**：
  1. 已新增 `src/watchdog/services/brain/release_gate_report_material.py`，统一 canonical material、`report_id` seed 与 `report_hash` 计算；
  2. `scripts/generate_release_gate_report.py` 与 `src/watchdog/services/brain/release_gate_loading.py` 已改为只消费 shared helper；
  3. 实现过程中暴露出真实契约缺口：script 生成的 canonical report 含 `shadow_decision_count` / `certification_packet_count`，但 loader schema 会误拒；现已补进 `ReleaseGateReport`；
  4. Hermes Agent 专家与 Anthropic Manager 专家复核均无 blocking/P1。

## Task 40.4 更新执行日志与 handoff 摘要

- **任务编号**：T404
- **状态**：已完成（2026-04-14）
- **目标**：同步 formal docs、执行日志与 `.ai-sdlc` 元数据，固定后续 handoff。
- **文件**：
  - `specs/040-release-gate-report-material-contract-and-hash-unification/task-execution-log.md`
  - `.ai-sdlc/work-items/040-release-gate-report-material-contract-and-hash-unification/execution-plan.yaml`
  - `.ai-sdlc/work-items/040-release-gate-report-material-contract-and-hash-unification/runtime.yaml`
  - `.ai-sdlc/work-items/040-release-gate-report-material-contract-and-hash-unification/resume-pack.yaml`
  - `.ai-sdlc/work-items/040-release-gate-report-material-contract-and-hash-unification/latest-summary.md`
- **可并行**：否
- **验收标准**：
  1. 执行日志已记录 red/green/review 闭环与 shared material/hash contract 收口；
  2. `.ai-sdlc` 元数据能准确恢复到下一执行入口；
  3. handoff 明确后续任何 report refresh / validation 都不得回到局部 helper。
- **验证**：
  - `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`
  - 人工审阅执行日志与 `.ai-sdlc` 元数据一致
- **完成情况**：
  1. 已把 red/green/review 闭环、实现提交与 formal handoff 写回执行日志；
  2. `.ai-sdlc` 元数据已同步到 040 完成态；
  3. handoff 已明确后续任何 report refresh / validation 都必须复用 shared helper。

## Task 40.5 完成 040 整体验证并交接下一 work item

- **任务编号**：T405
- **状态**：已完成（2026-04-14）
- **目标**：完成 040 的整体验证，并把 shared report material/hash contract 作为后续 work item 的正式依赖写回 handoff。
- **文件**：
  - `specs/040-release-gate-report-material-contract-and-hash-unification/task-execution-log.md`
  - `.ai-sdlc/work-items/040-release-gate-report-material-contract-and-hash-unification/latest-summary.md`
  - `.ai-sdlc/work-items/040-release-gate-report-material-contract-and-hash-unification/resume-pack.yaml`
- **可并行**：否
- **验收标准**：
  1. 040 的 shared report material/hash contract 已被明确为唯一正式生成面；
  2. handoff 明确后续入口不得复制 `report_id` / `report_hash` 算法；
  3. 后续扩展点已收敛到 shared helper 的复用，而不是再次分叉 report material 语义。
- **验证**：
  - `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`
  - 人工审阅 handoff 与总实施计划一致
- **完成情况**：
  1. `WI-040` 已完成：`release_gate_report` canonical material、`report_id` seed 与 `report_hash` 计算已成为唯一正式生成面；
  2. 下一批如需刷新 report / fixture / archive，只能声明依赖 shared helper，不能再复制局部 hash/material 算法；
  3. 最后一轮 Hermes Agent 专家与 Anthropic Manager 专家复核均无 blocking/P1。

## 整体验收

- 040 只负责把 `release_gate_report` canonical material、`report_id` seed 与 `report_hash` 计算正式化。
- 040 完成后，generator script、loader、fixture refresh 与后续任何入口都只能复用同一套 report material/hash surface。
- 040 不得新增新的 gate policy、旁路放行规则或 read-side 第二真相。
