# 执行日志：030-session-service-event-truth-write-barrier

> 对应规格：`specs/030-session-service-event-truth-write-barrier/spec.md`
>
> 对应任务：`specs/030-session-service-event-truth-write-barrier/tasks.md`

## 2026-04-12

- 完成 `T301`：已把总实施计划中的 `Task 1` 正式拆为 `WI-030`，并补齐 canonical `spec.md`、`plan.md`、`tasks.md`。
- 已将总实施计划回链到 `specs/030-session-service-event-truth-write-barrier/`，避免继续把总计划直接当执行入口。
- 当前未进入产品实现；下一执行入口固定为 `T302`。
- 复查中断工作区后确认：产品实现其实已经推进到 `session_spine / approvals / delivery / api` 多个既有模块，只是 formal docs 没有回填，导致 `tasks.md` 仍停留在“未开始”。
- 已验证通过：
  - `uv run pytest -q tests/test_watchdog_approval_loop.py tests/test_watchdog_delivery_store.py tests/test_watchdog_delivery_worker.py tests/test_watchdog_policy_engine.py tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_ops.py tests/test_watchdog_session_spine_api.py tests/test_long_running_autonomy_doc_contracts.py tests/test_openclaw_contracts.py`
  - `uv run pytest -q tests/test_watchdog_delivery_http.py tests/test_watchdog_delivery_store.py tests/test_watchdog_delivery_worker.py tests/test_watchdog_approval_loop.py tests/test_watchdog_ops.py tests/test_watchdog_policy_engine.py tests/test_watchdog_session_spine_api.py tests/test_watchdog_session_spine_projection.py tests/test_watchdog_session_spine_runtime.py tests/test_long_running_autonomy_doc_contracts.py tests/test_openclaw_contracts.py`
- 当前已验证的行为包括：
  - canonical approval identity、pending refresh、duplicate pending reconcile 与 supersede；
  - delivery outbox 的单调 `outbox_seq`、跨实例串行化、重试/死信/transport requeue；
  - `context_critical` runtime 先转人工审批，不再直接 auto recovery；
  - stable read surface 可叠加 canonical approval，startup 会收敛历史 stale pending approvals；
  - OpenClaw webhook bootstrap 可持久化最新 webhook endpoint，并把 transport dead-letter 重新排队。
- 当前仍未完成的缺口：
  - 原计划中的独立 `src/watchdog/services/session_service/` 落点尚未建立；
  - command lease 的 store / expiry requeue / duplicate-execution gating 已接入 `resident_orchestrator`，但 live lease renewal 与跨 worker 协调位点仍未补齐；
  - `memory_unavailable_degraded`、`memory_conflict_detected` 与 `stage_goal_conflict_detected` 仍主要停留在 docs contract / schema 约束，未形成独立 runtime writer；
  - `uv run ai-sdlc verify constraints` 因缺少 `ai-sdlc` 可执行入口而无法在本地验证。
- 已补上最小 `command lease` 存储切片：
  - 新增 `src/watchdog/services/session_spine/command_leases.py`，使用与 delivery outbox 一致的文件锁 + 原子替换模式，落盘 `command_claimed / command_lease_renewed / command_claim_expired / command_requeued / command_executed / command_failed`；
  - 新增 `tests/test_watchdog_command_leases.py`，锁定 canonical 事件顺序、`worker_id / lease_expires_at` 冻结，以及同一 worker 在旧 `claim_seq` 上的晚到结果会被拒绝；
  - 已验证通过：`uv run pytest -q tests/test_watchdog_command_leases.py` 与 `uv run pytest -q tests/test_watchdog_command_leases.py tests/test_watchdog_action_execution.py tests/test_watchdog_delivery_store.py`。
- 已把 command lease 最小接入现有热路径：
  - `create_app` 现在会实例化 `command_lease_store`，`ResidentOrchestrator` 会在 auto-execute 命令首次执行时写入 `command_claimed`，并在动作返回或抛出 control-link 错误后分别补记 `command_executed / command_failed`；
  - `tests/test_watchdog_session_spine_runtime.py` 已新增 runtime 回归，锁定 auto-continue 成功路径的 `claim -> executed` 与 control-link-error 路径的 `claim -> failed`；
  - 已验证通过：`uv run pytest -q tests/test_watchdog_command_leases.py tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_action_execution.py tests/test_long_running_autonomy_doc_contracts.py` 与 `uv run pytest -q tests/test_watchdog_command_leases.py tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_action_execution.py tests/test_watchdog_delivery_store.py tests/test_watchdog_policy_engine.py tests/test_long_running_autonomy_doc_contracts.py`。
- 已把 runtime command lease gating 补到位：
  - `ResidentOrchestrator.orchestrate_all()` 每个 tick 会先执行 `expire_and_requeue_expired()`，把过期命令稳定落盘为 `command_claim_expired -> command_requeued`；
  - auto-execute 路径现在只允许 `None | requeued` 状态重新 claim 并执行，已有有效 `claimed` 或已终态 `executed / failed` 的命令会直接跳过重复执行；
  - `tests/test_watchdog_session_spine_runtime.py` 新增并验证三条路径：已有有效 claim 不重复执行、过期 claim 先回队再重领执行、cached control-link-error receipt 不会在下一 tick 再次执行同一命令。
- 因此，`030` 的真实状态应为：`T302/T303/T304/T305/T306` 进行中；下一执行入口收敛为补齐 live lease renewal、决定是否把既有实现重构收敛到独立 `session_service` 模块，并继续把 lineage / recovery 记录补全。

## 2026-04-13

- 已补齐 `SessionService` 的 controlled event writer 缺口：
  - `src/watchdog/services/approvals/service.py` 现在会在 canonical approval response 成功落账后，额外记录 `human_override_recorded`；
  - `src/watchdog/services/session_service/service.py` 新增 `record_memory_unavailable_degraded()`、`record_memory_conflict_detected()` 与 `record_approval_expired()`，统一冻结 memory anomaly / approval expiry 的 canonical payload、related ids 与 correlation 规则；
  - `src/watchdog/services/delivery/worker.py` 与 `src/watchdog/api/openclaw_bootstrap.py` 先前已接入 `notification_requeued`，本轮重扫后 controlled session events 已全部存在明确 writer 落点。
- 已补充并通过的回归：
  - `uv run pytest -q tests/test_watchdog_approval_loop.py -k 'respond_to_canonical_approval_records_session_event or openclaw_response_api_uses_response_tuple_as_idempotency_key'`
  - `uv run pytest -q tests/test_watchdog_approval_loop.py`
  - `uv run pytest -q tests/test_openclaw_contracts.py`
  - `uv run pytest -q tests/test_watchdog_session_service.py`
- 当前对 `T304` 的判断更新为：
  - 审批请求、审批批准/拒绝、人工接管、通知重排队、memory anomalies 的 canonical writer 已落地；
  - `approval_expired` 目前只冻结到 `SessionService` writer，仓库内尚未找到真实 approval timeout / expiry 事实源，因此没有继续凭空扩展业务流；
  - 下一合理执行入口是决定 approval timeout 事实应落在哪个 runtime tick / reconcile path，再把该事实接到 `record_approval_expired()`。
- 已把真实 approval timeout fact source 接到启动期 reconcile：
  - `src/watchdog/services/approvals/service.py` 新增 `expire_pending_canonical_approvals()`，按 `created_at + approval_expiration_seconds` 计算过期点，并固定为“先写 `approval_expired` session event，再把 canonical approval 标成 `expired`”；
  - `src/watchdog/main.py` 的 `_reconcile_stale_pending_approvals()` 现已接入该 helper，并会把对应 approval envelope 一并 supersede 出 delivery outbox；
  - `respond_to_canonical_approval()` 现在会拒绝对 `expired` approval 的后续批准/拒绝/执行请求，避免过期后再次执行 side effect。
- 已补充并通过的回归：
  - `uv run pytest -q tests/test_watchdog_approval_loop.py -k 'expire_pending_canonical_approval or startup_reconcile_expires_stale_pending_approvals'`
  - `uv run pytest -q tests/test_watchdog_approval_loop.py tests/test_watchdog_session_service.py tests/test_watchdog_session_service_atomicity.py tests/test_watchdog_command_leases.py tests/test_watchdog_policy_engine.py tests/test_watchdog_session_spine_runtime.py`
- 当前对 `T304` 的判断更新为：
  - `approval_requested -> approval_approved | approval_rejected | approval_expired` 已全部由 Session events 驱动，且 `approval_expired` 已接上真实 timeout fact source；
  - 启动期 reconcile 已成为当前实现中的 approval expiry runtime source，后续若引入更细粒度后台 tick，只需复用同一 helper，不需要再改 event contract；
  - 因此 `T304` 可以回填为已完成，当前下一执行入口重新收敛到 `T305` 的 live lease renewal 与最终 `T306` 验证收口。
- `uv run ai-sdlc verify constraints` 仍无法执行，报错为缺少 `ai-sdlc` 可执行入口（`Failed to spawn: ai-sdlc`），因此 formal constraints 只能继续按仓库内 specs/tasks/log 进行人工回填。
