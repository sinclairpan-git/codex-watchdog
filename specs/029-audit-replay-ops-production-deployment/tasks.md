# 任务分解：029-audit-replay-ops-production-deployment

> 对应规格：`specs/029-audit-replay-ops-production-deployment/spec.md`

## Task 29.1 冻结审计、回放与生产化边界

- **任务编号**：T291
- **状态**：待开始
- **目标**：把审计、回放、运维与生产部署的边界冻结为 formal docs，不反向改写前五个 WI。
- **涉及文件**：
  - `docs/architecture/openclaw-codex-watchdog-full-product-loop-design.md`
  - `specs/029-audit-replay-ops-production-deployment/spec.md`
  - `specs/029-audit-replay-ops-production-deployment/plan.md`
  - `specs/029-audit-replay-ops-production-deployment/tasks.md`
- **验证**：人工审阅 formal docs 是否与总设计 Section 5 的 WI-6 边界一致。

## Task 29.2 新增审计与回放服务

- **任务编号**：T292
- **状态**：待开始
- **目标**：新增 canonical audit query 与 replay 服务。
- **涉及文件**：
  - `src/watchdog/services/audit/service.py`
  - `src/watchdog/services/audit/replay.py`
  - `tests/test_watchdog_audit.py`
  - `tests/test_watchdog_replay.py`
- **验证**：`uv run pytest -q tests/test_watchdog_audit.py tests/test_watchdog_replay.py`

## Task 29.3 补 ops surface、关键告警与 runbook

- **任务编号**：T293
- **状态**：待开始
- **目标**：补齐 metrics / health / alerts 与 operator runbook。
- **涉及文件**：
  - `src/watchdog/api/ops.py`
  - `src/watchdog/api/metrics.py`
  - `README.md`
  - `docs/getting-started.zh-CN.md`
- **验证**：人工审阅关键告警、runbook 与运维说明是否闭环。

## Task 29.4 锁住安装、升级、回滚与公网方案

- **任务编号**：T294
- **状态**：待开始
- **目标**：把安装、升级、回滚、密钥轮换与公网方案收成正式交付。
- **涉及文件**：
  - `README.md`
  - `docs/getting-started.zh-CN.md`
  - `tests/integration/test_openclaw_integration_spine.py`
- **验证**：`uv run pytest -q tests/integration/test_openclaw_integration_spine.py`

## 整体验收

- `029` 是完整产品闭环中的 `WI-6`，只负责审计、回放、运维与生产部署。
- `029` 完成后，整套产品闭环才算具备长期运营能力。
- `029` 不反向改写前 5 个 WI 的核心契约；发现缺口应登记 defect/backlog。
