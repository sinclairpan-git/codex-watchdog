# 执行日志：051-high-coupling-test-hardening

## 2026-04-16

### Phase 1：scope freeze / formal docs bootstrap

- 基于 `WI-050` handoff、`BL-2026-04-06-001` 与 owner 约束，已把 051 正式边界收敛为：
  - approval / callback / restart / session spine 的高耦合场景矩阵；
  - fake / stub 与真实 `AClient` 的 contract hardening；
  - `targeted / seam-smoke / full` 三层验证入口固定。
- 已明确 051 不承接 release blocker、不改 runtime semantics、不改 Feishu / OpenClaw 入口语义，也不引入前端 / UI 自动化。
- 已完成双对抗专家评审：
  - `Anthropic Manager Agent` 视角结论：051 现在可以启动，但只能先 formalize，不能直接进入实现；
  - `Hermes Agent` 视角结论：真正缺口是 fake/stub drift 与 suite topology，而不是继续平铺 approval/restart happy path。
- 已据此创建：
  - `spec.md`
  - `plan.md`
  - `tasks.md`
  - `seam-matrix.md`
  - `.ai-sdlc/work-items/051-high-coupling-test-hardening/*`
- 当前 canonical branch 已切到 `codex/051-high-coupling-test-hardening`。
- 当前下一执行入口固定为 `T512`：先写 red tests 锁定 fake/stub contract 与最小 seam smoke，再进入后续实现。

### Phase 2：fake/stub contract 与 seam smoke red/green

- 已新增 red tests：
  - `tests/test_watchdog_session_spine_api.py::test_fake_a_client_matches_a_control_agent_client_core_signature_contract`
  - `tests/test_watchdog_session_spine_api.py::test_fake_a_client_broken_stub_matches_a_control_agent_client_core_signature_contract`
  - `tests/integration/test_openclaw_integration_spine.py::test_integration_fake_a_client_matches_a_control_agent_client_core_signature_contract`
  - `tests/integration/test_openclaw_integration_spine.py::test_integration_fake_a_client_broken_stub_matches_a_control_agent_client_core_signature_contract`
  - `tests/test_watchdog_session_spine_api.py::test_seam_smoke_deferred_approval_delivery_survives_restart_and_updates_stable_reads`
- 红测证据：
  - `BrokenAClient` 在 `tests/test_watchdog_session_spine_api.py` 与 `tests/integration/test_openclaw_integration_spine.py` 中缺少 `list_tasks` 等真实 `AControlAgentClient` 已暴露的接口；
  - 初版 seam smoke 复用了带历史 pending approval 的 persisted seed，失败原因不是接缝缺口而是历史样本噪音，因此已修正为无历史噪音的最小链路。
- 已完成最小实现：
  - 为两个 `BrokenAClient` 补齐 `list_tasks / decide_approval / trigger_pause / trigger_handoff / trigger_resume / get_workspace_activity_envelope` 等 contract surface；
  - 将 seam smoke 改为显式构造单条 `approval -> delivered receipt -> restart -> stable read semantics` 链路。
- 当前验证：
  - `uv run pytest -q tests/test_watchdog_session_spine_api.py tests/integration/test_openclaw_integration_spine.py -k "fake_a_client or seam_smoke"`
  - 结果：`5 passed, 66 deselected in 0.56s`

### Phase 3：固定 targeted suites

- 已将最小高价值矩阵写入 `seam-matrix.md`，并为以下 suite 固定正式入口：
  - `targeted-bridge`
  - `targeted-a-control`
  - `targeted-watchdog`
- 当前验证：
  - `uv run pytest -q tests/test_codex_app_server_bridge.py -k "respond_failure or numeric_request_id_for_auto_approved_callback_retry_after_restart or restores_auto_approved_callback_retry_after_restart or legacy_command_approval_to_command_execution_callback_shape or legacy_permissions_approval_with_human_reason or does_not_restore_delivered_policy_auto_callback_after_restart"`
  - 结果：`6 passed, 8 deselected in 0.06s`
  - `uv run pytest -q tests/test_a_control_agent_control_flow.py -k "approval_callback_failure_keeps_request_pending or auto_approved_callback_can_be_retried_via_approval_decision_route or auto_approved_callback_can_be_retried_after_bridge_restart or delivered_policy_auto_callback_cannot_be_replayed_via_approval_decision_route or resume_replays_handoff_summary_into_live_thread or resume_failure_does_not_mark_task_running"`
  - 结果：`6 passed, 5 deselected in 0.44s`
  - `uv run pytest -q tests/test_watchdog_session_spine_api.py -k "deferred_policy_auto_approval_is_visible_across_stable_session_surfaces or reads_only_targeted_actionable_approval_slices or falls_back_to_project_approved_slice_when_targeted_deferred_retry_fails or reapplies_project_filter_when_upstream_ignores_it or actionable_approvals_are_globally_sorted_by_requested_at or restart_preserves_pending_approvals_on_stable_read_surfaces or restart_preserves_action_receipt_lookup_without_reexecution or legacy_approvals_proxy_fails_closed_on_runtime_error or legacy_approval_decision_proxy_fails_closed_on_runtime_error"`
  - 结果：`9 passed, 40 deselected in 0.87s`

### Phase 4：固定 seam-smoke / full 入口

- 已在 `seam-matrix.md` 明确 `seam-smoke` 与 `full` 的正式命令入口；
- 已明确 051 的去重复原则：不再继续平铺 approval inbox、canonical/alias happy path、已存在 restart persistence 回归。
- 当前验证：
  - `uv run pytest -q tests/test_watchdog_session_spine_api.py tests/integration/test_openclaw_integration_spine.py -k "fake_a_client or seam_smoke"`
  - 结果：`5 passed, 66 deselected in 0.51s`
  - `uv run pytest -q tests/test_codex_app_server_bridge.py tests/test_a_control_agent_control_flow.py tests/test_watchdog_session_spine_api.py tests/integration/test_openclaw_integration_spine.py tests/test_ai_sdlc_reconciliation.py tests/test_long_running_autonomy_doc_contracts.py`
  - 结果：`106 passed in 2.88s`

### Phase 5：051 formal closeout

- 已完成 `WI-051` 正式 closeout：
  - fake/stub drift contract 已锁定；
  - `targeted / seam-smoke / full` 三层入口已固定；
  - backlog 条目已从 `deferred` 改为 `completed`；
  - `.ai-sdlc` 状态已准备切换为 `completed`。
