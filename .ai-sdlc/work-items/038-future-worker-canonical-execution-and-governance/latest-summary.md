# Development Summary

Status: in_progress
Total Tasks: 5
Completed Tasks: 2
Halted Tasks: 0
Total Batches: 5
Completed Batches: 3
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
  - completion gate、frozen `decision_trace_ref` 回读与 worker runtime contract provenance 已补齐；
  - 当前 batch 已新增 future worker transition gate，禁止终态后的非法 `completed/consume`。
- `T384` 正在进行：
  - `build_ops_summary()` 已新增 `future_workers` 读侧视图，可区分 `requested/running/completed/failed/cancelled/rejected/consumed`；
  - `ops` 读侧已暴露 `worker_task_ref / decision_trace_ref / last_event_type / blocking_reason`；
  - `metrics_export.py` 已导出 future worker 状态与阻断原因 gauge；
  - stale/late rejection 的 e2e 支线仍待继续补齐。

## Latest Verification
- `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py` -> `3 passed in 0.02s`
- `uv run pytest -q tests/test_watchdog_future_worker_contract.py tests/test_watchdog_future_worker_runtime.py tests/e2e/test_watchdog_future_worker_execution.py` -> `6 passed in 0.86s`
- `uv run pytest -q tests/test_watchdog_future_worker_contract.py tests/test_watchdog_future_worker_runtime.py tests/e2e/test_watchdog_future_worker_execution.py tests/test_watchdog_brain_decision_loop.py tests/test_watchdog_memory_packets.py tests/test_watchdog_release_gate_evidence.py tests/test_long_running_autonomy_doc_contracts.py` -> `23 passed in 0.79s`
- `uv run pytest -q tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_feishu_control.py tests/test_watchdog_ops.py tests/test_watchdog_future_worker_contract.py tests/test_watchdog_future_worker_runtime.py tests/e2e/test_watchdog_future_worker_execution.py` -> `60 passed in 5.83s`
- `uv run pytest -q tests/test_watchdog_future_worker_contract.py tests/test_watchdog_future_worker_runtime.py tests/e2e/test_watchdog_future_worker_execution.py tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_feishu_control.py tests/test_watchdog_ops.py tests/test_watchdog_brain_decision_loop.py tests/test_watchdog_memory_packets.py tests/test_watchdog_release_gate_evidence.py tests/test_long_running_autonomy_doc_contracts.py` -> `79 passed in 5.67s`
- `uv run pytest -q tests/test_watchdog_future_worker_runtime.py tests/test_watchdog_ops.py` -> `22 passed in 0.93s`
- `uv run pytest -q tests/test_watchdog_future_worker_contract.py tests/e2e/test_watchdog_future_worker_execution.py tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_recovery_execution.py` -> `46 passed in 3.10s`
- `uv run pytest -q tests/test_watchdog_future_worker_contract.py tests/test_watchdog_future_worker_runtime.py tests/e2e/test_watchdog_future_worker_execution.py tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_recovery_execution.py tests/test_watchdog_ops.py tests/test_watchdog_brain_decision_loop.py tests/test_watchdog_memory_packets.py tests/test_watchdog_release_gate_evidence.py tests/test_long_running_autonomy_doc_contracts.py` -> `85 passed in 5.42s`

## Handoff
- 当前下一步是继续推进 `T383`，把 orchestrator/recovery 的 supersede / crash continuation 正式接线补齐。
- `T384` 的 ops/read-side 已落地，下一步补 stale/late rejection 的 e2e 支线后再整体收口。
- 后续工作不得回退到隐式共享状态、worker 本地真相或人工口头治理。
- Hermes Agent 专家 / Anthropic Manager 专家子线程本轮两次 wait 都超时，尚未形成正式 blocking/P1 verdict；当前只能依据本地回归继续推进。
