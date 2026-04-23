# 执行日志：046-session-event-gate-payload-write-contract

## 2026-04-14

### Phase 1：formal docs / spec freeze

- 基于 `WI-045` 完成态，探索下一 canonical work item。
- 本地收敛出的三个候选方向：
  - 方案 A：session event gate payload write contract；
  - 方案 B：policy / orchestrator 参数命名对齐；
  - 方案 C：e2e / golden-path typed helper cleanup。
- 对抗复核结果：
  - Hermes Agent 专家：推荐方案 A；认为 B 只是整洁性修补，C 只是测试整理；
  - Anthropic Manager 专家：推荐方案 A；要求范围进一步收窄为 session event 中的 gate payload fragment，不新增 schema/policy/testing platform。
- 冻结后的 046 边界：
  - 只做 `decision_validated` 与 `_command_terminal_payload()` 的 gate payload fragment 写侧 contract；
  - 首批实现只覆盖 `src/watchdog/services/session_spine/orchestrator.py` 与必要的 shared helper；
  - 不新增 policy 规则、schema、manifest、archive metadata、parameter rename campaign、fixture platform 或 e2e 改造层。
- 已创建 `spec.md / plan.md / tasks.md / task-execution-log.md` 与 `.ai-sdlc/work-items/046-*` 基线。
- 当前下一执行入口固定为 `T462`：先写失败测试锁定 gate payload contract，再进入实现。

### Phase 2：red tests 锁定 session event gate payload seam

- 在 `tests/test_watchdog_session_spine_runtime.py` 新增 gate payload contract module surface 红测。
- 新增 `decision_validated` 必须走 shared helper 的红测。
- 新增 `_command_terminal_payload()` 必须走 shared helper 的红测。
- 新增边界断言：`decision_validated` 不得包含 `release_gate_evidence_bundle`，`_command_terminal_payload()` 不得包含 `validator_verdict`。
- 红测结果：
  - `uv run pytest -q tests/test_watchdog_session_spine_runtime.py -k 'session_event_gate_payload_contract_module_exports_surface or records_release_gate_and_validator_verdict_in_session_events or command_terminal_payload_uses_gate_payload_contract'` 初次执行失败 3 项，符合预期。

### Phase 3：实现 session event gate payload contract

- 新增 `src/watchdog/services/session_spine/event_gate_payload_contract.py`：
  - 提供 `build_session_event_gate_payload(...)`；
  - 只输出 `validator_verdict` / `release_gate_verdict` / `release_gate_evidence_bundle` gate fragment；
  - typed read contract 会过滤 malformed gate payload。
- 在 `src/watchdog/services/session_spine/orchestrator.py`：
  - `decision_validated` 与 `_command_terminal_payload()` 改为复用 shared helper；
  - 保持 `decision_trace`、`completion_judgment`、`replay_summary`、`metrics_summary` 仍在 orchestrator。
- 实现批次提交：
  - `109c380 feat: formalize session event gate payload contract`

### Phase 4：验证与对抗复核

- 验证结果：
  - `uv run pytest -q tests/test_watchdog_session_spine_runtime.py -k 'session_event_gate_payload_contract_module_exports_surface or records_release_gate_and_validator_verdict_in_session_events or command_terminal_payload_uses_gate_payload_contract'` -> `3 passed, 51 deselected in 0.87s`
  - `uv run pytest -q tests/test_watchdog_session_spine_runtime.py tests/test_long_running_autonomy_doc_contracts.py` -> `57 passed in 3.42s`
- 对抗复核结果：
  - Aristotle：无 blocking/P1，建议明确 helper 只做 gate fragment；
  - Pascal：无 blocking/P1，建议补边界断言与过滤 malformed gate payload 说明。

### Phase 5：closeout / handoff

- formal docs 基线提交：
  - `c13c8f1 docs: add wi-046 session event gate contract plan`
- `WI-046` 现已完成，session event gate payload 写侧收口到 shared contract。
- 后续 handoff 约束：
  - helper 只输出 gate fragment，不接管其他 event 字段；
  - `decision_validated` 只写 `validator_verdict + release_gate_verdict`，不得写 `release_gate_evidence_bundle`；
  - `_command_terminal_payload()` 只写 `release_gate_verdict + release_gate_evidence_bundle`，不得写 `validator_verdict`；
  - 参数命名与 e2e 整理属于后续 work item，不属于 046 当前范围。
