# 任务分解：038-future-worker-canonical-execution-and-governance

> 对应规格：`specs/038-future-worker-canonical-execution-and-governance/spec.md`
>
> 对应计划：`specs/038-future-worker-canonical-execution-and-governance/plan.md`

## Task 38.1 冻结 038 formal docs 与 worker canonical execution 边界

- **任务编号**：T381
- **状态**：已完成（2026-04-14）
- **目标**：把 035 预留的 future worker/sub-agent schema 正式提升为独立 work item，并收紧为 canonical execution contract，而不是泛化并行框架。
- **文件**：
  - `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
  - `specs/038-future-worker-canonical-execution-and-governance/spec.md`
  - `specs/038-future-worker-canonical-execution-and-governance/plan.md`
  - `specs/038-future-worker-canonical-execution-and-governance/tasks.md`
  - `specs/038-future-worker-canonical-execution-and-governance/task-execution-log.md`
  - `.ai-sdlc/work-items/038-future-worker-canonical-execution-and-governance/*`
- **可并行**：否
- **验收标准**：
  1. 已明确 038 只实现 canonical worker execution contract，不实现通用任务平台；
  2. 已明确 038 只消费 033-037 已冻结的 recovery / memory refs / brain trace / Feishu / completion contract；
  3. 已明确 worker requested/start/summary/complete/fail/consume/reject 都必须进入 canonical truth；
  4. 已明确 worker 不得直接修改 Goal Contract、approval、risk band 或 completion truth；
  5. Hermes Agent 专家与 Anthropic Manager 专家复核后无 blocking/P1。
- **验证**：
  - `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`
- **完成情况**：
  1. 已新增 `Task 9` 到总实施计划，并挂到 `specs/038-future-worker-canonical-execution-and-governance/`；
  2. 已创建 `spec.md / plan.md / tasks.md / task-execution-log.md` 与 `.ai-sdlc/work-items/038-*` 基线；
  3. 已把 038 收紧为“worker canonical execution contract”，不回退到抽象 worker framework；
  4. Anthropic Manager 专家与 Hermes Agent 专家复核均无 blocking/P1。

## Task 38.2 写失败测试锁定 worker lifecycle、consume/reject 与 stale-result fail-closed

- **任务编号**：T382
- **状态**：已完成（2026-04-14）
- **目标**：用失败测试先锁定 worker/sub-agent 正式治理面，避免实现阶段把 worker 结果直接变成新真相。
- **文件**：
  - `tests/test_watchdog_future_worker_contract.py`
  - `tests/test_watchdog_future_worker_runtime.py`
  - `tests/e2e/test_watchdog_future_worker_execution.py`
- **可并行**：否
- **验收标准**：
  1. 覆盖 worker requested/start/heartbeat/summary/completed/failed/cancelled/consumed/rejected 的 canonical event 顺序；
  2. 覆盖 stale completion、duplicate start、late result、superseded result 与 scope drift 必须 fail closed；
  3. 覆盖 worker 只能消费 frozen refs，不能直接改 Goal Contract、approval、risk band 或 completion truth；
  4. 覆盖 parent consume worker result 前，worker 输出不得直接生效。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_future_worker_contract.py tests/test_watchdog_future_worker_runtime.py tests/e2e/test_watchdog_future_worker_execution.py`
- **完成情况**：
  1. 已新增 contract/runtime/e2e 三类红测，固定 `future_worker` 模块存在性、worker lifecycle canonical events 与 app-level service wiring；
  2. 首轮红测明确暴露三个真实缺口：`future_worker` 模块缺失、`Session Service` 不接受 `future_worker_*` event、`app.state.future_worker_service` 未接入；
  3. 当前三份测试已在最小接线后转绿。

## Task 38.3 补齐 canonical worker execution truth 与 runtime glue

- **任务编号**：T383
- **状态**：已完成（2026-04-14）
- **目标**：在不引入第二状态机的前提下，把 worker/sub-agent 正式纳入 Session truth、runtime 与 recovery。
- **文件**：
  - `src/watchdog/services/future_worker/models.py`
  - `src/watchdog/services/future_worker/service.py`
  - `src/watchdog/services/session_service/models.py`
  - `src/watchdog/services/session_service/service.py`
  - `src/watchdog/services/session_spine/orchestrator.py`
  - `src/watchdog/services/session_spine/recovery.py`
  - `src/watchdog/services/brain/models.py`
  - `src/watchdog/services/memory_hub/models.py`
- **可并行**：否
- **验收标准**：
  1. worker lifecycle 与 result consume/reject 已进入 canonical truth；
  2. worker 只消费 frozen refs，不读取 parent live truth 或 Memory Hub 私有热路径；
  3. worker 结果必须经 parent canonical consume 才能影响后续 decision/completion；
  4. crash / supersede / cancel / late-result 都进入同一条 canonical recovery/governance 链。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_future_worker_contract.py tests/test_watchdog_future_worker_runtime.py tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_recovery_execution.py`
  - `uv run pytest -q tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_future_worker_runtime.py tests/e2e/test_watchdog_future_worker_execution.py tests/test_watchdog_recovery_execution.py tests/test_watchdog_ops.py`
- **完成情况**：
  1. 已新增 `src/watchdog/services/future_worker/models.py` 与 `service.py`，提供 `FutureWorkerExecutionRequest`、`FutureWorkerResultEnvelope` 与最小 lifecycle service；
  2. 已在 `Session Service` 中登记 `future_worker_requested|started|heartbeat|summary_published|completed|failed|cancelled|result_consumed|result_rejected` canonical events；
  3. 已在 `create_app()` 中接入 `app.state.future_worker_service`，并打通 request/start/heartbeat/summary/completed/failed/cancelled/consume/reject 到 `Session Service` 的单一路径；
  4. parent-side canonical consume、stale-result rejection 的最小 service 已在位；
  5. 已把 `future_worker` 收紧成显式状态机，禁止 `failed/cancelled/rejected/consumed` 终态后继续 `completed/consume` 等非法跃迁，并固定 `consume/reject` 必须在 `completed` 之后发生；
  6. recovery continuation 现已会 supersede parent session 上未收口的 future worker：运行中 worker 记 `cancelled`，已完成未 consume 的 worker 记 `result_rejected`；
  7. orchestrator replay 现已只读取同 `decision_trace_ref` 的 worker truth，wrong-trace worker 事件不会混入当前 decision replay；
  8. parent command 成功后、以及 command 已 `executed` 的后续 tick 上，orchestrator 都会 canonical consume 同 trace 下已 `completed` 的 worker result；
  9. parent declarative `future_worker_requests` 已正式接入 orchestrator / decision evidence，只有整批 request schema + drift 预校验通过后才会 materialize `future_worker_requested`，避免 partial canonical truth。

## Task 38.4 收口 ops surfacing 与 formal worker e2e 主链

- **任务编号**：T384
- **状态**：已完成（2026-04-14）
- **目标**：把 worker/sub-agent 的正式运行层级、阻断原因与 stale-result rejection 暴露到 ops/read-side 与 e2e。
- **文件**：
  - `src/watchdog/api/ops.py`
  - `src/watchdog/observability/metrics_export.py`
  - `tests/test_watchdog_future_worker_runtime.py`
  - `tests/e2e/test_watchdog_future_worker_execution.py`
- **可并行**：否
- **验收标准**：
  1. ops/read-side 能区分 worker 在 requested/running/completed/failed/cancelled/rejected/consumed 哪一层；
  2. ops/read-side 能看到 supersede、late-result rejection、scope drift、budget overrun 等阻断原因；
  3. e2e 能固定至少一条正式 worker 主链与一条 stale/late rejection 支线。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_future_worker_runtime.py tests/e2e/test_watchdog_future_worker_execution.py tests/test_watchdog_ops.py`
  - `uv run pytest -q tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_future_worker_runtime.py tests/e2e/test_watchdog_future_worker_execution.py tests/test_watchdog_recovery_execution.py tests/test_watchdog_ops.py`
- **完成情况**：
  1. `build_ops_summary()` 已新增 `future_workers` 读侧视图，可区分 `requested/running/completed/failed/cancelled/rejected/consumed`；
  2. `ops` 读侧已暴露 `worker_task_ref / decision_trace_ref / last_event_type / blocking_reason`，可直接看见 `late_result` 等阻断原因；
  3. `metrics_export.py` 已新增 future worker 状态与阻断原因 gauge；
  4. `tests/e2e/test_watchdog_future_worker_execution.py` 已新增 late-result rejection 支线，固定 `rejected` 后不得再被 parent consume；
  5. recovery-supersede 与 late-result 两条 rejection 支线都已入测；
  6. e2e 现已固定 declarative request materialize -> worker start -> summary -> completed -> later-tick parent consume 的正式 golden path；
  7. same-trace replay、wrong-trace 排除、late-result rejection 与 consumed terminal read-side 现在都可从 ops/read-side 与 canonical event 链直接回看。

## Task 38.5 更新执行日志与 handoff 摘要

- **任务编号**：T385
- **状态**：已完成（2026-04-14）
- **目标**：同步 formal docs、执行日志与 `.ai-sdlc` 元数据，固定 038 的下一执行入口与治理口径。
- **文件**：
  - `specs/038-future-worker-canonical-execution-and-governance/task-execution-log.md`
  - `.ai-sdlc/work-items/038-future-worker-canonical-execution-and-governance/execution-plan.yaml`
  - `.ai-sdlc/work-items/038-future-worker-canonical-execution-and-governance/runtime.yaml`
  - `.ai-sdlc/work-items/038-future-worker-canonical-execution-and-governance/resume-pack.yaml`
  - `.ai-sdlc/work-items/038-future-worker-canonical-execution-and-governance/latest-summary.md`
- **可并行**：否
- **验收标准**：
  1. 执行日志已记录 red/green/review 闭环与 worker canonical contract 收口；
  2. `.ai-sdlc` 元数据能准确恢复到下一执行入口；
  3. handoff 明确 worker 结果何时才算真正生效，以及后续工作不得回退到隐式共享状态。
- **验证**：
  - `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`
  - 人工审阅执行日志与 `.ai-sdlc` 元数据一致
- **完成情况**：
  1. 已把 declarative worker request contract、same-trace consume 与 partial-materialization fail-closed 闭环写入执行日志；
  2. `.ai-sdlc` 元数据已更新到 `T385` 完成态，可直接恢复到 038 已收口的最新状态；
  3. handoff 已明确：future worker 结果只有在 parent canonical consume 后才算真正生效，后续工作不得回退到隐式共享状态或局部 worker 真相。

## 整体验收

- 038 只负责把 future worker / sub-agent 收敛为 canonical execution contract，不扩张成通用执行平台。
- 038 完成后，worker lifecycle、result consume/reject、stale/late/supersede/crash recovery 都必须进入 canonical truth。
- 038 完成后，worker 只消费 frozen refs，不能直接改 Goal Contract、approval、risk band 或 completion truth。
- 038 不得回退到隐式共享状态、worker 本地真相或人工口头治理。
