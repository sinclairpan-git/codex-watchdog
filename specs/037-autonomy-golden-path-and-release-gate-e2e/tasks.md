# 任务分解：037-autonomy-golden-path-and-release-gate-e2e

> 对应规格：`specs/037-autonomy-golden-path-and-release-gate-e2e/spec.md`
>
> 对应计划：`specs/037-autonomy-golden-path-and-release-gate-e2e/plan.md`

## Task 37.1 冻结 037 formal docs 与一期 e2e release blocker 边界

- **任务编号**：T371
- **状态**：已完成（2026-04-14）
- **目标**：把总实施计划中的 `Task 8` 正式拆成 canonical execution work item，并把 037 收紧为“一期正式通关主链 + release gate 硬阻断 + 无手工补状态的恢复验收”。
- **文件**：
  - `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
  - `specs/037-autonomy-golden-path-and-release-gate-e2e/spec.md`
  - `specs/037-autonomy-golden-path-and-release-gate-e2e/plan.md`
  - `specs/037-autonomy-golden-path-and-release-gate-e2e/tasks.md`
  - `specs/037-autonomy-golden-path-and-release-gate-e2e/task-execution-log.md`
  - `.ai-sdlc/work-items/037-autonomy-golden-path-and-release-gate-e2e/*`
- **可并行**：否
- **验收标准**：
  1. 已明确 037 的主目标是一条正式一期自治主链，而不是泛化 e2e 集合；
  2. 已明确 037 只消费 030-036 已冻结的 truth / goal / recovery / brain / release gate / Feishu control contract；
  3. 已明确 `release_gate_report`、runbook/script、`label_manifest`、样本冻结窗口与 artifact archive 是正式 blocking inputs；
  4. 已明确 worker crash、claim timeout、notification failure、supersede/stale interaction、人工 override 与 child continuation 都属于一期正式验收面；
  5. Hermes Agent 专家与 Anthropic Manager 专家复核后无 blocking/P1。
- **验证**：
  - `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`
  - 人工审阅 `spec.md / plan.md / tasks.md / .ai-sdlc` 元数据与 Task 8 边界一致
- **当前进展**：
  1. 已创建 `spec.md / plan.md / tasks.md / task-execution-log.md` 与 `.ai-sdlc/work-items/037-*` 基线；
  2. 已把 Task 8 正式挂到 canonical execution work item；
  3. Anthropic Manager 专家首轮复核无 blocking/P1；
  4. Hermes Agent 专家指出 `tool_schema_hash` drift 维度遗漏这一条 P1，现已补回 037 的 hard-blocker 清单；
  5. 修订后 Hermes Agent 专家与 Anthropic Manager 专家最终复核均无 blocking/P1。

## Task 37.2 写失败测试锁定一期 golden path、midstate recovery 与 release gate e2e blocker

- **任务编号**：T372
- **状态**：已完成（2026-04-14）
- **目标**：用失败测试先锁定一期正式通关标准，避免实现阶段把 e2e 降成演示脚本或旁路验收。
- **文件**：
  - `tests/e2e/test_watchdog_autonomy_golden_path.py`
  - `tests/e2e/test_watchdog_midstate_recovery.py`
  - `tests/e2e/test_watchdog_release_gate_e2e.py`
- **可并行**：否
- **验收标准**：
  1. 覆盖单一正式主链 `Feishu DM -> Goal Contract -> Brain -> Session write barrier -> command lease -> execution / approval -> completion -> replay / metrics`；
  2. 覆盖 worker crash、claim timeout、notification failure、`interaction_context_superseded`、stale interaction、人工 override 与 `remote compact` child continuation；
  3. 覆盖全流程不得依赖手工改库、手工补事件、手工替换 report 或绕过 release gate；
  4. 覆盖 `certification_packet_corpus + shadow_decision_ledger + release_gate_report` 与 formal artifacts 缺失/漂移时必须 fail closed；
  5. 覆盖这些 e2e 本身是 release blocker，而不是可跳过样例。
- **验证**：
  - `uv run pytest -q tests/e2e/test_watchdog_autonomy_golden_path.py tests/e2e/test_watchdog_midstate_recovery.py tests/e2e/test_watchdog_release_gate_e2e.py`
- **完成情况**：
  1. 已新增三条 e2e contract 测试，分别锁定 Feishu DM kickoff、midstate recovery/child continuation 与 release gate evidence bundle；
  2. 已明确看到三类真实缺口：Feishu kickoff contract 缺失、recovery 未收口 stale interaction、runtime 未暴露 formal release gate evidence bundle；
  3. 当前三条 e2e 已在最小接线后转绿。

## Task 37.3 补齐 golden path 所需的跨模块 glue 与恢复接续

- **任务编号**：T373
- **状态**：已完成（2026-04-14）
- **目标**：在不引入旁路状态机的前提下，把 Task 8 所需的 canonical refs、恢复接续与 completion evidence 真正接通。
- **文件**：
  - `src/watchdog/services/brain/release_gate.py`
  - `src/watchdog/services/brain/release_gate_evidence.py`
  - `src/watchdog/services/feishu_control/service.py`
  - `src/watchdog/services/session_service/service.py`
  - `src/watchdog/services/session_spine/command_leases.py`
  - `src/watchdog/services/session_spine/orchestrator.py`
- **可并行**：否
- **验收标准**：
  1. 命令租约恢复、通知投递恢复、人工接管、child session continuation 与 completion evidence 都已进入同一条 canonical 主链；
  2. `decision_trace_ref`、`approval_read_ref`、`release_gate_report`、interaction context、recovery tx 与 completion refs 均可从 e2e 主链回读；
  3. 不引入“先改 store 再补 event”或 e2e 专用真相层；
  4. golden path 在不手工修状态的前提下可重复通过。
- **验证**：
  - `uv run pytest -q tests/e2e/test_watchdog_autonomy_golden_path.py tests/e2e/test_watchdog_midstate_recovery.py tests/test_watchdog_command_leases.py tests/test_watchdog_session_spine_runtime.py`
- **完成情况**：
  1. 已在 `feishu_control` 中补上 `goal_contract_bootstrap` kickoff contract，使 Feishu DM 能创建/修订 Goal Contract，并把 session 交给既有 runtime/orchestrator 消费；
  2. 已在 `recovery.py` 中把 stale interaction supersede 与 recovery continuation 收口到同一条恢复真相链；
  3. 已在 runtime evidence 中补上 `release_gate_evidence_bundle`，把 `certification_packet_corpus`、`shadow_decision_ledger` 与 `release_gate_report_ref` 暴露到 decision evidence；
  4. 已在 `command_executed / command_failed` 的 canonical terminal payload 中补上 `completion_evidence_ref`、`completion_judgment`、`replay_ref`、`replay_summary`、`metrics_ref` 与 `metrics_summary`，并复用命令租约到 `Session Service` 的镜像链完成回读。

## Task 37.4 收口 release gate formal artifacts、阻断语义与 ops surfacing

- **任务编号**：T374
- **状态**：已完成（2026-04-14）
- **目标**：把 low-risk auto-decision 的 formal blocking inputs 与 fail-closed 行为真正接到 runtime 和 ops 观察面。
- **文件**：
  - `src/watchdog/services/brain/release_gate.py`
  - `src/watchdog/services/brain/release_gate_evidence.py`
  - `src/watchdog/api/ops.py`
  - `src/watchdog/observability/metrics_export.py`
  - `tests/e2e/test_watchdog_release_gate_e2e.py`
  - `tests/test_watchdog_ops.py`
- **可并行**：否
- **验收标准**：
  1. `release_gate_report`、runbook/script、`label_manifest`、样本冻结窗口、`generated_by`、`approved_by` 与 `artifact_ref` 缺失时必须阻断 auto execute；
  2. input hash、provider/model/prompt/schema、`policy_engine_version`、`decision_input_builder_version`、`tool_schema_hash`、`memory_provider_adapter_hash` 或 approval freshness 漂移时必须自动降级；
  3. ops/read-side 能明确看到阻断原因与 formal artifacts 元数据；
  4. 037 不会把 release gate 退回“人工说明即可放行”的软约束。
- **验证**：
  - `uv run pytest -q tests/e2e/test_watchdog_release_gate_e2e.py tests/test_watchdog_ops.py`
- **完成情况**：
  1. 已把 release gate degraded 决策收口为 `OpsSummary.release_gate_blockers`，显式暴露 `reason`、`report_id`、`report_hash`、`input_hash`、`release_gate_report_ref`、`certification_packet_corpus_ref` 与 `shadow_decision_ledger_ref`；
  2. `/api/v1/watchdog/ops/alerts` 现在会返回 formal blocker metadata，而不是只有抽象 alert 计数；
  3. `/metrics` 现在会导出 `watchdog_release_gate_blocker_active{reason=...}` gauge，保持 release gate 阻断语义在 read-side/metrics 双面可见。

## Task 37.5 更新执行日志与 handoff 摘要

- **任务编号**：T375
- **状态**：已完成（2026-04-14）
- **目标**：同步 formal docs、执行日志与 `.ai-sdlc` 元数据，固定下一执行入口与 release blocker 口径。
- **文件**：
  - `specs/037-autonomy-golden-path-and-release-gate-e2e/task-execution-log.md`
  - `.ai-sdlc/work-items/037-autonomy-golden-path-and-release-gate-e2e/execution-plan.yaml`
  - `.ai-sdlc/work-items/037-autonomy-golden-path-and-release-gate-e2e/runtime.yaml`
  - `.ai-sdlc/work-items/037-autonomy-golden-path-and-release-gate-e2e/resume-pack.yaml`
  - `.ai-sdlc/work-items/037-autonomy-golden-path-and-release-gate-e2e/latest-summary.md`
- **可并行**：否
- **验收标准**：
  1. 执行日志已记录 red/green/review 闭环与 release blocker 收口；
  2. `.ai-sdlc` 元数据能准确恢复到下一执行入口；
  3. handoff 明确 037 是否已经形成一期正式通关标准，或者具体阻断在哪个 gating point；
  4. handoff 明确后续工作不得再回退到人工演示、手工补状态或口头放行。
- **验证**：
  - `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`
  - 人工审阅执行日志与 `.ai-sdlc` 元数据一致
- **完成情况**：
  1. 已把 T373/T374 的 green 与验证证据同步回 `task-execution-log.md`；
  2. 已把 `.ai-sdlc/work-items/037-*` 的 batch/task/runtime 状态更新为可恢复的完成态；
  3. handoff 已明确 037 形成了一期正式通关与 release blocker 基线，后续工作不得回退到手工补状态或口头放行。

## 整体验收

- 037 是长时运行自治一期的 `Task 8`，只负责把正式通关标准与端到端 release gate 验收固化为 release blocker。
- 037 完成后，一期必须存在单一、可重复、可审计的自治主链，并且不依赖手工补状态。
- 037 完成后，`release_gate_report`、runbook/script、`label_manifest`、样本冻结窗口与 artifact archive 都应成为 low-risk auto-decision 的硬阻断输入。
- 037 不负责重写 030-036 的核心 contract；它只消费这些已冻结边界并把它们串成正式通关验收。
