# Spec：085-model-first-continuation-governance

## 背景

当前自动推进链路已经暴露出两个结构性缺口，而且它们会相互放大：

- `context_critical -> propose_recovery -> execute_recovery -> handoff/resume` 仍可在没有新人工指令的情况下反复自动触发；一旦 `session_id`、`fact_snapshot_version` 或 handoff 后状态快照发生变化，既有幂等键就会把它当成一次新的恢复执行；
- 外接模型当前只读取窄化后的 `session record`、`facts` 与 `session_truth`，并没有读到“项目总目标、当前分支/工单目标、当前进度、剩余任务、下一分支/下一工单入口、项目是否已停止推进”等正式真值，因此它无法稳定区分：
  - 继续当前分支；
  - 当前分支已完成，应切换到下一分支/下一工单；
  - 整个项目已完成，应停止自动推进；
  - 当前会话需要恢复，但不应该继续重复 handoff。

这导致系统会对已经停止开发、已完成或已进入 handoff/resume 过程的项目继续重复投递 `Handoff summary`，而且 Markdown 内容偏摘要，不是可直接执行的 continuation instruction。问题的根因不是前端展示，而是 **决策输入、资格门控、路由门控、packet 真值与抑制策略都没有完整落地**。

`WI-085` 的目标不是继续 patch 某一条 prompt，而是把“项目自动推进 / 分支切换 / 恢复续跑 / 停止推进”正式收口为 **model-first、fail-closed、带 lineage 的 continuation governance contract**。

## 范围

### In Scope

- formalize `WI-085` 的 owner、spec / plan / tasks 与后续 `.ai-sdlc` state mirror；
- 新增 **Project Continuation Decision Input**（简称 `PCDI`）作为外接模型与规则回退的统一输入面，显式包含项目级目标、分支级目标、当前进度、剩余任务、下一任务入口与停止推进状态；
- 将外接模型升级为 **model-first decision maker**：优先基于 `PCDI` 做“继续当前分支 / 恢复当前分支 / 切换下一分支 / 项目完成 / 等待人工 / 阻断”判定；
- 新增 **Continuation Eligibility Gate** 与 **Continuation Routing Gate**，并要求任何 handoff / resume / continuation packet 生成前都必须同时通过两道 gate；
- 引入 canonical **Continuation Packet** 真值对象，使 markdown handoff summary 退化为 packet 的渲染视图，而不是 source of truth；
- 为已停止项目、已完成项目、已完成分支、`handoff_in_progress` / `resuming` / `paused` / `waiting_for_direction` / stale snapshot 等状态补齐 suppression、dedupe 与 cooldown；
- 在外接模型失效时引入 **规则回退**，但只允许保守推进，不允许绕过 gate 或放大自动权限；
- 补齐 operator control-plane / audit / regression tests，使系统能明确回答“为什么继续、为什么不继续、继续到哪里、为什么停止”。

### Out of Scope

- 不在 `WI-085` 直接引入新的公网部署、真实组织安装或跨平台集成变更；
- 不把 GitHub merge / publish / release automation 一并并入本工单；
- 不把 continuation governance 退化成 prompt 工程或自由文本模板修补；
- 不允许仅靠前端隐藏消息来“解决”重复 handoff；
- 不在没有 authoritative branch/work-item truth 的情况下自动创建任意新分支或重写历史结论。

## Formal Source

- `src/watchdog/services/brain/provider_runtime.py`
- `src/watchdog/services/brain/service.py`
- `src/watchdog/services/brain/models.py`
- `src/watchdog/services/brain/validator.py`
- `src/watchdog/services/session_spine/orchestrator.py`
- `src/watchdog/services/session_spine/recovery.py`
- `src/watchdog/services/session_spine/facts.py`
- `src/watchdog/services/session_spine/task_state.py`
- `src/watchdog/services/session_spine/actions.py`
- `src/watchdog/services/action_executor/steer.py`
- `src/a_control_agent/api/recovery.py`
- `src/a_control_agent/storage/handoff_manager.py`
- `src/a_control_agent/storage/tasks_store.py`
- `tests/test_watchdog_brain_provider_runtime.py`
- `tests/test_watchdog_policy_engine.py`
- `tests/test_watchdog_policy_decisions.py`
- `tests/test_watchdog_session_spine_runtime.py`
- `tests/test_watchdog_session_spine_api.py`
- `tests/test_watchdog_openclaw_adapter.py`
- `tests/integration/test_openclaw_integration_spine.py`
- `.ai-sdlc/project/config/project-state.yaml`
- `.ai-sdlc/state/checkpoint.yml`
- `.ai-sdlc/state/resume-pack.yaml`
- `specs/084-runtime-truth-and-github-gate-hardening/spec.md`
- `docs/architecture/openclaw-codex-watchdog-full-product-loop-design.md`

## 非 Owner 约束

- **FR-8501**：`WI-085` 必须以外接模型理解为第一优先级；规则引擎只能作为 provider unavailable / invalid / stale / uncertified 时的保守回退，不得与模型并行竞争主判定。
- **FR-8502**：外接模型的正式输入不得再只依赖窄化后的 `session record`，而必须显式包含项目总目标、当前分支目标、当前进度、剩余任务、下一任务入口与项目/分支停止推进状态。
- **FR-8503**：任何 `handoff`、`resume`、`continue_session`、`continuation packet` 生成，必须先通过 eligibility gate 与 routing gate；任何一关失败都只能产生 deduped advisory，不得进入 dispatch queue。
- **FR-8504**：已停止开发、已完成、已归档、已关闭、已进入 branch transition、`handoff_in_progress`、`resuming`、`paused`、`waiting_for_direction` 的项目/会话，不得被自动继续推进。
- **FR-8505**：continuation 的逻辑唯一性必须绑定 `project_id + session_id + native_thread_id + decision_class + logical_target_ref`；`authoritative_snapshot_version` 只能作为 freshness / eligibility 证据，不得单独决定是否生成新 dispatch。
- **FR-8506**：markdown handoff summary 只能作为 `ContinuationPacket` 的渲染视图；不允许继续把 Markdown 文本当作恢复真值、幂等键输入或 routing 依据。
- **FR-8507**：任何 suppression、advisory、decision、packet、resume、branch switch candidate 都必须带 lineage / freshness / provenance，可被 operator surface 与审计日志回放。
- **FR-8508**：规则回退不能比模型路径更激进；在 provider 失效时，不得自动宣称项目完成、自动切换下一分支或重复触发新的 recovery handoff。

## 设计总览

`WI-085` 将自动推进链路收成五个明确组件：

1. **Project Continuation Decision Input (`PCDI`)**
   - 聚合项目级、分支级、会话级真值，成为模型判定与规则回退的唯一输入。
2. **Model-First Decision**
   - 外接模型先基于 `PCDI` 给出结构化 continuation verdict。
3. **Continuation Eligibility Gate**
   - 判定“这个项目/会话现在是否还允许被自动推进”。
4. **Continuation Routing Gate**
   - 判定“如果允许推进，应该继续哪个 thread/session/branch/work-item”。
5. **Continuation Packet**
   - 在两道 gate 都通过后，生成可执行的、可去重的、带 TTL 的 continuation packet，再由 handoff markdown/adapter/UI 进行视图渲染。

系统原则固定为：

> 先有 authoritative context，后有模型判定；先有 gate verdict，后有任何自动动作；先有 packet 真值，后有 summary 文案。

## 核心对象

### 1. Project Continuation Decision Input (`PCDI`)

`PCDI` 是外接模型与规则回退共用的 canonical input，至少必须包含以下字段：

- `project_ref`
  - `project_id`
  - `project_name`
  - `project_execution_state`
  - `project_total_goal`
  - `project_completion_definition`
- `branch_ref`
  - `active_work_item_id`
  - `active_branch`
  - `branch_goal`
  - `branch_completion_signals`
  - `next_work_item_seq`
  - `next_branch_candidate`
- `progress_ref`
  - `current_phase`
  - `current_phase_goal`
  - `latest_summary`
  - `completed_work`
  - `remaining_tasks`
  - `next_recommended_tasks`
  - `files_touched`
- `session_ref`
  - `session_id`
  - `native_thread_id`
  - `task_status`
  - `resume_target_phase`
  - `available_intents`
  - `last_progress_at`
  - `last_event_cursor`
- `governance_ref`
  - `goal_contract_version`
  - `goal_contract_readiness`
  - `pending_approval`
  - `operator_directives`
  - `do_not_continue`
- `freshness_ref`
  - `snapshot_epoch`
  - `snapshot_version`
  - `snapshot_observed_at`
  - `membership_source`
  - `membership_ttl_s`
  - `last_valid_packet_id`
  - `last_valid_packet_at`

`PCDI` 的 authoritative source 顺序固定为：

1. `Session Service + Goal Contract`；
2. `.ai-sdlc/project/config/project-state.yaml`、`.ai-sdlc/state/checkpoint.yml`、`.ai-sdlc/state/resume-pack.yaml`；
3. work-item `spec / plan / tasks / latest-summary`；
4. A-control-agent task/session truth；
5. bounded memory advisory。

任何来自 `memory_advisory_context`、自由文本总结或历史 packet 的内容，只能补充，不得覆盖前四层真值。

此外，`PCDI` 必须满足 **single authoritative snapshot** 硬约束：同一次 decision / fallback / packet reuse 中使用的 `project / branch / session / membership / approval / last_valid_packet` 必须来自同一份不可变 authoritative snapshot，且共享同一 `snapshot_epoch`。任何跨 epoch 拼接、TTL 不一致、membership 与 terminal-state 不同源、approval 与 packet truth 不同源，都必须直接 suppress，而不是交给模型“自行理解”。

### 2. Model-First Continuation Decision

外接模型的正式输出 schema 必须升级为 `provider-continuation-decision-v3`，至少包含：

- `continuation_decision`
  - `continue_current_branch`
  - `recover_current_branch`
  - `branch_complete_switch`
  - `project_complete`
  - `await_human`
  - `blocked`
- `decision_reason`
- `goal_coverage`
- `completion_confidence`
- `remaining_work_hypothesis[]`
- `next_branch_hypothesis`
- `routing_preference`
  - `same_thread`
  - `child_session`
  - `next_branch_session`
  - `none`
- `evidence_codes[]`

其中：

- `continue_current_branch` 表示当前分支目标未完成，且仍应在当前 branch boundary 内继续；
- `recover_current_branch` 表示当前分支目标未完成，但当前 thread/session 不适合直接继续，需要恢复续跑；
- `branch_complete_switch` 表示当前分支目标已经完成，且存在 authoritative 下一分支/下一工单入口；
- `project_complete` 表示项目总目标已满足，系统应停止自动推进；
- `await_human` 表示需要人工决策；
- `blocked` 表示证据不足、状态冲突或无法安全决策。

### 3. Continuation Eligibility Gate

eligibility gate 是 continuation / recovery 的硬门，必须在模型判定之后、任何动作之前执行。它至少检查：

- `project_execution_state` 不是 `stopped / archived / completed / closed`；
- `task_status` 不在 `handoff_in_progress / resuming / paused / waiting_for_direction / waiting_for_approval / completed / failed`；
- 当前 authoritative snapshot 未过期；
- 当前 routing target 仍属于 active membership，且 membership 未过 TTL；
- 不存在 `do_not_continue`、operator freeze、branch transition in progress；
- 自上一个 valid packet 以来存在有效状态增量，或当前 decision class 与上一个 packet 不同；
- goal contract / approval / risk boundary 允许该类动作继续向下游执行。

gate 输出必须是单一真值对象：

- `status = eligible | suppressed`
- `suppression_reason`
- `authoritative_snapshot_version`
- `checked_at`
- `lineage_refs[]`

若 `status=suppressed`，系统只能产生 deduped advisory，不得生成新 packet，不得刷新 handoff markdown，不得写入 dispatch queue。

`pending_approval` 在 eligibility gate 中必须是无条件硬门：只要 `pending_approval=true`，系统就必须强制输出 `await_human` 或 `suppressed`，并同时禁止 packet 创建、route 生成、handoff/resume、branch switch 与 fallback packet reuse；不得存在 advisory-only 的下游继续路径。

### 4. Continuation Routing Gate

routing gate 负责回答“往哪里继续”。它必须同时维护：

- `continuation_identity`
  - `project_id`
  - `session_id`
  - `native_thread_id`
  - `decision_class`
  - `logical_target_ref`
- `route_freshness_ref`
  - `authoritative_snapshot_version`
  - `route_ttl_s`

也就是说，逻辑 continuation 的唯一性与 freshness 必须拆开；快照刷新只能触发重新校验，不能天然生成一条新的 continuation。

它至少输出：

- `routing_status = routed | suppressed`
- `route_kind = same_thread | child_session | next_branch_session | none`
- `continuation_identity`
- `identity_state = issued | consumed | invalidated`
- `route_key`
- `target_project_id`
- `target_session_id`
- `target_thread_id`
- `target_work_item_id`
- `suppression_reason`
- `route_ttl_s`

规则固定为：

- 若当前 decision 为 `continue_current_branch`，优先同 thread 继续；
- 若当前 decision 为 `recover_current_branch`，只允许在当前 branch boundary 内选 `same_thread` 或 `child_session`；
- 任一 `continuation_identity` 在 `identity_state=consumed` 或 `identity_state=invalidated` 前，只允许被 dispatch 一次；同一 identity 不得因 snapshot bump、membership refresh 或模型重跑而重新派发；
- 若当前 decision 为 `branch_complete_switch`，必须先确认 authoritative `next_work_item_seq / next_branch_candidate` 存在且未关闭；
- 若当前 decision 为 `branch_complete_switch`，必须额外生成显式的 `branch_switch_token`，并定义 `issued -> consumed -> invalidated` 生命周期；同一 token 未被消费或未失效前不得再次派发下一分支；
- 若当前 decision 为 `project_complete`，routing gate 必须返回 `suppressed + route_kind=none`，从而阻断任何 continuation packet；
- 任何 route drift、thread ambiguity、snapshot stale、next branch truth 缺失，都必须 suppress。

### 5. Continuation Packet

`ContinuationPacket` 是恢复/续跑的 source of truth。它至少包含：

- `packet_id`
- `packet_version`
- `decision_class`
- `continuation_identity`
- `project_id`
- `session_id`
- `native_thread_id`
- `route_key`
- `target_route`
- `project_total_goal`
- `branch_goal`
- `current_progress_summary`
- `completed_work[]`
- `remaining_tasks[]`
- `first_action`
- `continue_boundary`
- `stop_conditions[]`
- `operator_boundary`
- `source_refs`
  - `goal_contract_version`
  - `authoritative_snapshot_version`
  - `decision_trace_ref`
  - `lineage_refs[]`
- `freshness`
  - `generated_at`
  - `expires_at`
- `dedupe`
  - `dedupe_key`
  - `supersedes_packet_id`
- `packet_state = issued | consumed | invalidated`

handoff markdown / OpenClaw 展示必须改为从 `ContinuationPacket` 渲染，正文最少要能让 Codex App 直接读到：

- 整个项目总目标是什么；
- 当前分支/工单目标是什么；
- 目前已经完成了什么；
- 当前还剩什么；
- 这一轮继续时第一步具体要做什么；
- 在什么条件下应该停止继续并转成人工决策。

“一段摘要”不再满足 contract。

渲染契约还必须满足：

- markdown 是对 packet 的只读、deterministic、lossless 投影；
- markdown 必须显式带出 `packet_id`、`continuation_identity`、`route_key`、`decision_source`、`suppression_reason`（若有）；
- adapter / UI 不得把 markdown 二次改写后重新当成新的 truth、`latest-summary`、`PCDI` 输入、模型输入、route 输入或 dedupe 输入。

## 规则回退

当外接模型满足以下任一条件时，系统进入 rules fallback：

- provider 未配置；
- provider 超时/不可达；
- provider 输出不符合 schema；
- provider certification / freshness 不满足；
- `PCDI` 关键字段缺失，无法构造合格模型输入。

rules fallback 必须遵守：

- 仍然消费同一份 `PCDI`；
- 仍然必须经过 eligibility gate 与 routing gate；
- 只能输出：
  - `continue_current_branch`
  - `await_human`
  - `blocked`
- 只有在存在 fresh 的 `last_valid_packet` 且 route 未漂移时，才允许保守复用已有 continuation packet；
- 复用旧 packet 前，必须重新运行完整的 eligibility / terminal suppression，并重新核对当前 `project_execution_state`、`task_status`、`pending_approval`、`do_not_continue`、operator freeze、`snapshot_epoch`、`continuation_identity` 与 `route_key`；任一变化都必须判定该 packet 已失效，不得 replay；
- 不得在 fallback 中自动判定 `project_complete`、`branch_complete_switch` 或创建新的 recovery handoff。

## 状态与抑制语义

为避免“项目已停但还在发 summary”，`WI-085` 必须把 continuation governance 从单一 task status 扩展到项目级 execution state。至少需要以下 project-level 状态：

- `active`
- `paused`
- `stopped`
- `branch_transition_in_progress`
- `completed`
- `archived`

自动推进只允许 `project_execution_state=active`。一旦项目进入 `stopped / completed / archived`，任何新的 `context_critical`、`repeat_failure`、`stuck_no_progress` 都只能产生 rate-limited advisory，不得再触发 handoff/resume。

同样地，只要项目或分支进入 non-active / terminal 状态，所有已发出的 `ContinuationPacket`、`continuation_identity`、`branch_switch_token` 与 fallback replay 资格都必须立即失效；系统不得再做 route reconstruction、packet reuse、handoff/resume 或 branch switch replay。

## Operator Control Plane

operator surface 至少需要稳定显示：

- 当前 decision verdict；
- 当前 eligibility verdict 与 suppression reason；
- 当前 routing verdict 与 target；
- 最近一次 valid packet；
- packet TTL / freshness；
- 当前项目是否 `active / stopped / completed / archived`；
- 当前分支是否完成、是否存在下一分支入口；
- 判定来源是 `external_model` 还是 `rules_fallback`；
- 谁生成了该 verdict、使用了哪个 schema / model / snapshot；
- `continuation_identity` 当前是否已消费；
- `branch_switch_token` / `transition_token` 当前状态；
- `consumed_at`；
- `last_dispatch_result`；
- `rendered_from_packet_id` 与其内容哈希。

这部分必须成为 operator 可以直接判断“为什么还在推 / 为什么已经停推”的单一控制面，而不是靠翻 audit log 猜。

advisory / suppression / packet dispatch 的限频也必须统一挂在同一控制面节流策略之下，避免 handoff 噪音被简单替换成 advisory 噪音。

## 功能需求

- **FR-8509**：系统必须新增 `PCDI` builder，并把 `.ai-sdlc` project / checkpoint / resume truth、goal contract、session truth、latest-summary/plan/tasks 统一折叠成可审计输入对象。
- **FR-8510**：`provider_runtime` 必须升级为 continuation decision v3 schema，外接模型优先基于 `PCDI` 输出项目/分支级 verdict，而不是仅对 session 事实做局部推断。
- **FR-8511**：`DecisionIntent` / orchestrator / policy 映射必须能显式表达 `continue_current_branch`、`recover_current_branch`、`branch_complete_switch`、`project_complete`、`await_human`、`blocked`。
- **FR-8511A**：`PCDI` builder、rules fallback 与 packet reuse 必须共享同一 `snapshot_epoch`；任何跨 epoch 混合输入都必须 suppress。
- **FR-8512**：任何自动 continuation / recovery 执行前，必须先通过 `ContinuationEligibilityGate`；任何失败都必须返回可审计 suppression reason。
- **FR-8513**：任何 packet / handoff / resume 生成前，必须先通过 `ContinuationRoutingGate`；routing gate 必须同时产出稳定的 `continuation_identity` 与独立的 freshness 证据，不能把 snapshot bump 直接当成新 route。
- **FR-8513A**：continuation identity 必须与 snapshot freshness 拆离；同一逻辑 continuation 不能因为 snapshot bump 就被视为新的 dispatch。
- **FR-8513B**：任何 `continuation_identity` 必须具有显式 `issued / consumed / invalidated` 生命周期；同一 identity 在未失效前不得重复 dispatch。
- **FR-8514**：`context_critical` 在 `handoff_in_progress`、`resuming`、`branch_transition_in_progress`、`project_execution_state!=active`、stale snapshot、no delta、do_not_continue 场景下必须被 suppress，不得重复触发新 handoff。
- **FR-8515**：`ContinuationPacket` 必须成为恢复/续跑真值，Markdown summary 只能由 packet 渲染，且必须含有“项目总目标、当前分支目标、当前进度、剩余任务、第一步动作、停止条件”。
- **FR-8515A**：packet 渲染必须是 deterministic / lossless 投影，并显式带出 `packet_id`、`continuation_identity`、`route_key` 与 `decision_source`。
- **FR-8515B**：markdown 渲染不得回写进 `latest-summary`、`PCDI`、模型输入或任何 authoritative truth 链路。
- **FR-8516**：系统必须为 `execute_recovery` 建立与 `continue_session` 同级的 dedupe / cooldown / suppression contract，且 advisory 也必须限频。
- **FR-8517**：当模型判定 `branch_complete_switch` 时，系统必须先验证 authoritative `next_work_item_seq / next_branch_candidate`；验证失败时降级为 `await_human` 或 `blocked`，不得假设下一分支存在。
- **FR-8517A**：`branch_complete_switch` 必须带单次消费的 `transition_token / transition_epoch`；同一 branch completion verdict 未被消费或未过期前，不得重复切出下一分支会话。
- **FR-8517B**：`branch_switch_token` 必须具有显式 `issued / consumed / invalidated` 生命周期，并在 consume/invalidate 后写回 authoritative truth。
- **FR-8518**：当模型判定 `project_complete` 时，系统必须把项目推进状态切到非 `active`，并阻断所有后续自动 continuation / recovery。
- **FR-8519**：rules fallback 必须消费与模型同构的 `PCDI`，并且只能保守推进，不得产生更高权限动作。
- **FR-8519A**：rules fallback 复用旧 packet 前必须重新校验当前 `project_execution_state`、`pending_approval`、`do_not_continue`、operator freeze、snapshot freshness 与 route identity。
- **FR-8519B**：只要当前 state 进入 non-active / terminal / approval-blocked，系统必须立即使旧 packet reuse 资格失效，不能继续 replay。
- **FR-8520**：所有 decision / suppression / packet / route verdict 必须落审计与 operator projection，支持 replay 与回归验证。

## 验证要求

- `uv run pytest -q tests/test_watchdog_brain_provider_runtime.py tests/test_watchdog_policy_engine.py tests/test_watchdog_policy_decisions.py tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_session_spine_api.py tests/test_watchdog_openclaw_adapter.py tests/integration/test_openclaw_integration_spine.py`
- `uv run pytest -q`
- `uv run ruff check`
- `uv run python -m ai_sdlc verify constraints`
- `uv run python -m ai_sdlc status`
