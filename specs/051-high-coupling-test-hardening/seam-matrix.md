# Seam Matrix：051-high-coupling-test-hardening

## 目标

把 `BL-2026-04-06-001` 中的高耦合接缝整理成最小高价值矩阵。051 只吸收已经存在或即将 red-test 锁定的 seam，不继续平铺更多相似 happy path。

## targeted-bridge

### Seam：callback defer / retry / restart / legacy restore

- `test_bridge_preserves_auto_approved_callback_retry_after_respond_failure`
- `test_bridge_restores_numeric_request_id_for_auto_approved_callback_retry_after_restart`
- `test_bridge_restores_auto_approved_callback_retry_after_restart`
- `test_bridge_restore_defaults_legacy_command_approval_to_command_execution_callback_shape`
- `test_bridge_restore_detects_legacy_permissions_approval_with_human_reason`
- `test_bridge_does_not_restore_delivered_policy_auto_callback_after_restart`

### 覆盖目标

- callback send failure -> deferred retry
- restart restore 后 callback shape 不漂移
- legacy persisted row 恢复
- delivered replay guard

### 固定验证入口

`uv run pytest -q tests/test_codex_app_server_bridge.py -k "respond_failure or numeric_request_id_for_auto_approved_callback_retry_after_restart or restores_auto_approved_callback_retry_after_restart or legacy_command_approval_to_command_execution_callback_shape or legacy_permissions_approval_with_human_reason or does_not_restore_delivered_policy_auto_callback_after_restart"`

## targeted-a-control

### Seam：decision route -> callback -> task state transition

- `test_approval_callback_failure_keeps_request_pending`
- `test_auto_approved_callback_can_be_retried_via_approval_decision_route`
- `test_auto_approved_callback_can_be_retried_after_bridge_restart`
- `test_delivered_policy_auto_callback_cannot_be_replayed_via_approval_decision_route`
- `test_resume_replays_handoff_summary_into_live_thread`
- `test_resume_failure_does_not_mark_task_running`

### 覆盖目标

- approval callback 失败时状态保持正确
- deferred callback replay
- bridge restart 后 callback replay
- delivered callback guard
- resume / handoff restore 状态迁移

### 固定验证入口

`uv run pytest -q tests/test_a_control_agent_control_flow.py -k "approval_callback_failure_keeps_request_pending or auto_approved_callback_can_be_retried_via_approval_decision_route or auto_approved_callback_can_be_retried_after_bridge_restart or delivered_policy_auto_callback_cannot_be_replayed_via_approval_decision_route or resume_replays_handoff_summary_into_live_thread or resume_failure_does_not_mark_task_running"`

## targeted-watchdog

### Seam：session spine actionable approval slices / filter / fallback / restart / fail-closed

- `test_deferred_policy_auto_approval_is_visible_across_stable_session_surfaces`
- `test_session_spine_reads_only_targeted_actionable_approval_slices`
- `test_session_spine_falls_back_to_project_approved_slice_when_targeted_deferred_retry_fails`
- `test_session_spine_reapplies_project_filter_when_upstream_ignores_it`
- `test_actionable_approvals_are_globally_sorted_by_requested_at`
- `test_watchdog_restart_preserves_pending_approvals_on_stable_read_surfaces`
- `test_watchdog_restart_preserves_action_receipt_lookup_without_reexecution`
- `test_legacy_approvals_proxy_fails_closed_on_runtime_error`
- `test_legacy_approval_decision_proxy_fails_closed_on_runtime_error`

### 覆盖目标

- actionable approval slice 选择与回退
- project-scoped filtering
- restart restore to stable read surfaces
- legacy approvals proxy fail-closed

### 固定验证入口

`uv run pytest -q tests/test_watchdog_session_spine_api.py -k "deferred_policy_auto_approval_is_visible_across_stable_session_surfaces or reads_only_targeted_actionable_approval_slices or falls_back_to_project_approved_slice_when_targeted_deferred_retry_fails or reapplies_project_filter_when_upstream_ignores_it or actionable_approvals_are_globally_sorted_by_requested_at or restart_preserves_pending_approvals_on_stable_read_surfaces or restart_preserves_action_receipt_lookup_without_reexecution or legacy_approvals_proxy_fails_closed_on_runtime_error or legacy_approval_decision_proxy_fails_closed_on_runtime_error"`

## seam-smoke

### 新增正式烟测目标

1. fake / stub contract：
   - `FakeAClient` 与真实 `AClient` 在核心读写接口上的参数名、keyword-only 形态、过滤语义一致。
2. 单链路 smoke：
   - `deferred approval -> callback retry/delivered -> restart -> Watchdog stable read semantics`

### 验收口径

- 不追求替代 full integration；
- 只证明 backlog 所指的主接缝是一条连续链路，而不是碎片 case 拼装。

### 固定验证入口

`uv run pytest -q tests/test_watchdog_session_spine_api.py tests/integration/test_openclaw_integration_spine.py -k "fake_a_client or seam_smoke"`

## full

### 目标

- 把上述 `targeted-*` 与 `seam-smoke` 纳入正式全量验证说明；
- 不额外新增大量相似用例；
- full 入口只是编排和固定，不是继续扩大 scope。

### 固定验证入口

`uv run pytest -q tests/test_codex_app_server_bridge.py tests/test_a_control_agent_control_flow.py tests/test_watchdog_session_spine_api.py tests/integration/test_openclaw_integration_spine.py tests/test_ai_sdlc_reconciliation.py tests/test_long_running_autonomy_doc_contracts.py`

## 去重复原则

- 不再继续扩写 approval inbox 与 canonical/alias happy path 的重复测试；
- 不把已存在的 restart pending approvals / action receipts 回归重复定义为新矩阵项；
- 后续新增测试必须先证明属于 fake/stub drift、suite topology 或现有矩阵未覆盖的真实 seam。
