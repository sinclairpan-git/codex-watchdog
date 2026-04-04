# 任务分解：006-m5-hardening

> 对应规格：`specs/006-m5-hardening/spec.md`

## Batch 1

### Task 5.1 可观测性 `/metrics`

- **任务编号**：T51
- **依赖**：无
- **验收**：A 与 Watchdog 均提供 `GET /metrics`（Prometheus text）；含任务数与审计聚合计数；`pytest tests/test_m5_metrics.py` 通过。

### Task 5.2 resume 状态机 + 工作区活动 + Codex 占位

- **任务编号**：T52
- **依赖**：T51（可并行文档上无硬依赖，实现顺序先 T51）
- **验收**：`resuming`→`running`；`GET .../workspace-activity` 返回摘要；存在 `codex` 占位模块；相关单测通过。

### Task 5.3 集成测试与交付物

- **任务编号**：T53
- **依赖**：T52
- **验收**：`tests/integration/test_prd_chains.py`；`scripts/export_openapi.py`；`examples/openclaw_watchdog_client.py`；`README` 更新；`pytest -q` 全绿。
