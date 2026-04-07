---
related_doc:
  - "docs/architecture/openclaw-codex-watchdog-full-product-loop-design.md"
  - "specs/026-canonical-action-approval-response-loop/spec.md"
---

# Outbox / Delivery / Retry / Receipt — 功能规格说明

## 概述

`027-outbox-delivery-retry-receipt` 是完整产品闭环中的 `WI-4`。它的目标是把 envelope 投递补成可靠系统，让 Watchdog 主动通知 OpenClaw 时具备持久 outbox、顺序语义、重试、去重与 receipt 确认。

## 功能需求

- **FR-2701**：027 必须引入持久化 `decision_outbox` 与 `delivery_outbox`。
- **FR-2702**：027 必须引入 `outbox_seq`，作为同一投递流内的稳定单调顺序语义；`created_at` 不能作为最终 tie-breaker。
- **FR-2703**：027 必须按决策结果类型冻结投递矩阵：
  - `auto_execute_and_notify` -> `DecisionEnvelope`，再 `NotificationEnvelope(notification_kind=decision_result)`
  - `require_user_decision` -> 先只发 `ApprovalEnvelope`；用户响应后再发 `NotificationEnvelope(notification_kind=approval_result)`
  - `block_and_alert` -> 只发 `NotificationEnvelope(severity=critical)`
- **FR-2704**：027 必须保证同一 `session_id` 下，先按 `fact_snapshot_version`，再按持久化单调序号投递。
- **FR-2705**：027 必须允许不同 session 并行投递，但同一 session 不得乱序。
- **FR-2706**：027 必须把 `envelope_id` 作为投递幂等主键；OpenClaw 回调失败重试时 `envelope_id` 不得变化。
- **FR-2707**：027 必须把 delivered 条件收紧为：
  - HTTP `2xx`
  - `accepted = true`
  - 响应体 `envelope_id` 与请求一致
  - 存在 `receipt_id`
- **FR-2708**：027 必须把 `408`、`429`、`5xx` 与网络超时视为 retryable failure。
- **FR-2709**：027 必须把协议不完整的 `2xx` 视为 retryable failure，而不是 delivered。
- **FR-2710**：027 必须实现指数退避与最大重试上限；超过上限后必须落 `delivery_failed` 并让后续通知层可发 critical 告警。
- **FR-2711**：027 必须补齐测试，至少锁住：
  - 投递矩阵
  - 顺序语义
  - `envelope_id` 幂等
  - delivered 判定
  - retry/backoff
  - 死信/失败升级
- **FR-2712**：027 不得重跑 policy engine，不得承担 action / approval 业务判定。
- **FR-2713**：027 不得生成第二套业务状态机；只消费 canonical decision / execution / approval result records。

### 用户故事 1：服务主动通知不会因为瞬时网络错误而丢失

场景 1：OpenClaw 短暂返回 `503`，delivery worker 自动重试而不是丢通知。

场景 2：重试期间同一个 envelope 维持同一个 `envelope_id`，宿主可安全去重。

### 用户故事 2：同一会话的 envelope 不会乱序到达

场景 1：同一 session 连续产生 `DecisionEnvelope` 与 `NotificationEnvelope`，宿主按固定顺序接收。

场景 2：不同 session 的 envelope 可以并行，不互相阻塞。

## 非目标

- 不重跑风险判定。
- 不执行 canonical action 或 approval business logic。
- 不定义 OpenClaw 渲染细节或飞书卡片模板。
- 不实现审计/回放产品面之外的宿主逻辑。
