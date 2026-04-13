# 任务分解：030-session-service-event-truth-write-barrier

> 对应规格：`specs/030-session-service-event-truth-write-barrier/spec.md`
>
> 对应总设计：`docs/architecture/codex-long-running-autonomy-design.md`
>
> 对应总实施计划：`docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`

## Batch 1

### Task 30.1 冻结 030 formal docs 与执行边界

- **任务编号**：T301
- **状态**：已完成（2026-04-12 回填）
- **依赖**：无
- **文件**：
  - `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
  - `specs/030-session-service-event-truth-write-barrier/spec.md`
  - `specs/030-session-service-event-truth-write-barrier/plan.md`
  - `specs/030-session-service-event-truth-write-barrier/tasks.md`
  - `specs/030-session-service-event-truth-write-barrier/task-execution-log.md`
- **可并行**：否
- **验收标准**：
  1. 总实施计划中的 `Task 1` 已回链到 canonical `specs/030-.../`；
  2. 030 的边界已明确限定为 canonical 写面与写入闸门；
  3. 030 已明确排除 projection 替换、Goal Contract、Brain / Recovery、Feishu 与 Memory Hub 检索逻辑；
  4. 下一执行入口已经收敛到 T302，而不是直接跳进产品代码泛化修改。
- **验证**：人工审阅 `spec.md / plan.md / tasks.md` 是否与总设计和总实施计划一致。
- **完成情况**：已把总实施计划的 `Task 1` 正式拆成 `WI-030`，并固定后续执行入口为 `T302`。

## Batch 2

### Task 30.2 新增 Session event 契约与 append-only writer

- **任务编号**：T302
- **状态**：已完成（2026-04-13 回填）
- **依赖**：T301
- **文件**：
  - `src/watchdog/services/session_service/models.py`
  - `src/watchdog/services/session_service/store.py`
  - `tests/test_watchdog_session_service.py`
  - `tests/test_watchdog_session_service_atomicity.py`
- **可并行**：否
- **验收标准**：
  1. 存在 `SessionEventRecord`、`SessionLineageRecord`、`RecoveryTransactionRecord`；
  2. writer 支持 append-only、single-writer、原子追加与幂等去重；
  3. schema 中已保留 `memory_unavailable_degraded`、`memory_conflict_detected` 与 `stage_goal_conflict_detected`；
  4. 写锁丢失、原子追加失败与崩溃恢复场景都有失败测试和通过路径。
- **验证**：`uv run pytest -q tests/test_watchdog_session_service.py tests/test_watchdog_session_service_atomicity.py`
- **当前实现备注**：
  1. `src/watchdog/services/session_service/models.py`、`store.py` 与 `service.py` 已正式落地，`SessionEventRecord / SessionLineageRecord / RecoveryTransactionRecord`、append-only store、最小 query facade 与 recovery writer 已收敛到独立模块；
  2. `tests/test_watchdog_session_service.py` 与 `tests/test_watchdog_session_service_atomicity.py` 已锁定 schema、顺序、幂等去重、原子追加与 single-writer 约束；
  3. `memory_unavailable_degraded`、`memory_conflict_detected` 与 `approval_expired` 的稳定 writer 已补入 `SessionService`，后续 runtime 只需要接真实事实源，不需要再改 canonical event contract。

## Batch 3

### Task 30.3 接入 policy / orchestrator 的 pre-command write barrier

- **任务编号**：T303
- **状态**：进行中（2026-04-12 校准）
- **依赖**：T302
- **文件**：
  - `src/watchdog/services/session_service/service.py`
  - `src/watchdog/services/policy/engine.py`
  - `src/watchdog/services/policy/decisions.py`
  - `src/watchdog/services/session_spine/orchestrator.py`
  - `tests/test_watchdog_session_service.py`
  - `tests/test_watchdog_policy_engine.py`
  - `tests/test_watchdog_session_spine_runtime.py`
- **可并行**：否
- **验收标准**：
  1. `decision_proposed -> decision_validated -> command_created` 顺序被硬性锁定；
  2. canonical 写入失败时命令不会被创建或投递；
  3. runtime 热路径已经通过 `Session Service` 落账，而不是旁路写入；
  4. 既有 policy / runtime 非回归测试仍通过。
- **验证**：`uv run pytest -q tests/test_watchdog_session_service.py tests/test_watchdog_policy_engine.py tests/test_watchdog_session_spine_runtime.py`
- **当前实现备注**：
  1. `persisted session spine -> policy decision -> canonical approval / delivery outbox` 的热路径已被 `tests/test_watchdog_policy_engine.py`、`tests/test_watchdog_session_spine_runtime.py` 与 `tests/test_watchdog_session_spine_api.py` 锁定；
  2. `context_critical` 场景已经改为先路由到 canonical approval request，而不是直接自动执行 recovery；
  3. 但当前仍是依托既有 `session_spine` 写面收口，尚未形成原计划命名下的独立 `Session Service` 模块。

## Batch 4

### Task 30.4 收敛审批、通知、人工接管与记忆异常 canonical events

- **任务编号**：T304
- **状态**：已完成（2026-04-13 approval timeout fact source）
- **依赖**：T303
- **文件**：
  - `src/watchdog/services/session_service/service.py`
  - `src/watchdog/services/approvals/service.py`
  - `tests/test_watchdog_session_service.py`
  - `tests/test_watchdog_approval_loop.py`
- **可并行**：否
- **验收标准**：
  1. `approval_requested -> approval_approved | approval_rejected | approval_expired` 由 Session events 驱动；
  2. `notification_announced -> notification_receipt_recorded -> human_override_recorded` 由 Session events 驱动；
  3. `memory_unavailable_degraded` 与 `memory_conflict_detected` 已成为 canonical event；
  4. `stage_goal_conflict_detected` 至少进入 schema / query facade，可被后续 work item 直接消费；
  5. `approvals` 服务只保留兼容 facade / inbox cache 职责。
- **验证**：`uv run pytest -q tests/test_watchdog_session_service.py tests/test_watchdog_approval_loop.py`
- **当前实现备注**：
  1. canonical approval materialization、同一 approval 的幂等响应、startup reconcile、delivery supersede/requeue 与 stable read surface overlay 已有测试通过；
  2. OpenClaw webhook bootstrap 已能把 transport dead-letter 重新排队，审批/通知兼容面也已稳定；
  3. `SessionService` 已补齐 `memory_unavailable_degraded`、`memory_conflict_detected` 与 `approval_expired` 的稳定 writer，`tests/test_watchdog_session_service.py` 已锁定其 correlation / related_ids / payload 语义；
  4. 启动期 `_reconcile_stale_pending_approvals()` 现在会基于 `created_at + approval_expiration_seconds` 计算真实过期事实，先调用 `SessionService.record_approval_expired()`，再把 canonical approval 关成 `expired` 并 supersede delivery outbox，`tests/test_watchdog_approval_loop.py` 已锁定该写屏障顺序与 expired 响应拒绝路径。

## Batch 5

### Task 30.5 冻结命令租约、重排队与恢复位点

- **任务编号**：T305
- **状态**：已完成（2026-04-13 live lease renewal）
- **依赖**：T304
- **文件**：
  - `src/watchdog/services/session_spine/command_leases.py`
  - `src/watchdog/services/session_service/service.py`
  - `src/watchdog/services/session_spine/orchestrator.py`
  - `tests/test_watchdog_command_leases.py`
  - `tests/test_watchdog_session_spine_runtime.py`
- **可并行**：否
- **验收标准**：
  1. `command_claimed -> command_lease_renewed -> command_claim_expired -> command_requeued` 成为 canonical 事件链；
  2. `worker_id` 与 `lease_expires_at` 被稳定冻结在事件中；
  3. 命令重排队后，晚到结果会被拒绝；
  4. `SessionLineageRecord` 与 `RecoveryTransactionRecord` 已足以支撑后续 replay / recovery work item 接入。
- **验证**：`uv run pytest -q tests/test_watchdog_command_leases.py tests/test_watchdog_session_spine_runtime.py`
- **当前实现备注**：
  1. 已新增 `src/watchdog/services/session_spine/command_leases.py` 与 `tests/test_watchdog_command_leases.py`，把 `command_claimed -> command_lease_renewed -> command_claim_expired -> command_requeued` canonical 事件链先冻结为可持久化、可回放的 JSON store；
  2. 事件与当前命令状态都会稳定保留 `worker_id`、`lease_expires_at`，并通过 `claim_seq` 拒绝同一 worker 在旧租约代际上的晚到结果；
  3. `create_app -> ResidentOrchestrator` 已接入该租约存储：orchestrator tick 会先执行过期租约的 `command_claim_expired -> command_requeued`，对 `resident_orchestrator` 自己仍持有的有效 claim 会写入 `command_lease_renewed` 延长租约，仅 `None | requeued` 状态允许重新 `claim` 并执行；`claimed / executed / failed` 状态都会阻止重复 auto-execute，动作结束后补记 `command_executed | command_failed`；
  4. `tests/test_watchdog_session_spine_runtime.py` 与 `tests/test_watchdog_command_leases.py` 已锁定四条热路径：已有有效跨 worker claim 时跳过重复执行、resident orchestrator 的有效 claim 会 live renew、过期 claim 先回队后重领执行、同一 claim 的多次续租都会稳定镜像进 `SessionService` 而不发生幂等冲突；
  5. `SessionLineageRecord / RecoveryTransactionRecord`、对应 writer 与 recovery 回归已在 `session_service` / `recovery_execution` 路径落地，因此本任务的剩余缺口已收敛完成。

## Batch 6

### Task 30.6 完成 030 整体验证并为下一 work item 交接

- **任务编号**：T306
- **状态**：已完成（2026-04-13，本地 formal constraints 仍受 `ai_sdlc` 模块缺失阻塞）
- **依赖**：T305
- **文件**：
  - `tests/test_watchdog_session_service.py`
  - `tests/test_watchdog_session_service_atomicity.py`
  - `tests/test_watchdog_approval_loop.py`
  - `tests/test_watchdog_command_leases.py`
  - `tests/test_watchdog_policy_engine.py`
  - `tests/test_watchdog_session_spine_runtime.py`
  - `tests/test_long_running_autonomy_doc_contracts.py`
  - `specs/030-session-service-event-truth-write-barrier/task-execution-log.md`
- **可并行**：否
- **验收标准**：
  1. 030 所需测试全部通过；
  2. formal docs 与执行日志已更新到最终状态；
  3. 交接口径明确下一 work item 只做 `session_spine` projection 替换，不回头补 030 的写真源；
  4. 030 没有顺手把 Goal Contract、Brain / Recovery、Feishu 或 Memory Hub 检索逻辑实现进来。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_session_service.py tests/test_watchdog_session_service_atomicity.py tests/test_watchdog_approval_loop.py tests/test_watchdog_command_leases.py tests/test_watchdog_policy_engine.py tests/test_watchdog_session_spine_runtime.py tests/test_long_running_autonomy_doc_contracts.py`
  - `uv run python -m ai_sdlc verify constraints`
- **当前实现备注**：
  1. 已实际通过：`tests/test_watchdog_delivery_http.py tests/test_watchdog_delivery_store.py tests/test_watchdog_delivery_worker.py tests/test_watchdog_approval_loop.py tests/test_watchdog_ops.py tests/test_watchdog_policy_engine.py tests/test_watchdog_session_spine_api.py tests/test_watchdog_session_spine_projection.py tests/test_watchdog_session_spine_runtime.py tests/test_long_running_autonomy_doc_contracts.py tests/test_openclaw_contracts.py`，共 120 个用例；
  2. 另已通过：`uv run pytest -q tests/test_watchdog_command_leases.py tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_action_execution.py tests/test_watchdog_delivery_store.py tests/test_watchdog_policy_engine.py tests/test_long_running_autonomy_doc_contracts.py`，共 35 个用例；本轮还补充锁定了 command lease runtime gating；
  3. 2026-04-13 已通过：`uv run pytest -q tests/test_watchdog_approval_loop.py tests/test_watchdog_session_service.py tests/test_watchdog_session_service_atomicity.py tests/test_watchdog_command_leases.py tests/test_watchdog_policy_engine.py tests/test_watchdog_session_spine_runtime.py`，共 59 个用例，并补齐 approval timeout 到 `approval_expired` 的真实事实源；
  4. 2026-04-13 已通过：`uv run pytest -q tests/test_watchdog_session_service.py tests/test_watchdog_session_service_atomicity.py tests/test_watchdog_approval_loop.py tests/test_watchdog_command_leases.py tests/test_watchdog_policy_engine.py tests/test_watchdog_session_spine_runtime.py tests/test_long_running_autonomy_doc_contracts.py`，共 62 个用例；本轮同时补齐了 resident orchestrator live lease renewal 与重复续租镜像的幂等键隔离；
  5. `uv run python -m ai_sdlc verify constraints` 当前仍无法执行；仓库内没有 `ai-sdlc` console script，且当前环境也未安装 `ai_sdlc` Python 模块；
  6. 在仓库内 tests / specs / execution log 维度，030 的写面与命令租约写真源已收敛，下一 work item 应只继续 `session_spine` projection 替换，不再回头补 030 的写真源。

## 预期结果

- `WI-030` 将把“写前记账”从设计原则变成正式执行入口。
- 030 完成后，`Session Service` 写面、写入闸门与命令租约恢复位点已经成立。
- 下一 work item 可以专注于 `session_spine` 读面切到 Session events projection，而不是继续回头补 canonical 写真源。
