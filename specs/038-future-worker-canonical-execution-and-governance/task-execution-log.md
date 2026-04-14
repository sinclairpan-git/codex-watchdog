# 执行日志：038-future-worker-canonical-execution-and-governance

## 2026-04-14

### Phase 1：formal docs / spec freeze

- 基于 `WI-035` 和 `WI-037` 的 handoff，正式追加 `WI-038`。
- 把目标边界收紧为：
  - worker/sub-agent 只作为 canonical execution contract 实现，不扩张为通用 worker framework；
  - worker requested/start/heartbeat/summary/completed/failed/cancelled/consumed/rejected 都必须进入 `Session Service`；
  - worker 只能消费冻结的 `DecisionTrace`、packet refs、retrieval handles 与 distilled summary；
  - worker 不得直接修改 Goal Contract、approval、risk band、completion truth 或 release gate verdict；
  - stale/late/duplicate/supersede/crash recovery 都必须 fail closed 并进入 canonical truth。
- 已创建 `spec.md / plan.md / tasks.md / task-execution-log.md` 与 `.ai-sdlc/work-items/038-*` 基线。
- 本地验证：
  - `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py` -> `3 passed in 0.02s`
- 对抗复核：
  - Anthropic Manager 专家：无 blocking/P1；
  - Hermes Agent 专家：无 blocking/P1。
- `T381` 已满足 formal docs baseline 条件，下一执行入口切到 `T382`，开始 worker lifecycle / consume / reject 红测。

### Phase 2 / 3：worker lifecycle red -> green

- 已新增：
  - `tests/test_watchdog_future_worker_contract.py`
  - `tests/test_watchdog_future_worker_runtime.py`
  - `tests/e2e/test_watchdog_future_worker_execution.py`
- 首轮红测明确暴露三条实现缺口：
  - `src/watchdog/services/future_worker/` 模块不存在；
  - `Session Service` 不接受 `future_worker_*` canonical events；
  - `create_app()` 尚未接入 `app.state.future_worker_service`。
- 已完成最小 green 接线：
  - 新增 `src/watchdog/services/future_worker/models.py` 与 `service.py`，定义 `FutureWorkerExecutionRequest`、`FutureWorkerResultEnvelope` 与最小 lifecycle service；
  - `src/watchdog/services/session_service/models.py` 现已接受 `future_worker_requested|started|heartbeat|summary_published|completed|failed|cancelled|result_consumed|result_rejected`；
  - `src/watchdog/main.py` 现已接入 `app.state.future_worker_service`；
  - service 现已打通 request/start/heartbeat/summary/completed/failed/cancelled/consume/reject 到 `Session Service`。
- 本轮验证：
  - `uv run pytest -q tests/test_watchdog_future_worker_contract.py tests/test_watchdog_future_worker_runtime.py tests/e2e/test_watchdog_future_worker_execution.py` -> `6 passed in 0.86s`
  - `uv run pytest -q tests/test_watchdog_future_worker_contract.py tests/test_watchdog_future_worker_runtime.py tests/e2e/test_watchdog_future_worker_execution.py tests/test_watchdog_brain_decision_loop.py tests/test_watchdog_memory_packets.py tests/test_watchdog_release_gate_evidence.py tests/test_long_running_autonomy_doc_contracts.py` -> `23 passed in 0.79s`
  - `uv run pytest -q tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_feishu_control.py tests/test_watchdog_ops.py tests/test_watchdog_future_worker_contract.py tests/test_watchdog_future_worker_runtime.py tests/e2e/test_watchdog_future_worker_execution.py` -> `60 passed in 5.83s`
  - `uv run pytest -q tests/test_watchdog_future_worker_contract.py tests/test_watchdog_future_worker_runtime.py tests/e2e/test_watchdog_future_worker_execution.py tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_feishu_control.py tests/test_watchdog_ops.py tests/test_watchdog_brain_decision_loop.py tests/test_watchdog_memory_packets.py tests/test_watchdog_release_gate_evidence.py tests/test_long_running_autonomy_doc_contracts.py` -> `79 passed in 5.67s`
- 对抗复检：
  - Anthropic Manager 专家：无 blocking/P1；
  - Hermes Agent 专家：无 blocking/P1。
- 当前下一执行入口停在 `T383`，继续把 orchestrator/recovery/ops 级治理补齐，而不是停留在 service-level lifecycle。

### Phase 3 / 4：worker governance state machine + ops read-side

- 已补红测并转绿：
  - `failed/cancelled` 终态后不允许再 `completed`；
  - `ops/read-side` 必须暴露 future worker 层级与 `blocking_reason`；
  - metrics 必须导出 future worker 状态与阻断原因。
- 已完成实现：
  - `src/watchdog/services/future_worker/service.py`
    - 新增显式 transition gate；
    - 禁止 `failed/cancelled/rejected/consumed` 终态后的非法跃迁；
    - 强制 `consume/reject` 必须在 `completed` 之后发生。
  - `src/watchdog/api/ops.py`
    - `OpsSummary` 已新增 `future_workers`；
    - read-side 可区分 `requested/running/completed/failed/cancelled/rejected/consumed`；
    - read-side 可回看 `decision_trace_ref`、`last_event_type` 与 `blocking_reason`。
  - `src/watchdog/observability/metrics_export.py`
    - 已新增 future worker canonical status / blocked reason gauge。
- 本轮验证：
  - `uv run pytest -q tests/test_watchdog_future_worker_runtime.py tests/test_watchdog_ops.py` -> `22 passed in 0.93s`
  - `uv run pytest -q tests/test_watchdog_future_worker_contract.py tests/e2e/test_watchdog_future_worker_execution.py tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_recovery_execution.py` -> `46 passed in 3.10s`
  - `uv run pytest -q tests/test_watchdog_future_worker_contract.py tests/test_watchdog_future_worker_runtime.py tests/e2e/test_watchdog_future_worker_execution.py tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_recovery_execution.py tests/test_watchdog_ops.py tests/test_watchdog_brain_decision_loop.py tests/test_watchdog_memory_packets.py tests/test_watchdog_release_gate_evidence.py tests/test_long_running_autonomy_doc_contracts.py` -> `85 passed in 5.42s`
- 对抗复核：
  - 已两次发起 Hermes Agent 专家 / Anthropic Manager 专家子线程复核；
  - 两轮 `wait_agent` 均超时，未形成正式 blocking/P1 verdict；
  - 本 batch 仅能确认本地回归通过，正式专家复核需在下一批继续补做。
- 当前收口判断：
  - `T383` 仍未完成，因为 orchestrator/recovery 对 supersede / crash continuation 的正式接线还没落地；
  - `T384` 已进入进行中，ops/read-side 已落地，但 stale/late rejection 的 e2e 支线仍待补齐。

### Phase 3：recovery continuation supersede future workers

- 已补红测并转绿：
  - recovery continuation 发生时，parent session 上运行中的 future worker 必须进入 `future_worker_cancelled`；
  - recovery continuation 发生时，已完成但尚未被 parent consume 的 future worker result 必须进入 `future_worker_result_rejected`。
- 已完成实现：
  - `src/watchdog/services/session_spine/recovery.py`
    - recovery 记账后会扫描 parent session 的 future worker canonical events；
    - 对 `requested/running` worker 统一写 `future_worker_cancelled(reason=recovery_superseded_by_child_session)`；
    - 对 `completed` 但未 consume 的 worker 统一写 `future_worker_result_rejected(reason=recovery_superseded_by_child_session)`。
  - `tests/test_watchdog_recovery_execution.py`
    - 已固定 recovery supersede parent future workers 的正式红/绿链。
- 本轮验证：
  - `uv run pytest -q tests/test_watchdog_recovery_execution.py -k supersedes_parent_future_workers` -> `1 passed in 0.30s`
  - `uv run pytest -q tests/test_watchdog_recovery_execution.py tests/test_watchdog_future_worker_runtime.py tests/e2e/test_watchdog_future_worker_execution.py tests/test_watchdog_ops.py` -> `30 passed in 1.27s`
  - `uv run pytest -q tests/test_watchdog_future_worker_contract.py tests/test_watchdog_future_worker_runtime.py tests/e2e/test_watchdog_future_worker_execution.py tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_recovery_execution.py tests/test_watchdog_ops.py tests/test_watchdog_brain_decision_loop.py tests/test_watchdog_memory_packets.py tests/test_watchdog_release_gate_evidence.py tests/test_long_running_autonomy_doc_contracts.py` -> `86 passed in 4.19s`
- 当前收口判断：
  - `T383` 继续推进，但剩余缺口已收敛到 orchestrator 侧 create/consume 正式接线；
  - recovery 侧的 parent-worker supersede 治理已不再缺位。

### Phase 4：late-result rejection e2e branch

- 已新增 `tests/e2e/test_watchdog_future_worker_execution.py` 支线：
  - 固定 `requested -> started -> completed -> result_rejected(late_result)`；
  - 固定 `rejected` 后 parent `consume_result` 必须 fail closed。
- 本轮验证：
  - `uv run pytest -q tests/e2e/test_watchdog_future_worker_execution.py` -> `2 passed in 0.47s`
  - `uv run pytest -q tests/e2e/test_watchdog_future_worker_execution.py tests/test_watchdog_recovery_execution.py tests/test_watchdog_future_worker_runtime.py tests/test_watchdog_ops.py` -> `31 passed in 1.06s`
- 当前收口判断：
  - `T384` 的 late-result rejection 支线已进入正式 e2e；
  - 继续向前时，应优先把 orchestrator 侧 create/consume 接线补齐，再决定是否需要更长的 stale-result parent-decision 主链 e2e。

### Phase 3 / 4：orchestrator replay + consume 正式接线

- 已补红测并转绿：
  - parent terminal replay 必须把同 `decision_trace_ref` 的 `future_worker_*` 事件升为 `required_event_ids`；
  - wrong-trace worker 事件不得混入当前 decision replay；
  - parent command 成功后，同 trace 下已 `completed` 且未 `consumed/rejected` 的 worker result 必须由 orchestrator canonical consume。
- 已完成实现：
  - `src/watchdog/services/session_spine/orchestrator.py`
    - `_decision_relevant_session_events()` 现在只纳入 `decision_*`、`command_created` 与同 trace 的 `future_worker_*`；
    - `session_semantic_replay.required_event_ids` 现已覆盖同 trace worker truth，而不是只看 parent decision 三件套；
    - command 成功后、`command_executed` 落账前，会 canonical consume 同 trace 下处于 `completed` 的 worker result。
  - `src/watchdog/services/future_worker/service.py`
    - 非 `requested` 的 lifecycle / reject / consume / transition_rejected 事件现在都会继承冻结的 `decision_trace_ref`；
    - `result_rejected` 与 `transition_rejected` 不再静默掉出 parent replay / ops / audit。
  - `tests/test_watchdog_session_spine_runtime.py`
    - 已固定 same-trace worker truth 被 replay 读取；
    - 已固定 wrong-trace worker truth 被 replay 排除；
    - 已固定 command 成功后 `future_worker_result_consumed` 会按当前 `decision_id` 正式落账。
- 本轮验证：
  - `uv run pytest -q tests/test_watchdog_session_spine_runtime.py -k future_worker_events` -> `2 passed in 1.17s`
  - `uv run pytest -q tests/test_watchdog_session_spine_runtime.py -k consumes_completed_future_worker_results_for_same_trace` -> `1 passed in 1.25s`
  - `uv run pytest -q tests/test_watchdog_future_worker_runtime.py tests/e2e/test_watchdog_future_worker_execution.py` -> `11 passed in 2.20s`
  - `uv run pytest -q tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_future_worker_runtime.py tests/e2e/test_watchdog_future_worker_execution.py tests/test_watchdog_recovery_execution.py tests/test_watchdog_ops.py` -> `74 passed in 5.59s`
- 对抗复核：
  - Anthropic Manager 专家：无 blocking/P1；
  - Hermes Agent 专家：无 blocking/P1。
- 当前收口判断：
  - `T383` 现在只剩“parent 如何正式声明 / 请求 future worker contract”的 create-side 接线未完成；
  - `T384` 的 replay/read-side/consume 主链已进一步收紧，但完整 worker create -> run -> consume golden path 仍待补最后一段 declarative request contract。

### Phase 3 / 4 / 5：declarative request contract + full-chain handoff

- 已补红测并转绿：
  - orchestrator 必须从 decision evidence 物化 declarative `future_worker_requests`，写出 canonical `future_worker_requested`；
  - 同一 `decision_trace_ref` 下重复 tick 不得重复 request；
  - parent command 已 `executed` 的后续 tick，仍需 consume 同 trace 下后完成的 worker result；
  - declarative worker request batch 若存在后项 drift，不得留下前项已写入的 partial canonical truth。
- 已完成实现：
  - `src/watchdog/services/session_spine/orchestrator.py`
    - 新增 `FutureWorkerExecutionRequest` contract 消费；
    - `_record_command_created()` 对同一 `decision_id + command_id` 幂等跳过；
    - `_materialize_future_worker_requests()` 现已先做整批 request schema + drift 预校验，再统一写 `future_worker_requested`；
    - command 已 `executed` 的后续 tick 现在也会调用 same-trace completed worker consume 路径。
  - `tests/test_watchdog_session_spine_runtime.py`
    - 已固定 declarative worker request 只物化一次；
    - 已固定 request batch 中后项 drift 时不得留下前项 partial materialization。
  - `tests/e2e/test_watchdog_future_worker_execution.py`
    - 已固定 declarative request materialize -> started -> summary_published -> completed -> later-tick result_consumed 的正式主链。
- 本轮验证：
  - `uv run pytest -q tests/test_watchdog_session_spine_runtime.py -k 'materializes_future_worker_requests_once_per_decision_trace or rejects_partial_future_worker_request_materialization'` -> `2 passed, 40 deselected in 0.84s`
  - `uv run pytest -q tests/e2e/test_watchdog_future_worker_execution.py -k materializes_and_consumes_future_worker_chain` -> `1 passed, 2 deselected in 0.74s`
  - `uv run pytest -q tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_future_worker_runtime.py tests/e2e/test_watchdog_future_worker_execution.py tests/test_watchdog_recovery_execution.py tests/test_watchdog_ops.py` -> `77 passed in 6.22s`
- 对抗复核：
  - Hermes Agent 专家：先指出一个真实 P1，`future_worker_requests` 若边遍历边落账会导致后项 drift 时留下前项 partial materialization；
  - 修复后再次复核，Hermes Agent 专家：无 blocking/P1；
  - Anthropic Manager 专家：无 blocking/P1。
- 最终收口判断：
  - `T383` 已完成：worker canonical truth、runtime glue、recovery supersede、same-trace replay/consume 与 declarative request contract 已全部闭环；
  - `T384` 已完成：ops/read-side、late-result rejection 与 formal worker golden-path e2e 已全部收口；
  - 下一步只剩 `T385` 的 handoff / metadata 完成态同步。
