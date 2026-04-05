---
related_doc:
  - "openclaw-codex-watchdog-prd.md"
  - "docs/architecture/openclaw-codex-watchdog-g0-and-v010-design.md"
---

# OpenClaw Integration Spine — 功能规格说明

## 概述

在 `008-codex-live-control-plane` 与 `009-task-events-stream` 已完成的基础上，`010-openclaw-integration-spine` 不再扩张底层能力，而是补齐 **OpenClaw 可稳定消费的会话监管骨架**：通过 **中立 contract 包 + L2 稳定投影层 + L3 独立 adapter spine**，完成 `intent -> session projection / watchdog action -> reply model` 的最小可用闭环。

010 的唯一目标固定为：

> 建立 OpenClaw 可稳定消费的会话监管骨架，完成 `intent -> session projection / watchdog action -> reply model` 的最小可用闭环，而非实现完整实时监管与自动恢复体系。

## 功能需求

- **FR-1001**：010 必须先定义中立 contract 包，稳定对象、枚举与版本语义不得落在 `openclaw` 命名空间下，也不得依附于渠道 runtime 语义。
- **FR-1002**：010 至少冻结以下稳定契约对象：`SessionProjection`、`TaskProgressView`、`FactRecord`、`ApprovalProjection`、`WatchdogAction`、`WatchdogActionResult`、`ReplyModel`。
- **FR-1003**：所有 stable contract 必须显式携带 `contract_version` 与 `schema_version`；`SessionProjection` 与 `TaskProgressView` 必须显式区分 `thread_id` 与 `native_thread_id`。
- **FR-1004**：Watchdog 必须提供 L2 稳定投影层，把 raw task / approval / stuck signal / control-link state 归并为 `SessionProjection`、`TaskProgressView` 与 `FactRecord[]`，OpenClaw 不得直接依赖 A-Control-Agent 原始任务对象或其字段形状。
- **FR-1005**：`FactRecord` 必须作为稳定解释原子，为 `why_stuck`、`explain_blocker` 与 `request_recovery` 的解释路径提供统一来源；这三类语义不得再由 adapter 临时拼接字符串替代。
- **FR-1006**：010 的最小 read intent 集固定为：`get_session`、`get_progress`、`why_stuck`、`explain_blocker`、`list_pending_approvals`。
- **FR-1007**：010 的最小 write intent / action 集固定为：`continue_session`、`request_recovery`、`approve_approval`、`reject_approval`。
- **FR-1008**：`request_recovery` 在 010 中只允许返回恢复可用性说明；不得执行 handoff、resume、新线程续跑或任何自动恢复编排。
- **FR-1009**：Watchdog 必须以 `WatchdogAction -> WatchdogActionResult` 作为 canonical stable write contract，并提供 `POST /api/v1/watchdog/actions` 作为 canonical stable write route。
- **FR-1010**：若保留人类友好的路径级动作路由，它们只能作为 canonical action route 的包装别名；不得形成第二套结果模型或旁路幂等逻辑。
- **FR-1011**：Watchdog 必须提供最小稳定 read API 面，至少覆盖：
  - `GET /api/v1/watchdog/sessions/{project_id}`
  - `GET /api/v1/watchdog/sessions/{project_id}/progress`
  - `GET /api/v1/watchdog/sessions/{project_id}/pending-approvals`
- **FR-1012**：上述 read API 的语义返回值必须是 `ReplyModel`；write API 的语义返回值必须是 `WatchdogActionResult`。当前仓库的 `ok/err` envelope 只作为 transport wrapper，不得替代 semantic contract。
- **FR-1013**：`ReplyModel` 必须同时包含 `reply_kind` 与 `reply_code`；010 至少冻结以下 `reply_code`：`session_projection`、`task_progress_view`、`stuck_explanation`、`blocker_explanation`、`approval_queue`、`approval_result`、`action_result`、`recovery_availability`、`control_link_error`、`unsupported_intent`。
- **FR-1014**：OpenClaw adapter spine 必须作为 L3 独立层存在，只消费中立 contract 与 stable API / service；不得直连 A-Control-Agent、不得直连 SSE、不得混入飞书或其他渠道运行时代码。
- **FR-1015**：所有 write action 必须支持最小幂等设计；相同 `(action_code, project_id, approval_id, idempotency_key)` 的重试必须返回相同 `WatchdogActionResult` 或稳定 `noop` 结果。
- **FR-1016**：`continue_session` 在 010 中只允许复用当前仓库已存在的最小安全路径；当前实现阶段默认通过 Watchdog 既有 `evaluate -> steer` 链路完成，不得借机引入完整自动恢复、后台 supervisor 或渠道侧补逻辑。
- **FR-1017**：010 必须补齐三层验证：稳定契约测试、adapter spine 适配层测试、最小集成测试；这些测试必须围绕完整最小契约，而不是围绕被简化后的路径动作集合。
- **FR-1018**：010 明确不交付完整实时事件覆盖、常驻 supervisor、全量自动恢复闭环、飞书/渠道运行时代码，以及任何跨层偷实现。

### 用户故事 1：OpenClaw 稳定读取会话与进展

OpenClaw 需要获取项目会话的稳定身份、进展与解释，但不希望耦合到底层 task schema。

场景 1：调用 `GET /api/v1/watchdog/sessions/{project_id}`，获得稳定 `SessionProjection`。

场景 2：调用 `GET /api/v1/watchdog/sessions/{project_id}/progress`，获得稳定 `TaskProgressView` 与对应事实来源。

场景 3：即便底层 `TaskStore` 字段后续扩展，OpenClaw 仍只依赖稳定枚举、受控字段集与 `reply_code`。

### 用户故事 2：OpenClaw 解释“为什么卡住 / 为什么被阻塞”

OpenClaw 需要稳定回答“为什么卡住了”与“当前阻塞点是什么”，且答案不能依赖渠道端临时拼文案。

场景 1：调用 `why_stuck` 时，adapter 基于 `FactRecord` 输出 `reply_code=stuck_explanation`。

场景 2：调用 `explain_blocker` 时，adapter 基于 `FactRecord` 输出 `reply_code=blocker_explanation`，并给出相关 `approval_id` 或链路事实。

### 用户故事 3：OpenClaw 发起一次最小 continue 动作

OpenClaw 需要向 Watchdog 发出一次“继续推进”的最小稳定动作。

场景 1：调用 `POST /api/v1/watchdog/actions` 并提交 `WatchdogAction(action_code=continue_session)`，Watchdog 复用现有最小安全 continue 路径并返回统一 `WatchdogActionResult`。

场景 2：若当前条件不允许推进，返回稳定的 `blocked` / `noop` 结果，而不是暴露底层异常细节或旁路行为。

### 用户故事 4：OpenClaw 请求恢复建议但不执行恢复

OpenClaw 需要询问“当前是否适合恢复”，但 010 不应真的执行恢复动作。

场景 1：调用 `POST /api/v1/watchdog/actions` 并提交 `WatchdogAction(action_code=request_recovery)`，系统返回 `reply_code=recovery_availability`。

场景 2：返回结果中可以说明“可恢复 / 不可恢复 / 建议下一步”，但不得触发 handoff、resume 或新线程续跑。

### 用户故事 5：OpenClaw 稳定处理审批

OpenClaw 需要展示待审批项并允许人工通过或拒绝，且动作结果可重试。

场景 1：调用 `GET /api/v1/watchdog/sessions/{project_id}/pending-approvals`，拿到稳定 `ApprovalProjection[]`。

场景 2：调用 `POST /api/v1/watchdog/actions` 并提交 `approve_approval` / `reject_approval`，获得统一 `WatchdogActionResult` 或 adapter 层 `ReplyModel(reply_code=approval_result)`。

场景 3：同一个 `idempotency_key` 重试不会造成重复审批副作用。

## 非目标

- 不把 `GET .../events` 的 SSE 或任何 WebSocket 纳入 010 stable contract。
- 不实现常驻 supervisor 或定时后台监管。
- 不实现真实 handoff / resume / 新线程恢复执行闭环。
- 不实现飞书或其他渠道运行时代码。
- 不让 OpenClaw 直连 A-Control-Agent，也不让 stable API 原样透出 raw envelope。
- 不把 `why_stuck` / `explain_blocker` 无声移出 scope；它们在 010 中是正式范围，而不是可选文案行为。
