---
related_doc:
  - "docs/architecture/openclaw-codex-watchdog-full-product-loop-design.md"
  - "specs/027-outbox-delivery-retry-receipt/spec.md"
  - "specs/023-codex-client-openclaw-route-template/spec.md"
---

# OpenClaw Webhook / Response API / Reference Runtime — 功能规格说明

## 概述

`028-openclaw-webhook-response-api-reference-runtime` 是完整产品闭环中的 `WI-5`。它的目标是把“OpenClaw 如何接入”从口头说明收成稳定契约和最小参考宿主实现。

## 功能需求

- **FR-2801**：028 必须定义 Watchdog -> OpenClaw 的主动回调入口：
  - `POST /openclaw/v1/watchdog/envelopes`
- **FR-2802**：028 必须定义 OpenClaw -> Watchdog 的结构化响应入口：
  - `POST /api/v1/openclaw/responses`
- **FR-2803**：028 必须冻结 webhook 请求头，至少包含：
  - `Authorization: Bearer <token>`
  - `X-Watchdog-Delivery-Id`
  - `X-Watchdog-Timestamp`
  - `X-Watchdog-Signature`
- **FR-2804**：028 必须冻结 webhook 成功响应 contract，至少包含：
  - `accepted`
  - `envelope_id`
  - `receipt_id`
  - `received_at`
- **FR-2805**：028 必须冻结 OpenClaw 回流 Watchdog 的 response contract，至少包含：
  - `envelope_id`
  - `envelope_type`
  - `approval_id`
  - `decision_id`
  - `response_action`
  - `response_token`
  - `user_ref`
  - `channel_ref`
  - `client_request_id`
- **FR-2806**：028 必须提供 envelope 到宿主展示层的映射规范：
  - `NotificationEnvelope` -> 事后通知 / 告警
  - `DecisionEnvelope` -> 自动决策真值通知
  - `ApprovalEnvelope` -> 人工裁决请求
- **FR-2807**：028 必须提供最小 OpenClaw reference runtime / template，证明宿主只消费稳定 envelope / response contract，而不拥有第二套业务内核。
- **FR-2808**：028 必须把宿主边界写清：
  - OpenClaw 只做接收、渲染、输入、回传
  - OpenClaw 不做决策、不做风险分类、不做第二套状态机
- **FR-2809**：028 必须补齐文档与模板验证，至少锁住：
  - receipt 回应 shape
  - response API request shape
  - envelope 到宿主行为映射
- **FR-2810**：028 不得在 reference runtime 中引入第二套策略引擎、第二套审批语义或第二套 session spine。

### 用户故事 1：OpenClaw 可以按固定契约接入，而不是继续靠口头说明

场景 1：宿主实现只需要按 contract 接收 envelope 并渲染，不需要理解内部决策细节。

场景 2：用户响应通过固定 response API 回流，Watchdog 再做 canonical 解释与执行。

## 非目标

- 不实现风险判定、action execution 或 delivery retry。
- 不实现飞书机器人 runtime 本身。
- 不把 reference runtime 扩成第二个 Watchdog 内核。
