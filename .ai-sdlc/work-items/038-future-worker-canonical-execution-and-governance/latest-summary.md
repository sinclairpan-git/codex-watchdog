# Development Summary

Status: in_progress
Total Tasks: 5
Completed Tasks: 2
Halted Tasks: 0
Total Batches: 5
Completed Batches: 2
Last Committed Task: T382

## Notes
- `WI-038` 已从 `WI-035` / `WI-037` 的 handoff 正式追加，目标是把 future worker / sub-agent 从声明式预留 schema 收口成 canonical execution contract。
- 当前 formal docs 已冻结的关键边界：
  - worker requested/start/heartbeat/summary/completed/failed/cancelled/consumed/rejected 都必须进入 `Session Service`；
  - worker 只消费冻结的 `DecisionTrace`、packet refs、retrieval handles 与 distilled summary；
  - worker 不得直接修改 Goal Contract、approval、risk band、completion truth 或 release gate verdict；
  - stale/late/duplicate/supersede/crash recovery 都必须 fail closed 并进入 canonical truth。
- `T381` 已完成：
  - 已新增 `Task 9` 到总实施计划；
  - 已创建 `spec.md / plan.md / tasks.md / task-execution-log.md` 与 `.ai-sdlc/work-items/038-*` 基线。
  - Anthropic Manager 专家与 Hermes Agent 专家复核均无 blocking/P1。
- `T382` 已完成：
  - 新增 contract/runtime/e2e 三类红测；
  - 首轮红测暴露 `future_worker` 模块缺失、`Session Service` 无 `future_worker_*` event、`app.state.future_worker_service` 未接入；
  - 当前三份测试已转绿。
- `T383` 正在进行：
  - 已新增 `src/watchdog/services/future_worker/models.py` 与 `service.py`；
  - `Session Service` 已登记 `future_worker_*` canonical events；
  - `create_app()` 已接入 `app.state.future_worker_service`；
  - completion gate、frozen `decision_trace_ref` 回读与 worker runtime contract provenance 已补齐。

## Latest Verification
- `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py` -> `3 passed in 0.02s`
- `uv run pytest -q tests/test_watchdog_future_worker_contract.py tests/test_watchdog_future_worker_runtime.py tests/e2e/test_watchdog_future_worker_execution.py` -> `6 passed in 0.86s`
- `uv run pytest -q tests/test_watchdog_future_worker_contract.py tests/test_watchdog_future_worker_runtime.py tests/e2e/test_watchdog_future_worker_execution.py tests/test_watchdog_brain_decision_loop.py tests/test_watchdog_memory_packets.py tests/test_watchdog_release_gate_evidence.py tests/test_long_running_autonomy_doc_contracts.py` -> `23 passed in 0.79s`
- `uv run pytest -q tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_feishu_control.py tests/test_watchdog_ops.py tests/test_watchdog_future_worker_contract.py tests/test_watchdog_future_worker_runtime.py tests/e2e/test_watchdog_future_worker_execution.py` -> `60 passed in 5.83s`
- `uv run pytest -q tests/test_watchdog_future_worker_contract.py tests/test_watchdog_future_worker_runtime.py tests/e2e/test_watchdog_future_worker_execution.py tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_feishu_control.py tests/test_watchdog_ops.py tests/test_watchdog_brain_decision_loop.py tests/test_watchdog_memory_packets.py tests/test_watchdog_release_gate_evidence.py tests/test_long_running_autonomy_doc_contracts.py` -> `79 passed in 5.67s`

## Handoff
- 当前下一步是继续推进 `T383`，把 orchestrator/recovery/ops 级治理补齐，不停留在 service-level lifecycle。
- 后续工作不得回退到隐式共享状态、worker 本地真相或人工口头治理。
- Anthropic Manager 专家与 Hermes Agent 专家对当前 batch 复检均无 blocking/P1。
