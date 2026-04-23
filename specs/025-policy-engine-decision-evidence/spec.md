---
related_doc:
  - "docs/architecture/codex-watchdog-full-product-loop-design.md"
  - "specs/024-resident-supervision-session-spine-persistence/spec.md"
---

# 策略引擎与决策证据包 — 功能规格说明

## 概述

`025-policy-engine-decision-evidence` 是完整产品闭环中的 `WI-2`。它建立在 `024` 提供的 canonical persisted session spine 之上，目标是把“默认自治，例外升级”收成可执行、可审计、可重放的策略判定层。

`025` 只解决：

- 如何从 persisted facts 产出稳定决策结果；
- 如何把 `human_gate / hard_block`、受控不确定条件与动作注册策略收成 canonical policy engine；
- 如何为每次决策落一份结构化的决策证据包。

`025` 不解决真实动作执行、人工审批回流、主动消息投递或 Feishu/Feishu 宿主接入。

## 功能需求

- **FR-2501**：025 必须只消费 `024` 产出的 canonical persisted session spine 与 `fact_snapshot_version`，不得重新在策略层直接向 Codex runtime service 发 raw query 取事实。
- **FR-2502**：025 必须把外部稳定决策结果冻结为：
  - `auto_execute_and_notify`
  - `require_user_decision`
  - `block_and_alert`
- **FR-2503**：025 必须把风险边界冻结为两类：
  - `human_gate`
  - `hard_block`
- **FR-2504**：025 必须把“服务自己判断不确定”收成受控枚举，至少包含：
  - `evidence_missing`
  - `fact_conflict`
  - `policy_conflict`
  - `action_unregistered`
  - `risk_unexplainable`
  - `mapping_incomplete`
  - `idempotency_uncertain`
- **FR-2505**：025 必须冻结判定顺序：
  1. 先判断 `human_gate`
  2. 再判断 `hard_block`
  3. 再判断动作是否有已注册策略
  4. 只有证据完备、风险可解释、映射完整、幂等确定时，才允许 `auto_execute_and_notify`
- **FR-2506**：025 必须引入 `policy_version`，并让每次决策都记录命中的策略版本。
- **FR-2507**：025 必须引入 `decision_key`，至少覆盖：
  - `session_id`
  - `fact_snapshot_version`
  - `policy_version`
  - `decision_result`
  - `action_ref`
  - `approval_id`
- **FR-2508**：025 必须保证同一 `decision_key` 只能生成一份 canonical decision；重试只允许重投，不允许重判。
- **FR-2509**：025 必须为每次策略判定生成决策证据包，至少包含：
  - `facts`
  - `matched_policy_rules`
  - `risk_class`
  - `decision`
  - `decision_reason`
  - `why_not_escalated` 或 `why_escalated`
  - `idempotency_key`
  - `target_session / project / thread / approval ids`
  - `policy_version`
  - `fact_snapshot_version`
- **FR-2510**：025 必须允许同一 persisted snapshot 被重复读取，但不得在事实未变化时制造第二份语义上等价但 `decision_key` 不同的决策。
- **FR-2511**：025 必须补齐策略引擎单元测试与最小集成验证，至少锁住：
  - `human_gate` 到 `require_user_decision`
  - 受控不确定条件到 `block_and_alert`
  - 注册动作在证据完备前提下到 `auto_execute_and_notify`
  - `decision_key` 去重
  - `policy_version` 与 `fact_snapshot_version` 落证据包
- **FR-2512**：025 不得实现 canonical action execution，不得真正调用 continue / recovery / approval callback。
- **FR-2513**：025 不得实现 `DecisionEnvelope / ApprovalEnvelope / NotificationEnvelope` 的 outbox 或投递；最多只产出后续 `026/027` 可消费的 canonical decision records。

### 用户故事 1：服务能根据 persisted facts 做出可解释的自动或升级判定

场景 1：某个 session 的 persisted facts 命中已注册动作，且不触发 `human_gate / hard_block`，策略引擎输出 `auto_execute_and_notify`。

场景 2：某个 session 命中受控不确定条件，如 `mapping_incomplete`，策略引擎直接输出 `block_and_alert`，而不是伪装成可人工放行请求。

### 用户故事 2：同一事实快照不会被重复判定成多份 canonical decision

场景 1：resident workers 重启或重复消费同一 persisted snapshot 时，`decision_key` 维持稳定，不产生第二份 canonical decision。

场景 2：后续 delivery 重试只重投，不反过来触发新的 policy evaluation。

### 用户故事 3：后续执行与投递链可以复用决策证据包

场景 1：`026` 可以直接读取 canonical decision records，而不用再次重算风险分类。

场景 2：`027` 可以直接复用 `decision_result / policy_version / fact_snapshot_version / idempotency_key` 作为 outbox 与审计前提。

## 非目标

- 不执行 continue、recovery、approval callback 或任何真实动作。
- 不引入 `ApprovalEnvelope / DecisionEnvelope / NotificationEnvelope` 的投递实现。
- 不实现 Feishu webhook、Feishu 渠道渲染或用户输入回流。
- 不实现 receipt、retry、delivery outbox。
- 不反向修改 `024` 的 session spine 持久化契约。
