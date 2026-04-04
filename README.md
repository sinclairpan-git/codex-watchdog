# OpenClaw × Codex 双机会话监管系统（M1 骨架）

需求真值见根目录 `openclaw-codex-watchdog-prd.md`；本仓库按 AI-SDLC 工作项 `specs/001-openclaw-codex-watchdog/` 实施 **M1：基础链路**。

## 组件

| 目录 | 说明 |
|------|------|
| `src/a_control_agent/` | A 机侧：任务创建/查询 API、文件型持久化、统一 envelope |
| `src/watchdog/` | B 机侧：`/api/v1/watchdog/tasks/{project_id}/progress` 代理 A 侧状态 |

## 本地运行

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

**A-Control-Agent**（终端 1）：

```bash
export A_AGENT_API_TOKEN=dev-token-change-me
python -m uvicorn a_control_agent.main:app --host 127.0.0.1 --port 8710 --app-dir src
```

**Watchdog**（终端 2）：

```bash
export WATCHDOG_API_TOKEN=dev-token-change-me
export WATCHDOG_A_AGENT_TOKEN=dev-token-change-me
python -m uvicorn watchdog.main:app --host 127.0.0.1 --port 8720 --app-dir src
```

配置样例：`config/examples/*.env.example`。

## 测试

```bash
pytest -q
```

## AI-SDLC

```bash
python -m ai_sdlc verify constraints
python -m ai_sdlc status
```
