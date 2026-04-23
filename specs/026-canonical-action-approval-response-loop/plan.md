---
related_doc:
  - "docs/architecture/codex-watchdog-full-product-loop-design.md"
  - "specs/026-canonical-action-approval-response-loop/spec.md"
  - "specs/025-policy-engine-decision-evidence/spec.md"
---

# 实施计划：026-canonical-action-approval-response-loop

## 目标

把 canonical decision layer 推进到真实动作与审批响应闭环，但严格停在 execution semantics，不进入 delivery 或宿主渲染。

## 架构摘要

- **Decision in, execution out**：026 只消费 decision records，不重跑 policy。
- **Approval is canonical**：人工裁决先收成 canonical approval records，再映射回 action execution。
- **No delivery ownership**：执行层只产 execution/approval result records，由 `027` 负责可靠投递。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Action Registry | `src/watchdog/services/actions/registry.py` | canonical action registry 与动作元数据 |
| Action Executor | `src/watchdog/services/actions/executor.py` | 消费 decision records，调用 runtime 侧动作 |
| Approval Loop | `src/watchdog/services/approvals/service.py` | canonical approvals、响应幂等、approve/reject 语义 |
| API Surface | `src/watchdog/api/session_spine_actions.py`, `src/watchdog/api/feishu_responses.py` | canonical action / response 入口 |
| 验证 | `tests/test_watchdog_action_execution.py`, `tests/test_watchdog_approval_loop.py` | registry、执行、审批、响应幂等 |

## 边界纪律

- `026` 负责 canonical action / approval execution 语义。
- `026` 不拥有 delivery retry、receipt 或 envelope 投递。
- `026` 不拥有宿主展示语义或飞书卡片逻辑。

## 分阶段计划

### Phase 1：冻结 action registry 与 approval model

- 动作注册表
- approval record
- 响应 contract 与幂等键

### Phase 2：接 canonical decision records

- `auto_execute_and_notify` -> canonical action execution
- `require_user_decision` -> approval pending

### Phase 3：实现用户响应回流

- `approve`
- `reject`
- `execute_action`
- 响应幂等

### Phase 4：测试与最小文档

- 执行成功/失败
- 审批幂等
- 审批后执行

## 测试计划

- `tests/test_watchdog_action_execution.py`
  - canonical action registry
  - action execution success/failure
- `tests/test_watchdog_approval_loop.py`
  - approval record lifecycle
  - `(envelope_id, response_action, client_request_id)` 幂等
  - approve/reject 语义

## 主要风险与应对

- 风险 1：执行层偷偷重跑 policy
  - 应对：只接受 canonical decision records 输入
- 风险 2：审批响应重放导致重复执行
  - 应对：严格响应幂等键
- 风险 3：执行层承担 delivery 责任
  - 应对：执行层只落 result records，不做投递

## 验收口径

只有当以下条件同时满足，026 才算完成：

1. canonical action registry 与 approval loop 已落地；
2. 用户响应可被稳定映射到 canonical action / approval decision；
3. 响应重放不会重复执行；
4. 执行层结果可被后续 `027` 直接消费；
5. 本工作项仍未引入 delivery retry 或宿主渲染逻辑。
