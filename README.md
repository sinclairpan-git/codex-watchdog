# codex-watchdog

`codex-watchdog` 是面向 Codex 长任务监管、恢复、审批和 Feishu 控制面的运行时仓库。当前主链路已经完全切到 Feishu 自建机器人与本地 runtime；仓库内保留的是：

- `src/a_control_agent/`：Codex runtime 控制服务实现
- `src/watchdog/`：监管、stable session spine、自动决策、恢复、Feishu 控制面与通知
- `examples/codex_watchdog_client.py`：最小 HTTP 调用模板
- `docs/openapi/`：OpenAPI 导出产物

需求真值位于 [`codex-watchdog-prd.md`](codex-watchdog-prd.md)。
部署与接入说明见 [`docs/getting-started.zh-CN.md`](docs/getting-started.zh-CN.md)。

## Release Docs

`v0.6.0`

- Windows offline bundle: `ai-sdlc-offline-0.6.0.zip`
- macOS / Linux offline bundle: `ai-sdlc-offline-0.6.0.tar.gz`
- Release notes: `docs/releases/v0.6.0.md`

## 当前架构

```text
Feishu 自建机器人 -> codex-watchdog -> Codex runtime service -> Codex / 本地 workspace
```

仓库当前推荐的控制面是 Feishu 自建机器人。Watchdog 负责：

- 汇总多项目 session directory / progress / facts / approvals
- 执行 supervision、continue、pause、resume、handoff、recovery
- 维护 canonical decision / receipt / delivery / audit truth
- 对接 Feishu 事件入口、长连接和交互回流

## 本地运行

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

启动 Codex runtime 控制服务：

```bash
export A_AGENT_API_TOKEN=dev-token-change-me
export A_AGENT_CODEX_HOME="${HOME}/.codex"
python -m uvicorn a_control_agent.main:app --host 127.0.0.1 --port 8710 --app-dir src
```

启动 watchdog：

```bash
export WATCHDOG_API_TOKEN=dev-token-change-me
export WATCHDOG_CODEX_RUNTIME_TOKEN=dev-token-change-me
uv run python -m uvicorn watchdog.main:create_runtime_app --host 127.0.0.1 --port 8720 --factory --app-dir src
```

配置样例：

- [`config/examples/a-agent.env.example`](config/examples/a-agent.env.example)
- [`config/examples/watchdog.env.example`](config/examples/watchdog.env.example)

## 验证

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

关键 smoke 环境变量：

- `WATCHDOG_SMOKE_FEISHU_CONTROL_PROJECT_ID`
- `WATCHDOG_SMOKE_FEISHU_CONTROL_GOAL_MESSAGE`
- `WATCHDOG_SMOKE_FEISHU_CONTROL_EXPECTED_SESSION_ID`
- `WATCHDOG_SMOKE_FEISHU_CONTROL_HTTP_TIMEOUT_S`
- `WATCHDOG_SMOKE_FEISHU_DISCOVERY_EXPECTED_PROJECT_IDS`
- `WATCHDOG_SMOKE_PROVIDER_LIVE=true`
- `WATCHDOG_SMOKE_PROVIDER_HTTP_TIMEOUT_S`

对于 `feishu-control`，如果没有经操作者确认的可写 live target，脚本必须返回 `skipped` 与 `operator_confirmation_required`，并在证据里保留 `confirm_mutating_live_target`。也就是说，没有明确的 `project_id + goal_message` 时，必须按 `fail-closed` 处理，而不是替你猜值继续写入 `goal_contract_bootstrap`。

对于 `feishu-discovery`，默认验证文本是 `项目列表`，返回必须命中 `list_sessions/session_directory`，并覆盖 `WATCHDOG_SMOKE_FEISHU_DISCOVERY_EXPECTED_PROJECT_IDS` 中声明的项目；如果 payload 带出子会话，还需要看到 `recovery_child_session_id`。

如果需要生成 OpenAPI：

```bash
python scripts/export_openapi.py
```

如果需要常驻启动 watchdog：

```bash
WATCHDOG_ENV_FILE="$PWD/.env.w" ./scripts/install_watchdog_launchd.sh
```

仓库包含的 launchd 模板是：

- [`config/examples/com.codex.watchdog.plist`](config/examples/com.codex.watchdog.plist)

## 示例

[`examples/codex_watchdog_client.py`](examples/codex_watchdog_client.py) 提供最小 stable route 调用模板，覆盖：

- 查询进展
- 查询卡点
- 继续推进
- 查询审批 inbox
- 审批通过 / 拒绝

当前主控制面已经是 Feishu。仓库不再包含任何旧宿主 webhook / response runtime。

Feishu 官方入口相关的关键信息也保留在仓库文档中：

- `scripts/watchdog_feishu_long_connection.py`
- `im.message.receive_v1`
- `im.chat.access_event.bot_p2p_chat_entered_v1`
- [`docs/operations/external-integration-live-acceptance.md`](docs/operations/external-integration-live-acceptance.md)
