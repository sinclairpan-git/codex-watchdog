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
