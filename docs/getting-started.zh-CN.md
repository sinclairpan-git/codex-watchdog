# codex-watchdog：部署与使用指引

本文只描述当前有效架构：`Feishu 自建机器人 -> codex-watchdog -> Codex runtime service -> Codex`。旧宿主方案已经退出主链路，不再作为推荐部署方式。

## 1. 组件边界

| 组件 | 说明 |
|------|------|
| Codex runtime service | 由 `src/a_control_agent/` 提供实现，负责本地 Codex thread / turn / approvals / handoff / resume 等受控动作 |
| codex-watchdog | 由 `src/watchdog/` 提供实现，负责 stable session spine、监督、恢复、决策、Feishu 控制面和通知 |
| Feishu 自建机器人 | 仓库外部组件；负责把用户消息送进 watchdog，并展示 watchdog 的结果 |

## 2. 本地启动

### 2.1 启动 Codex runtime service

准备环境变量：

```bash
export A_AGENT_API_TOKEN=dev-token-change-me
export A_AGENT_HOST=127.0.0.1
export A_AGENT_PORT=8710
export A_AGENT_CODEX_HOME="${HOME}/.codex"
```

启动：

```bash
python -m uvicorn a_control_agent.main:app --host "$A_AGENT_HOST" --port "$A_AGENT_PORT" --app-dir src
```

配置样例见：

- [`config/examples/a-agent.env.example`](../config/examples/a-agent.env.example)

### 2.2 启动 watchdog

准备环境变量：

```bash
export WATCHDOG_API_TOKEN=dev-token-change-me
export WATCHDOG_CODEX_RUNTIME_BASE_URL=http://127.0.0.1:8710
export WATCHDOG_CODEX_RUNTIME_TOKEN=dev-token-change-me
```

启动：

```bash
uv run python -m uvicorn watchdog.main:create_runtime_app --host 127.0.0.1 --port 8720 --factory --app-dir src
```

配置样例见：

- [`config/examples/watchdog.env.example`](../config/examples/watchdog.env.example)

推荐的关键变量至少包括：

- `WATCHDOG_DELIVERY_TRANSPORT=feishu`
- `WATCHDOG_FEISHU_EVENT_INGRESS_MODE=long_connection`
- `WATCHDOG_FEISHU_CALLBACK_INGRESS_MODE=long_connection`
- `WATCHDOG_FEISHU_VERIFICATION_TOKEN`
- `WATCHDOG_BRAIN_PROVIDER_NAME=openai-compatible`
- `WATCHDOG_BRAIN_PROVIDER_BASE_URL`
- `WATCHDOG_BRAIN_PROVIDER_API_KEY`
- `WATCHDOG_BRAIN_PROVIDER_MODEL`
- `WATCHDOG_SMOKE_PROVIDER_LIVE=true`
- `WATCHDOG_SMOKE_PROVIDER_HTTP_TIMEOUT_S`
- `WATCHDOG_MEMORY_PREVIEW_AI_AUTOSDLC_CURSOR_ENABLED=true`

## 3. Feishu 接入

仓库支持两种 Feishu 入口：

- HTTP callback：`/api/v1/watchdog/feishu/events`
- long connection：`scripts/watchdog_feishu_long_connection.py`

如果要启用长连接：

```bash
export WATCHDOG_FEISHU_EVENT_INGRESS_MODE=long_connection
export WATCHDOG_FEISHU_CALLBACK_INGRESS_MODE=long_connection
uv run python scripts/watchdog_feishu_long_connection.py
```

飞书控制台至少需要订阅：

- `im.message.receive_v1`
- `im.chat.access_event.bot_p2p_chat_entered_v1`

如果长连接“看起来已连上”，但本地没有收到事件，先去飞书后台 `日志检索 > 事件日志检索` 确认平台是否真的把消息推下来了。

## 4. 验收命令

最小 smoke：

```bash
export WATCHDOG_BASE_URL=http://127.0.0.1:8720
export WATCHDOG_API_TOKEN=dev-token-change-me
uv run python scripts/watchdog_external_integration_smoke.py
uv run python scripts/watchdog_external_integration_smoke.py --target feishu
uv run python scripts/watchdog_external_integration_smoke.py --target feishu-control
uv run python scripts/watchdog_external_integration_smoke.py --target feishu-discovery
uv run python scripts/watchdog_external_integration_smoke.py --target provider
uv run python scripts/watchdog_external_integration_smoke.py --target memory
uv run python scripts/watchdog_external_integration_smoke.py --target provider --markdown-report artifacts/watchdog-live-acceptance.md
```

关键 smoke 变量：

- `WATCHDOG_SMOKE_FEISHU_CONTROL_PROJECT_ID`
- `WATCHDOG_SMOKE_FEISHU_CONTROL_GOAL_MESSAGE`
- `WATCHDOG_SMOKE_FEISHU_CONTROL_EXPECTED_SESSION_ID`
- `WATCHDOG_SMOKE_FEISHU_CONTROL_HTTP_TIMEOUT_S`
- `WATCHDOG_SMOKE_FEISHU_DISCOVERY_EXPECTED_PROJECT_IDS`

如果 `feishu-control` 没有经过确认的可写 live target，脚本必须返回 `skipped` 与 `operator_confirmation_required`。证据里必须带上 `confirm_mutating_live_target`，并明确说明缺的是可写 live target，而不是让系统自行推断 `project_id + goal_message`。这里必须继续按 `fail-closed` 处理；命中的写入语义是 `goal_contract_bootstrap`。

如果 `feishu-discovery` 被启用，默认命令是 `项目列表`，成功结果必须能看到 `list_sessions/session_directory`，并覆盖 `WATCHDOG_SMOKE_FEISHU_DISCOVERY_EXPECTED_PROJECT_IDS`。若响应中包含 child-session 续跑信息，也必须检查 `recovery_child_session_id`。

## 5. launchd 常驻

安装 watchdog 的 launchd：

```bash
WATCHDOG_ENV_FILE="$PWD/.env.w" ./scripts/install_watchdog_launchd.sh
```

模板文件：

- [`config/examples/com.codex.watchdog.plist`](../config/examples/com.codex.watchdog.plist)

## 6. 最小客户端模板

[`examples/codex_watchdog_client.py`](../examples/codex_watchdog_client.py) 提供最小 HTTP 模板，覆盖：

- `query_progress(project_id)`
- `query_stuck(project_id)`
- `continue_session(project_id, operator, idempotency_key)`
- `list_approval_inbox(project_id?)`
- `approve_approval(...)`
- `reject_approval(...)`

AI_AutoSDLC preview cursor 相关入口：

- `/api/v1/watchdog/memory/preview/ai-autosdlc-cursor`
- 当未开启时，返回里应体现 `enabled=false`
- 相关 contract 标识为 `contract_name=ai-autosdlc-cursor`

## 7. OpenAPI

```bash
python scripts/export_openapi.py
```
