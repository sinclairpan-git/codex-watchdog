# OpenClaw × Codex 双机会话监管系统

需求真值见根目录 `openclaw-codex-watchdog-prd.md`。本仓库以 AI-SDLC 工作项递进交付：**M1** 基础链路、`specs/002-*` M2 监管、`specs/004-*` M3 审批、`specs/005-*` M4 恢复、`specs/006-*` **M5 加固**（指标、集成测试、OpenAPI 与 OpenClaw 调用示例等，不含飞书/OpenClaw 渠道插件）。

**部署与 A/B 机使用说明（含对接参数清单）**：见 [`docs/getting-started.zh-CN.md`](docs/getting-started.zh-CN.md)。

## 组件

| 目录 | 说明 |
|------|------|
| `src/a_control_agent/` | A 机侧：任务 / steer / handoff / resume / 审批、持久化、`/metrics` |
| `src/watchdog/` | B 机侧：stable session spine、progress / evaluate / recover / 审批代理、`/metrics` |
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
export A_AGENT_CODEX_HOME="${HOME}/.codex"
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

010 冻结后的 OpenClaw 最小稳定接口面：

- `GET /api/v1/watchdog/sessions/{project_id}` 返回稳定 `SessionProjection`
- `GET /api/v1/watchdog/sessions/{project_id}/progress` 返回稳定 `TaskProgressView`
- `GET /api/v1/watchdog/sessions/{project_id}/pending-approvals` 返回稳定审批队列
- `GET /api/v1/watchdog/sessions/{project_id}/events` 返回稳定、版本化的 `SessionEvent` SSE
- `POST /api/v1/watchdog/actions` 是 canonical write surface，提交 `WatchdogAction`
- `POST /api/v1/watchdog/sessions/{project_id}/actions/continue`
- `POST /api/v1/watchdog/sessions/{project_id}/actions/request-recovery`
- `POST /api/v1/watchdog/approvals/{approval_id}/approve`
- `POST /api/v1/watchdog/approvals/{approval_id}/reject`

其中路径级动作接口只是 alias wrapper；真正稳定的动作契约是
`WatchdogAction -> WatchdogActionResult`。`request_recovery` 在 010 仍是
advisory-only，只返回恢复可用性说明，不触发真实 handoff / resume。

011 在 010 stable surface 旁边新增了只读稳定事件面：
`GET /api/v1/watchdog/sessions/{project_id}/events`。它会把 raw 事件投影成
版本化 `SessionEvent`，当前最小稳定事件集包括 `session_created`、
`native_thread_bound`、`guidance_posted`、`handoff_requested`、
`session_resumed`、`approval_resolved`，未知 raw 类型会降级为
`session_updated`。默认持续跟随新事件，也可用 `?follow=false` 只回放当前快照。

原始事件流仍保留：
`GET /api/v1/tasks/{project_id}/events` 直接返回 A 侧原始 SSE；
若 OpenClaw 不直接连 A，也可经 Watchdog 代理读取
`GET /api/v1/watchdog/tasks/{project_id}/events`。

原有 `progress / evaluate / approvals / recover / events` raw / legacy 接口继续保留，
但不再承担 OpenClaw 稳定契约角色。

若 A-Control-Agent 与 Codex Desktop 跑在同一台机器，默认启动路径现在会直接读取
`~/.codex`（可由 `A_AGENT_CODEX_HOME` 覆盖），自动发现当前 active workspace 的 thread，
并按 `A_AGENT_CODEX_SYNC_INTERVAL_SECONDS` 周期刷新到任务存储。

若需要真实下行控制，可开启本地 bridge：

```bash
export A_AGENT_CODEX_BRIDGE_ENABLED=true
export A_AGENT_CODEX_BRIDGE_COMMAND='codex app-server --listen stdio://'
```

A-Control-Agent 会以子进程方式拉起本地 Codex app-server，并通过 stdio bridge 执行
`thread/read`、`turn/start`、`turn/steer` 与审批回写。

若暂时不启用 bridge，仍可继续用 `POST /api/v1/tasks/native-threads` 或
`python examples/register_native_thread.py --payload examples/native_thread_payload.json`
把当前原生 Codex thread 注册进 A-Control-Agent，再经 Watchdog / OpenClaw 查询。

## GitHub PR / Codex Review 演示

推荐工作流：

1. 从 `main` 拉出功能分支。
2. 在分支上完成改动并推送到 GitHub。
3. 发起 Pull Request，请求合并回 `main`。
4. 在 PR 评论里使用 `@codex review` 触发首轮机器评审。
5. 根据 review 评论补修改动、补测试，再次推送到同一个分支。
6. 通过人工复核后再合并。

对这个仓库，建议让 Codex 先检查明显 bug、回归风险和测试缺口，再由人工 reviewer 判断需求、设计和长期维护取舍。

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
