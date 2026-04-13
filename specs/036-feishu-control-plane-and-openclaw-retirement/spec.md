---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/030-session-service-event-truth-write-barrier/spec.md"
  - "specs/031-session-spine-events-projection-read-surface/spec.md"
  - "specs/032-goal-contract-persistence-and-governance/spec.md"
  - "specs/033-recovery-transaction-lineage/spec.md"
  - "specs/035-brain-decision-boundary-and-release-gate/spec.md"
---

# Feishu 主控制面与 OpenClaw 主链路退役 — 功能规格说明

## 概述

`036-feishu-control-plane-and-openclaw-retirement` 是长时运行自治一期的第七个正式执行 work item。它把总实施计划中的 `Task 7` 从“继续往 OpenClaw 上补 webhook/runtime”收紧成“Feishu 成为唯一主控制面，OpenClaw 退为兼容层”。

036 的目标不是再造一套通知外壳，而是冻结控制真相纪律：

> 所有审批确认、人工 override、通知送达回执与交互窗口更新，都必须先落 `Session Service` canonical events，再由 Feishu 控制面或兼容适配层把这些事件映射为外部 I/O。

这条边界同时吸收两组外部约束：

- **Hermes Agent 边界**：control-plane state 必须有单一真源；interaction context、ACL、过期和 replay protection 不得散落在多条 callback 链路里各自决定。
- **Anthropic Manager 边界**：人机交互链路必须区分“系统想发消息”“消息已送达”“用户回复有效”“旧上下文已 superseded”，并确保过期或晚到消息只进入审计而不回写业务真相。

因此，036 的首要目标不是“飞书接上了”，而是保证任何外部交互都不能绕过 Session truth，也不能让 OpenClaw 继续充当主控制面。

## 功能需求

- **FR-3601**：Feishu 自建机器人必须成为唯一主控制面。高风险确认、人工 override、审批结果与恢复入口只允许通过受 ACL 约束的 Feishu DM 进入；群聊最多只能承载只读进展同步、跳转链接或引用受控上下文后的确认引导。
- **FR-3602**：每个可执行交互都必须显式绑定 `interaction_context_id`、`interaction_family_id`、`actor_id`、`channel_kind`、`issued_at`、`action_window_expires_at` 与 replay-protection key。任何缺失这些字段的控制消息都不得驱动审批、override、恢复或完成判定。
- **FR-3603**：同一 `interaction_family_id` 任意时刻只允许一个当前有效的 `interaction_context_id`。需要补发、换窗口、过期续发或切换渠道时，系统必须先写 `interaction_context_superseded`，再生成新的交互上下文；旧上下文的晚到送达、晚到回复或晚到回执只能进入审计。
- **FR-3604**：审批确认、通知回执、人工 override 与控制命令的处理都必须先写 `Session Service` canonical events，再更新 projection、approval state、delivery outbox 或 runtime checkpoint。任何外部 API handler 都不得直接改 approval store、delivery store 或 resident runtime 状态而不写事件。
- **FR-3605**：通知链路必须显式建模 `notification_announced`、`notification_delivery_succeeded`、`notification_delivery_failed`、`notification_requeued`、`notification_receipt_recorded`、`interaction_context_superseded` 与 `interaction_window_expired`。系统必须区分“业务上需要通知”“已送达用户”“用户回复有效”“回复已过期/陈旧”。
- **FR-3606**：Feishu 控制面必须对 actor binding 与 ACL 做硬校验。`actor_id`、目标 `project_id/session_id`、允许动作集合与 interaction family 必须一致；不匹配、跨项目、过期或重放的请求只能写审计/拒绝事件，不能推进真实审批或 override。
- **FR-3607**：高风险动作确认只能接受 Feishu DM 上下文中的有效交互。即使同一个 actor 在群聊或旧上下文中点击了“批准”，系统也必须拒绝把它映射为高风险 approval event。
- **FR-3608**：通知投递必须冻结 attempt 级幂等键，至少覆盖 `interaction_context_id + actor_id + delivery_channel + attempt_ordinal`。重复送达、重复回执或补发后旧 attempt 的晚到成功不得让 superseded 上下文重新变成有效入口。
- **FR-3609**：OpenClaw bootstrap、callbacks、adapter 与 delivery client 在 036 之后只能作为迁移期兼容层存在。它们可以承载稳定读接口、兼容 webhook bootstrap 或已定义的回传协议，但不得再决定主控制面路由、交互有效性、approval freshness 或 notification state truth。
- **FR-3610**：`src/watchdog/main.py` 注册的主控制面入口必须显式暴露 Feishu control API，并把 OpenClaw 相关入口标记为 compatibility-only surface。后续运行时 wiring 必须以 Feishu handler/service 为主路径，而不是反过来让 Feishu 包一层 OpenClaw。
- **FR-3611**：当通知发送失败、窗口过期、旧上下文 stale 或 worker/recovery 需要人工接管时，系统必须优先创建新的可追踪交互上下文并写明 supersede/expired 原因；不得复用旧 `interaction_context_id` 假装继续有效。
- **FR-3612**：036 必须冻结“兼容但不主导”的 OpenClaw 合同：兼容层仍可读取 Session/query/action receipts 等 stable read contract，也可接受迁移期回传以便审计，但所有回传都必须经过同一套 interaction validity / actor binding / event-first write barrier，不能绕道成为并行主入口。
- **FR-3613**：Feishu 控制面生成的审批/override/通知上下文必须与 035 已冻结的 `Brain intent + DecisionTrace + release gate verdict` 协同工作。没有当前有效决策上下文、approval read ref 或 release gate 资格时，Feishu 不得擅自把建议态抬升成可执行态。

### 用户故事 1：高风险确认只能在受控 DM 中生效

operator 需要确保高风险批准不会因为群聊、过期窗口或旧消息误点而生效。

场景 1：系统向 Feishu DM 发出审批请求，用户在有效窗口内确认，系统先写 canonical approval event，再允许执行面消费。

场景 2：同一用户在旧上下文或群聊里回复“批准”，系统只写拒绝/审计事件，不改变当前 approval truth。

### 用户故事 2：通知补发后旧上下文不能双生效

operator 需要在发送失败、超时或补发后仍保持单一有效交互窗口。

场景 1：`notification_delivery_failed` 后系统写 `notification_requeued` 并为同一 interaction family 生成新 context。

场景 2：旧 context 的晚到送达回执到达时，系统只记录审计，不把旧消息重新标成当前有效。

### 用户故事 3：OpenClaw 只能保留兼容读写协议

operator 需要在迁移期继续兼容 OpenClaw 接入，但不能让它继续承担主控制职责。

场景 1：OpenClaw bootstrap 仍可更新兼容 webhook 地址，供迁移期通知出站使用。

场景 2：任何通过 OpenClaw 回传的审批或 override 都必须复用 Feishu/control-plane 同一套 interaction validity 与 event-first discipline，不能形成并行状态机。

## 非目标

- 不在 036 中完成端到端一期通关或 e2e golden path；那是后续 work item 的职责。
- 不在 036 中直接删除全部 OpenClaw 代码或兼容接口；036 只把它退为 compatibility-only surface。
- 不在 036 中重写 Brain、release gate、Goal Contract 或 recovery transaction 的核心实现；036 只消费 030-035 已冻结的 contract。
- 不在 036 中引入绕开 `Session Service` 的外部消息状态机、旁路缓存或“先写外部成功再补事件”的捷径。
