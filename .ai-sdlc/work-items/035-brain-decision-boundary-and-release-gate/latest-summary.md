# Development Summary

Status: active
Total Tasks: 5
Completed Tasks: 1
Halted Tasks: 0
Total Batches: 5
Completed Batches: 1
Last Committed Task: T351

## Notes
- `WI-035` 仍在执行 `T354`，主目标没变：把 Brain/release-gate/replay/provider drift 的资格判断全部绑回 canonical runtime，而不是在不同模块里维护平行 contract。
- 上一切片已经把 resident runtime 默认放行路径接回正式 `release_gate_report` artifact；本切片继续收掉 provider certification / replay 仍在手写 runtime contract 的第二真相。
- `src/watchdog/services/brain/provider_certification.py` 现在新增共享 `build_runtime_contract(...)`：
  - provider/model/prompt/output 由调用方显式提供；
  - `risk_policy_version / decision_input_builder_version / policy_engine_version / tool_schema_hash / memory_provider_adapter_hash` 统一来自 `Settings`；
  - provider certification、replay 和 release-gate runtime 可以共用同一份 settings-driven contract。
- `src/watchdog/services/session_spine/orchestrator.py` 已改成通过同一 helper 构建 release-gate runtime contract，不再单独手拼版本字段。
- 本切片新增了两条 red-green：
  - provider certification 能直接从 `Settings` 构建完整 runtime contract；
  - replay 能直接消费这份 settings-driven contract，并在 frozen/current 一致时保持无 drift。
- 这一步之后，035 剩余的高优先级缺口继续收敛到两处：
  - 是否把共享 runtime contract 显式上提到更统一的 config/runtime surface，而不是只作为 helper 存在；
  - 是否把 `report_load_failed`、runtime drift 等降级原因继续暴露到 ops/read-side surface，而不是只留在 canonical decision evidence。

## Latest Verification
- `uv run pytest -q tests/test_watchdog_provider_certification.py tests/test_watchdog_decision_replay.py -k 'build_runtime_contract_reads_versions_from_settings or packet_replay_accepts_settings_built_runtime_contract'` -> `2 passed, 9 deselected in 0.17s`
- `uv run pytest -q tests/test_watchdog_provider_certification.py tests/test_watchdog_decision_replay.py tests/test_watchdog_release_gate.py tests/test_watchdog_release_gate_evidence.py tests/test_watchdog_session_spine_runtime.py` -> `57 passed in 3.93s`

## Next Slice
- 继续沿 `T354` 收口更高层 runtime/config surface，优先评估是否把共享 runtime contract 与 drift/degrade 原因暴露到 ops/read-side，而不是继续扩新的判断分支。
