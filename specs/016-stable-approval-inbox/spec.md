---
related_doc:
  - "openclaw-codex-watchdog-prd.md"
  - "docs/architecture/openclaw-codex-watchdog-g0-and-v010-design.md"
  - "specs/010-openclaw-integration-spine/spec.md"
  - "specs/015-stable-session-explanations/spec.md"
---

# Stable Approval Inbox — 功能规格说明

## 概述

在 `010-015` 完成 session spine、事件、恢复执行、监管评估、receipt 与 explanation 之后，Watchdog 对 OpenClaw 的 stable surface 还剩一个明显缺口：

- session 级 `pending-approvals` 已稳定化；
- approve / reject 写动作也已经进入 canonical `WatchdogAction -> WatchdogActionResult`；
- 但“跨项目查看当前待处理审批”的入口仍只有 legacy `/api/v1/watchdog/approvals` raw proxy。

这意味着上层如果要做全局 approvals inbox，只能继续消费 A-Control-Agent 的 raw approvals payload，而不是 Watchdog 的中立 stable contract。

016 的唯一目标固定为：

> 建立 stable approval inbox read surface，让 OpenClaw 与其他调用方能够读取跨项目 pending approvals 的稳定 `ReplyModel + ApprovalProjection[]`，同时保持现有 raw `/watchdog/approvals` 与 `/decision` 兼容接口不变。

## 功能需求

- **FR-1601**：016 必须补一个独立 stable approval inbox read surface；不得把 stable 语义直接塞回 legacy `/api/v1/watchdog/approvals` raw proxy。
- **FR-1602**：016 的 canonical stable route 固定为：
  - `GET /api/v1/watchdog/approval-inbox`
- **FR-1603**：该 route 只覆盖 `pending approvals` inbox；不扩张为已批准 / 已拒绝历史查询，也不提供任意 status passthrough。
- **FR-1604**：route 必须返回既有 `ReplyModel`，其中：
  - `reply_kind=approvals`
  - `reply_code=approval_inbox`
  - `intent_code=list_approval_inbox`
  - `approvals` 为稳定 `ApprovalProjection[]`
- **FR-1605**：016 可以支持可选 `project_id` query 参数，用于把全局 inbox 收窄到单项目；但无论是否传入 `project_id`，都只能返回 `pending` 审批。
- **FR-1606**：approval inbox 必须继续复用既有 `ApprovalProjection`，不得引入新的 parallel DTO，也不得把 raw approvals payload 直接透传给 stable route。
- **FR-1607**：016 必须推进 session spine schema version，并把新增 `reply_code=approval_inbox` 作为正式稳定契约的一部分；`contract_version` 继续保持 `watchdog-session-spine/v1alpha1`。
- **FR-1608**：OpenClaw adapter 必须新增 `list_approval_inbox` intent，并返回与 HTTP stable route 同源的 `ReplyModel`；不得在 adapter 层自己直连 raw `/watchdog/approvals`。
- **FR-1609**：016 不新增新的 write action。approve / reject 仍通过既有 stable action surface 完成；legacy `/api/v1/watchdog/approvals/{approval_id}/decision` 继续只做兼容。
- **FR-1610**：016 必须补齐 contract 测试、stable inbox API 测试、adapter 测试、以及 raw `/watchdog/approvals` / `/decision` 的非回归测试。
- **FR-1611**：README、getting-started 与 OpenAPI 必须把 approval inbox 纳入 stable read surface，并明确它与 session 级 `pending-approvals` 的区别：
  - `pending-approvals`：单项目会话视角
  - `approval-inbox`：跨项目待处理审批视角

### 用户故事 1：OpenClaw 查看全局待审批队列

OpenClaw 需要知道当前有哪些项目正在等人做审批决策，而不是先知道某个 project_id。

场景 1：调用 `GET /api/v1/watchdog/approval-inbox`，返回多个项目的 `ApprovalProjection[]`。

场景 2：返回体中的每个审批都带 `project_id`、`thread_id` 与 `native_thread_id`，便于上层继续跳转或发起 stable approve/reject action。

### 用户故事 2：按项目收窄 inbox，但不退回 raw queue

上层已经知道 `project_id`，但仍希望用全局 inbox 同一套稳定语义，而不是退回 session 特化 route。

场景 1：调用 `GET /api/v1/watchdog/approval-inbox?project_id=repo-a`，仅返回 `repo-a` 的 pending approvals。

场景 2：route 返回 `ReplyModel(reply_code=approval_inbox)`，而不是复用 legacy `/watchdog/approvals` raw body。

### 用户故事 3：Adapter 与 HTTP 共享同一 stable inbox 语义

同一个审批队列从 adapter 和 HTTP 看上去应该是同一份 stable contract。

场景 1：OpenClaw adapter `list_approval_inbox` 返回的 `reply_code` 与 HTTP route 完全一致。

场景 2：adapter 侧不会再写一套 ad-hoc approvals list 映射逻辑。

## 非目标

- 不新增 approval history、cursor、分页、排序或聚合统计协议。
- 不改变 session 级 `GET /api/v1/watchdog/sessions/{project_id}/pending-approvals` 的既有稳定语义。
- 不改变 approve / reject / request_recovery / execute_recovery / evaluate_supervision 的动作面。
- 不替换或删除 legacy `/api/v1/watchdog/approvals` 与 `/api/v1/watchdog/approvals/{approval_id}/decision`。
