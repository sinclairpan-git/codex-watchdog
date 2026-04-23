# 执行日志：050-observability-restart-security-and-acceptance

## 2026-04-16

### Phase 1：scope recovery / formal docs freeze

- 基于 PRD `13/14/17`、`M5`、总实施计划的 `Task 8` 与 owner ledger `matrix-row-0061`，已把 050 正式边界收敛为：
  - observability / health / metrics evidence；
  - A/B 重启恢复与 reliability closeout；
  - fail-closed control-link security / availability contract；
  - release-blocking acceptance closeout。
- 已明确 050 不重开 048 的 runtime semantics，也不重开 049 的 Feishu/Feishu 入口语义。
- 已创建 `spec.md / plan.md / tasks.md / task-execution-log.md` 与 `.ai-sdlc/work-items/050-*` 基线。
- 当前 canonical branch 已切到 `codex/050-observability-restart-security-and-acceptance`。
- 当前下一执行入口固定为 `T502`：先写失败测试锁定 observability / acceptance contract，再进入实现。

### Phase 2：first red/green slice for metrics acceptance

- 已先选择 PRD `14.3 可观测性` 中最明确且可独立推进的 slice：任务数、待审批数、恢复次数指标导出。
- 新增 red test：
  - `tests/test_watchdog_ops.py::test_watchdog_metrics_exports_task_approval_and_recovery_totals`
- 首轮运行：
  - `uv run pytest -q tests/test_watchdog_ops.py -k "task_approval_and_recovery_totals or critical_ops_alert_gauges"`
  - 结果：`1 failed, 1 passed`
  - 稳定红点：`/metrics` 尚未导出 `watchdog_task_records_total`、`watchdog_approval_pending_total`、`watchdog_recovery_receipts_total`
- 已在 `src/watchdog/observability/metrics_export.py` 追加只读聚合：
  - `TaskStore.count_tasks()`
  - `CanonicalApprovalStore.list_records()` 的 pending 计数
  - `ActionReceiptStore.list_items()` 中 `execute_recovery + completed` 的 receipt 计数
- 当前验证：
  - `uv run pytest -q tests/test_watchdog_ops.py -k "task_approval_and_recovery_totals or critical_ops_alert_gauges or future_worker_status_and_blocking_reason"`
  - 结果：`4 passed, 16 deselected in 0.38s`
- 050 仍停在 `T502 in_progress`，后续继续补 healthz / restart recovery / fail-closed acceptance red tests。

### Phase 2：healthz / restart observability slices

- 已补第二批 red/green，覆盖 `release_gate_blockers` 与 runtime 侧重启可见性：
  - `tests/test_watchdog_ops.py::test_watchdog_healthz_degrades_when_release_gate_blocker_exists_without_alert_bucket`
  - `tests/test_a_control_agent.py::test_healthz_reports_persisted_thread_counts_after_restart`
  - `tests/test_a_control_agent.py::test_healthz_counts_projects_distinct_from_threads`
- 红测证据：
  - Watchdog `/healthz` 在只有 `release_gate_blockers`、没有普通 alert bucket 时仍返回 `ok`；
  - Codex runtime service `/healthz` 不暴露持久化 thread/project 计数；
  - `TaskStore.count_projects()` 错把 thread 数当作 project 数。
- 已完成最小实现：
  - `src/watchdog/api/ops.py`：`build_ops_summary()` 现在在存在 `release_gate_blockers` 时也会降级为 `degraded`；
  - `src/watchdog/main.py`：`/healthz` 追加 `release_gate_blockers` 计数；
  - `src/a_control_agent/main.py`：`/healthz` 追加 `tracked_threads` / `tracked_projects`；
  - `src/a_control_agent/storage/tasks_store.py`：`count_projects()` 改为读取持久化 project map，而非复用 thread 数。
- 当前验证：
  - `uv run pytest -q tests/test_watchdog_ops.py tests/test_a_control_agent.py`
  - 结果：`37 passed in 0.81s`
- 当前 reconciliation inventory：
  - `active=050-observability-restart-security-and-acceptance`
  - `next_seq=51`
  - `missing=()`
  - `stale=()`

### Phase 2：metrics semantics alignment slices

- 已补第三批 `T502` red/green，聚焦 observability 指标与 read-side 语义一致性：
  - `tests/test_a_control_agent.py::test_metrics_export_projects_distinct_from_threads`
  - `tests/test_watchdog_ops.py::test_watchdog_metrics_pending_approval_total_uses_latest_pending_record_per_session`
- 红测证据：
  - runtime 侧 `/metrics` 缺少 `aca_projects_total`，无法直接观测 distinct project 数；
  - watchdog 侧 `watchdog_approval_pending_total` 会把过期 pending records 一并算入，和 `ops summary` 的 latest-record 语义不一致。
- 已完成最小实现：
  - `src/a_control_agent/observability/metrics_export.py`：新增 `aca_projects_total`；
  - `src/watchdog/observability/metrics_export.py`：`watchdog_approval_pending_total` 复用 `_latest_approval_records(...)`，与 ops summary 对齐。
- 当前验证：
  - `uv run pytest -q tests/test_watchdog_ops.py tests/test_a_control_agent.py tests/test_ai_sdlc_reconciliation.py tests/test_long_running_autonomy_doc_contracts.py`
  - 结果：`49 passed in 0.95s`

### Phase 2：task store path compatibility slice

- 已补第四批 `T502` red/green，聚焦 Watchdog metrics 对 Codex runtime service 持久化路径的兼容读取：
  - `tests/test_watchdog_ops.py::test_watchdog_metrics_reads_task_totals_from_a_control_agent_store_path`
- 红测证据：
  - Watchdog metrics 只读取 `tasks.json`，而 Codex runtime service 正式持久化路径为 `tasks_store.json`；
  - 在只存在 `tasks_store.json` 时，`watchdog_task_records_total` 会错误返回 `0`。
- 已完成最小实现：
  - `src/watchdog/observability/metrics_export.py` 新增 `_task_store_for_metrics(...)`；
  - 读取顺序调整为优先 `tasks_store.json`，回退 `tasks.json`，保持对旧测试/旧数据的兼容。
- 当前验证：
  - `uv run pytest -q tests/test_watchdog_ops.py -k "reads_task_totals_from_a_control_agent_store_path or task_approval_and_recovery_totals or pending_approval_total_uses_latest_pending_record_per_session"`
  - 结果：`3 passed, 20 deselected in 0.43s`

### Phase 4：restart / fail-closed reliability slices

- 已补第五批 `T504` red/green，聚焦 Watchdog legacy approvals proxy 的 fail-closed 一致性：
  - `tests/test_watchdog_session_spine_api.py::test_legacy_approvals_proxy_fails_closed_on_runtime_error`
  - `tests/test_watchdog_session_spine_api.py::test_legacy_approval_decision_proxy_fails_closed_on_runtime_error`
- 红测证据：
  - `watchdog.api.approvals_proxy` 在 `httpx.Client().__enter__()` 触发 `RuntimeError` 时会直接返回 `500`；
  - `GET /api/v1/watchdog/approvals` 与 `POST /api/v1/watchdog/approvals/{approval_id}/decision` 未与其他 legacy route 保持同等 `CONTROL_LINK_ERROR` fail-closed 语义。
- 已完成最小实现：
  - `src/watchdog/api/approvals_proxy.py` 新增 `_a_client(settings)`；
  - 它统一固定 `trust_env=False`，避免环境代理污染 Watchdog -> Codex runtime service 控制链路；
  - `list_approvals_watchdog` 与 `decision_watchdog` 现在共同捕获 `httpx.RequestError`、`RuntimeError`、`OSError` 并返回显式 `CONTROL_LINK_ERROR`。
- 当前验证：
  - `uv run pytest -q tests/test_watchdog_session_spine_api.py -k "legacy_approvals_proxy_fails_closed_on_runtime_error or legacy_approval_decision_proxy_fails_closed_on_runtime_error"`
  - 结果：`2 passed, 42 deselected in 0.38s`

### Phase 4：restart persistence acceptance slices

- 已补第六批 `T504` acceptance tests，验证正式写入后跨 `create_app()` 重建实例的恢复闭环：
  - `tests/test_watchdog_session_spine_api.py::test_watchdog_restart_preserves_pending_approvals_on_stable_read_surfaces`
  - `tests/test_watchdog_session_spine_api.py::test_watchdog_restart_preserves_action_receipt_lookup_without_reexecution`
- 证据覆盖：
  - Watchdog 首次实例通过 `session_spine_store` / `canonical_approval_store` 写入后，重启实例仍可从 `/api/v1/watchdog/sessions/{project_id}`、`/pending-approvals`、`/approval-inbox` 读到 pending approval；
  - Watchdog 首次实例通过正式 action route 生成 receipt 后，重启实例仍可从 `/api/v1/watchdog/action-receipts` 查询到稳定 receipt，且不会重新触发 steer。
- 当前验证：
  - `uv run pytest -q tests/test_watchdog_session_spine_api.py -k "restart_preserves_pending_approvals_on_stable_read_surfaces or restart_preserves_action_receipt_lookup_without_reexecution"`
  - 结果：`2 passed, 44 deselected in 0.53s`

### Phase 5：050 formal closeout

- 已执行 050 正式验收集：
  - `uv run pytest -q tests/test_watchdog_ops.py tests/test_watchdog_session_spine_api.py tests/test_a_control_agent.py tests/test_watchdog_release_gate.py tests/test_ai_sdlc_reconciliation.py tests/test_long_running_autonomy_doc_contracts.py`
  - 结果：`115 passed in 3.02s`
- 050 的 release-blocking 条款现已全部关闭：
  - observability / `/healthz` / metrics/export contract 已冻结；
  - A/B restart recovery 与 Watchdog pending approvals / receipts persistence 已有正式回归；
  - A 不可达时的 fail-closed `CONTROL_LINK_ERROR` contract 已补齐到 legacy read/write surface；
  - acceptance / release gate / docs contract 与 AI-SDLC reconciliation 仍保持通过。
- 当前 handoff：
  - `WI-050` 正式完成；
  - `next_work_item_seq=51` 保持为唯一下一执行入口；
  - `WI-051` 仅保留高耦合 hardening，不再承接任何 release blocker。
