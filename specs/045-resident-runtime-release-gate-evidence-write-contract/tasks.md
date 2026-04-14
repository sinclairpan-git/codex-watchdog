# 任务分解：045-resident-runtime-release-gate-evidence-write-contract

> 对应规格：`specs/045-resident-runtime-release-gate-evidence-write-contract/spec.md`
>
> 对应计划：`specs/045-resident-runtime-release-gate-evidence-write-contract/plan.md`

## Task 45.1 冻结 045 formal docs 与 resident runtime write seam 边界

- **任务编号**：T451
- **状态**：已完成（2026-04-14）
- **目标**：把总实施计划中的 `Task 16` 正式拆成 canonical execution work item，并把 045 收紧为 resident runtime release-gate evidence write-side contract。
- **文件**：
  - `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
  - `specs/045-resident-runtime-release-gate-evidence-write-contract/spec.md`
  - `specs/045-resident-runtime-release-gate-evidence-write-contract/plan.md`
  - `specs/045-resident-runtime-release-gate-evidence-write-contract/tasks.md`
  - `specs/045-resident-runtime-release-gate-evidence-write-contract/task-execution-log.md`
  - `.ai-sdlc/work-items/045-resident-runtime-release-gate-evidence-write-contract/*`
- **可并行**：否
- **验收标准**：
  1. 已明确 045 只做 resident runtime release-gate evidence write seam；
  2. 已明确 045 只消费既有 release-gate typed models 与 loading contract；
  3. 已明确 045 不引入新的 policy、schema、测试平台、manifest、archive metadata 或 parameter rename campaign；
  4. Hermes Agent 专家与 Anthropic Manager 专家复核后无 blocking/P1。
- **验证**：
  - `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`
  - 人工审阅 `spec.md / plan.md / tasks.md / .ai-sdlc` 元数据与 Task 16 边界一致
- **完成情况**：
  1. 已新增 `Task 16` 到总实施计划，并挂到 `specs/045-resident-runtime-release-gate-evidence-write-contract/`；
  2. 已创建 `spec.md / plan.md / tasks.md / task-execution-log.md` 与 `.ai-sdlc/work-items/045-*` 基线；
  3. 已把 045 收紧为 resident runtime 的 `release_gate_verdict + release_gate_evidence_bundle` 写侧 seam，而不是参数命名或测试整理；
  4. Hermes Agent 专家与 Anthropic Manager 专家复核均无 blocking/P1。

## Task 45.2 写失败测试锁定 release-gate evidence write-side contract

- **任务编号**：T452
- **状态**：未开始
- **目标**：用失败测试先锁定 resident runtime 对 release-gate evidence 的唯一 write-side surface。
- **文件**：
  - `tests/test_watchdog_session_spine_runtime.py`
- **可并行**：否
- **验收标准**：
  1. 覆盖 resident runtime 不得继续在 orchestrator 中内联拼装 release-gate verdict/bundle；
  2. 覆盖正式 report path 与 fallback path 都必须通过 shared helper 输出同一 canonical shape；
  3. 覆盖现有 evidence shape 保持不变。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_session_spine_runtime.py`

## Task 45.3 实现最小 shared write helper 与 resident runtime 收口

- **任务编号**：T453
- **状态**：未开始
- **目标**：让 resident runtime 只通过 shared write-side contract 组装 release-gate evidence。
- **文件**：
  - `src/watchdog/services/brain/release_gate_write_contract.py`
  - `src/watchdog/services/session_spine/orchestrator.py`
  - `tests/test_watchdog_session_spine_runtime.py`
- **可并行**：否
- **验收标准**：
  1. `_decision_evidence_for_intent()` 已改为复用 shared write-side helper；
  2. 正式 report path 与 report load failure fallback 都通过同一 helper 组装；
  3. 现有 evidence shape、read-side surface 与 policy semantics 不变；
  4. 不引入 schema、manifest、persistence、parameter rename 或 workflow 变化。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_session_spine_runtime.py tests/test_long_running_autonomy_doc_contracts.py`

## Task 45.4 更新执行日志与 handoff 摘要

- **任务编号**：T454
- **状态**：未开始
- **目标**：同步 formal docs、执行日志与 `.ai-sdlc` 元数据，固定后续 handoff。
- **文件**：
  - `specs/045-resident-runtime-release-gate-evidence-write-contract/task-execution-log.md`
  - `.ai-sdlc/work-items/045-resident-runtime-release-gate-evidence-write-contract/execution-plan.yaml`
  - `.ai-sdlc/work-items/045-resident-runtime-release-gate-evidence-write-contract/runtime.yaml`
  - `.ai-sdlc/work-items/045-resident-runtime-release-gate-evidence-write-contract/resume-pack.yaml`
  - `.ai-sdlc/work-items/045-resident-runtime-release-gate-evidence-write-contract/latest-summary.md`
- **可并行**：否
- **验收标准**：
  1. 执行日志已记录方案选择、red/green/review 闭环与 write seam 收口；
  2. `.ai-sdlc` 元数据能准确恢复到下一执行入口；
  3. handoff 明确后续 resident runtime producer 只能复用 shared write-side contract。
- **验证**：
  - `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`
  - 人工审阅执行日志与 `.ai-sdlc` 元数据一致

## Task 45.5 完成 045 整体验证并交接后续 work item

- **任务编号**：T455
- **状态**：未开始
- **目标**：完成 045 的整体验证，并把 release-gate write-side contract 作为后续 work item 的正式依赖写回 handoff。
- **文件**：
  - `specs/045-resident-runtime-release-gate-evidence-write-contract/task-execution-log.md`
  - `.ai-sdlc/work-items/045-resident-runtime-release-gate-evidence-write-contract/latest-summary.md`
  - `.ai-sdlc/work-items/045-resident-runtime-release-gate-evidence-write-contract/resume-pack.yaml`
- **可并行**：否
- **验收标准**：
  1. 045 的 release-gate evidence write-side contract 已被明确为唯一正式 producer seam；
  2. handoff 明确后续 producer 不得再复制 `ReleaseGateEvidenceBundle(...)` 拼装逻辑；
  3. 最后一轮 Hermes Agent 专家与 Anthropic Manager 专家复核均无 blocking/P1。
- **验证**：
  - `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`
  - 人工审阅 handoff 与总实施计划一致

## 整体验收

- 045 只负责把 resident runtime 的 release-gate evidence 写侧正式化成单一 shared contract。
- 045 完成后，后续任何 resident runtime producer 都只能复用 shared write-side contract，不得再手工拼装 `ReleaseGateEvidenceBundle(...)`。
- 045 不得新增 policy、schema、persistence、manifest 或新的第二真相。
