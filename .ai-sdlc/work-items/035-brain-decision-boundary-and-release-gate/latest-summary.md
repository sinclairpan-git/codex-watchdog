# Development Summary

Status: active
Total Tasks: 5
Completed Tasks: 1
Halted Tasks: 0
Total Batches: 5
Completed Batches: 1
Last Committed Task: T351

## Notes
- `WI-035` 仍在执行 `T354`，当前主线已经从“让 runtime gate 可观测”推进到“让 ops/read-side 直接看到具体 degrade reason”。
- 目前已经完成的主干收口有三层：
  - resident runtime 默认放行路径正式消费 `release_gate_report` artifact；
  - provider certification / replay / release-gate runtime 已共用同一套 settings-driven runtime contract builder；
  - runtime gate 降级现在已进入现有 ops/read-side surface，而不只停在 canonical decision evidence。
- 本切片把 ops 告警从总桶进一步拆成具体 reason：
  - `src/watchdog/api/ops.py` 现在按 canonical decision 的 `uncertainty_reasons` 分桶 runtime gate 降级；
  - 同时继续用 `matched_policy_rules` 作为 runtime gate 告警准入条件，避免从 verdict payload 再造一套旁路逻辑；
  - 最终会直接暴露出 `runtime_gate_report_load_failed`、`runtime_gate_report_expired`、`runtime_gate_approval_stale` 这类 alert code，healthz/ops/metrics 自动继承。
- 这一步之后，035 的剩余高优先级缺口进一步收敛到两处：
  - 是否把共享 runtime contract 再上提到更明确的 runtime/config surface，而不是停在 helper 级别；
  - 是否给 runtime gate reason 建一个更稳定的 taxonomy，避免后续 reason 命名漂移直接映射到 ops label。

## Latest Verification
- `uv run pytest -q tests/test_watchdog_ops.py -k 'runtime_gate_degradation_alert or breaks_runtime_gate_alerts_down_by_degrade_reason'` -> `2 passed, 7 deselected in 0.66s`
- `uv run pytest -q tests/test_watchdog_ops.py tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_policy_engine.py tests/test_watchdog_release_gate.py tests/test_watchdog_release_gate_evidence.py` -> `63 passed in 3.92s`

## Next Slice
- 继续沿 `T354` 收口 shared runtime contract 的 runtime/config surface，优先避免 contract builder 继续停留在 helper 级别。
