# Development Summary

Status: active
Total Tasks: 5
Completed Tasks: 1
Halted Tasks: 0
Total Batches: 5
Completed Batches: 1
Last Committed Task: T351

## Notes
- `WI-035` 仍在执行 `T354`，当前主线已经从“把 shared runtime contract + taxonomy 正式写入 runbook”推进到“把这组治理规则下沉到 generated release_gate_report + fixture contract”。
- 当前已经收口的主干有五层：
  - resident runtime 默认放行路径正式消费 `release_gate_report` artifact；
  - runtime gate 降级已进入现有 ops/read-side surface；
  - runtime gate alert 已经按稳定 taxonomy 分桶，而不是直接暴露原始 `degrade_reason`；
  - shared runtime contract 已有显式的 `Settings.build_runtime_contract(...)` surface；
  - runtime gate reason 现在也被归并到稳定 taxonomy。
- 本切片把这组约束继续下沉到 report/fixture generation contract：
  - `ReleaseGateReport` 现在必须携带 `runtime_contract_surface_ref`；
  - `ReleaseGateReport` 现在必须携带 `runtime_gate_reason_taxonomy`，并归档 passthrough reasons、validator reasons、`*_mismatch` 规则、`validator_degraded`、`contract_mismatch`、`unknown` 与 `raw_reason_labels_forbidden=true`；
  - `scripts/generate_release_gate_report.py` 会默认写入这组 metadata；
  - `tests/fixtures/release_gate_expected_report.json` 已改成由脚本重生成，避免 fixture 脱离脚本 contract。
- 对抗 review 指出我一开始只把 taxonomy 下沉了一半，仍会和 `ops` normalizer 分叉；这一点已经收口：
  - `src/watchdog/services/brain/release_gate.py` 现在拥有共享 taxonomy 常量和 `normalize_runtime_gate_reason(...)`；
  - `src/watchdog/api/ops.py` 已改为直接复用这份 shared classifier，不再维护第二套 reason bucket 定义。
  - fix 后两位对抗 reviewer 二次确认均已无 blocking/P1；测试 helper 里的重复 taxonomy literal 也已改成导入默认常量。
- 这一步之后，035 的剩余高优先级缺口继续收敛到两处：
  - 是否把这组 governance metadata 再上提到 evidence bundle 或显式 report validation helper，而不是只停在 report payload；
  - 是否让 release-gate/provider/replay 侧的后续流程文档明确引用 report-level governance contract，而不是只在单一 runbook 中定义。

## Latest Verification
- `uv run pytest -q tests/test_watchdog_release_gate.py tests/test_watchdog_release_gate_evidence.py tests/test_watchdog_ops.py -k 'runtime_governance_contract or runtime_invalidation_fields or fixtures_are_checked_in or normalizes_runtime_gate_reason_taxonomy or unknown_runtime_gate_reason'` -> `5 passed, 19 deselected in 1.14s`
- `uv run pytest -q tests/test_watchdog_release_gate.py tests/test_watchdog_release_gate_evidence.py tests/test_watchdog_session_spine_runtime.py -k 'runtime_governance_contract or runtime_invalidation_fields or fixtures_are_checked_in or configured_release_gate_report'` -> `5 passed, 43 deselected in 1.27s`
- `uv run pytest -q tests/test_watchdog_release_gate.py tests/test_watchdog_release_gate_evidence.py tests/test_watchdog_ops.py tests/test_watchdog_policy_engine.py tests/test_watchdog_session_spine_runtime.py tests/test_long_running_autonomy_doc_contracts.py` -> `70 passed in 5.38s`

## Next Slice
- 继续沿 `T354` 评估是否把 report-level governance metadata 上提到 evidence bundle / validation helper，并把相关流程文档收口成统一入口。
