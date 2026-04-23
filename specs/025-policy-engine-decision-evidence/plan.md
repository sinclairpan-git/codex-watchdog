---
related_doc:
  - "docs/architecture/codex-watchdog-full-product-loop-design.md"
  - "specs/025-policy-engine-decision-evidence/spec.md"
  - "specs/024-resident-supervision-session-spine-persistence/spec.md"
---

# 实施计划：025-policy-engine-decision-evidence

## 目标

把“默认自治，例外升级”的设计收成 canonical policy engine 与 decision evidence layer，让后续执行、审批与投递都消费稳定决策真值，而不是各自再次判断。

## 架构摘要

- **Policy on persisted facts**：只消费 `024` 的 canonical session spine 与 persisted snapshot。
- **Canonical decision layer**：先产出 canonical decision，再由后续工作项决定如何执行或投递。
- **No execution / no delivery**：025 只负责怎么判与为什么这么判，不负责真实执行与消息投递。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Policy Engine | `src/watchdog/services/policy/engine.py` | `human_gate / hard_block`、判定顺序、稳定决策结果 |
| Policy Rules | `src/watchdog/services/policy/rules.py` | 风险边界、动作注册策略、受控不确定条件 |
| Decision Records | `src/watchdog/services/policy/decisions.py` | `decision_key`、canonical decision record、证据包 |
| Session Integration | `src/watchdog/services/session_spine/service.py` | 为策略层暴露 persisted snapshot 读取接口 |
| 验证 | `tests/test_watchdog_policy_engine.py`, `tests/test_watchdog_policy_decisions.py`, `tests/test_watchdog_session_spine_api.py` | 判定、去重、证据包、读取接缝 |

## 边界纪律

- `025` 只拥有“怎么判”的语义，不拥有真实动作执行。
- `025` 不拥有 envelope outbox、receipt、retry、webhook。
- `025` 不拥有宿主渲染、飞书文案投递或用户输入回流。

## 分阶段计划

### Phase 1：冻结风险边界与判定顺序

- 固化 `human_gate / hard_block`
- 固化受控不确定条件枚举
- 固化稳定决策结果枚举与优先级

### Phase 2：引入 canonical decision records

- 引入 `policy_version`
- 引入 `decision_key`
- 定义 canonical decision record 与决策证据包结构

### Phase 3：接 persisted snapshot

- 让策略层只读 `024` 的 persisted snapshot
- 补齐“事实未变化时不得重判”的边界

### Phase 4：测试与最小 operator notes

- 锁住判定矩阵
- 锁住 `decision_key` 去重
- 锁住 `policy_version / fact_snapshot_version` 审计字段

## 测试计划

- `tests/test_watchdog_policy_engine.py`
  - `human_gate -> require_user_decision`
  - `hard_block -> block_and_alert`
  - 已注册动作 + 证据完备 -> `auto_execute_and_notify`
- `tests/test_watchdog_policy_decisions.py`
  - `decision_key` 稳定性
  - 同一事实快照不重复生成 canonical decision
- `tests/test_watchdog_session_spine_api.py`
  - persisted snapshot 与策略层接缝不回归

## 主要风险与应对

- 风险 1：策略层偷跑真实动作
  - 应对：执行逻辑留给 `026`，025 只落 decision records
- 风险 2：重复判定导致下游重复投递
  - 应对：引入 `decision_key` 并锁住“重试只重投，不重判”
- 风险 3：受控不确定条件退化成自由文案
  - 应对：测试只允许枚举命中，不允许自由文本分支

## 验收口径

只有当以下条件同时满足，025 才算完成：

1. persisted facts 已能被 canonical policy engine 消费；
2. 稳定决策结果、`human_gate / hard_block` 与受控不确定条件已落代码与测试；
3. 每次判定都有 canonical decision record 与决策证据包；
4. 同一 `decision_key` 不会产生重复 canonical decision；
5. 本工作项仍未引入真实执行、delivery 或宿主 runtime。
