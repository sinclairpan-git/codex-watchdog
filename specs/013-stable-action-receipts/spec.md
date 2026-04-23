---
related_doc:
  - "codex-watchdog-prd.md"
  - "docs/architecture/codex-watchdog-g0-and-v010-design.md"
  - "specs/010-runtime-integration-spine/spec.md"
  - "specs/011-stable-session-events/spec.md"
  - "specs/012-stable-recovery-execution/spec.md"
---

# Stable Action Receipts — 功能规格说明

## 概述

在 `010-runtime-integration-spine` 冻结 stable read/write spine、`011-stable-session-events` 冻结只读 stable event surface、`012-stable-recovery-execution` 冻结真实恢复执行动作之后，`013-stable-action-receipts` 的目标是继续补齐 **稳定 receipt 查询面**：让 Feishu 与其他上层调用方能够读取 Watchdog 已持久化的幂等动作结果，而不是通过重复提交动作、猜测副作用是否已发生，或绑定 legacy / transport 层返回体。

013 的唯一目标固定为：

> 建立 stable action receipt query surface，使上层可以按 `(action_code, project_id, approval_id?, idempotency_key)` 读取稳定、版本化的动作收据结果，而不是重复执行动作或依赖 raw/legacy 返回体。

## 功能需求

- **FR-1301**：013 必须在现有中立 `session_spine` contract 上新增稳定收据查询语义；不得把 receipt 查询塞进 `feishu` 命名空间或 legacy 路由中。
- **FR-1302**：013 至少冻结以下新增稳定契约元素：`ActionReceiptQuery`、`ReplyCode.action_receipt`、`ReplyCode.action_receipt_not_found`，以及 `ReplyModel.action_result`。
- **FR-1303**：013 必须提供 canonical stable read route：`GET /api/v1/watchdog/action-receipts`；其查询条件至少包括 `action_code`、`project_id`、`idempotency_key`，并允许可选 `approval_id`。
- **FR-1304**：013 可以提供人类友好的 alias route `GET /api/v1/watchdog/sessions/{project_id}/action-receipts/{action_code}/{idempotency_key}`，但该 alias 只是 canonical query 的包装器，不是主契约。
- **FR-1305**：当 receipt 存在时，stable read route 必须返回 `ReplyModel(reply_kind=action_result, reply_code=action_receipt)`，并在 `action_result` 字段中承载稳定 `WatchdogActionResult`；不得泄漏底层存储文件格式。
- **FR-1306**：当 receipt 不存在时，stable read route 必须返回稳定 `ReplyModel(reply_kind=action_result, reply_code=action_receipt_not_found)`；不得通过重新执行动作来“补齐”结果，也不得直接把 transport 404 当作唯一语义表达。
- **FR-1307**：receipt 查询必须严格复用 Watchdog 已冻结的幂等键模型：`(action_code, project_id, approval_id, idempotency_key)`；不得新增旁路 key 生成规则。
- **FR-1308**：Feishu adapter spine 必须新增 `get_action_receipt` intent，并将其映射到 stable `ReplyModel`；adapter 不得直接读取 `action_receipts.json`。
- **FR-1309**：013 的 receipt 查询必须只依赖 Watchdog 本地 `ActionReceiptStore`；不得重新访问 Codex runtime service、不得重放 side effect、不得调用 legacy recover / approvals / steer 路由来推断结果。
- **FR-1310**：013 必须显式推进 session spine schema version，以反映新增 query object / reply code / reply payload 字段；`contract_version` 继续保持 `watchdog-session-spine/v1alpha1`。
- **FR-1311**：013 必须补齐契约测试、receipt lookup 测试、stable API 测试、adapter 测试、最小集成测试，以及对既有 stable action/write 逻辑的非回归验证。

### 用户故事 1：上层查询已提交动作的稳定结果

Feishu 在提交 `continue_session`、`approve_approval`、`execute_recovery` 之后，需要能按同一幂等键读取已持久化结果，而不是再次执行相同动作。

场景 1：调用 `GET /api/v1/watchdog/action-receipts?action_code=continue_session&project_id=repo-a&idempotency_key=idem-continue-1`，获得 `ReplyModel(reply_code=action_receipt)`，其中 `action_result.effect=steer_posted`。

场景 2：对 `execute_recovery` 使用相同查询键，可获得 `WatchdogActionResult(reply_code=recovery_execution_result)`，而无需重新触发 handoff / resume。

### 用户故事 2：receipt 缺失时返回稳定“未找到”语义

上层需要把“当前没有这个 receipt”与“网络失败 / 上游不可达”区分清楚。

场景 1：查询一个不存在的 `(action_code, project_id, idempotency_key)`，返回 `ReplyModel(reply_code=action_receipt_not_found)`。

场景 2：上述未找到结果不触发任何 side effect，也不访问 Codex runtime service。

### 用户故事 3：approval receipt 查询不引入新 key 模型

审批动作的 receipt 需要继续绑定既有幂等 tuple，而不是偷偷换主键。

场景 1：查询 `approve_approval` / `reject_approval` receipt 时，可额外提供 `approval_id`。

场景 2：receipt key 仍与 `010` 已冻结的幂等语义保持一致。

## 非目标

- 不把 `WatchdogActionResult` 并入 `011` stable session event model。
- 不引入 action receipt SSE、cursor/backfill、WebSocket 或常驻 supervisor。
- 不新增 side effect，也不把 receipt 查询升级成重试执行器。
- 不改写 `010-012` 已有 canonical write surface、legacy raw 路由或 advisory-only recovery 语义。
- 不让 Feishu adapter 直接读本地 receipt 存储文件。
