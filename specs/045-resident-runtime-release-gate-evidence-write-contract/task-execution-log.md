# 执行日志：045-resident-runtime-release-gate-evidence-write-contract

## 2026-04-14

### Phase 1：formal docs / spec freeze

- 基于 `WI-044` 完成态，探索下一 canonical work item。
- 本地收敛出的三个候选方向：
  - 方案 A：resident runtime release-gate evidence write-side contract；
  - 方案 B：policy engine / orchestrator evidence 参数命名收口；
  - 方案 C：e2e / golden-path typed helper cleanup。
- 对抗复核结果：
  - Hermes Agent 专家：推荐方案 A；认为 B 只是整洁性修补，C 只是测试整理；
  - Anthropic Manager 专家：推荐方案 A；要求范围进一步收窄为 resident runtime 的 release-gate evidence write-side seam，不新增 schema/policy/persistence/testing platform。
- 冻结后的 045 边界：
  - 只做 resident runtime 的 `release_gate_verdict + release_gate_evidence_bundle` 写侧组装 contract；
  - 首批实现只覆盖 `src/watchdog/services/session_spine/orchestrator.py` 与必要的 shared write helper；
  - 不新增 policy 规则、schema、manifest、archive metadata、parameter rename campaign、fixture platform 或 e2e 改造层。
- 已创建 `spec.md / plan.md / tasks.md / task-execution-log.md` 与 `.ai-sdlc/work-items/045-*` 基线。
- freeze 复核结果：
  - Hermes Agent 专家：无 blocking/P1，并要求 helper 只收口 `release_gate_verdict + release_gate_evidence_bundle` 两字段；
  - Anthropic Manager 专家：无 blocking/P1，并要求 helper 不得顺手接管 `decision_trace`、`validator_verdict` 或其他 intent evidence。
- 当前下一执行入口固定为 `T452`：先写失败测试锁定 write-side contract，再进入实现。

### Phase 2：red tests 锁定 release-gate write seam

- 在 `tests/test_watchdog_session_spine_runtime.py` 新增 shared write contract module surface 红测，锁定 resident runtime 必须依赖 shared write-side helper。
- 新增正式 report auto-execute path 必须经过 shared helper 的红测。
- 新增 `report_load_failed` fallback path 必须经过同一 shared helper 的红测。
- 红测结果：
  - `uv run pytest -q tests/test_watchdog_session_spine_runtime.py -k 'release_gate_write_contract_runtime_module_exports_typed_surface or uses_configured_release_gate_report_for_auto_execute or uses_release_gate_write_contract_for_report_load_failed_fallback'` 初次执行失败 3 项，确认当前实现仍存在 orchestrator 内联写侧组装 seam，符合预期。

### Phase 3：实现 resident runtime release-gate write-side contract

- 新增 `src/watchdog/services/brain/release_gate_write_contract.py`：
  - 提供 `ReleaseGateRuntimeEvidenceWriteBundle / build_release_gate_runtime_evidence(...)`；
  - 只负责 `release_gate_verdict + release_gate_evidence_bundle` 两字段；
  - 正式 report path 直接复用 `LoadedReleaseGateArtifacts.evidence_bundle`；
  - fallback path 统一组装当前既有的 minimal `ReleaseGateEvidenceBundle` surface。
- 在 `src/watchdog/services/session_spine/orchestrator.py`：
  - `_decision_evidence_for_intent()` 改为只通过 shared write-side helper 写入 release-gate evidence；
  - 删除 orchestrator 内联 `ReleaseGateEvidenceBundle(...)` 拼装与相关无用 import。
- 在 `tests/test_watchdog_session_spine_runtime.py`：
  - 补充 direct helper 单测，锁定正式 report path 保留 loaded artifact bundle，fallback path 不接管其他 intent evidence 字段。
- 实现批次提交：
  - `8070841 feat: formalize release gate write-side contract`

### Phase 4：验证与对抗复核

- 验证结果：
  - `uv run pytest -q tests/test_watchdog_session_spine_runtime.py -k 'release_gate_write_contract_runtime_module_exports_typed_surface or uses_configured_release_gate_report_for_auto_execute or uses_release_gate_write_contract_for_report_load_failed_fallback'` -> `3 passed, 47 deselected in 0.75s`
  - `uv run pytest -q tests/test_watchdog_session_spine_runtime.py -k 'release_gate_write_contract_' tests/test_long_running_autonomy_doc_contracts.py` -> `4 passed, 51 deselected in 1.34s`
  - `uv run pytest -q tests/test_watchdog_session_spine_runtime.py tests/test_long_running_autonomy_doc_contracts.py` -> `55 passed in 4.46s`
- 对抗复核结果：
  - Hermes Agent 专家：无 blocking/P1，并建议保留 direct helper 单测；
  - Anthropic Manager 专家：无 blocking/P1，并要求 helper 继续只覆盖 `release_gate_verdict + release_gate_evidence_bundle`。

### Phase 5：closeout / handoff

- formal docs 基线提交：
  - `19fa3ff docs: add wi-045 write-side contract plan`
- `WI-045` 现已完成，正式把 resident runtime 的 release-gate evidence 写侧组装收口到 shared contract。
- 后续 handoff 约束：
  - 后续任何 resident runtime producer 都不得再复制 `ReleaseGateEvidenceBundle(...)` 拼装逻辑；
  - 如需组装 runtime decision evidence 中的 `release_gate_verdict + release_gate_evidence_bundle`，必须复用 `src/watchdog/services/brain/release_gate_write_contract.py`；
  - helper 不得顺手接管 `decision_trace`、`validator_verdict` 或其他 intent evidence；
  - 参数命名与 e2e 整理属于后续 work item，不属于 045 当前范围。
