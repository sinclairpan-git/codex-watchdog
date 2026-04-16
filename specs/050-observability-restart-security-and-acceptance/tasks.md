# 任务分解：050-observability-restart-security-and-acceptance

> 对应规格：`specs/050-observability-restart-security-and-acceptance/spec.md`
>
> 对应计划：`specs/050-observability-restart-security-and-acceptance/plan.md`

## Task 50.1 冻结 050 owner 边界与 formal docs

- **任务编号**：T501
- **状态**：已完成
- **目标**：把 050 的 observability / restart / security / acceptance 边界固定成 formal truth。
- **文件**：
  - `openclaw-codex-watchdog-prd.md`
  - `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
  - `specs/050-observability-restart-security-and-acceptance/*`
  - `.ai-sdlc/work-items/050-observability-restart-security-and-acceptance/*`
  - `.ai-sdlc/state/checkpoint.yml`
  - `.ai-sdlc/project/config/project-state.yaml`
- **可并行**：否
- **验收标准**：
  1. 已明确 050 不重开 048/049 语义；
  2. 已明确 050 只接 observability / restart / security / acceptance closeout；
  3. 已完成 work item formal docs、mirror 与 checkpoint 切换。
- **验证**：
  - 人工审阅 formal docs 与 `.ai-sdlc` 一致

## Task 50.2 写失败测试锁定 observability / acceptance contract

- **任务编号**：T502
- **状态**：已完成
- **目标**：先用 red tests 冻结 `/healthz`、metrics、restart recovery、fail-closed error 与 acceptance evidence contract。
- **文件**：
  - `src/watchdog/api/ops.py`
  - `src/watchdog/observability/metrics_export.py`
  - `src/watchdog/services/a_client/client.py`
  - `src/watchdog/services/feishu_control/service.py`
  - `tests/test_watchdog_ops.py`
  - `tests/test_watchdog_session_spine_api.py`
  - `tests/test_a_control_agent.py`
  - `tests/test_watchdog_release_gate.py`
- **可并行**：否
- **验收标准**：
  1. 覆盖 `/healthz` 与 observability surface；
  2. 覆盖关键查询路径性能或等价 evidence contract；
  3. 覆盖 A/B 重启恢复与 fail-closed 错误语义；
  4. 覆盖 PRD 17.* 的 acceptance closeout 入口。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_ops.py tests/test_watchdog_session_spine_api.py tests/test_a_control_agent.py tests/test_watchdog_release_gate.py`

## Task 50.3 实现 observability / health / metrics evidence

- **任务编号**：T503
- **状态**：已完成
- **目标**：补齐 `/healthz`、结构化日志和 metrics/export surface 的正式 evidence。
- **文件**：
  - `src/watchdog/api/ops.py`
  - `src/watchdog/observability/metrics_export.py`
  - `tests/test_watchdog_ops.py`
- **可并行**：否
- **验收标准**：
  1. `/healthz` 和指标导出存在稳定 contract；
  2. 任务/审批/恢复相关指标可读；
  3. observability evidence 可被 acceptance/release gate 消费。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_ops.py`

## Task 50.4 实现 restart / security / reliability closeout

- **任务编号**：T504
- **状态**：已完成
- **目标**：补齐 A/B 重启恢复、A 不可达 fail-closed 与 reliability acceptance 条款。
- **文件**：
  - `src/watchdog/services/a_client/client.py`
  - `src/watchdog/services/session_spine/service.py`
  - `src/watchdog/services/feishu_control/service.py`
  - `tests/test_a_control_agent.py`
  - `tests/test_watchdog_session_spine_api.py`
  - `tests/test_watchdog_release_gate.py`
- **可并行**：否
- **验收标准**：
  1. A 重启后 project/thread 映射仍可解析；
  2. Watchdog 重启后 pending approvals / recent action receipts 仍可读取；
  3. A 不可达时返回显式 fail-closed 错误；
  4. 安全与可靠性 acceptance 条款有正式证据。
- **验证**：
  - `uv run pytest -q tests/test_a_control_agent.py tests/test_watchdog_session_spine_api.py tests/test_watchdog_release_gate.py`

## Task 50.5 完成 050 整体验证并交接 WI-051

- **任务编号**：T505
- **状态**：已完成
- **目标**：关闭 050，并把剩余高耦合 hardening 留给 `WI-051`。
- **文件**：
  - `specs/050-observability-restart-security-and-acceptance/task-execution-log.md`
  - `.ai-sdlc/work-items/050-observability-restart-security-and-acceptance/*`
- **可并行**：否
- **验收标准**：
  1. release-blocking 的 observability / restart / security / acceptance 条款已经正式关闭；
  2. `.ai-sdlc` 元数据准确指向 `WI-051` 前的下一执行入口；
  3. 050 不再残留入口语义类待办。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_ops.py tests/test_watchdog_session_spine_api.py tests/test_a_control_agent.py tests/test_watchdog_release_gate.py tests/test_ai_sdlc_reconciliation.py tests/test_long_running_autonomy_doc_contracts.py`
