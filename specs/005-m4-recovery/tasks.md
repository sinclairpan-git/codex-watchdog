# 任务分解：005-m4-recovery

> 对应规格：`specs/005-m4-recovery/spec.md`

## Batch 1：M4 实现

### Task 4.1 A-Control-Agent：handoff / resume API

- **任务编号**：T41
- **依赖**：无
- **文件**：`src/a_control_agent/api/recovery.py`, `src/a_control_agent/storage/handoff_manager.py`, `src/a_control_agent/main.py`
- **可并行**：否
- **验收标准**：
  1. `POST .../handoff` 与 `POST .../resume` 符合 PRD envelope；
  2. handoff 生成非空 markdown 文件；
  3. `pytest tests/test_m4_agent_recovery.py` 通过。
- **验证**：`pytest tests/test_m4_agent_recovery.py -q`

### Task 4.2 Watchdog：recover 编排

- **任务编号**：T42
- **依赖**：T41
- **文件**：`src/watchdog/api/recover_watchdog.py`, `src/watchdog/main.py`
- **可并行**：否
- **验收标准**：
  1. `POST /api/v1/watchdog/tasks/{project_id}/recover` 存在；
  2. A 不可达时 CONTROL_LINK_ERROR；
  3. `pytest tests/test_m4_watchdog_recover.py` 通过。
- **验证**：`pytest tests/test_m4_watchdog_recover.py -q`
