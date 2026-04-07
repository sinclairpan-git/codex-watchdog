---
related_doc:
  - "docs/architecture/openclaw-codex-watchdog-full-product-loop-design.md"
  - "specs/025-policy-engine-decision-evidence/spec.md"
---

# Canonical Action / Approval Response 闭环 — 功能规格说明

## 概述

`026-canonical-action-approval-response-loop` 是完整产品闭环中的 `WI-3`。它接收 `025` 产出的 canonical decision records，把“会判断”推进到“能安全执行、能安全审批、能形成 canonical response 闭环”。

`026` 的唯一目标固定为：

> 让 Watchdog 能基于 canonical decision records 安全执行已批准动作，或把需要人工裁决的请求收成 canonical approval loop，并把用户响应稳定映射回 canonical action / approval decision。

## 功能需求

- **FR-2601**：026 必须引入 canonical action registry，明确哪些动作可以被 `auto_execute_and_notify` 或人工批准后执行。
- **FR-2602**：026 必须让动作执行严格消费 `025` 产出的 canonical decision records，不得再次重跑风险判定。
- **FR-2603**：026 必须新增 canonical approval records，并让 `require_user_decision` 稳定映射到待响应审批对象。
- **FR-2604**：026 必须实现 `ApprovalEnvelope` 对应的 canonical approval model，至少包含：
  - `approval_id`
  - `approval_kind`
  - `requested_action`
  - `requested_action_args`
  - `approval_token`
  - `decision_options`
  - `policy_version`
  - `fact_snapshot_version`
  - `idempotency_key`
- **FR-2605**：026 必须定义用户响应 canonical contract，v1 只允许：
  - `approve`
  - `reject`
  - `execute_action`
- **FR-2606**：026 必须把用户响应幂等键冻结为：
  - `(envelope_id, response_action, client_request_id)`
- **FR-2607**：026 必须保证同一响应幂等键重放时，不重复执行 approval decision 或 canonical action。
- **FR-2608**：026 必须支持“审批后执行”的 canonical 闭环：
  - `approve` -> 记录 approval decision -> 执行 canonical action
  - `reject` -> 记录 approval rejection -> 不执行动作
- **FR-2609**：026 必须把动作执行与审批执行的结果写入可被后续 `027` 投递层消费的 canonical execution/approval result records。
- **FR-2610**：026 必须补齐测试，至少锁住：
  - canonical action registry 约束
  - 审批幂等
  - 响应幂等
  - approve/reject 语义
  - 审批后执行与执行失败的 canonical 结果
- **FR-2611**：026 不得实现 delivery retry、receipt 或 OpenClaw webhook。
- **FR-2612**：026 不得实现飞书文案渲染，不得在 execution layer 持有渠道语义。

### 用户故事 1：服务能安全执行已注册动作，而不是让宿主自己决定怎么做

场景 1：某个 canonical decision 为 `auto_execute_and_notify`，服务直接从 canonical action registry 解析动作并调用 A 侧执行。

场景 2：动作执行失败时，服务落 canonical execution result，供后续投递层生成告警。

### 用户故事 2：需要人工裁决的请求能形成稳定审批闭环

场景 1：策略层输出 `require_user_decision` 后，服务创建 canonical approval record，等待用户响应。

场景 2：用户通过宿主回传 `approve` 或 `reject`，服务只执行一次相应语义。

## 非目标

- 不实现 envelope delivery outbox、retry、receipt 或 OpenClaw webhook。
- 不实现飞书 UI、宿主渲染或消息投递。
- 不重新运行策略判定。
- 不实现运维告警与生产部署面。
