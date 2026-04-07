# 任务分解：025-policy-engine-decision-evidence

> 对应规格：`specs/025-policy-engine-decision-evidence/spec.md`

## Task 25.1 冻结 policy matrix 与 canonical decision model

- **任务编号**：T251
- **状态**：已完成
- **目标**：把 `human_gate / hard_block`、受控不确定条件、稳定决策结果与 `decision_key` 收成可执行文档与模型边界。
- **涉及文件**：
  - `docs/architecture/openclaw-codex-watchdog-full-product-loop-design.md`
  - `specs/025-policy-engine-decision-evidence/spec.md`
  - `specs/025-policy-engine-decision-evidence/plan.md`
  - `specs/025-policy-engine-decision-evidence/tasks.md`
- **验证**：人工审阅 formal docs 是否与总设计 Section 3 / 5 的 WI-2 边界一致。
- **完成情况**：policy matrix、受控不确定条件、稳定决策结果与 `decision_key` 边界已冻结。

## Task 25.2 新增 canonical policy engine 与 decision records

- **任务编号**：T252
- **状态**：已完成
- **目标**：新增 policy engine、规则表与 canonical decision records。
- **涉及文件**：
  - `src/watchdog/services/policy/engine.py`
  - `src/watchdog/services/policy/rules.py`
  - `src/watchdog/services/policy/decisions.py`
  - `tests/test_watchdog_policy_engine.py`
  - `tests/test_watchdog_policy_decisions.py`
- **验证**：`uv run pytest -q tests/test_watchdog_policy_engine.py tests/test_watchdog_policy_decisions.py`
- **完成情况**：已交付 canonical policy engine、规则表与 decision record store。

## Task 25.3 把策略层接到 persisted session spine

- **任务编号**：T253
- **状态**：已完成
- **目标**：让策略层只消费 canonical persisted snapshot，不再走 raw query。
- **涉及文件**：
  - `src/watchdog/services/session_spine/service.py`
  - `src/watchdog/services/policy/engine.py`
  - `tests/test_watchdog_session_spine_api.py`
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_api.py tests/test_watchdog_policy_engine.py`
- **完成情况**：策略层现在只消费 resident session spine 的 persisted snapshot，不再走 raw fact query。

## Task 25.4 锁住决策证据包与最小文档

- **任务编号**：T254
- **状态**：已完成
- **目标**：补齐决策证据包、去重与最小 operator notes。
- **涉及文件**：
  - `src/watchdog/services/policy/decisions.py`
  - `README.md`
  - `docs/getting-started.zh-CN.md`
- **验证**：`uv run pytest -q tests/test_watchdog_policy_decisions.py`
- **完成情况**：决策证据包、去重键与最小 operator notes 已固定，供 026/027 直接消费。

## 整体验收

- `025` 是完整产品闭环中的 `WI-2`，只负责 canonical policy engine 与 decision evidence layer。
- `025` 完成后，后续 `026/027` 可以直接消费 canonical decision records，而不是重新判断风险。
- `025` 不引入真实执行、delivery outbox 或 OpenClaw runtime。
