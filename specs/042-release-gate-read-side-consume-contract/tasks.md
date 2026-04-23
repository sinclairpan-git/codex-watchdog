# 任务分解：042-release-gate-read-side-consume-contract

> 对应规格：`specs/042-release-gate-read-side-consume-contract/spec.md`
>
> 对应计划：`specs/042-release-gate-read-side-consume-contract/plan.md`

## Task 42.1 冻结 042 formal docs 与 read-side consume 边界

- **任务编号**：T421
- **状态**：已完成（2026-04-14）
- **目标**：把总实施计划中的 `Task 13` 正式拆成 canonical execution work item，并把 042 收紧为 shared typed read-side consume contract。
- **文件**：
  - `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
  - `specs/042-release-gate-read-side-consume-contract/spec.md`
  - `specs/042-release-gate-read-side-consume-contract/plan.md`
  - `specs/042-release-gate-read-side-consume-contract/tasks.md`
  - `specs/042-release-gate-read-side-consume-contract/task-execution-log.md`
  - `.ai-sdlc/work-items/042-release-gate-read-side-consume-contract/*`
- **可并行**：否
- **验收标准**：
  1. 已明确 042 只做 shared helper / typed model + 现有 consumer 收口；
  2. 已明确 042 只消费 039/040/041 已冻结的 loading/material/refresh contract；
  3. 已明确 042 不引入测试平台、新 query facade、manifest、archive metadata 或新的 read platform；
  4. Hermes Agent 专家与 Anthropic Manager 专家复核后无 blocking/P1。
- **验证**：
  - `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`
  - 人工审阅 `spec.md / plan.md / tasks.md / .ai-sdlc` 元数据与 Task 13 边界一致
- **完成情况**：
  1. 已新增 `Task 13` 到总实施计划，并挂到 `specs/042-release-gate-read-side-consume-contract/`；
  2. 已创建 `spec.md / plan.md / tasks.md / task-execution-log.md` 与 `.ai-sdlc/work-items/042-*` 基线；
  3. 已把 042 收紧为 shared typed read-side consume contract，而不是测试平台或新的 read facade；
  4. Hermes Agent 专家与 Anthropic Manager 专家复核均无 blocking/P1。

## Task 42.2 写失败测试锁定 read-side consume contract

- **任务编号**：T422
- **状态**：已完成（2026-04-14）
- **目标**：用失败测试先锁定 read-side consumer 对 release gate decision evidence 的唯一 consume surface。
- **文件**：
  - `tests/test_watchdog_ops.py`
  - `tests/test_watchdog_session_spine_runtime.py`
- **可并行**：否
- **验收标准**：
  1. 覆盖 shared typed helper/module surface 必须存在；
  2. 覆盖 `ops.py` 通过 shared helper 读取 blocker metadata，而不是手工剥取 evidence dict；
  3. 覆盖 resident runtime 读取 runtime pass qualification 时不再依赖裸 dict 假设；
  4. 覆盖 malformed / partial evidence 必须 fail closed。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_ops.py tests/test_watchdog_session_spine_runtime.py`
- **完成情况**：
  1. 已新增 shared read contract module surface 红测；
  2. 已锁定 `ops.py` 对 partial / malformed bundle 的整包 fail-closed；
  3. 已锁定 resident runtime 不得把缺字段或缺 bundle 的 formal pass verdict 当作有效 runtime gate；
  4. 初次红测确认当前缺口就是 helper 缺失与 read-side 继续消费裸 dict。

## Task 42.3 实现最小 read-side helper 与 consumer 收口

- **任务编号**：T423
- **状态**：已完成（2026-04-14）
- **目标**：交付 shared typed read contract，并让首批正式 consumer 只通过它读取 release gate evidence。
- **文件**：
  - `src/watchdog/services/brain/release_gate_read_contract.py`
  - `src/watchdog/api/ops.py`
  - `src/watchdog/services/session_spine/orchestrator.py`
  - `tests/test_watchdog_ops.py`
  - `tests/test_watchdog_session_spine_runtime.py`
- **可并行**：否
- **验收标准**：
  1. 已新增 shared typed helper / parsing surface；
  2. `ops.py` 与 resident runtime 已改为消费 shared helper；
  3. malformed / partial evidence 继续 fail closed；
  4. 不引入 policy、schema、persistence、manifest 或 query facade 变化。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_ops.py tests/test_watchdog_session_spine_runtime.py tests/test_long_running_autonomy_doc_contracts.py`
- **完成情况**：
  1. 已新增 `src/watchdog/services/brain/release_gate_read_contract.py`，统一 typed 解析 `release_gate_verdict + release_gate_evidence_bundle`；
  2. `src/watchdog/api/ops.py` 与 resident runtime 读侧已改为只消费 shared helper；
  3. 已修掉两轮对抗复核指出的 P1：formal pass verdict 在缺 bundle 或 partial bundle 时继续 fail closed；
  4. future-worker patched evidence 与 e2e 也已补成完整 formal bundle，避免半截 evidence 继续漏过 runtime consume path。

## Task 42.4 更新执行日志与 handoff 摘要

- **任务编号**：T424
- **状态**：已完成（2026-04-14）
- **目标**：同步 formal docs、执行日志与 `.ai-sdlc` 元数据，固定后续 handoff。
- **文件**：
  - `specs/042-release-gate-read-side-consume-contract/task-execution-log.md`
  - `.ai-sdlc/work-items/042-release-gate-read-side-consume-contract/execution-plan.yaml`
  - `.ai-sdlc/work-items/042-release-gate-read-side-consume-contract/runtime.yaml`
  - `.ai-sdlc/work-items/042-release-gate-read-side-consume-contract/resume-pack.yaml`
  - `.ai-sdlc/work-items/042-release-gate-read-side-consume-contract/latest-summary.md`
- **可并行**：否
- **验收标准**：
  1. 执行日志已记录方案选择、red/green/review 闭环与 consumer 收口；
  2. `.ai-sdlc` 元数据能准确恢复到下一执行入口；
  3. handoff 明确后续 consumer 只能复用 shared read contract。
- **验证**：
  - `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`
  - 人工审阅执行日志与 `.ai-sdlc` 元数据一致
- **完成情况**：
  1. 已把方案选择、freeze、红测缺口、实现与两轮 P1 修复写回执行日志；
  2. `.ai-sdlc` 元数据已同步到 042 完成态；
  3. handoff 已明确后续任何 consumer 都必须复用 shared read contract。

## Task 42.5 完成 042 整体验证并交接后续 work item

- **任务编号**：T425
- **状态**：已完成（2026-04-14）
- **目标**：完成 042 的整体验证，并把 read-side consume contract 作为后续 work item 的正式依赖写回 handoff。
- **文件**：
  - `specs/042-release-gate-read-side-consume-contract/task-execution-log.md`
  - `.ai-sdlc/work-items/042-release-gate-read-side-consume-contract/latest-summary.md`
  - `.ai-sdlc/work-items/042-release-gate-read-side-consume-contract/resume-pack.yaml`
- **可并行**：否
- **验收标准**：
  1. 042 的 typed read-side consume contract 已被明确为唯一正式读侧入口；
  2. handoff 明确后续 consumer 不得再复制 verdict/bundle 字段路径；
  3. 后续扩展点已收敛到 shared read contract 复用，而不是新 query platform。
- **验证**：
  - `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`
  - 人工审阅 handoff 与总实施计划一致
- **完成情况**：
  1. `WI-042` 已完成：release gate decision evidence 的 read-side consume path 已收敛到唯一 typed contract；
  2. 后续 consumer 不得再复制 verdict/bundle 字段路径或把 partial evidence 当作 formal runtime gate；
  3. 最后一轮 Hermes Agent 专家与 Anthropic Manager 专家复核均无 blocking/P1。

## 整体验收

- 042 只负责把 release gate decision evidence 的 read-side consume path 正式化成单一 typed contract。
- 042 完成后，后续任何 read-side consumer 都只能复用 shared helper / typed model，不得再手工剥取 evidence dict。
- 042 不得新增 policy、schema、persistence、manifest 或新的第二真相。
