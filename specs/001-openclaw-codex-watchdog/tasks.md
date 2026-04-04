# 任务分解：001-openclaw-codex-watchdog

> 对应规格：`specs/001-openclaw-codex-watchdog/spec.md`  
> 需求真值：`openclaw-codex-watchdog-prd.md`

## Batch 1：M1 基础链路与仓库骨架

### Task 1.1 初始化 A-Control-Agent 与 Watchdog 仓库骨架及配置样例

- **任务编号**：T11
- **依赖**：无
- **文件**：`src/a_control_agent/`, `src/watchdog/`, `config/examples/`, `README.md`
- **可并行**：否
- **验收标准**：
  1. 两个服务目录具备可启动入口（`main` 或等价）与 `/healthz` 占位；
  2. A/B 两侧配置样例包含监听地址与共享 Token 占位；
  3. `python -m ai_sdlc verify constraints` 无 BLOCKER。
- **验证**：`python -m ai_sdlc verify constraints`

### Task 1.2 实现 PRD §9.3 最小任务 API（创建任务、查询状态）

- **任务编号**：T12
- **依赖**：T11
- **文件**：`src/a_control_agent/api/`, `src/a_control_agent/storage/`
- **可并行**：否
- **验收标准**：
  1. `POST /api/v1/tasks` 与 `GET /api/v1/tasks/{project_id}` 返回统一 envelope；
  2. 持久化 `project_id` ↔ `thread_id` 映射（可为文件型存储）；
  3. 单元测试覆盖参数校验与鉴权失败路径。
- **验证**：`pytest`（项目内测试命令）

### Task 1.3 Watchdog 进展查询代理与 A 侧不可达错误语义

- **任务编号**：T13
- **依赖**：T12
- **文件**：`src/watchdog/api/`, `src/watchdog/services/a_client/`
- **可并行**：否
- **验收标准**：
  1. `GET /api/v1/watchdog/tasks/{project_id}/progress` 聚合 A 侧状态字段；
  2. A 不可达时返回明确错误码/文案，不伪造 running；
  3. 集成测试使用 mock A-Control-Agent。
- **验证**：`pytest`（集成测试）
