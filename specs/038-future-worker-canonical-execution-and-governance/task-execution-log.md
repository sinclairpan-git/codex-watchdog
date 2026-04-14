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
