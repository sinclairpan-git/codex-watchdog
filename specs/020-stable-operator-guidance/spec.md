---
related_doc:
  - "codex-watchdog-prd.md"
  - "docs/architecture/codex-watchdog-g0-and-v010-design.md"
  - "specs/010-runtime-integration-spine/spec.md"
  - "specs/014-stable-supervision-evaluation/spec.md"
  - "specs/019-stable-workspace-activity/spec.md"
---

# Stable Operator Guidance — 功能规格说明

## 概述

在 `010-019` 已经建立 stable session spine、events、receipts、recovery、supervision、workspace activity 与 Feishu adapter 之后，当前仍有一个明显的 legacy write seam：

- Codex runtime service 已经提供 `POST /api/v1/tasks/{project_id}/steer`；
- Watchdog 内部也已经通过 `continue_session` / `evaluate_supervision` 间接复用 steer；
- 但上层调用方还没有一个稳定、版本化、可幂等的“显式人工指导”动作模型，只能继续依赖 raw `/steer`。

020 的唯一目标固定为：

> 建立 stable operator-guidance write surface，让 Feishu 与其他上层调用方能够通过 Watchdog canonical `WatchdogAction` 提交最小可控的人类指导消息，而不是直接绑定 Codex runtime service raw `/steer`。

## 功能需求

- **FR-2001**：020 必须新增稳定动作枚举 `ActionCode.POST_OPERATOR_GUIDANCE`，canonical write surface 仍固定为：
  - `POST /api/v1/watchdog/actions`
- **FR-2002**：020 必须新增人类友好的 alias route：
  - `POST /api/v1/watchdog/sessions/{project_id}/actions/post-guidance`
- **FR-2003**：canonical action body 固定为 `WatchdogAction(action_code=post_operator_guidance)`，其中 stable 参数只允许通过 `arguments` 传递：
  - `arguments.message`：必填，非空字符串
  - `arguments.reason_code`：可选，默认 `operator_guidance`
  - `arguments.stuck_level`：可选，范围 `0..4`
- **FR-2004**：alias route 必须把以下 top-level 字段映射到同一套 stable `WatchdogAction.arguments`：
  - `message`
  - `reason_code`
  - `stuck_level`
  - 同时继续接受 `operator`、`idempotency_key`、`note`
- **FR-2005**：020 的动作执行必须复用既有 `post_steer(...)` executor，不得新开直连 Codex runtime service 的平行实现。
- **FR-2006**：动作执行成功时必须返回稳定 `WatchdogActionResult`：
  - `action_code=post_operator_guidance`
  - `action_status=completed`
  - `effect=steer_posted`
  - `reply_code=action_result`
- **FR-2007**：当 `arguments.message` 缺失、为空或 `stuck_level` 非法时，020 必须返回稳定错误结果，而不是让 alias route 和 adapter 各自临时校验：
  - `action_status=error`
  - `reply_code=action_not_available`
- **FR-2008**：020 必须支持 Feishu adapter intent：
  - `post_operator_guidance`
  - 该 intent 必须映射到 `ActionCode.POST_OPERATOR_GUIDANCE`
- **FR-2009**：020 必须保持 `request_recovery`、`evaluate_supervision` 与 `continue_session` 的既有 steer 语义不变；新增 operator guidance 不得改变原有动作效果、receipt key 或监督逻辑。
- **FR-2010**：020 引入新的 stable action code，因此 session spine `schema_version` 必须从 `2026-04-05.019` 推进到 `2026-04-05.020`。
- **FR-2011**：README、getting-started 与 OpenAPI 必须明确写清：
  - `/api/v1/watchdog/actions`：canonical stable operator-guidance write surface
  - `/api/v1/watchdog/sessions/{project_id}/actions/post-guidance`：human-friendly alias
  - `/api/v1/tasks/{project_id}/steer`：legacy raw route，继续存在但不承担 stable contract 角色
- **FR-2012**：020 必须补齐契约测试、action/idempotency 测试、API 测试、adapter 测试、最小 integration 测试，以及 raw `/steer` 非回归测试。

### 用户故事 1：上层可以通过稳定动作显式提交人工指导

Feishu 需要向某个 session 注入一段最小人工指导，而不直接依赖 raw `/steer`。

场景 1：调用 `POST /api/v1/watchdog/actions`，提交 `WatchdogAction(action_code=post_operator_guidance)` 与非空 `arguments.message`，返回 `WatchdogActionResult(effect=steer_posted)`。

场景 2：相同 `project_id + idempotency_key` 重试不会重复下发 steer。

### 用户故事 2：canonical route、alias route 与 adapter 共享同一套稳定语义

同一个 operator guidance 请求在 HTTP canonical、HTTP alias 和 Feishu adapter 上必须复用同一套稳定执行结果。

场景 1：alias route `POST /api/v1/watchdog/sessions/{project_id}/actions/post-guidance` 返回与 canonical route 同源的 `WatchdogActionResult`。

场景 2：adapter `post_operator_guidance(project_id=..., arguments.message=...)` 返回与 HTTP route 同源的 `ReplyModel(reply_code=action_result)`。

### 用户故事 3：legacy `/steer` 继续存在，但不再是 stable write contract

已有脚本与历史调用可能仍直接依赖 Codex runtime service raw steer route。

场景 1：020 落地后，`POST /api/v1/tasks/{project_id}/steer` 继续工作且基础行为不回归。

场景 2：文档明确 stable operator guidance 与 raw steer 的角色边界。

## 非目标

- 不新增 supervisor 策略、常驻监管或自动恢复策略。
- 不扩展为任意 channel/runtime guidance transport。
- 不为 operator guidance 新增独立 receipt schema、事件 schema 或 reply code。
- 不改变既有 `continue_session`、`request_recovery`、`execute_recovery`、`evaluate_supervision`、审批动作的 contract。
- 不移除 raw `/api/v1/tasks/{project_id}/steer`。
