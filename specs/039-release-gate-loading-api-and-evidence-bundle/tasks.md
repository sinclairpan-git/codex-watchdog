# 任务分解：039-release-gate-loading-api-and-evidence-bundle

> 对应规格：`specs/039-release-gate-loading-api-and-evidence-bundle/spec.md`
>
> 对应计划：`specs/039-release-gate-loading-api-and-evidence-bundle/plan.md`

## Task 39.1 冻结 039 formal docs 与 shared loading / evidence bundle 边界

- **任务编号**：T391
- **状态**：已完成（2026-04-14）
- **目标**：把总实施计划中的 `Task 10` 正式拆成 canonical execution work item，并把 039 收紧为 `release_gate_report` shared loading API 与 evidence bundle 回读 contract。
- **文件**：
  - `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
  - `specs/039-release-gate-loading-api-and-evidence-bundle/spec.md`
  - `specs/039-release-gate-loading-api-and-evidence-bundle/plan.md`
  - `specs/039-release-gate-loading-api-and-evidence-bundle/tasks.md`
  - `specs/039-release-gate-loading-api-and-evidence-bundle/task-execution-log.md`
  - `.ai-sdlc/work-items/039-release-gate-loading-api-and-evidence-bundle/*`
- **可并行**：否
- **验收标准**：
  1. 已明确 039 只做 shared loading API / evidence bundle，不扩新的 release gate 行为；
  2. 已明确 039 只消费 035/037/038 已冻结的 release gate / e2e / future worker contract；
  3. 已明确后续任何消费 `release_gate_report` 的入口都必须复用 shared loader / bundle；
  4. Hermes Agent 专家与 Anthropic Manager 专家复核后无 blocking/P1。
- **验证**：
  - `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`
  - 人工审阅 `spec.md / plan.md / tasks.md / .ai-sdlc` 元数据与 Task 10 边界一致
- **完成情况**：
  1. 已新增 `Task 10` 到总实施计划，并挂到 `specs/039-release-gate-loading-api-and-evidence-bundle/`；
  2. 已创建 `spec.md / plan.md / tasks.md / task-execution-log.md` 与 `.ai-sdlc/work-items/039-*` 基线；
  3. 已把 039 收紧为 shared loading / evidence bundle contract，而不是扩新的 gate policy；
  4. Hermes Agent 专家与 Anthropic Manager 专家复核均无 blocking/P1。

## Task 39.2 写失败测试锁定 shared loading API 与 evidence bundle contract

- **任务编号**：T392
- **状态**：已完成（2026-04-14）
- **目标**：用失败测试先锁定 release gate shared loading / evidence bundle 的正式边界，避免后续入口继续复制 helper 逻辑。
- **文件**：
  - `tests/test_watchdog_release_gate.py`
  - `tests/test_watchdog_release_gate_evidence.py`
  - `tests/test_watchdog_ops.py`
  - `tests/test_watchdog_session_spine_runtime.py`
- **可并行**：否
- **验收标准**：
  1. 覆盖 `release_gate_report` 只能通过单一 shared loader 进入 runtime；
  2. 覆盖 `release_gate_evidence_bundle` 能统一暴露 formal artifacts 与治理元数据；
  3. 覆盖 ops/read-side 不得自行重算 report validity；
  4. 覆盖报告缺失、过期、hash drift、runtime contract drift、非对象 JSON 与默认值补全漂移都必须 fail closed。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_release_gate.py tests/test_watchdog_release_gate_evidence.py tests/test_watchdog_ops.py tests/test_watchdog_session_spine_runtime.py`
- **完成情况**：
  1. 已为 `release_gate_loading` 新增 shared loader surface 红测，并锁定 report hash drift 必须 fail closed；
  2. 已为 `ReleaseGateEvidenceBundle` 锁定 `label_manifest_ref / generated_by / report_approved_by / report_id / report_hash / input_hash` 治理元数据；
  3. 已锁定 ops/read-side 只能透传 canonical blocker metadata，不能自行补算；
  4. 已锁定 runtime success / degraded path 都必须挂统一 `release_gate_evidence_bundle`，且报告损坏、治理漂移、非对象 JSON 都只能 `report_load_failed`。

## Task 39.3 实现最小 shared loading API 与 evidence bundle

- **任务编号**：T393
- **状态**：已完成（2026-04-14）
- **目标**：交付单一 shared loader 与 canonical evidence bundle surface，让 runtime / ops / 后续入口共享同一套 release gate 解释面。
- **文件**：
  - `src/watchdog/services/brain/release_gate_loading.py`
  - `src/watchdog/services/brain/release_gate.py`
  - `src/watchdog/services/brain/release_gate_evidence.py`
  - `src/watchdog/services/session_spine/orchestrator.py`
  - `src/watchdog/api/ops.py`
  - `src/watchdog/observability/metrics_export.py`
- **可并行**：否
- **验收标准**：
  1. shared loader 已统一 `release_gate_report` 的 read/parse/validate/hash/drift 判定；
  2. evidence bundle 已统一 formal artifacts 与 blocker metadata 回读面；
  3. orchestrator、ops/read-side 与 metrics 只消费 shared loader / bundle 输出；
  4. 不引入新的 gate 状态机、旁路放行规则或 read-side 第二真相。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_release_gate.py tests/test_watchdog_release_gate_evidence.py tests/test_watchdog_ops.py tests/test_watchdog_session_spine_runtime.py`
- **完成情况**：
  1. 已新增 `src/watchdog/services/brain/release_gate_loading.py`，统一 `release_gate_report` 的读取、schema 校验、canonical hash exactness 与 runtime contract surface；
  2. 已把 `ReleaseGateEvidenceBundle` 扩成唯一正式 blocker/evidence 回读面，承载 formal artifacts 与治理元数据；
  3. orchestrator 已改为只消费 shared loader 输出，并在 load failure 时保留最小 canonical evidence bundle；
  4. ops read-side 已改为直接透传 shared bundle metadata，不再拼装第二真相；
  5. Hermes Agent 专家与 Anthropic Manager 专家复核均无 blocking/P1。

## Task 39.4 更新执行日志与 handoff 摘要

- **任务编号**：T394
- **状态**：已完成（2026-04-14）
- **目标**：同步 formal docs、执行日志与 `.ai-sdlc` 元数据，固定后续 handoff。
- **文件**：
  - `specs/039-release-gate-loading-api-and-evidence-bundle/task-execution-log.md`
  - `.ai-sdlc/work-items/039-release-gate-loading-api-and-evidence-bundle/execution-plan.yaml`
  - `.ai-sdlc/work-items/039-release-gate-loading-api-and-evidence-bundle/runtime.yaml`
  - `.ai-sdlc/work-items/039-release-gate-loading-api-and-evidence-bundle/resume-pack.yaml`
  - `.ai-sdlc/work-items/039-release-gate-loading-api-and-evidence-bundle/latest-summary.md`
- **可并行**：否
- **验收标准**：
  1. 执行日志已记录 red/green/review 闭环与 shared loading contract 收口；
  2. `.ai-sdlc` 元数据能准确恢复到下一执行入口；
  3. handoff 明确后续任何 release gate consumer 都不得回到局部 helper 解析。
- **验证**：
  - `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`
  - 人工审阅执行日志与 `.ai-sdlc` 元数据一致
- **完成情况**：
  1. 已把 red/green/review 闭环、实现提交与 formal handoff 写回执行日志；
  2. `.ai-sdlc` 元数据已同步到 039 完成态；
  3. handoff 已明确后续任何 release gate consumer 都必须复用 shared loading / evidence bundle contract。

## Task 39.5 完成 039 整体验证并交接下一 work item

- **任务编号**：T395
- **状态**：已完成（2026-04-14）
- **目标**：完成 039 的整体验证，并把 shared loading / bundle contract 作为后续 work item 的正式依赖写回 handoff。
- **文件**：
  - `specs/039-release-gate-loading-api-and-evidence-bundle/task-execution-log.md`
  - `.ai-sdlc/work-items/039-release-gate-loading-api-and-evidence-bundle/latest-summary.md`
  - `.ai-sdlc/work-items/039-release-gate-loading-api-and-evidence-bundle/resume-pack.yaml`
- **可并行**：否
- **验收标准**：
  1. 039 的 shared loader / evidence bundle contract 已被明确为唯一正式消费面；
  2. handoff 明确后续入口不得复制 parse/validate 逻辑；
  3. 后续扩展点已收敛到 shared API 的复用，而不是再次分叉 release gate 语义。
- **验证**：
  - `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`
  - 人工审阅 handoff 与总实施计划一致
- **完成情况**：
  1. `WI-039` 已完成：`release_gate_report` shared loading API 与 `release_gate_evidence_bundle` 已成为唯一正式消费面；
  2. 下一批如需扩展 release gate consumer，只能声明依赖 `release_gate_loading.py` 与 canonical evidence bundle，不能再回退到局部 helper；
  3. 最后一轮 Hermes Agent 专家与 Anthropic Manager 专家复核均无 blocking/P1。

## 整体验收

- 039 只负责把 `release_gate_report` shared loading API 与 evidence bundle 回读 contract 正式化。
- 039 完成后，runtime、ops/read-side 与后续任何入口都只能复用同一套 release gate loading / bundle surface。
- 039 不得新增新的 gate policy、旁路放行规则或 read-side 第二真相。
