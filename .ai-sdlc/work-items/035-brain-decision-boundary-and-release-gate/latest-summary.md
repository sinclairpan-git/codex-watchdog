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
- 第三轮实现已开始替换 legacy action-first 入口：done session 不再直接被 `_select_action_ref()` 短路为 no-op，而是经由 `BrainDecisionService.evaluate_session(...)` 归纳成 `candidate_closure`，再落成 `post_operator_guidance -> require_user_decision` 的 canonical decision/approval。
- 同一切片已继续补强到 legacy auto-continue/recovery 热路径：`evaluate_persisted_session_policy(...)` 现在显式接收 `brain_intent`，使 `decision_proposed / decision_validated` 对 `continue_session` 也能落出 `brain_intent=propose_execute`，不再只在 candidate_closure 分支有 Brain 痕迹。
- 最新一轮对抗式代码评审后，Brain wiring 已按 reviewer 的 P1 重新收口：Brain intent 直接从 persisted facts 归纳，不再从 legacy `_select_action_ref()` 反推；orchestrator 也不再用 action-first 结果决定是否执行，`observe_only` 会真正阻断 auto-continue，`candidate_closure`/`require_approval` 则统一回到 policy engine 生成 `require_user_decision`。
- decision projection 也已改成“Session decision events 成功后再写 `PolicyDecisionStore`”，避免 canonical event 写失败时残留 orphan decision。
- 第二轮复审后又继续收掉了剩余 gate/identity 问题：`decision_key` 现在区分 `brain_intent`，candidate-closure approval identity 现在包含 `fact_snapshot_version` 与 `brain_intent`，而 orchestrator 只有在 `brain_intent=propose_execute` 且 validator/release-gate verdict 都是 `pass` 时才会真正进入 auto-execute。
- 最新增量切片又补齐了剩余 Brain intent 的 runtime consume：`require_approval`、`propose_recovery`、`suggest_only` 现在都能落成显式 canonical decision/result，其中 `suggest_only` 会走 `block_and_alert` notification，而不是被 runtime 静默吞掉。
- 该切片的复审问题也已收口：auto-continue cooldown 现在只压 `propose_execute`，不会再把复用 `continue_session` 作为推荐 action 的 `require_approval / suggest_only` 静默吞掉。
- `observe_only` 也已从静默 no-op 收紧成显式 runtime consume：有 facts 时会落 `brain_observe_only -> block_and_alert` notification，没有 facts 时仍保持 no-op，避免 phantom session 被平白写出 decision。
- 最新切片已开始把 validator/release-gate trace 绑定落到真实 runtime：
  - `DecisionValidator` 不再只是 pass-through，`ReleaseGateEvaluator` 也不再要求测试手工伪造 verdict；orchestrator 会先生成 `decision_trace / validator_verdict / release_gate_verdict`，再交给 policy；
  - `policy.engine` 现在会对 `brain_intent=propose_execute` 执行 fail-closed：缺 runtime gate evidence 或 verdict 非 `pass` 时，不能再继续 `auto_execute_and_notify`；
  - `decision_validated` canonical event 现在会携带完整 `decision_trace`，默认 auto-continue 也会带上 `report_id / report_hash / input_hash / decision_trace_ref / approval_read_ref`；
  - 旧的 ungated decision projection 现在会在 runtime tick 上被升级成带 gate evidence 的当前 decision，避免 legacy projection 长期绕开新 gate。
- 最新切片又补齐了 release-gate 的正式 artifact 骨架：
  - 已新增 `scripts/generate_release_gate_report.py`、`docs/operations/release-gate-runbook.md` 和 `tests/fixtures/release_gate_*`，把 deterministic `release_gate_report`、冻结窗口、`label_manifest`、`generated_by`、`report_approved_by` 与 `artifact_ref` 先固化进 repo；
  - `ReleaseGateEvaluator` 现在在显式提供 `ReleaseGateReport` 时会校验报告过期、输入哈希漂移以及 provider/schema/runtime contract 漂移，不再只是无条件回显 verdict；
  - 当前还没把正式 artifact report 接回 resident runtime 默认放行路径，`replay.py` 和 `provider_certification.py` 也还没有从 schema 骨架推进到可验证逻辑。
- 最新验证结果：
  - `uv run pytest -q tests/test_watchdog_brain_decision_loop.py tests/test_watchdog_provider_certification.py tests/test_watchdog_decision_replay.py tests/test_watchdog_release_gate.py tests/test_watchdog_release_gate_evidence.py` -> `12 passed in 0.16s`
  - `uv run pytest -q tests/test_watchdog_policy_decisions.py tests/test_watchdog_brain_decision_loop.py tests/test_watchdog_provider_certification.py tests/test_watchdog_decision_replay.py tests/test_watchdog_release_gate.py tests/test_watchdog_release_gate_evidence.py` -> `17 passed in 0.15s`
  - `uv run pytest -q tests/test_watchdog_session_spine_runtime.py -k 'records_release_gate_and_validator_verdict or fails_closed_when_decision_event_write_fails'` -> `2 passed, 24 deselected in 0.71s`
  - `uv run pytest -q tests/test_watchdog_approval_loop.py -k 'freshness or reuses_same_record or refreshes_pending_record'` -> `4 passed, 15 deselected in 0.81s`
  - `uv run pytest -q tests/test_watchdog_approval_loop.py tests/test_watchdog_policy_decisions.py tests/test_watchdog_brain_decision_loop.py tests/test_watchdog_provider_certification.py tests/test_watchdog_decision_replay.py tests/test_watchdog_release_gate.py tests/test_watchdog_release_gate_evidence.py tests/test_watchdog_session_spine_runtime.py -k 'freshness or reuses_same_record or refreshes_pending_record or brain or release_gate or decision or fails_closed_when_decision_event_write_fails or records_release_gate_and_validator_verdict or carries_brain_intent or brain_intent_adapter'` -> `25 passed, 37 deselected in 0.95s`
  - `uv run pytest -q tests/test_watchdog_session_spine_runtime.py -k candidate_closure_review` -> `1 passed, 25 deselected in 0.90s`
  - `uv run pytest -q tests/test_watchdog_brain_decision_loop.py tests/test_watchdog_policy_decisions.py tests/test_watchdog_session_spine_runtime.py` -> `34 passed in 2.56s`
  - `uv run pytest -q tests/test_watchdog_approval_loop.py tests/test_watchdog_policy_decisions.py tests/test_watchdog_brain_decision_loop.py tests/test_watchdog_provider_certification.py tests/test_watchdog_decision_replay.py tests/test_watchdog_release_gate.py tests/test_watchdog_release_gate_evidence.py tests/test_watchdog_session_spine_runtime.py` -> `62 passed in 2.81s`
  - `uv run pytest -q tests/test_watchdog_session_spine_runtime.py -k 'records_command_lease_for_auto_continue or candidate_closure_review'` -> `2 passed, 24 deselected in 0.74s`
  - `uv run pytest -q tests/test_watchdog_session_spine_runtime.py -k 'does_not_execute_when_brain_observes_only or fails_closed_when_decision_event_write_fails or candidate_closure_review or records_command_lease_for_auto_continue'` -> `4 passed, 23 deselected in 0.72s`
  - `uv run pytest -q tests/test_watchdog_policy_decisions.py tests/test_watchdog_policy_engine.py tests/test_watchdog_approval_loop.py tests/test_watchdog_session_spine_runtime.py -k 'brain_intent or candidate_closure_override or require_approval_override or resolved_candidate_closure_record or release_gate_or_validator_do_not_pass or stable_for_same_snapshot'` -> `8 passed, 53 deselected in 0.98s`
  - `uv run pytest -q tests/test_watchdog_approval_loop.py tests/test_watchdog_policy_decisions.py tests/test_watchdog_policy_engine.py tests/test_watchdog_brain_decision_loop.py tests/test_watchdog_provider_certification.py tests/test_watchdog_decision_replay.py tests/test_watchdog_release_gate.py tests/test_watchdog_release_gate_evidence.py tests/test_watchdog_session_spine_runtime.py` -> `73 passed in 4.25s`
  - `uv run pytest -q tests/test_watchdog_session_spine_runtime.py -k 'brain_require_approval or brain_propose_recovery or brain_suggest_only'` -> `3 passed, 28 deselected in 2.09s`
  - `uv run pytest -q tests/test_watchdog_policy_engine.py tests/test_watchdog_session_spine_runtime.py` -> `38 passed in 3.60s`
  - `uv run pytest -q tests/test_watchdog_session_spine_runtime.py -k 'cooldown_only_suppresses_propose_execute or brain_require_approval or brain_propose_recovery or brain_suggest_only'` -> `4 passed, 28 deselected in 1.19s`
  - `uv run pytest -q tests/test_watchdog_session_spine_runtime.py -k 'skips_phantom_approval_when_only_pending_flag_is_set or does_not_execute_when_brain_observes_only or cooldown_only_suppresses_propose_execute or brain_require_approval or brain_propose_recovery or brain_suggest_only'` -> `6 passed, 26 deselected in 0.63s`
  - `uv run pytest -q tests/test_watchdog_policy_engine.py tests/test_watchdog_session_spine_runtime.py` -> `39 passed in 2.49s`
  - `uv run pytest -q tests/test_watchdog_policy_engine.py -k 'fails_closed_when_propose_execute_lacks_runtime_gate_evidence or allows_auto_execution_when_goal_contract_is_ready'` -> `2 passed, 6 deselected in 0.23s`
  - `uv run pytest -q tests/test_watchdog_session_spine_runtime.py -k 'records_command_lease_for_auto_continue or fails_closed_when_auto_execute_decision_lacks_gate_evidence'` -> `2 passed, 31 deselected in 1.01s`
  - `uv run pytest -q tests/test_watchdog_policy_engine.py tests/test_watchdog_session_spine_runtime.py` -> `41 passed in 3.55s`
  - `uv run pytest -q tests/test_watchdog_approval_loop.py tests/test_watchdog_policy_decisions.py tests/test_watchdog_brain_decision_loop.py tests/test_watchdog_provider_certification.py tests/test_watchdog_decision_replay.py tests/test_watchdog_release_gate.py tests/test_watchdog_release_gate_evidence.py` -> `38 passed in 1.09s`
  - `uv run pytest -q tests/test_watchdog_release_gate.py -k generate_release_gate_report_script_produces_expected_fixture` -> `1 passed, 3 deselected in 0.16s`
  - `uv run pytest -q tests/test_watchdog_release_gate_evidence.py -k 'fixtures_are_checked_in or runbook_documents_scripted_artifacts_and_manual_splicing_ban'` -> `2 passed, 2 deselected in 0.02s`
  - `uv run pytest -q tests/test_watchdog_release_gate.py -k 'accepts_current_matching_report or degrades_expired_report or degrades_on_input_hash_drift'` -> `3 passed, 4 deselected in 0.24s`
  - `uv run pytest -q tests/test_watchdog_release_gate.py tests/test_watchdog_release_gate_evidence.py tests/test_long_running_autonomy_doc_contracts.py` -> `14 passed in 0.28s`
  - `uv run pytest -q tests/test_watchdog_policy_engine.py tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_approval_loop.py tests/test_watchdog_policy_decisions.py tests/test_watchdog_brain_decision_loop.py tests/test_watchdog_provider_certification.py tests/test_watchdog_decision_replay.py` -> `74 passed in 3.76s`
- 下一执行入口已收敛到两块：一是把正式 `release_gate_report` artifact 接回 runtime 默认路径，二是把 `replay.py / provider_certification.py` 从 schema 骨架推进到真正的 drift/incomplete 校验逻辑。
