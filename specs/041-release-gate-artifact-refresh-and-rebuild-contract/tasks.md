# 任务分解：041-release-gate-artifact-refresh-and-rebuild-contract

> 对应规格：`specs/041-release-gate-artifact-refresh-and-rebuild-contract/spec.md`
>
> 对应计划：`specs/041-release-gate-artifact-refresh-and-rebuild-contract/plan.md`

## Task 41.1 冻结 041 formal docs 与 refresh / rebuild 边界

- **任务编号**：T411
- **状态**：已完成（2026-04-14）
- **目标**：把总实施计划中的 `Task 12` 正式拆成 canonical execution work item，并把 041 收紧为 `release_gate_report` refresh / rebuild / fixture regeneration 的单一正式入口。
- **文件**：
  - `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
  - `specs/041-release-gate-artifact-refresh-and-rebuild-contract/spec.md`
  - `specs/041-release-gate-artifact-refresh-and-rebuild-contract/plan.md`
  - `specs/041-release-gate-artifact-refresh-and-rebuild-contract/tasks.md`
  - `specs/041-release-gate-artifact-refresh-and-rebuild-contract/task-execution-log.md`
  - `.ai-sdlc/work-items/041-release-gate-artifact-refresh-and-rebuild-contract/*`
- **可并行**：否
- **验收标准**：
  1. 已明确 041 只做单一 refresh 命令 + runbook + contract test；
  2. 已明确 041 只消费 037/039/040 已冻结的 hard-blocker、shared loading 与 shared material contract；
  3. 已明确 041 不引入 manifest、archive metadata store 或新的元数据平台；
  4. Hermes Agent 专家与 Anthropic Manager 专家复核后无 blocking/P1。
- **验证**：
  - `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`
  - 人工审阅 `spec.md / plan.md / tasks.md / .ai-sdlc` 元数据与 Task 12 边界一致
- **完成情况**：
  1. 已新增 `Task 12` 到总实施计划，并挂到 `specs/041-release-gate-artifact-refresh-and-rebuild-contract/`；
  2. 已创建 `spec.md / plan.md / tasks.md / task-execution-log.md` 与 `.ai-sdlc/work-items/041-*` 基线；
  3. 已把 041 收紧为 refresh contract，而不是新的 metadata / archive 平台；
  4. Hermes Agent 专家与 Anthropic Manager 专家复核均无 blocking/P1。

## Task 41.2 写失败测试锁定 refresh / rebuild contract

- **任务编号**：T412
- **状态**：已完成（2026-04-14）
- **目标**：用失败测试先锁定 `release_gate_report` 的 refresh / archive rebuild / fixture regeneration 只能通过单一命令入口完成。
- **文件**：
  - `tests/test_watchdog_release_gate.py`
- **可并行**：否
- **验收标准**：
  1. 覆盖 refresh command module/CLI surface 必须存在；
  2. 覆盖 refresh 命令只能复用 shared material helper、现有 generator 与 shared loader；
  3. 覆盖 refresh 输出必须 loader-valid；
  4. 覆盖 drift / 缺字段 / 输入缺失都必须 fail closed。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_release_gate.py`
- **完成情况**：
  1. 已新增 refresh command module/CLI surface 红测；
  2. 已锁定 refresh 输出必须被 shared loader 直接接受；
  3. 已锁定输入缺失时必须 fail closed；
  4. 初次红测确认当前缺口就是 refresh script 缺失。

## Task 41.3 实现最小 refresh 命令与 runbook contract

- **任务编号**：T413
- **状态**：已完成（2026-04-14）
- **目标**：交付单一 refresh 命令入口，并把 refresh 的输入、输出、成功态与失败纪律正式写入 runbook。
- **文件**：
  - `scripts/refresh_release_gate_artifacts.py`
  - `scripts/generate_release_gate_report.py`
  - `docs/operations/release-gate-runbook.md`
  - `tests/test_watchdog_release_gate.py`
  - `tests/test_watchdog_release_gate_evidence.py`
- **可并行**：否
- **验收标准**：
  1. refresh 命令已成为唯一正式入口；
  2. refresh 命令只复用现有 generator、shared material helper 与 shared loader；
  3. runbook 已正式记录 refresh 输入/输出/成功态与 fail-closed 条件；
  4. 不引入 manifest、schema 变化、policy 变化或新的 read-side surface。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_release_gate.py tests/test_watchdog_release_gate_evidence.py tests/test_long_running_autonomy_doc_contracts.py`
- **完成情况**：
  1. 已新增 `scripts/refresh_release_gate_artifacts.py` 作为唯一 refresh / rebuild / regeneration 命令；
  2. refresh 命令只委托现有 generator、shared material helper 与 shared loader，不再重写 report material/hash 逻辑；
  3. runbook 已正式加入 `Refresh / Rebuild Contract` 章节，明确唯一正式命令与禁止人工编辑 JSON；
  4. Hermes Agent 专家与 Anthropic Manager 专家复核均无 blocking/P1。

## Task 41.4 更新执行日志与 handoff 摘要

- **任务编号**：T414
- **状态**：已完成（2026-04-14）
- **目标**：同步 formal docs、执行日志与 `.ai-sdlc` 元数据，固定后续 handoff。
- **文件**：
  - `specs/041-release-gate-artifact-refresh-and-rebuild-contract/task-execution-log.md`
  - `.ai-sdlc/work-items/041-release-gate-artifact-refresh-and-rebuild-contract/execution-plan.yaml`
  - `.ai-sdlc/work-items/041-release-gate-artifact-refresh-and-rebuild-contract/runtime.yaml`
  - `.ai-sdlc/work-items/041-release-gate-artifact-refresh-and-rebuild-contract/resume-pack.yaml`
  - `.ai-sdlc/work-items/041-release-gate-artifact-refresh-and-rebuild-contract/latest-summary.md`
- **可并行**：否
- **验收标准**：
  1. 执行日志已记录 red/green/review 闭环与 refresh contract 收口；
  2. `.ai-sdlc` 元数据能准确恢复到下一执行入口；
  3. handoff 明确后续任何 refresh / rebuild 都不得回到人工 JSON 编辑或局部 helper。
- **验证**：
  - `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`
  - 人工审阅执行日志与 `.ai-sdlc` 元数据一致
- **完成情况**：
  1. 已把方案对抗评估、freeze、red/green/review 闭环与实现提交写回执行日志；
  2. `.ai-sdlc` 元数据已同步到 041 完成态；
  3. handoff 已明确后续任何 refresh / rebuild 都必须复用单一 refresh 命令与 shared helper。

## Task 41.5 完成 041 整体验证并交接下一 work item

- **任务编号**：T415
- **状态**：已完成（2026-04-14）
- **目标**：完成 041 的整体验证，并把 refresh contract 作为后续 work item 的正式依赖写回 handoff。
- **文件**：
  - `specs/041-release-gate-artifact-refresh-and-rebuild-contract/task-execution-log.md`
  - `.ai-sdlc/work-items/041-release-gate-artifact-refresh-and-rebuild-contract/latest-summary.md`
  - `.ai-sdlc/work-items/041-release-gate-artifact-refresh-and-rebuild-contract/resume-pack.yaml`
- **可并行**：否
- **验收标准**：
  1. 041 的 refresh / rebuild contract 已被明确为唯一正式 operator workflow；
  2. handoff 明确后续入口不得复制 refresh 逻辑或回到人工拼装；
  3. 后续扩展点已收敛到 refresh 命令的复用，而不是新的 metadata 平台。
- **验证**：
  - `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`
  - 人工审阅 handoff 与总实施计划一致
- **完成情况**：
  1. `WI-041` 已完成：refresh / rebuild / regeneration 已成为唯一正式 operator workflow；
  2. 下一批如需继续扩展 release gate operator path，只能建立在单一 refresh 命令之上，不能再引入 manifest 或人工拼装流程；
  3. 最后一轮 Hermes Agent 专家与 Anthropic Manager 专家复核均无 blocking/P1。

## 整体验收

- 041 只负责把 `release_gate_report` refresh / archive rebuild / fixture regeneration 正式化成单一 operator contract。
- 041 完成后，后续任何 refresh / rebuild 都只能复用 refresh 命令、shared material helper 与 shared loader。
- 041 不得新增 manifest、policy 变化、schema 变化或新的第二真相。
