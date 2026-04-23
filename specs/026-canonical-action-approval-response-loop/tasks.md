# 任务分解：026-canonical-action-approval-response-loop

> 对应规格：`specs/026-canonical-action-approval-response-loop/spec.md`

## Task 26.1 冻结 action registry 与 approval response 边界

- **任务编号**：T261
- **状态**：已完成
- **目标**：把 canonical action registry、approval record 与响应幂等键收敛成 formal boundary。
- **涉及文件**：
  - `docs/architecture/codex-watchdog-full-product-loop-design.md`
  - `specs/026-canonical-action-approval-response-loop/spec.md`
  - `specs/026-canonical-action-approval-response-loop/plan.md`
  - `specs/026-canonical-action-approval-response-loop/tasks.md`
- **验证**：人工审阅 formal docs 是否与总设计 Section 4 / 5 的 WI-3 边界一致。
- **完成情况**：canonical action registry、approval record 与 response idempotency 边界已冻结。

## Task 26.2 新增 canonical action registry 与 executor

- **任务编号**：T262
- **状态**：已完成
- **目标**：新增 canonical action registry 与执行器，消费 decision records 调用 runtime-side 动作。
- **涉及文件**：
  - `src/watchdog/services/actions/registry.py`
  - `src/watchdog/services/actions/executor.py`
  - `tests/test_watchdog_action_execution.py`
- **验证**：`uv run pytest -q tests/test_watchdog_action_execution.py`
- **完成情况**：已交付 canonical action registry、executor 与 execution result records。

## Task 26.3 新增 approval loop 与响应幂等

- **任务编号**：T263
- **状态**：已完成
- **目标**：落 canonical approval records、approve/reject 语义与响应幂等。
- **涉及文件**：
  - `src/watchdog/services/approvals/service.py`
  - `src/watchdog/api/feishu_responses.py`
  - `tests/test_watchdog_approval_loop.py`
- **验证**：`uv run pytest -q tests/test_watchdog_approval_loop.py`
- **完成情况**：已落 canonical approval records、approve/reject/execute_action 响应闭环与幂等键。

## Task 26.4 锁住 execution/approval result records 与文档

- **任务编号**：T264
- **状态**：已完成
- **目标**：让执行结果与审批结果可被 `027` 直接消费，并补最小 operator notes。
- **涉及文件**：
  - `src/watchdog/services/actions/executor.py`
  - `src/watchdog/services/approvals/service.py`
  - `README.md`
  - `docs/getting-started.zh-CN.md`
- **验证**：`uv run pytest -q tests/test_watchdog_action_execution.py tests/test_watchdog_approval_loop.py`
- **完成情况**：execution/approval result records 与最小 operator notes 已固定，供 027 可靠投递直接消费。

## 整体验收

- `026` 是完整产品闭环中的 `WI-3`，只负责 canonical execution / approval response semantics。
- `026` 完成后，后续 `027` 可以基于 canonical result records 做可靠投递。
- `026` 不引入 retry、receipt、webhook 或宿主渲染逻辑。
