# 任务分解：007-prd-alignment

> 对应规格：`specs/007-prd-alignment/spec.md`

## Batch 1

### Task 7.1 stuck_level 与 steer / handoff

- **任务编号**：T71
- **依赖**：无
- **文件**：`src/a_control_agent/api/tasks.py`, `src/a_control_agent/storage/tasks_store.py`, `src/a_control_agent/api/recovery.py`
- **可并行**：否
- **验收标准**：
  1. `POST .../steer` 可携带 `stuck_level` 并持久化；
  2. `handoff` 后任务含 `stuck_level` 为 4；
  3. 相关 `pytest` 通过。
- **验证**：`pytest tests/test_007_alignment.py -q`（与本批测试文件）

### Task 7.2 evaluate 结合工作区活动 + recover auto-resume

- **任务编号**：T72
- **依赖**：T71
- **文件**：`src/watchdog/services/status_analyzer/stuck.py`, `src/watchdog/api/supervision.py`, `src/watchdog/services/action_executor/steer.py`, `src/watchdog/settings.py`, `src/watchdog/api/recover_watchdog.py`, `config/examples/watchdog.env.example`
- **可并行**：否
- **验收标准**：
  1. `evaluate_stuck` 在 `repo_recent_change_count>0` 时不因时间阈值单独 steer；
  2. `recover_auto_resume` 为 true 时 handoff 成功后调用 `resume`；
  3. `pytest` 全绿。
- **验证**：`pytest -q`

### Task 7.3 文档与登记

- **任务编号**：T73
- **依赖**：T72
- **文件**：`specs/007-prd-alignment/research.md`, `README.md`（若有必要增补一行）
- **可并行**：否
- **验收标准**：
  1. `research.md` 含未编码偏差表；
  2. `python -m ai_sdlc verify constraints` 无 BLOCKER。
- **验证**：`python -m ai_sdlc verify constraints`
