# OpenClaw × Codex 双机会话监管系统

需求真值见根目录 `openclaw-codex-watchdog-prd.md`。本仓库以 AI-SDLC 工作项递进交付：**M1** 基础链路、`specs/002-*` M2 监管、`specs/004-*` M3 审批、`specs/005-*` M4 恢复、`specs/006-*` **M5 加固**（指标、集成测试、OpenAPI 与 OpenClaw 调用示例等，不含飞书/OpenClaw 渠道插件）。

## 组件

| 目录 | 说明 |
|------|------|
| `src/a_control_agent/` | A 机侧：任务 / steer / handoff / resume / 审批、持久化、`/metrics` |
| `src/watchdog/` | B 机侧：progress / evaluate / recover / 审批代理、`/metrics` |
| `docs/openapi/` | OpenAPI JSON（`python scripts/export_openapi.py` 生成） |
| `examples/` | OpenClaw 侧调用 Watchdog 的 HTTP 示例（无飞书） |

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

## 可观测性（M5）

两侧服务均提供 **`GET /metrics`**（Prometheus 文本），便于抓取任务数、审计事件计数与 Watchdog 自动 steer 等（见 PRD §14.3）。

## OpenAPI 与集成示例

```bash
python scripts/export_openapi.py
```

示例脚本：`examples/openclaw_watchdog_client.py`（需设置 `WATCHDOG_BASE_URL`、`WATCHDOG_API_TOKEN`）。

## 测试

```bash
pytest -q
```

含 `tests/integration/` 多步链（无飞书）。

## AI-SDLC

```bash
python -m ai_sdlc verify constraints
python -m ai_sdlc status
```
