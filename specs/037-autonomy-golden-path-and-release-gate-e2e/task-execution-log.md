# 执行日志：037-autonomy-golden-path-and-release-gate-e2e

## 2026-04-14

### Phase 1：formal docs / spec freeze

- 基于 `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md` 的 `Task 8`，正式拆出 `WI-037`。
- 把目标边界收紧为：
  - 一期只允许一条正式自治主链；
  - `release_gate_report`、runbook/script、`label_manifest`、样本冻结窗口与 artifact archive 是 low-risk auto-decision 的正式 blocking inputs；
  - worker crash、claim timeout、notification failure、supersede/stale interaction、人工 override 与 child session continuation 都属于一期正式验收面；
  - 通关标准必须建立在 030-036 已冻结的 canonical contract 之上，而不是 e2e 阶段重新发明状态机。
- 已创建 `spec.md / plan.md / tasks.md / task-execution-log.md` 与 `.ai-sdlc/work-items/037-*` 基线。
- Anthropic Manager 专家首轮复核无 blocking/P1。
- Hermes Agent 专家指出一个 P1：037 初版遗漏了 035 已冻结的 `tool_schema_hash` drift 维度，导致 release gate hard blocker 被削薄。
- 已按该反馈把 `tool_schema_hash` 补回 `spec.md`、`plan.md` 与 `tasks.md` 的 hard-blocker / drift 校验清单。
- Hermes Agent 专家修订后快速复核：无 blocking/P1。
- `T371` 已满足 formal docs baseline 条件，下一执行入口切到 `T372`，开始一期 golden path / midstate recovery / release gate e2e 红测。

### Phase 2 / 3：golden path e2e red -> green

- 已新增：
  - `tests/e2e/test_watchdog_autonomy_golden_path.py`
  - `tests/e2e/test_watchdog_midstate_recovery.py`
  - `tests/e2e/test_watchdog_release_gate_e2e.py`
- 首轮红测明确暴露三条跨模块缺口：
  - `Feishu` control 只能处理 approval response，缺少 Goal Contract kickoff contract；
  - recovery transaction 虽能写 lineage/adopt truth，但尚未收口 stale interaction supersede；
  - runtime evidence 只有 `release_gate_verdict`，没有 formal `release_gate_evidence_bundle`。
- 已完成最小 green 接线：
  - `src/watchdog/services/feishu_control/service.py` 与 `src/watchdog/api/feishu_control.py` 现在支持 `goal_contract_bootstrap`，由 Feishu DM 创建或修订 Goal Contract；
  - `src/watchdog/services/session_spine/recovery.py` 现在会在 recovery continuation 时显式 supersede 旧 interaction context，并生成新的 recovery context；
  - `src/watchdog/services/session_spine/orchestrator.py` 现在把 `release_gate_evidence_bundle` 落入 decision evidence；
  - `src/watchdog/settings.py` 补齐 formal evidence artifact refs。
- 本地验证：
  - `uv run pytest -q tests/e2e/test_watchdog_autonomy_golden_path.py tests/e2e/test_watchdog_midstate_recovery.py tests/e2e/test_watchdog_release_gate_e2e.py` -> `3 passed in 1.45s`
  - `uv run pytest -q tests/e2e/test_watchdog_autonomy_golden_path.py tests/e2e/test_watchdog_midstate_recovery.py tests/e2e/test_watchdog_release_gate_e2e.py tests/test_watchdog_feishu_control.py tests/test_watchdog_release_gate.py tests/test_watchdog_release_gate_evidence.py tests/test_watchdog_recovery_execution.py tests/test_watchdog_session_spine_runtime.py tests/test_long_running_autonomy_doc_contracts.py` -> `70 passed in 4.77s`
- 当前下一执行入口停在 `T373`，继续补 completion evidence / replay-metrics 归档与更完整的一期主链闭环。

### Phase 3 / 4 / 5：completion evidence、ops surfacing 与 handoff 收口

- 已完成 `T373` 剩余 glue：
  - `src/watchdog/services/session_spine/command_leases.py` 的 terminal result 现在接受结构化 payload，并沿既有 `command lease -> Session Service` 镜像链写回 canonical 事件；
  - `src/watchdog/services/session_spine/orchestrator.py` 现在会在 `command_executed / command_failed` payload 中落账 `completion_evidence_ref`、`completion_judgment`、`replay_ref`、`replay_summary`、`metrics_ref` 与 `metrics_summary`；
  - golden path e2e 现在显式断言 completion / replay / metrics refs 来自主链终态事件，而不是额外测试专用存储。
- 已完成 `T374` 收口：
  - `src/watchdog/api/ops.py` 现在把 release gate degraded 决策暴露为 `release_gate_blockers`，包含 formal blocker 元数据；
  - `src/watchdog/observability/metrics_export.py` 现在导出 `watchdog_release_gate_blocker_active{reason=...}`；
  - `tests/test_watchdog_ops.py` 已固定 read-side 与 metrics 面都能看到 release gate blocker metadata。
- 本轮验证：
  - `uv run pytest -q tests/e2e/test_watchdog_autonomy_golden_path.py tests/test_watchdog_command_leases.py tests/test_watchdog_ops.py` -> `19 passed in 0.92s`
  - `uv run pytest -q tests/e2e/test_watchdog_autonomy_golden_path.py tests/e2e/test_watchdog_midstate_recovery.py tests/e2e/test_watchdog_release_gate_e2e.py tests/test_watchdog_command_leases.py tests/test_watchdog_ops.py tests/test_watchdog_feishu_control.py tests/test_watchdog_release_gate.py tests/test_watchdog_release_gate_evidence.py tests/test_watchdog_recovery_execution.py tests/test_watchdog_session_spine_runtime.py tests/test_long_running_autonomy_doc_contracts.py` -> `88 passed in 5.37s`
- 对抗复核：
  - Anthropic Manager 专家：无 blocking/P1；
  - Hermes Agent 专家口径复核：无 blocking/P1。
- `T373`、`T374` 与 `T375` 已满足收口条件，`WI-037` 现可视作一期正式通关与 release blocker 基线。
