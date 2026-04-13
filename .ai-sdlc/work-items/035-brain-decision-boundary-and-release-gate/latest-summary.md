# Development Summary

Status: active
Total Tasks: 5
Completed Tasks: 1
Halted Tasks: 0
Total Batches: 5
Completed Batches: 1
Last Committed Task: T351

## Notes
- `WI-035` 的主线仍是把 Brain decision boundary、validator、release gate、replay/provider drift 全部绑定回 canonical runtime，而不是引入第二套 truth。
- 当前切片已把 resident runtime 默认放行路径从 `report:resident_default` 收紧到“优先消费正式 `release_gate_report` artifact”：
  - `src/watchdog/settings.py` 新增 `release_gate_report_path` 与 runtime contract 版本字段；
  - `src/watchdog/services/session_spine/orchestrator.py` 现在会加载 formal `ReleaseGateReport`、透传 runtime contract，并把 `now` 传给 `ReleaseGateEvaluator` 做 expiry 校验；
  - 配置了 formal report 时，auto-continue 的 canonical decision evidence 会绑定正式 `report_id/report_hash/input_hash`；
  - report 过期、漂移或加载失败时会显式降级，`propose_execute` 不再静默回退到 resident default。
- 当前切片顺手补了一个额外 fail-closed：如果设置了 `release_gate_report_path` 但 artifact 读不出来或不合法，runtime 会写出 `report_load_failed` verdict，而不是忽略配置继续放行。
- `tests/test_watchdog_session_spine_runtime.py` 已新增两条 red-green：一条锁定 formal report 接线，一条锁定 expired report 的 `block_and_alert` 降级。
- 这一步之后，035 剩余的高优先级缺口更聚焦在两处：
  - 把 provider certification / replay 的 runtime contract 来源继续收紧，避免 drift matrix 只在单测里成立；
  - 评估 `report_load_failed`、runtime drift 等降级原因是否需要继续暴露到 ops/read model，而不是只停留在 canonical decision evidence。

## Latest Verification
- `uv run pytest -q tests/test_watchdog_session_spine_runtime.py -k 'uses_configured_release_gate_report_for_auto_execute or degrades_when_configured_release_gate_report_is_expired'` -> `2 passed, 33 deselected in 0.84s`
- `uv run pytest -q tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_policy_engine.py tests/test_watchdog_release_gate.py tests/test_watchdog_release_gate_evidence.py` -> `54 passed in 3.74s`

## Next Slice
- 继续沿 `T354` 收口 runtime contract 的第二真相问题，优先把 provider certification / replay 与 runtime settings 的来源对齐，再决定是否扩 ops/read-side surfacing。
