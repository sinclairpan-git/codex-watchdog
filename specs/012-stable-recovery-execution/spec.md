---
related_doc:
  - "codex-watchdog-prd.md"
  - "docs/architecture/codex-watchdog-g0-and-v010-design.md"
  - "specs/005-m4-recovery/spec.md"
  - "specs/010-runtime-integration-spine/spec.md"
  - "specs/011-stable-session-events/spec.md"
---

# Stable Recovery Execution — 功能规格说明

## 概述

在 `010-runtime-integration-spine` 冻结 advisory-only `request_recovery`、`011-stable-session-events` 冻结只读 stable event surface 之后，`012-stable-recovery-execution` 的目标是继续补齐 **真实恢复执行的稳定动作面**：让 Feishu 与其他上层调用方能够通过 canonical `WatchdogAction -> WatchdogActionResult` 触发最小恢复闭环，而不是继续依赖 legacy `/watchdog/tasks/{project_id}/recover` 路径级编排。

012 的唯一目标固定为：

> 在不改写 `request_recovery` advisory-only 语义的前提下，新增稳定 `execute_recovery` 动作，完成 `critical -> handoff -> optional resume` 的最小稳定执行闭环，并保持 legacy recover route 非回归。

## 功能需求

- **FR-1201**：012 必须在现有中立 `session_spine` contract 上新增真实恢复执行动作；不得把 `request_recovery` 从 advisory-only 偷改成 side-effect action。
- **FR-1202**：012 至少冻结以下新增稳定契约元素：`ActionCode.execute_recovery`、`ReplyCode.recovery_execution_result`、`Effect.handoff_triggered`、`Effect.handoff_and_resume`。
- **FR-1203**：012 必须继续使用 `POST /api/v1/watchdog/actions` 作为 canonical stable write route；动作体仍为 `WatchdogAction`，结果仍为 `WatchdogActionResult`。
- **FR-1204**：Watchdog 必须提供人类友好的 alias route `POST /api/v1/watchdog/sessions/{project_id}/actions/execute-recovery`，但该 alias 只是 canonical action 的包装器，不是主契约。
- **FR-1205**：`execute_recovery` 成功执行前必须先读取稳定投影所依赖的任务事实；当 `context_pressure != critical` 时，动作必须返回稳定 `noop` 结果，不得调用 Codex runtime service `handoff` 或 `resume`。
- **FR-1206**：当 `context_pressure == critical` 时，`execute_recovery` 必须调用 Codex runtime service `POST /api/v1/tasks/{project_id}/handoff`；若 `recover_auto_resume=true`，则在 handoff 成功后继续尝试 `POST /api/v1/tasks/{project_id}/resume`。
- **FR-1207**：`execute_recovery` 的稳定结果必须通过 `WatchdogActionResult.action_status`、`effect`、`reply_code`、`message` 与 `facts` 表达最小执行语义；不得把 legacy raw response 结构直接泄漏为 stable contract。
- **FR-1208**：当 handoff 成功但 auto-resume 失败时，`execute_recovery` 必须返回一个稳定、可重试、已记录 handoff 的结果；不得因为 resume 失败而丢失 handoff 成功事实。
- **FR-1209**：Feishu adapter spine 必须新增 `execute_recovery` intent，并将其映射到 stable `WatchdogActionResult -> ReplyModel(reply_code=recovery_execution_result)`。
- **FR-1210**：`request_recovery` 必须继续保持 advisory-only，`ReplyCode.recovery_availability` 与 `Effect.advisory_only` 语义不得变化。
- **FR-1211**：legacy raw route `POST /api/v1/watchdog/tasks/{project_id}/recover` 必须继续保留既有行为与注册路径，不承担 stable contract 角色。
- **FR-1212**：012 必须显式推进 session spine schema version，以反映 stable action enum 的新增；`contract_version` 继续保持 `watchdog-session-spine/v1alpha1`。
- **FR-1213**：012 必须补齐契约测试、恢复编排测试、stable API 测试、adapter 测试、最小集成测试，以及 legacy recover 非回归测试。

### 用户故事 1：上层通过稳定动作面执行真实恢复

Feishu 需要在会话进入 `critical` 时执行真实恢复，但不能围绕 legacy recover route 的路径和返回体编程。

场景 1：调用 `POST /api/v1/watchdog/actions` 并提交 `WatchdogAction(action_code=execute_recovery)`，在 `critical` 条件下获得 `WatchdogActionResult(reply_code=recovery_execution_result, effect=handoff_triggered|handoff_and_resume)`。

场景 2：重复提交同一 `(action_code, project_id, idempotency_key)` 时，不重复触发 handoff / resume。

### 用户故事 2：非 critical 会话不会被误触发恢复

上层需要把“可执行恢复”与“当前不该恢复”区分清楚。

场景 1：当 `context_pressure=low|medium` 时，`execute_recovery` 返回稳定 `noop` 结果。

场景 2：上述 `noop` 不触发任何 handoff / resume side effect。

### 用户故事 3：010 的 advisory-only 契约保持不变

上层仍然可以先问“能不能恢复”，再决定是否执行真实恢复。

场景 1：`request_recovery` 继续返回 `reply_code=recovery_availability`。

场景 2：`execute_recovery` 与 `request_recovery` 并存，但语义不混淆。

## 非目标

- 不把 `request_recovery` 升级成真实恢复执行器。
- 不引入 supervisor、自动循环恢复策略、重试编排器或多步恢复流程图引擎。
- 不新增渠道 runtime、飞书集成或跨渠道通知。
- 不修改 011 stable event model 去合成动作回执事件。
- 不废弃 legacy `/watchdog/tasks/{project_id}/recover`；012 只要求其非回归并与 stable action 并存。
