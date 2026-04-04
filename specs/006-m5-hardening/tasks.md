# 任务分解：006-m5-hardening

> 对应规格：`specs/006-m5-hardening/spec.md`

## Batch 1

### Task 5.1 可观测性 `/metrics`

- **任务编号**：T51
- **依赖**：无
- **文件**：`src/a_control_agent/observability/`, `src/a_control_agent/main.py`, `src/watchdog/observability/`, `src/watchdog/main.py`, `tests/test_m5_metrics.py`
- **可并行**：否
- **验收标准**：
  1. A 与 Watchdog 均提供 `GET /metrics`（Prometheus 文本）；
  2. 输出含任务数与审计聚合计数；
  3. `pytest tests/test_m5_metrics.py` 通过。
- **验证**：`pytest tests/test_m5_metrics.py -q`

### Task 5.2 resume 状态机 + 工作区活动 + Codex 占位

- **任务编号**：T52
- **依赖**：T51
- **文件**：`src/a_control_agent/api/recovery.py`, `src/a_control_agent/api/tasks.py`, `src/a_control_agent/repo_activity.py`, `src/a_control_agent/services/codex/`
- **可并行**：否
- **验收标准**：
  1. `resume` 路径先将任务置为 `resuming` 再置为 `running`；
  2. `GET /api/v1/tasks/{project_id}/workspace-activity` 返回基于 cwd 的 mtime 摘要；
  3. 存在 `CodexClient` Protocol 与 `NoOpCodexClient` 默认实现。
- **验证**：`pytest tests/test_m4_agent_recovery.py tests/integration/test_prd_chains.py -q`（与 T53 联跑时以全量 `pytest -q` 为准）

### Task 5.3 集成测试与交付物

- **任务编号**：T53
- **依赖**：T52
- **文件**：`tests/integration/`, `scripts/export_openapi.py`, `examples/openclaw_watchdog_client.py`, `docs/openapi/`, `README.md`
- **可并行**：否
- **验收标准**：
  1. `tests/integration/test_prd_chains.py` 覆盖多步链；
  2. `python scripts/export_openapi.py` 可生成 `docs/openapi/*.json`；
  3. `examples/openclaw_watchdog_client.py` 演示 Watchdog progress 调用；
  4. `README.md` 含 M5、指标与 OpenAPI 说明；
  5. `pytest -q` 全绿。
- **验证**：`pytest -q`
