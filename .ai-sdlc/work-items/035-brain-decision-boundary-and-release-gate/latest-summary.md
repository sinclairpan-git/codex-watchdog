# Development Summary

Status: active
Total Tasks: 5
Completed Tasks: 1
Halted Tasks: 0
Total Batches: 5
Completed Batches: 1
Last Committed Task: T351

## Notes
- `WI-035` 仍在执行 `T354`，当前主线已经从“把 runtime gate 接到 canonical decision”推进到“把 gate 降级结果暴露到现有 ops/read-side surface”。
- 前两步已经完成：
  - resident runtime 默认放行路径正式消费 `release_gate_report` artifact；
  - provider certification / replay / release-gate runtime 已共用同一套 settings-driven runtime contract builder。
- 本切片继续把 `report_load_failed`、`report_expired`、validator/release-gate 降级从“只写在 decision evidence”推进到 ops/read-side：
  - `src/watchdog/api/ops.py` 新增 `runtime_gate_degraded` alert；
  - 该 alert 统一从 canonical decision 的 `matched_policy_rules` 读取 `runtime_gate_missing / release_gate_degraded / validator_gate_degraded`，不再额外解析 verdict payload；
  - `/healthz`、`/api/v1/watchdog/ops/alerts` 和 metrics 都会自动继承这条新 surface，因为它们复用同一份 `build_ops_summary(...)`。
- 这一步之后，035 的剩余高优先级缺口进一步收敛：
  - 是否把具体 `degrade_reason` 继续细分为更明确的 ops/read-side breakdown，而不是只有统一的 `runtime_gate_degraded`；
  - 是否把共享 runtime contract 再上提到更明确的 runtime/config surface，而不是停留在 helper 级别。

## Latest Verification
- `uv run pytest -q tests/test_watchdog_ops.py -k runtime_gate_degradation_alert` -> `1 passed, 7 deselected in 0.69s`
- `uv run pytest -q tests/test_watchdog_ops.py tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_policy_engine.py tests/test_watchdog_release_gate.py tests/test_watchdog_release_gate_evidence.py` -> `62 passed in 4.13s`

## Next Slice
- 继续沿 `T354` 收口 ops/read-side 的分辨率，优先评估是否把具体 `degrade_reason` 做成 breakdown，而不是继续扩新的 gate 控制流。
