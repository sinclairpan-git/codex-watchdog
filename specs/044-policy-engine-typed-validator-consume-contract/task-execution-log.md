# 执行日志：044-policy-engine-typed-validator-consume-contract

## 2026-04-14

### Phase 1：formal docs / spec freeze

- 基于 `WI-043` 完成态，探索下一 canonical work item。
- 本地收敛出的三个候选方向：
  - 方案 A：typed validator consume contract for policy engine + resident runtime；
  - 方案 B：resident runtime release-gate evidence write-side contract；
  - 方案 C：e2e / golden-path raw evidence assertion cleanup。
- 对抗复核结果：
  - Hermes Agent 专家：推荐方案 A；认为 B 不是下一主要生产 seam，C 有 P1 级 scope drift 风险；
  - Anthropic Manager 专家：推荐方案 A；要求范围进一步收窄为 `policy engine + resident runtime` 的 validator consume seam，不新增 policy/schema/persistence/testing platform。
- 冻结后的 044 边界：
  - 只做 `policy engine` 与 resident runtime 对 validator evidence 的 typed consume contract；
  - 首批实现只覆盖 `src/watchdog/services/policy/engine.py`、`src/watchdog/services/session_spine/orchestrator.py` 与必要的 shared helper；
  - 不新增 policy 规则、schema、manifest、archive metadata、release-gate write helper、fixture platform 或 e2e 改造层。
- 已创建 `spec.md / plan.md / tasks.md / task-execution-log.md` 与 `.ai-sdlc/work-items/044-*` 基线。
- freeze 复核结果：
  - Hermes Agent 专家：无 blocking/P1，并要求 resident runtime 范围只覆盖 auto-execute/runtime-gate 判断链；
  - Anthropic Manager 专家：无 blocking/P1，并要求 shared helper 只做 typed read contract，不再新增第二层 helper。
- 当前下一执行入口固定为 `T442`：先写失败测试锁定 typed validator consume contract，再进入实现。

### Phase 2：red tests 锁定 validator consume seam

- 在 `tests/test_watchdog_policy_engine.py` 新增 shared validator read contract module surface 红测，锁定 `policy engine` 必须依赖 shared typed validator contract。
- 新增 malformed `validator_verdict` pass payload 时必须 fail closed 的红测，禁止 `"status": "pass"` 继续通过 raw dict 漏过。
- 在 `tests/test_watchdog_session_spine_runtime.py` 新增 resident runtime validator read contract surface 红测与 malformed pass validator payload fail-closed 红测。
- 红测结果：
  - `uv run pytest -q tests/test_watchdog_policy_engine.py tests/test_watchdog_session_spine_runtime.py` 初次执行失败，确认当前实现仍有 raw validator dict consume seam，符合预期。

### Phase 3：实现 typed validator consume contract

- 新增 `src/watchdog/services/brain/validator_read_contract.py`：
  - 提供 `ValidatorDecisionReadSnapshot / read_validator_decision_evidence(...)`；
  - 支持 decision evidence 中的 nested `validator_verdict` 与 legacy raw verdict dict；
  - 对 malformed legacy raw payload 继续保留 `has_verdict_payload`，确保 consumer 走 fail-closed 而不是误判成 missing。
- 在 `src/watchdog/services/policy/engine.py` 完成 consume seam 收口：
  - `evaluate_persisted_session_policy(...)` 与 `_runtime_gate_override(...)` 改为通过 typed validator contract 解释 validator gate；
  - `_goal_contract_evidence(...)` 改为只写回 canonicalized validator verdict；
  - 删除 raw dict `_verdict_is_pass/_verdict_reason` 解释路径。
- 在 `src/watchdog/services/session_spine/orchestrator.py`：
  - `_decision_allows_auto_execute` / `_decision_has_runtime_gate` 改为复用 typed validator contract；
  - resident runtime 调用 `evaluate_persisted_session_policy(...)` 时改为传入完整 `intent_evidence`，避免上游继续手工剥取 raw validator dict。
- 实现批次提交：
  - `9451d3e feat: formalize policy engine validator contract`

### Phase 4：验证与对抗复核

- 验证结果：
  - `uv run pytest -q tests/test_watchdog_policy_engine.py -k 'validator_read_contract_module_exports_policy_surface or validator_pass_payload_is_malformed or allows_auto_execution_when_goal_contract_is_ready' tests/test_watchdog_session_spine_runtime.py -k 'validator_read_contract_runtime_module_exports_typed_surface or rejects_malformed_pass_validator_verdict or rejects_incomplete_pass_release_gate_verdict or rejects_pass_verdict_without_bundle or rejects_pass_verdict_with_partial_bundle'` -> `5 passed, 56 deselected in 0.49s`
  - `uv run pytest -q tests/test_watchdog_policy_engine.py tests/test_watchdog_session_spine_runtime.py tests/test_long_running_autonomy_doc_contracts.py` -> `64 passed in 4.87s`
- 对抗复核结果：
  - Hermes Agent 专家：无 blocking/P1，并建议后续把 `validator_verdict` 参数名改成更贴近完整 evidence 的命名；
  - Anthropic Manager 专家：无 blocking/P1，并要求在 handoff 中明确 legacy raw dict 兼容只是过渡路径。

### Phase 5：closeout / handoff

- formal docs 基线提交：
  - `a1df030 docs: add wi-044 validator contract plan`
- `WI-044` 现已完成，正式把 `policy engine` 与 resident runtime 中的 validator consume seam 收口到 shared typed contract。
- 后续 handoff 约束：
  - 后续任何 validator consumer 都不得再复制 raw validator dict 解释逻辑；
  - 如需解释 `validator_verdict`，必须复用 `src/watchdog/services/brain/validator_read_contract.py`；
  - legacy raw dict 兼容路径仅用于过渡，不应再被新的 consumer 当作正式 contract 输入扩散；
  - 参数命名与 write-side 整理属于后续 work item，不属于 044 当前范围。
