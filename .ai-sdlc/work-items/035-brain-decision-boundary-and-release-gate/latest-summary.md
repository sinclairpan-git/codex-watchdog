# Development Summary

Status: active
Total Tasks: 5
Completed Tasks: 1
Halted Tasks: 0
Total Batches: 5
Completed Batches: 1
Last Committed Task: T351

## Notes
- `WI-035` 已从总实施计划的 `Task 6` 正式拆出，当前 formal docs、任务分解、执行日志与 `.ai-sdlc` 元数据已经落地。
- 当前实现断点来自仓库现状：`src/watchdog/services/policy/engine.py` 仍直接从 persisted facts 生成 `CanonicalDecisionRecord`，`src/watchdog/services/session_spine/orchestrator.py` 仍直接消费 `decision_result` 进入 approval / auto execute。
- `SessionService.get_events(...)`、recovery truth 与 memory anomaly writer 已可作为 `DecisionTrace` 的 canonical anchor；`MemoryHubService.packet_inputs()` 已提供 bounded `refs / quality / worker_scope` contract，035 只消费这些 contract。
- 035 的执行目标已收紧为 `DecisionIntent + DecisionTrace + provider certification + replay + runtime-enforced release gate`，不把 `Brain` 做成新的 prompt/runtime 中枢。
- 对抗式文档评审后，已额外冻结 4 条关键边界：`brain_intent -> runtime disposition` adapter、替换旧 action-first 入口、`action approval` 与 `report_approved_by` 分离、以及 release gate verdict/degrade 必须先写 canonical Session decision event。
- `T352/T353` 第一轮已启动：`src/watchdog/services/brain/` 最小 contract 骨架与 `policy/decisions.py` 中的 `brain_intent -> runtime disposition` adapter 已落地。
- 第二轮实现已补到 runtime/event 与 approval contract：`orchestrator.py` 已把 `brain_intent`、`validator_verdict`、`release_gate_verdict` 写入 canonical Session decision events；`CanonicalApprovalRecord` 已补入 `goal_contract_version` 与 `expires_at`，并新增 freshness helper。
- 最新验证结果：
  - `uv run pytest -q tests/test_watchdog_brain_decision_loop.py tests/test_watchdog_provider_certification.py tests/test_watchdog_decision_replay.py tests/test_watchdog_release_gate.py tests/test_watchdog_release_gate_evidence.py` -> `12 passed in 0.16s`
  - `uv run pytest -q tests/test_watchdog_policy_decisions.py tests/test_watchdog_brain_decision_loop.py tests/test_watchdog_provider_certification.py tests/test_watchdog_decision_replay.py tests/test_watchdog_release_gate.py tests/test_watchdog_release_gate_evidence.py` -> `17 passed in 0.15s`
  - `uv run pytest -q tests/test_watchdog_session_spine_runtime.py -k 'records_release_gate_and_validator_verdict or fails_closed_when_decision_event_write_fails'` -> `2 passed, 24 deselected in 0.71s`
  - `uv run pytest -q tests/test_watchdog_approval_loop.py -k 'freshness or reuses_same_record or refreshes_pending_record'` -> `4 passed, 15 deselected in 0.81s`
  - `uv run pytest -q tests/test_watchdog_approval_loop.py tests/test_watchdog_policy_decisions.py tests/test_watchdog_brain_decision_loop.py tests/test_watchdog_provider_certification.py tests/test_watchdog_decision_replay.py tests/test_watchdog_release_gate.py tests/test_watchdog_release_gate_evidence.py tests/test_watchdog_session_spine_runtime.py -k 'freshness or reuses_same_record or refreshes_pending_record or brain or release_gate or decision or fails_closed_when_decision_event_write_fails or records_release_gate_and_validator_verdict or carries_brain_intent or brain_intent_adapter'` -> `25 passed, 37 deselected in 0.95s`
- 下一执行入口已收敛到替换旧 action-first 入口：继续让 Brain 先于 `_select_action_ref()` 决策，而不是被 runtime 预选动作短路。
