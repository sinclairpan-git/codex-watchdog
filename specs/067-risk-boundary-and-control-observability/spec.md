# Spec：067-risk-boundary-and-control-observability

## 背景

当前仓库已经补上了一批与审批风险边界和控制面可观测性相关的运行时改动，但它们还没有被 formal owner 收口：

- `Codex runtime service` 的 `classify_risk()` 已开始对工作区外访问、网络、系统级命令、凭据读取、发布动作采取 fail-closed 分类；
- `Codex runtime service /healthz` 已返回 `tracked_threads`、`tracked_projects`；
- `Codex runtime service /metrics` 已输出 `aca_projects_total`；
- `Watchdog /healthz` 已把 release gate blockers 纳入 degraded 判定；
- `Watchdog /metrics` 已输出 task/approval/recovery 的聚合总量。

`WI-067` 的目标是把这条“审批风险边界 + 控制面可观测性”主线冻结为正式 contract，确保它不再只是零散实现，而是有明确 owner、验证面与 closeout 证据。

## 范围

### In Scope

- `src/a_control_agent/risk/classifier.py`
- `src/a_control_agent/main.py`
- `src/a_control_agent/observability/metrics_export.py`
- `src/watchdog/api/ops.py`
- `src/watchdog/observability/metrics_export.py`
- `tests/test_m3_risk.py`
- `tests/test_a_control_agent.py`
- `tests/test_watchdog_ops.py`
- `ai_sdlc` 工单文档与状态同步

### Out of Scope

- 不在本工单内重写审批对象模型；
- 不扩张新的审批渠道或消息模板；
- 不重开 session spine / memory hub / delivery runtime；
- 不在本工单内做性能压测或外部部署。

## Formal Source

- `codex-watchdog-prd.md`
- `docs/superpowers/specs/2026-04-14-coverage-audit-matrix.md`
- `src/a_control_agent/risk/classifier.py`
- `src/a_control_agent/main.py`
- `src/a_control_agent/observability/metrics_export.py`
- `src/watchdog/api/ops.py`
- `src/watchdog/observability/metrics_export.py`

## 非 Owner 约束

- **FR-6701**：审批风险分级必须对工作区外访问、网络、系统级命令、凭据访问、发布动作 fail-closed，不允许默许自动放行。
- **FR-6702**：`L0/L1` 才允许自动通过；`L2/L3` 必须进入人工 gate。
- **FR-6703**：健康检查和指标面必须暴露对操作者有意义的聚合真值，而不是只返回 “服务活着”。
- **FR-6704**：`Watchdog /healthz` 的 degraded 判定不得忽略 release gate blockers。
- **FR-6705**：本工单只 formalize 风险边界与 observability surface，不顺手引入新业务动作。

## 功能需求

- **FR-6706**：`classify_risk()` 至少必须把以下输入归入非自动审批等级：
  - 工作区外访问，如 `../`
  - 网络权限或网络命令
  - `sudo` / 系统服务 / 系统路径
  - 凭据、token、password、API key
  - 发布、部署、release、publish
- **FR-6707**：`auto_approve_allowed()` 必须固定为仅 `L0/L1=true`，`L2/L3=false`。
- **FR-6708**：`Codex runtime service /healthz` 必须返回：
  - `status`
  - `tracked_threads`
  - `tracked_projects`
- **FR-6709**：`Codex runtime service /metrics` 必须稳定输出：
  - `aca_tasks_total`
  - `aca_projects_total`
- **FR-6710**：`Watchdog /healthz` 必须在有 release gate blockers 时返回 `degraded`。
- **FR-6711**：`Watchdog /metrics` 必须稳定输出：
  - `watchdog_task_records_total`
  - `watchdog_approval_pending_total`
  - `watchdog_recovery_receipts_total`
- **FR-6712**：targeted tests 必须证明：
  - 风险分类器对上述边界 fail-closed；
  - `Codex runtime service` healthz/metrics 返回项目级聚合；
  - `Watchdog` healthz/metrics 对 release gate blockers 和聚合计数可观测。

## Docs baseline hash recipe

`docs_baseline_ref` 生成方式沿用现有 work item 规则，artifact set 固定为：

- `specs/067-risk-boundary-and-control-observability/spec.md`
- `specs/067-risk-boundary-and-control-observability/plan.md`
- `specs/067-risk-boundary-and-control-observability/tasks.md`
- `specs/067-risk-boundary-and-control-observability/task-execution-log.md`
- `.ai-sdlc/work-items/067-risk-boundary-and-control-observability/execution-plan.yaml`
- `.ai-sdlc/work-items/067-risk-boundary-and-control-observability/latest-summary.md`
