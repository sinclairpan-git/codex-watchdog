# Task Execution Log：085-model-first-continuation-governance

## Batch 1

- 时间：`2026-04-20T15:20:03Z`
- 任务：`T851`
- 状态：completed
- 记录：
  - 已创建 `WI-085` 的 `spec / plan / tasks`。
  - 已完成两轮常驻专家对抗评审，并将结论收敛进正式文档。
  - 已切换当前工作分支到 `codex/085-model-first-continuation-governance`。
  - 已把顶层 `.ai-sdlc` active state 与 work-item mirror 指向 `WI-085`。

## Batch 2

- 时间：`2026-04-20T15:37:57Z`
- 任务：`T852`
- 状态：completed
- 记录：
  - 已新增 `PCDI` 正式输入模型，显式承载 project / branch / progress / governance / freshness truth。
  - `BrainDecisionService` 已开始从 goal contract 与 `.ai-sdlc` active state 构造 `PCDI`，并在 provider 前执行 goal-contract / pending-approval / non-active precondition hard gate。
  - `OpenAICompatibleBrainProvider` 已支持 continuation decision v3，同时兼容 legacy v2；`branch_complete_switch` 现保留为 first-class signal，并携带 `continuation_identity / route_key / branch_switch_token / target_work_item_seq`。
  - 已补齐 provider 专项负路径回归，并通过 `tests/test_watchdog_brain_provider_runtime.py` 与更大一圈 session spine / adapter 回归。

## Batch 3

- 时间：`2026-04-20T16:19:07Z`
- 任务：`T853`
- 状态：completed
- 记录：
  - 已把 `project_execution_state` 正式接入 `facts -> projection -> orchestrator -> actions -> recovery -> session-event fallback` 主链路；`project_not_active` 现会抑制 `continue_session / execute_recovery` 与 resident auto action 映射。
  - `BrainDecisionService` 的 project state 归一化已改为 fail-closed：任一 authoritative source 出现 `paused / stopped / branch_transition_in_progress / completed / archived / closed` 都先于 active-like stage 生效，避免 stale `resume-pack.current_stage` 把已停止项目误判成 active。
  - continuation 相关 action (`continue_session / resume_session / force_handoff / retry_with_conservative_path`) 已统一套上 hard gate；non-active project、pending approval、terminal / in-flight 状态都会在动作前 fail-closed。
  - `perform_recovery_execution()` 已开始同时读取 approvals 真值，不再只信 task 上的 `pending_approval` 布尔位；direct recovery / live bundle / session-events fallback 三条读路径现统一吃到 authoritative project state overlay。
  - 已完成两轮常驻专家对抗评审并收敛遗留 blocker；targeted regression 共 `350 passed`，`ruff check` 与 `ai_sdlc verify constraints` 均通过。

## Batch 4

- 时间：`2026-04-20T16:56:26Z`
- 任务：`T854`
- 状态：completed
- 记录：
  - 已为 `continuation_gate_evaluated / continuation_identity_* / branch_switch_token_* / continuation_replay_invalidated` 补齐稳定写面，并把 recovery / orchestrator / actions 的 lineage / provenance 真值统一接入 `SessionService`。
  - resident orchestrator 现会把 provider / rules continuation governance 明确落成 gate verdict；manual direct actions 也会写 gate verdict，但 canonical decision 已预写 gate 的路径不会再重复追加伪 `manual_action` 事件。
  - authoritative project execution state 的 `.ai-sdlc` 读取根路径已修正为仓库根目录；unknown state 现 fail-closed 为 `project_state_unavailable`，自动推进与 recovery 会被统一阻断。
  - `recovery_transaction_id / source_packet_id` 已与 handoff summary 文本脱钩；`failed_retryable` recovery 现在会写 `continuation_identity_invalidated + continuation_replay_invalidated`，不再留下 issued 悬挂身份或旧 route replay 缺口。
  - `branch_switch_token` 已在 decision lifecycle 的 eligible / suppressed 写出 `issued / invalidated` 审计事件；其真正的单次消费与 dispatch closeout 转入 `T855` 状态机实现。
  - 已通过相关回归：`tests/test_watchdog_action_execution.py tests/test_watchdog_action_idempotency.py tests/test_watchdog_recovery_execution.py tests/test_watchdog_session_service.py`（`61 passed`）、`tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_brain_provider_runtime.py tests/test_watchdog_session_spine_api.py tests/test_watchdog_feishu_adapter.py tests/integration/test_feishu_integration_spine.py -k "continuation or recovery or branch_switch_token or authoritative_project_state or project_state_unavailable or failed_retryable or provider_continue"`（`37 passed, 268 deselected`）、以及更小圈 targeted runtime/api/integration 子集全部绿色；`ruff check` 通过。

## Batch 5

- 时间：`2026-04-20T18:26:38Z`
- 任务：`T855`
- 状态：completed
- 记录：
  - 已把 `branch_complete_switch` 从“只有 provider verdict、没有执行落点”的半成品状态，正式接成 `post_operator_guidance` closeout 路径；其语义被收敛为“带权威真值约束的下一分支推进指令投递”，不再伪装成 recovery / handoff / 空 summary。
  - `policy / orchestrator / actions / session_service` 已同时补齐：`branch_complete_switch -> post_operator_guidance` 映射、auto execute eligibility、authoritative next-target 缺失时 fail-closed block、以及 `branch_switch_token` 在 guidance 成功投递后 `consumed`、失败时 `invalidated` 的 authoritative closeout。
  - branch switch token 的审计链现额外绑定 `continuation_identity + route_key`，避免 token 只剩“发过一次”而无法证明消费属于哪条 continuation route。
  - operator guidance 文本已改为携带 `项目总目标 / 当前分支目标 / 当前进度 / 后续任务` 的明确执行指令；当缺少 `target_work_item_seq + branch_switch_token` 这类权威 next-branch truth 时，不再自动推进。
  - 已补齐红绿回归：`tests/test_watchdog_policy_engine.py -k "branch_complete_switch"`、`tests/test_watchdog_action_execution.py -k "branch_switch_token"`、`tests/test_watchdog_session_spine_runtime.py -k "branch_complete_switch or records_branch_switch_token_lifecycle"` 全绿；随后扩圈 `tests/test_watchdog_action_execution.py tests/test_watchdog_action_idempotency.py tests/test_watchdog_policy_engine.py tests/test_watchdog_session_service.py tests/test_watchdog_session_spine_runtime.py` 共 `161 passed`，并通过 `ruff check`。

## Batch 6

- 时间：`2026-04-21T01:02:11Z`
- 任务：`T856`
- 状态：completed
- 记录：
  - 已把 continuation control-plane 正式投影到 `TaskProgressView.continuation_control_plane`，显式暴露 `continuation_identity / identity_state / branch_switch_token / token_state / consumed_at / route_key / packet_id / decision_source / snapshot_version / snapshot_epoch / last_dispatch_result / dispatch_cooldown`。
  - `last_dispatch_result` 现优先读取 `ActionReceiptStore` 真值，再用 command terminal 事件做只读 fallback；API 与 Feishu adapter 读面已统一透传 receipt store 与 orchestration state，避免 operator 只能靠 markdown/summary 猜状态。
  - resident orchestrator 的 auto-dispatch cooldown 已从 project-only `auto_continue_checkpoint` 收敛为 shared `auto_dispatch_checkpoint`；guard 先匹配 `project + continuation_identity + route_key`，再回退到同 `continuation_identity` 的最近 checkpoint，避免 snapshot bump 直接绕过 suppression。
  - 为了封住 crash window，shared checkpoint 现具备 `claimed -> completed / failed` 生命周期：外部 dispatch 前先写 `claimed`，成功后写 `completed`，失败时写 `failed`；projection 也会显式暴露 `dispatch_cooldown.checkpoint_state`。
  - 顺手修复了一个历史缺口：`continue_session` 的 runtime 侧结构化拒绝不再被错误折叠成 `CONTROL_LINK_ERROR`，而会保留原始 reject code/message。
  - 已完成两轮常驻专家评审并收敛 blocker；扩圈验证 `tests/test_watchdog_action_execution.py tests/test_watchdog_action_idempotency.py tests/test_watchdog_policy_engine.py tests/test_watchdog_session_service.py tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_session_spine_api.py tests/test_watchdog_feishu_adapter.py` 共 `325 passed`，`ruff check` 通过。

## Batch 7

- 时间：`2026-04-21T02:15:30Z`
- 任务：`T857`
- 状态：completed
- 记录：
  - 已把 `ContinuationPacket` 真值对象正式贯通到 runtime-side handoff markdown、Watchdog recovery/resume 与 session-service freeze/write 面；`handoff_packet_frozen` 现稳定写出 `continuation_packet + packet_hash + rendered_markdown_hash + rendered_from_packet_id`，operator control-plane 与 Feishu adapter 统一读这组 packet truth，而不是继续猜 markdown summary。
  - 已把过期的 recover/handoff 对齐测试收口到当前 contract：`tests/test_007_alignment.py`、`tests/test_m4_watchdog_recover.py`、`tests/test_a_control_agent_control_flow.py` 不再 patch 已脱离调用链的 `httpx.Client`，而是直接验证 `AControlAgentClient.trigger_handoff/trigger_resume` 与 packet render contract。
  - 已确认 `ContinuationPacket` render 只承担 deterministic 视图角色；渲染文本不再回流成 `PCDI`、routing input、dedupe 输入或 authoritative recovery truth。

## Batch 8

- 时间：`2026-04-21T02:15:30Z`
- 任务：`T858`
- 状态：completed
- 记录：
  - provider external-integration smoke harness 已修复：synthetic provider probe 现先写入 `autonomous_ready` goal contract，再验证 provider success path 与 resident fallback path，避免被新的 goal-contract precondition 直接短路成伪失败。
  - 已完成 plan 指定验证：`uv run pytest -q tests/test_watchdog_brain_provider_runtime.py tests/test_watchdog_policy_engine.py tests/test_watchdog_policy_decisions.py tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_session_spine_api.py tests/test_watchdog_feishu_adapter.py tests/integration/test_feishu_integration_spine.py` -> `336 passed`；`uv run pytest -q` -> `1091 passed`；`uv run ruff check`、`uv run python -m ai_sdlc verify constraints`、`uv run python -m ai_sdlc status` 全部通过。
  - `WI-085` 至此闭环：系统可稳定区分 continue current branch / recover current branch / branch complete switch / project complete / await human / blocked，并保持停止项目 fail-closed，不再重复投递无意义 summary。
