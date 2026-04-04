# 任务分解：002-m2-supervision

> 对应规格：`specs/002-m2-supervision/spec.md`  
> 需求真值：`openclaw-codex-watchdog-prd.md`

## Batch 1：M2 监管与审计实现

### Task 2.1 A-Control-Agent：steer API 与审计事件追加

- **任务编号**：T21
- **依赖**：无
- **文件**：`src/a_control_agent/api/tasks.py`, `src/a_control_agent/storage/tasks_store.py`, `src/a_control_agent/audit.py`
- **可并行**：否
- **验收标准**：
  1. 实现 `POST /api/v1/tasks/{project_id}/steer`，请求体含 `message`、`source`、`reason`（PRD §9.3.3）；
  2. 持久化审计事件（JSONL 或等价），并更新任务上 `last_summary` 或相关字段；
  3. 单元测试覆盖鉴权失败与成功路径。
- **验证**：`pytest tests/test_m2_steer.py -q`

### Task 2.2 Watchdog：stuck 规则与循环失败计数

- **任务编号**：T22
- **依赖**：T21
- **文件**：`src/watchdog/services/status_analyzer/stuck.py`, `src/watchdog/services/audit.py`
- **可并行**：否
- **验收标准**：
  1. 提供纯函数或类：输入任务快照与阈值配置，输出是否应升级 `stuck_level` 及原因；
  2. 对相同 `last_error_signature` 递增 `failure_count` 的规则有单元测试；
  3. 审计写入与 FR-104 字段一致。
- **验证**：`pytest tests/test_m2_stuck.py -q`

### Task 2.3 Watchdog：对 A 侧发起 steer 的编排入口

- **任务编号**：T23
- **依赖**：T22
- **文件**：`src/watchdog/services/action_executor/steer.py`, `src/watchdog/api/supervision.py`
- **可并行**：否
- **验收标准**：
  1. 提供内部或 HTTP 接口（如 `POST /api/v1/watchdog/tasks/{project_id}/evaluate`）触发一次「拉取 A 状态 → 分析 → 必要时 steer」；
  2. A 不可达时返回 `CONTROL_LINK_ERROR` 语义，与 M1 一致；
  3. 集成测试使用 httpx mock。
- **验证**：`pytest tests/test_m2_watchdog_supervision.py -q`
