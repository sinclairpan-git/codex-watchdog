# OpenClaw × Codex 双机监管：部署与使用指引

本文说明本仓库**实际交付了什么**、**A 机 / B 机各自跑什么**、**两机如何对接**，以及在当前推荐形态下，**两台 macOS 机器**应该如何一步步部署、升级与验收。

---

## 1. 本仓库交付了什么（边界）

| 交付物 | 说明 |
|--------|------|
| **A-Control-Agent** | 运行在 **A 机** 的 FastAPI 服务：任务创建/查询、steer、handoff、resume、审批、工作区活动摘要、审计与 `/metrics`。已内置两层 Codex 集成：`1)` 默认读取同机 `~/.codex` 自动发现当前 active workspace 的 thread；`2)` 可选启动本地 `codex app-server --listen stdio://` bridge，执行下行控制与审批回写。 |
| **Watchdog** | 逻辑上位于 **OpenClaw 前** 的 FastAPI 服务：通过 HTTP **调用 A** 拉取任务状态，提供 stable session spine、稳定 supervision evaluation / recover / 审批与事件读面，以及 `/metrics`。它既可以独立运行在 **B 机**，也可以与 `A-Control-Agent` 同机部署在 **A 机** 后再通过稳定入口暴露给 B。 从 025 开始，策略层只消费 resident session spine 的 persisted snapshot，并产出 canonical decision record / decision evidence，而不再向 A 侧直接发 raw fact query。 |
| **OpenClaw 侧** | 本仓库**不包含**飞书机器人或生产级 OpenClaw 插件；当前提供 **HTTP API**、`examples/openclaw_watchdog_client.py` 调用模板，以及 `examples/openclaw_webhook_runtime.py` 最小 reference runtime，供你在 OpenClaw 宿主里对接 Watchdog。 |

**数据流（目标架构）**：

```text
飞书 → OpenClaw(B) → Watchdog(可在 A 或 B) ──HTTPS+Bearer──→ A-Control-Agent(A) ──stdio/本地子进程──→ Codex app-server（可选）
```

当前实现中，**OpenClaw 只需对接 Watchdog**；Watchdog 再对接 A-Control-Agent。

025 当前新增的最小策略真值约定如下：

- canonical policy seam 是 `evaluate_session_policy_from_persisted_spine(...)`；它只读 persisted session spine。
- canonical decision 去重键是 `decision_key = session_id + fact_snapshot_version + policy_version + decision_result + action_ref + approval_id`。
- 决策证据包至少包含 `facts`、`matched_policy_rules`、`risk_class`、`decision`、`decision_reason`、`why_*_escalated`、`policy_version`、`fact_snapshot_version`、`idempotency_key` 与 `operator_notes`。
- 025 仍然不执行真实动作，也不做 envelope / delivery；这些留给后续 026/027。

### 1.1 当前推荐部署约定

- **仓库地址**：`https://github.com/sinclairpan-git/openclaw-codex-watchdog.git`
- **A / B 都是 macOS**，都建议使用 `launchd` 守护进程方式启动。
- **A 与 B 都保留一份同版本代码工程**；不要让两台机器漂在不同分支或不同提交上。
- 首次安装与后续升级都按**执行时 `origin/main` 的最新提交**进行；先打印该提交时间与摘要，再由 A、B 同步切到同一个提交。
- 飞书和 OpenClaw 之间的消息通道**不需要改协议**；需要改的是 OpenClaw 收到消息后的路由逻辑，让它改为调用 Watchdog。

当前文档基线安装约定如下：

```bash
export REPO_URL=https://github.com/sinclairpan-git/openclaw-codex-watchdog.git
export APP_DIR="$HOME/openclaw-codex-watchdog"
```

首次安装：

```bash
git clone "$REPO_URL" "$APP_DIR"
cd "$APP_DIR"
git fetch --tags origin
git log origin/main -1 --date=iso --pretty=format:'RELEASE_REF=%H%nRELEASE_TIME=%cd%nRELEASE_SUBJECT=%s'
RELEASE_REF="$(git rev-parse origin/main)"
git checkout "$RELEASE_REF"
uv sync
```

若本机已存在代码工程，则跳过 `git clone`，只执行：

```bash
cd "$APP_DIR"
git fetch --tags origin
git log origin/main -1 --date=iso --pretty=format:'RELEASE_REF=%H%nRELEASE_TIME=%cd%nRELEASE_SUBJECT=%s'
RELEASE_REF="$(git rev-parse origin/main)"
git checkout "$RELEASE_REF"
uv sync
```

后续升级时，不再手填占位版本，而是先读取远端最新提交时间，再按该提交升级：

```bash
cd "$HOME/openclaw-codex-watchdog"
git fetch --tags origin
git log origin/main -1 --date=iso --pretty=format:'LATEST_REF=%H%nLATEST_TIME=%cd%nLATEST_SUBJECT=%s'
LATEST_REF="$(git rev-parse origin/main)"
git checkout "$LATEST_REF"
uv sync
```

升级顺序固定为：**先升 A，再升 B，最后验证 OpenClaw 调用 B**。

---

## 2. A 机（跑 Codex 的开发机）怎么用

### 2.1 你需要准备什么

- Python **≥ 3.11**，建议用 [uv](https://github.com/astral-sh/uv) 或 venv。
- 本仓库克隆到 A 机（或仅部署打包后的服务与配置）。
- 与 B 机 **网络互通**（同局域网 / VPN / Tailscale 等），且 A 上服务监听地址能被 B 访问（勿把服务只绑在 `127.0.0.1` 若 B 在另一台机器）。

### 2.2 安装、启动与开机自启（macOS 推荐）

先准备并安装到指定版本：

```bash
export REPO_URL=https://github.com/sinclairpan-git/openclaw-codex-watchdog.git
export APP_DIR="$HOME/openclaw-codex-watchdog"

git clone "$REPO_URL" "$APP_DIR" 2>/dev/null || true
cd "$APP_DIR"
git fetch --tags origin
git log origin/main -1 --date=iso --pretty=format:'RELEASE_REF=%H%nRELEASE_TIME=%cd%nRELEASE_SUBJECT=%s'
RELEASE_REF="$(git rev-parse origin/main)"
git checkout "$RELEASE_REF"
uv sync
mkdir -p "$APP_DIR/bin" "$HOME/Library/LaunchAgents"
```

从 **`config/examples/a-agent.env.example`** 复制一份，例如 `.env.a`，设置：

| 变量 | 含义 |
|------|------|
| `A_AGENT_API_TOKEN` | **强随机**共享密钥；所有访问 A 的 API 都要带 `Authorization: Bearer <token>` |
| `A_AGENT_HOST` | 监听地址；跨机访问时常用 `0.0.0.0` |
| `A_AGENT_PORT` | 默认 `8710` |
| `A_AGENT_DATA_DIR` | 任务与审计落盘目录（默认 `.data/a_control_agent`） |
| `A_AGENT_CODEX_HOME` | Codex Desktop 本地状态目录；默认 `~/.codex` |
| `A_AGENT_CODEX_SYNC_INTERVAL_SECONDS` | 采集当前本地 Codex thread 的轮询周期（默认 `30` 秒） |
| `A_AGENT_CODEX_BRIDGE_ENABLED` | 是否启用本地 Codex app-server bridge；要实现完整 continue / 审批回写时建议 `true` |
| `A_AGENT_CODEX_BRIDGE_COMMAND` | 启动命令；默认 `codex app-server --listen stdio://` |
| `A_AGENT_CODEX_BRIDGE_REQUEST_TIMEOUT_SECONDS` | bridge 请求超时（默认 `10` 秒） |

推荐环境文件内容：

```bash
A_AGENT_API_TOKEN=<强随机tokenA>
A_AGENT_HOST=0.0.0.0
A_AGENT_PORT=8710
A_AGENT_DATA_DIR=.data/a_control_agent
A_AGENT_CODEX_HOME=~/.codex
A_AGENT_CODEX_SYNC_INTERVAL_SECONDS=30
A_AGENT_CODEX_BRIDGE_ENABLED=true
A_AGENT_CODEX_BRIDGE_COMMAND=codex app-server --listen stdio://
A_AGENT_CODEX_BRIDGE_REQUEST_TIMEOUT_SECONDS=10
```

写启动脚本 `"$APP_DIR/bin/start-a-agent.sh"`：

```bash
#!/bin/zsh
set -euo pipefail
APP_DIR="$HOME/openclaw-codex-watchdog"
cd "$APP_DIR"
set -a
source "$APP_DIR/.env.a"
set +a
exec uv run uvicorn a_control_agent.main:app \
  --host "$A_AGENT_HOST" \
  --port "$A_AGENT_PORT" \
  --app-dir src
```

为脚本赋权：

```bash
chmod +x "$APP_DIR/bin/start-a-agent.sh"
```

写 `launchd` 文件 `~/Library/LaunchAgents/com.openclaw.a-control-agent.plist`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>com.openclaw.a-control-agent</string>
    <key>ProgramArguments</key>
    <array>
      <string>/bin/zsh</string>
      <string>/Users/YOUR_USER/openclaw-codex-watchdog/bin/start-a-agent.sh</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/YOUR_USER/openclaw-codex-watchdog</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/YOUR_USER/Library/Logs/openclaw-a-agent.out.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/YOUR_USER/Library/Logs/openclaw-a-agent.err.log</string>
  </dict>
</plist>
```

将 `YOUR_USER` 替换为真实用户名后，加载并启动：

```bash
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.openclaw.a-control-agent.plist" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.openclaw.a-control-agent.plist"
launchctl kickstart -k "gui/$(id -u)/com.openclaw.a-control-agent"
```

健康检查：

```bash
curl http://127.0.0.1:8710/healthz
curl http://<A的IP>:8710/healthz
```

看日志：

```bash
tail -f "$HOME/Library/Logs/openclaw-a-agent.out.log"
tail -f "$HOME/Library/Logs/openclaw-a-agent.err.log"
```

后续升级：

```bash
cd "$HOME/openclaw-codex-watchdog"
git fetch --tags origin
git log origin/main -1 --date=iso --pretty=format:'LATEST_REF=%H%nLATEST_TIME=%cd%nLATEST_SUBJECT=%s'
LATEST_REF="$(git rev-parse origin/main)"
git checkout "$LATEST_REF"
uv sync
launchctl kickstart -k "gui/$(id -u)/com.openclaw.a-control-agent"
```

### 2.3 与「Codex」的关系（重要）

- 本服务 **不会自动替你操作 Codex UI**。
- 但如果 A-Control-Agent 与 Codex Desktop 在**同一台机器**，默认启动路径会读取
  `A_AGENT_CODEX_HOME`（默认 `~/.codex`）：
  - 从本地 `state_5.sqlite` 找出当前 active workspace 的 thread
  - 读取 rollout JSONL，提取 `last_summary`、`phase`、`files_touched`、`pending_approval`、`context_pressure`
  - 以 `thread_id` upsert 到 A-Control-Agent 的任务存储
- 若设置 `A_AGENT_CODEX_BRIDGE_ENABLED=true`，A-Control-Agent 会以子进程方式启动本地
  `codex app-server --listen stdio://`，并通过 stdio bridge 执行：
  - `thread/read`
  - `turn/start`
  - `turn/steer`
  - 审批请求登记与审批决策回写
- 若不启用 bridge，服务仍然可以只依赖本地 `~/.codex` 采集与手动注册工作。

### 2.4 未启用 app-server bridge 时，如何接当前原生 Codex thread

现在有两条路：

1. **自动采集（推荐）**  
   A-Control-Agent 跑在 Codex Desktop 同机时，直接启动即可；默认会自动读取 `~/.codex`，
   按 `A_AGENT_CODEX_SYNC_INTERVAL_SECONDS` 周期同步当前 active workspace 的 thread。

2. **手动/外部注册**  
   如果你要接入的 thread 不在本机 `~/.codex`，或希望由外部流程显式推送状态，继续使用：
   - `POST /api/v1/tasks/native-threads`
   - 示例 payload：`examples/native_thread_payload.json`
   - 示例脚本：`examples/register_native_thread.py`

手动注册示例：

```bash
export A_AGENT_BASE_URL=http://<A的IP>:8710
export A_AGENT_API_TOKEN=<与 A_AGENT_API_TOKEN 相同>
uv run python examples/register_native_thread.py \
  --payload examples/native_thread_payload.json
```

如果要更新同一个 thread 的最新状态，继续对同一路径重复 `POST` 即可；以同一个
`thread_id` 上报时会执行 upsert，而不是创建新 thread。

---

## 3. B 机（跑 OpenClaw 的机器）怎么用

### 3.1 Watchdog 安装、启动与开机自启（macOS 推荐）

若你采用“**Watchdog 与 A-Control-Agent 同机部署在 A**”的形态，这一节可跳过；B 机只需要拿到 `WATCHDOG_BASE_URL` 与 `WATCHDOG_API_TOKEN` 去调用 A 上暴露出来的 Watchdog 稳定入口。

同样在 B 机准备并安装到指定版本：

```bash
export REPO_URL=https://github.com/sinclairpan-git/openclaw-codex-watchdog.git
export APP_DIR="$HOME/openclaw-codex-watchdog"

git clone "$REPO_URL" "$APP_DIR" 2>/dev/null || true
cd "$APP_DIR"
git fetch --tags origin
git log origin/main -1 --date=iso --pretty=format:'RELEASE_REF=%H%nRELEASE_TIME=%cd%nRELEASE_SUBJECT=%s'
RELEASE_REF="$(git rev-parse origin/main)"
git checkout "$RELEASE_REF"
uv sync
mkdir -p "$APP_DIR/bin" "$HOME/Library/LaunchAgents"
```

从 **`config/examples/watchdog.env.example`** 复制，例如 `.env.w`：

| 变量 | 含义 |
|------|------|
| `WATCHDOG_API_TOKEN` | Watchdog 自身 API 的密钥；**OpenClaw 调 Watchdog** 时使用 |
| `WATCHDOG_HOST` / `WATCHDOG_PORT` | B 上监听地址与端口（默认 `8720`） |
| `WATCHDOG_A_AGENT_BASE_URL` | **A-Control-Agent 的根 URL**，例如 `http://10.0.0.5:8710` 或 `https://a-agent.internal` |
| `WATCHDOG_A_AGENT_TOKEN` | **必须与 `A_AGENT_API_TOKEN` 一致**（Watchdog 代表 B 去调用 A） |
| `WATCHDOG_HTTP_TIMEOUT_S` | 调用 A 的超时（秒） |
| `WATCHDOG_DATA_DIR` | Watchdog 侧审计等（默认 `.data/watchdog`） |
| `WATCHDOG_RECOVER_AUTO_RESUME` | `context_pressure` 为 critical 时，handoff 成功后是否再自动调 A 的 `resume`（`true`/`false`） |
| `WATCHDOG_OPENCLAW_WEBHOOK_BASE_URL` | Watchdog 主动回调 OpenClaw 的根 URL；实际投递路径固定为 `/openclaw/v1/watchdog/envelopes` |
| `WATCHDOG_OPENCLAW_WEBHOOK_TOKEN` | Watchdog 调 OpenClaw webhook 时使用的 Bearer token |
| `WATCHDOG_DELIVERY_TRANSPORT` | 当前 delivery transport；默认 `openclaw`，切到 Feishu 主控制面时设为 `feishu` |
| `WATCHDOG_FEISHU_EVENT_INGRESS_MODE` / `WATCHDOG_FEISHU_CALLBACK_INGRESS_MODE` | Feishu 入站模式；默认 `callback`，本地无公网域名时建议都设为 `long_connection` |
| `WATCHDOG_FEISHU_APP_ID` / `WATCHDOG_FEISHU_APP_SECRET` | Feishu 自建应用凭据；启用 Feishu direct delivery 时必填 |
| `WATCHDOG_FEISHU_VERIFICATION_TOKEN` | Feishu 官方 event subscription / URL verification 使用的 verification token |
| `WATCHDOG_FEISHU_RECEIVE_ID` / `WATCHDOG_FEISHU_RECEIVE_ID_TYPE` | Watchdog 出站消息默认投递目标，例如 `chat_id` 或其他 Feishu receive id |
| `WATCHDOG_FEISHU_INTERACTION_WINDOW_SECONDS` | Feishu ingress 允许的交互窗口秒数；默认 `900` |
| `WATCHDOG_DELIVERY_WORKER_INTERVAL_SECONDS` | delivery worker 轮询 `delivery_outbox` 的周期（默认 `5` 秒） |
| `WATCHDOG_DELIVERY_INITIAL_BACKOFF_SECONDS` | delivery 重试初始退避秒数（默认 `5` 秒，之后指数退避） |
| `WATCHDOG_DELIVERY_MAX_ATTEMPTS` | 单 envelope 最大投递次数；超限后落 `delivery_failed` |
| `WATCHDOG_SESSION_SPINE_REFRESH_INTERVAL_SECONDS` | resident session spine 后台刷新周期（默认 `30` 秒） |
| `WATCHDOG_RESIDENT_ORCHESTRATOR_INTERVAL_SECONDS` | resident policy/execution/delivery 编排周期（默认 `5` 秒） |
| `WATCHDOG_PROGRESS_SUMMARY_INTERVAL_SECONDS` | 同项目 progress summary 主动推送的最短间隔（默认 `300` 秒） |
| `WATCHDOG_OPS_BLOCKED_TOO_LONG_SECONDS` | `block_and_alert` 未消解多久后触发 `blocked_too_long`（默认 `900` 秒） |
| `WATCHDOG_OPS_APPROVAL_PENDING_TOO_LONG_SECONDS` | pending approval 超过多久后触发 `approval_pending_too_long`（默认 `900` 秒） |
| `WATCHDOG_BOOTSTRAP_WEBHOOK_BASE_URL` | A 机 public Watchdog 地址变化后，要主动通知的 B 机 bootstrap webhook 根 URL；实际路径固定为 `/openclaw/v1/watchdog/bootstrap` |
| `WATCHDOG_BOOTSTRAP_WEBHOOK_TOKEN` | 调 bootstrap webhook 时使用的 Bearer token |
| `WATCHDOG_PUBLIC_TUNNEL_LOG_PATH` | A 机 `cloudflared quick tunnel` 日志路径；notifier 从这里提取最新 `trycloudflare` URL |
| `WATCHDOG_PUBLIC_URL_STATE_FILE` | notifier 记录“上次已通知 URL”的持久文件 |
| `WATCHDOG_PUBLIC_URL_NOTIFY_INTERVAL_SECONDS` | notifier 轮询 tunnel 日志并检查 URL 变化的周期 |
| `WATCHDOG_PUBLIC_URL_SOURCE` | 回调到 B 机 bootstrap webhook 时携带的 source 字段 |
| `WATCHDOG_OPENCLAW_WEBHOOK_ENDPOINT_STATE_FILE` | A 机持久化 B 机最新公网 envelope webhook 根地址的文件；delivery 每次发送前优先读这里，store miss 时才回退到 `WATCHDOG_OPENCLAW_WEBHOOK_BASE_URL` |
| `WATCHDOG_BRAIN_PROVIDER_NAME` | Brain provider 选择；默认 `resident_orchestrator`，切到外部模型时设为 `openai-compatible` |
| `WATCHDOG_BRAIN_PROVIDER_BASE_URL` | `OpenAI-compatible` provider 根地址，例如 `https://api.openai.com/v1` |
| `WATCHDOG_BRAIN_PROVIDER_API_KEY` | `OpenAI-compatible` provider token |
| `WATCHDOG_BRAIN_PROVIDER_MODEL` | `OpenAI-compatible` provider 的模型 ID |

推荐环境文件内容：

```bash
WATCHDOG_API_TOKEN=<强随机tokenB>
WATCHDOG_HOST=0.0.0.0
WATCHDOG_PORT=8720
WATCHDOG_A_AGENT_BASE_URL=http://<A的IP>:8710
WATCHDOG_A_AGENT_TOKEN=<必须等于A_AGENT_API_TOKEN>
WATCHDOG_HTTP_TIMEOUT_S=10
WATCHDOG_DATA_DIR=.data/watchdog
WATCHDOG_RECOVER_AUTO_RESUME=true
WATCHDOG_OPENCLAW_WEBHOOK_BASE_URL=http://<OpenClaw的IP或域名>:8740
WATCHDOG_OPENCLAW_WEBHOOK_TOKEN=<强随机tokenOC>
WATCHDOG_DELIVERY_TRANSPORT=openclaw
WATCHDOG_DELIVERY_WORKER_INTERVAL_SECONDS=5
WATCHDOG_DELIVERY_INITIAL_BACKOFF_SECONDS=5
WATCHDOG_DELIVERY_MAX_ATTEMPTS=3
WATCHDOG_SESSION_SPINE_REFRESH_INTERVAL_SECONDS=30
WATCHDOG_RESIDENT_ORCHESTRATOR_INTERVAL_SECONDS=5
WATCHDOG_PROGRESS_SUMMARY_INTERVAL_SECONDS=300
WATCHDOG_OPS_BLOCKED_TOO_LONG_SECONDS=900
WATCHDOG_OPS_APPROVAL_PENDING_TOO_LONG_SECONDS=900
WATCHDOG_BOOTSTRAP_WEBHOOK_BASE_URL=http://127.0.0.1:8740
WATCHDOG_BOOTSTRAP_WEBHOOK_TOKEN=<B端bootstrap webhook token>
WATCHDOG_PUBLIC_TUNNEL_LOG_PATH=$HOME/Library/Logs/openclaw-watchdog.public-tunnel.err.log
WATCHDOG_PUBLIC_URL_STATE_FILE=.data/watchdog/public_endpoint_state.json
WATCHDOG_PUBLIC_URL_NOTIFY_INTERVAL_SECONDS=10
WATCHDOG_PUBLIC_URL_SOURCE=a-host-watchdog
WATCHDOG_OPENCLAW_WEBHOOK_ENDPOINT_STATE_FILE=.data/watchdog/openclaw_webhook_endpoint.json
WATCHDOG_BASE_URL=http://127.0.0.1:8720
WATCHDOG_DEFAULT_PROJECT_ID=
WATCHDOG_OPERATOR=openclaw
WATCHDOG_BRAIN_PROVIDER_NAME=resident_orchestrator
```

027 当前新增的最小可靠投递约定如下：

- Watchdog 会把 canonical decision / approval response 先持久化到 `WATCHDOG_DATA_DIR/policy_decisions.json` 与 `WATCHDOG_DATA_DIR/delivery_outbox.json`，再由后台 worker 异步投递给 OpenClaw。
- 同一 `session_id` 内固定按 `fact_snapshot_version` 再按 `outbox_seq` 投递；被 retry backoff 卡住的 session 只阻塞自己，不阻塞其他 session。
- `require_user_decision` 只先发 `ApprovalEnvelope`；OpenClaw 调 `POST /api/v1/watchdog/openclaw/responses` 完成 `approve` / `reject` / `execute_action` 后，Watchdog 会再补发 `NotificationEnvelope(notification_kind=approval_result)`。
- delivered 判定必须同时满足 `HTTP 2xx`、`accepted=true`、响应 `envelope_id` 与请求一致、以及存在 `receipt_id`；协议不完整的 `2xx` 仍会重试。
- worker 会在 `operator_notes` 中记录 `delivery_retry_scheduled`、`delivery_succeeded`、`delivery_dead_letter`，便于最小运维排障。
- 当前仓库还新增了 resident orchestrator：后台会持续执行 `session spine refresh -> policy evaluate -> auto recovery / approval materialize -> enqueue delivery -> call OpenClaw`，并对普通进展变化按 `progress_summary` 做节流主动推送；OpenClaw 不需要记住流程状态。
- 如果 B 机自己的公网 envelope webhook 地址会变化，A 机还提供 `POST /api/v1/watchdog/bootstrap/openclaw-webhook`。B 机只要带 `Authorization: Bearer <WATCHDOG_API_TOKEN>` 回传 `event_type=openclaw_webhook_base_url_changed`、`openclaw_webhook_base_url`、`changed_at`、`source`，A 机就会把最新地址持久化到 `WATCHDOG_OPENCLAW_WEBHOOK_ENDPOINT_STATE_FILE`，后续 delivery 自动切换到新地址。

### 3.2 切到 Feishu 主控制面（长连接优先，保留 HTTP fallback）

如果你已经有可用的 Feishu 自建应用，但本地没有公网域名，建议把 Feishu 的事件配置和回调配置都切成长连接模式。仓库内的 HTTP callback `POST /api/v1/watchdog/feishu/events` 继续保留，作为 repo-local smoke、回归测试与 fallback contract，不需要从飞书控制台删除。

最小环境变量建议如下：

```bash
WATCHDOG_FEISHU_EVENT_INGRESS_MODE=long_connection
WATCHDOG_FEISHU_CALLBACK_INGRESS_MODE=long_connection
WATCHDOG_FEISHU_APP_ID=<Feishu app id>
WATCHDOG_FEISHU_APP_SECRET=<Feishu app secret>
WATCHDOG_FEISHU_VERIFICATION_TOKEN=<Feishu verification token>
WATCHDOG_DELIVERY_TRANSPORT=feishu
WATCHDOG_FEISHU_RECEIVE_ID=<默认 chat_id 或 open_id>
WATCHDOG_FEISHU_RECEIVE_ID_TYPE=chat_id
WATCHDOG_FEISHU_INTERACTION_WINDOW_SECONDS=900
```

说明：

- `WATCHDOG_FEISHU_EVENT_INGRESS_MODE=long_connection` 与 `WATCHDOG_FEISHU_CALLBACK_INGRESS_MODE=long_connection` 会启用仓库内的长连接 bridge；
- 长连接 bridge 是独立脚本 `scripts/watchdog_feishu_long_connection.py`，不挂到 Watchdog 主服务的 lifespan 中；
- `WATCHDOG_DELIVERY_TRANSPORT=feishu` 会把 Watchdog 出站通知切到 Feishu direct delivery；
- `WATCHDOG_FEISHU_VERIFICATION_TOKEN` 仍作为长连接事件与 callback 的 token 校验真值；
- 若 `WATCHDOG_FEISHU_RECEIVE_ID` 还没拿到，可以先保持 `WATCHDOG_DELIVERY_TRANSPORT=openclaw`，先把 Feishu 入站控制面联通；
- 本仓库负责 Watchdog 这一侧的 callback contract，不负责 Feishu 自建应用本身的创建、安装与组织级开关。

最小验收顺序：

1. 保持 `GET /healthz` 正常；
2. 用同一份 `.env.w` 启动 Watchdog 主服务；
3. 单独启动长连接 bridge：

```bash
set -a
source .env.w
set +a
uv run python scripts/watchdog_feishu_long_connection.py
```

4. 在飞书后台把“事件配置”改为“使用长连接接收事件”，bridge 在线后点击“验证”；
5. 在“事件配置”里显式添加至少两条订阅事件：`im.message.receive_v1`（接收消息 v2.0）与 `im.chat.access_event.bot_p2p_chat_entered_v1`（控制台文案通常对应机器人进入单聊）；前者负责 DM 指令入口，后者负责首聊建链与拿到 `chat_id`；
6. 把“回调配置”也改成长连接模式；这条路径无需公网域名、无需额外加密回调地址；
7. 确认机器人相关权限与可用范围已经发布到你当前测试账号；如果这里只完成“长连接验证”而没有完成事件订阅或权限发布，DM 不会投递到本地 bridge；
8. 在 Feishu DM 里发送显式 `repo:<project_id> pause` 或 `/goal ...`，确认 Watchdog 收到 official ingress 并产生对应 canonical event；
9. 若本地 bridge 没有出现 `feishu long-connection message received: chat_id=...` 日志，先去飞书开发者后台的“日志检索 > 事件日志检索”确认平台是否真的推送了 `im.message.receive_v1`，不要先怀疑仓库内解析层；
10. 若已经补齐 `WATCHDOG_FEISHU_RECEIVE_ID`，再触发一条 approval/progress/notification，确认 delivery 走的是 Feishu；否则把这一步延后，不要口头声称出站已经就绪。

如果你想先做 repo-local fallback smoke，可以直接模拟 HTTP callback 的 `url_verification`：

```bash
curl -X POST "http://127.0.0.1:8720/api/v1/watchdog/feishu/events" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "url_verification",
    "token": "<WATCHDOG_FEISHU_VERIFICATION_TOKEN>",
    "challenge": "challenge-123"
  }'
```

预期返回：

```json
{"challenge":"challenge-123"}
```

这条 HTTP route 仍然保留，只是它现在承担的是 fallback / smoke contract，而不是“本地无公网域名时飞书控制台必须直连的正式入口”。

### 3.3 切到 OpenAI-compatible Brain provider

默认配置下，Watchdog 仍使用 `resident_orchestrator`。如果你要切到通用的 `OpenAI-compatible` 外部模型，把 `.env.w` 补成：

```bash
WATCHDOG_BRAIN_PROVIDER_NAME=openai-compatible
WATCHDOG_BRAIN_PROVIDER_BASE_URL=https://api.openai.com/v1
WATCHDOG_BRAIN_PROVIDER_API_KEY=<OpenAI-compatible token>
WATCHDOG_BRAIN_PROVIDER_MODEL=<model-id>
WATCHDOG_MEMORY_PREVIEW_AI_AUTOSDLC_CURSOR_ENABLED=false
```

说明：

- `WATCHDOG_BRAIN_PROVIDER_BASE_URL` 可以指向 OpenAI 官方接口，也可以指向其他兼容 `/chat/completions` contract 的 provider；
- `WATCHDOG_BRAIN_PROVIDER_API_KEY` 与 `WATCHDOG_BRAIN_PROVIDER_MODEL` 缺一不可；
- `WATCHDOG_SMOKE_PROVIDER_LIVE=true` 时，`scripts/watchdog_external_integration_smoke.py --target provider` 会真实请求当前 provider；未开启时默认仍走 synthetic contract，适合 repo-local 回归；
- 若真实 provider 响应更慢，可单独设置 `WATCHDOG_SMOKE_PROVIDER_HTTP_TIMEOUT_S`，避免顺手放大全局 `WATCHDOG_HTTP_TIMEOUT_S`；
- provider runtime 失败时，当前实现会 fail-closed 回退到既有 rule-based / resident runtime 路径，而不是直接放行。

建议验收顺序：

1. 先在 staging / 本地环境切 `WATCHDOG_BRAIN_PROVIDER_NAME=openai-compatible`；
2. 保持 `release_gate_report`、approval freshness 与 risk gate 仍然有效；
3. 触发一条低风险 Brain decision，确认 runtime contract 与 provider request 能正常生成；
4. 再验证 provider 配置缺失或请求失败时，系统会降级而不是 silent pass。

### 3.4 启用 Memory Hub AI_AutoSDLC preview cursor

`WI-071` 已把 Memory Hub 的 `ai-autosdlc-cursor` preview adapter 暴露成 app-level route，但该能力仍是 **preview contract**，默认保持关闭。若你需要给外部控制面或调试脚本读取 stage-aware cursor，请在 `.env.w` 中显式设置：

```bash
WATCHDOG_MEMORY_PREVIEW_AI_AUTOSDLC_CURSOR_ENABLED=true
```

说明：

- route 为 `POST /api/v1/watchdog/memory/preview/ai-autosdlc-cursor`；
- 该 route 仍受 `Authorization: Bearer <WATCHDOG_API_TOKEN>` 保护；
- 若开关保持默认 `false`，route 依然可调用，但返回的 preview payload 会保持 `enabled=false`；
- 这条能力只用于 preview / operator 调试，不改变 Brain、release gate 或 resident orchestrator 的主链决策语义。

最小 smoke test：

```bash
curl -X POST "http://127.0.0.1:8720/api/v1/watchdog/memory/preview/ai-autosdlc-cursor" \
  -H "Authorization: Bearer <WATCHDOG_API_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "request": {
      "project_id": "demo-project",
      "goal": "Close remaining repo-local operator readiness gaps",
      "current_stage": "execute",
      "recent_actions": ["scan docs contract", "review env sample"],
      "latest_summary": "WI-071 landed preview route; operator docs are being closed."
    },
    "quality": {
      "context_compression_ratio": 0.42,
      "summary_freshness_seconds": 90,
      "artifact_recall_ratio": 0.88,
      "pending_questions": []
    }
  }'
```

最小验收顺序：

1. 先确认 `WATCHDOG_MEMORY_PREVIEW_AI_AUTOSDLC_CURSOR_ENABLED=true` 已生效；
2. 调 `POST /api/v1/watchdog/memory/preview/ai-autosdlc-cursor`，确认响应里 `contract_name=ai-autosdlc-cursor`；
3. 确认启用后 `enabled=true`，且 `packet` 中包含当前 stage-aware cursor 内容；
4. 再把开关切回 `false`，确认 route 仍可调用但响应退回 `enabled=false` 的 preview 语义。

### 3.5 统一外部集成 smoke 验收

在本地或 staging 把 Watchdog 拉起后，建议先跑一次统一 smoke，确认外部控制面真正会用到的几个集成面都对齐：

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

说明：

- 默认会跑 `health`、`feishu`、`provider`、`memory` 四类检查；
- `feishu` 会验证 `POST /api/v1/watchdog/feishu/events` 的 `url_verification` 合约；
- `feishu-control` 是额外的 repo-local callback contract smoke，会发送一条 `im.message.receive_v1` 的 DM 文本事件，内容固定为 `repo:<project_id> /goal <goal_message>`，验证官方入口能否真正落到 `goal_contract_bootstrap`；
- `feishu-discovery` 会发送一条默认文本为 `项目列表` 的 Feishu DM synthetic event，要求官方入口真正落到 `list_sessions/session_directory`，并覆盖 `WATCHDOG_SMOKE_FEISHU_DISCOVERY_EXPECTED_PROJECT_IDS` 中声明的项目集合；
- 如果返回的 `progresses[]` 中存在 `recovery_outcome=new_child_session`，脚本还会检查 `message` 里展示的子会话标识与 `recovery_child_session_id` 归一后保持一致；
- 运行 `feishu-control` 前至少要配置 `WATCHDOG_SMOKE_FEISHU_CONTROL_PROJECT_ID` 与 `WATCHDOG_SMOKE_FEISHU_CONTROL_GOAL_MESSAGE`，而且这两个值必须对应一个经操作者确认的可写 live target；这条 smoke 会进入真实 `goal_contract_bootstrap` 写路径，缺失时会以 `operator_confirmation_required` 的 `skipped` 明确提示，并在 evidence 中要求 `confirm_mutating_live_target`，而不是自动猜值；如果没有经确认的 `project_id + goal_message` 组合，整包验收必须继续按 fail-closed 处理；如果还希望锁定具体 session，可额外配置 `WATCHDOG_SMOKE_FEISHU_CONTROL_EXPECTED_SESSION_ID`；若真实数据量较大导致 repo-local callback contract 超过默认 3 秒，可单独设置 `WATCHDOG_SMOKE_FEISHU_CONTROL_HTTP_TIMEOUT_S` 放宽这一项窗口；
- 运行 `feishu-discovery` 前至少要配置 `WATCHDOG_SMOKE_FEISHU_DISCOVERY_EXPECTED_PROJECT_IDS`；若想调整查询文案或操作人，可额外配置 `WATCHDOG_SMOKE_FEISHU_DISCOVERY_COMMAND_TEXT` 与 `WATCHDOG_SMOKE_FEISHU_DISCOVERY_ACTOR_OPEN_ID`；若真实数据量较大导致这条目录发现 smoke 超过默认 30 秒，可单独设置 `WATCHDOG_SMOKE_FEISHU_DISCOVERY_HTTP_TIMEOUT_S`；
- `provider` 默认验证 `WATCHDOG_BRAIN_PROVIDER_NAME=openai-compatible` 时的结构化决策 contract 与 provider 请求失败后的回退路径；显式设置 `WATCHDOG_SMOKE_PROVIDER_LIVE=true` 后，success probe 会真实请求当前 provider；
- 若真实 provider 验收需要更长等待时间，可单独设置 `WATCHDOG_SMOKE_PROVIDER_HTTP_TIMEOUT_S`；
- `memory` 会验证 `POST /api/v1/watchdog/memory/preview/ai-autosdlc-cursor` 的 preview contract；
- 某项能力未启用时允许返回 `skipped`；若能力已启用但配置缺失、返回字段不匹配或回退语义异常，则应视为阻断问题。

排障时仍可继续使用上面的 `curl` 手工调用；这个脚本的目标是把健康检查、飞书入口、外部 provider、Memory Hub preview 收拢成一条统一的 operator 验收路径。
若要沉淀验收记录，可追加 `--markdown-report <path>` 直接输出 Markdown 证据文档；脚本默认 stdout 仍保持 JSON，方便机器读取。

若要把这些步骤用于 staging / production-like 环境的正式联调，请以 `docs/operations/external-integration-live-acceptance.md` 作为 canonical runbook；本节只保留快速上手与命令示例。

仓库已经直接提供可复用脚本与模板：

- `scripts/start_watchdog.sh`
- `scripts/install_watchdog_launchd.sh`
- `scripts/start_watchdog_endpoint_notifier.sh`
- `scripts/install_watchdog_endpoint_notifier_launchd.sh`
- `config/examples/com.openclaw.watchdog.plist`
- `config/examples/com.openclaw.watchdog.endpoint-notifier.plist`

如果你仍想自己写，等价启动脚本如下：

```bash
#!/bin/zsh
set -euo pipefail
APP_DIR="$HOME/openclaw-codex-watchdog"
cd "$APP_DIR"
set -a
source "$APP_DIR/.env.w"
set +a
exec uv run uvicorn watchdog.main:create_runtime_app \
  --host "$WATCHDOG_HOST" \
  --port "$WATCHDOG_PORT" \
  --factory \
  --app-dir src
```

为脚本赋权：

```bash
chmod +x "$APP_DIR/bin/start-watchdog.sh"
```

等价的 `launchd` 模板如下；仓库内已提供 `config/examples/com.openclaw.watchdog.plist`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>com.openclaw.watchdog</string>
    <key>ProgramArguments</key>
    <array>
      <string>/bin/zsh</string>
      <string>/Users/YOUR_USER/openclaw-codex-watchdog/bin/start-watchdog.sh</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/YOUR_USER/openclaw-codex-watchdog</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/YOUR_USER/Library/Logs/openclaw-watchdog.out.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/YOUR_USER/Library/Logs/openclaw-watchdog.err.log</string>
  </dict>
</plist>
```

最简单的安装方式是直接执行：

```bash
cd "$APP_DIR"
WATCHDOG_ENV_FILE="$APP_DIR/.env.w" ./scripts/install_watchdog_launchd.sh
WATCHDOG_ENV_FILE="$APP_DIR/.env.w" ./scripts/install_watchdog_endpoint_notifier_launchd.sh
```

如果 A 机还额外跑了 `cloudflared quick tunnel` 给 Watchdog 暴露公网地址，建议同时安装 endpoint notifier。它会持续读取 `WATCHDOG_PUBLIC_TUNNEL_LOG_PATH`，提取最新 `https://*.trycloudflare.com`，仅在 URL 变化时回调 B 机的 bootstrap webhook，并把已通知状态落盘到 `WATCHDOG_PUBLIC_URL_STATE_FILE`，避免重复通知。

如果 B 机也用 `cloudflared quick tunnel` 给 `POST /openclaw/v1/watchdog/envelopes` 暴露公网地址，则推荐让 B 机额外跑一个对称 notifier：它读取 B 本地当前公网 webhook 根地址，变化时回调 `POST <A机当前Watchdog公网地址>/api/v1/watchdog/bootstrap/openclaw-webhook`。这样 A/B 两端的 quick tunnel 地址都能在重启后自动重新对齐，不需要手改 `.env.w` 或依赖 OpenClaw 记忆。

这会自动把模板渲染到 `~/Library/LaunchAgents/com.openclaw.watchdog.plist`，并完成 `launchctl bootstrap` 与 `launchctl kickstart -k`。若你需要手工重启服务，可直接执行：

```bash
launchctl kickstart -k "gui/$(id -u)/com.openclaw.watchdog"
```

如果仍要手工安装，命令如下：

```bash
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.openclaw.watchdog.plist" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.openclaw.watchdog.plist"
launchctl kickstart -k "gui/$(id -u)/com.openclaw.watchdog"
```

健康检查：

```bash
curl http://127.0.0.1:8720/healthz
curl http://<B的IP>:8720/healthz
curl -H "Authorization: Bearer <WATCHDOG_API_TOKEN>" \
  http://127.0.0.1:8720/api/v1/watchdog/sessions
curl -H "Authorization: Bearer <WATCHDOG_API_TOKEN>" \
  http://127.0.0.1:8720/api/v1/watchdog/ops/alerts
```

看日志：

```bash
tail -f "$HOME/Library/Logs/openclaw-watchdog.out.log"
tail -f "$HOME/Library/Logs/openclaw-watchdog.err.log"
```

后续升级：

```bash
cd "$HOME/openclaw-codex-watchdog"
git fetch --tags origin
git log origin/main -1 --date=iso --pretty=format:'LATEST_REF=%H%nLATEST_TIME=%cd%nLATEST_SUBJECT=%s'
LATEST_REF="$(git rev-parse origin/main)"
git checkout "$LATEST_REF"
uv sync
launchctl kickstart -k "gui/$(id -u)/com.openclaw.watchdog"
```

### 3.2 OpenClaw 怎么调 Watchdog（不经过本仓库代码）

本仓库**不包含**飞书机器人或 OpenClaw runtime；023 交付的是 `examples/openclaw_watchdog_client.py`
里的 `WatchdogTemplateClient`，它把 OpenClaw 常见消息模板收敛到 stable Watchdog HTTP routes。

这里的边界要明确：

- **飞书和 OpenClaw 之间的通道协议不需要改变**。
- 需要改变的是 **OpenClaw 收到飞书消息后的处理逻辑**，让它改为调用 Watchdog，而不是直接对接 A 或依赖手工查询。
- OpenClaw 应只访问 B 上的 Watchdog；不要让 OpenClaw 直接访问 A。

OpenClaw 最小模板建议优先复用以下 4 类消息：

| 消息类型 | 模板方法 | 稳定路由 |
|------|------|------|
| 查询进展 | `query_progress(project_id)` | `GET /api/v1/watchdog/sessions/{project_id}/progress` |
| 查询卡点 | `query_stuck(project_id)` | `GET /api/v1/watchdog/sessions/{project_id}/stuck-explanation` |
| 继续推进 | `continue_session(project_id, operator, idempotency_key)` | `POST /api/v1/watchdog/sessions/{project_id}/actions/continue` |
| 查询审批 inbox | `list_approval_inbox(project_id?)` | `GET /api/v1/watchdog/approval-inbox` |
| 审批决策 | `approve_approval(approval_id, operator, idempotency_key, note)` / `reject_approval(approval_id, operator, idempotency_key, note)` | `POST /api/v1/watchdog/approvals/{approval_id}/approve|reject` |
| 审批响应回流 | 宿主回传 `envelope_id + envelope_type + approval_id + decision_id + response_action + response_token + user_ref + channel_ref + client_request_id` | `POST /api/v1/watchdog/openclaw/responses` |

OpenClaw 模板的环境变量建议最少包括：

| 变量 | 作用 |
|------|------|
| `WATCHDOG_BASE_URL` | Watchdog 对外根 URL，例如 `http://<Watchdog的IP或域名>:8720` |
| `WATCHDOG_API_TOKEN` | OpenClaw 调 Watchdog 时使用的 Bearer Token |
| `WATCHDOG_DEFAULT_PROJECT_ID` | 缺省 `project_id`；显式参数优先，适合单项目会话或固定路由 |
| `WATCHDOG_OPERATOR` | 缺省操作人，示例模板默认值为 `openclaw` |

`project_id` 路由策略：

1. 模板调用显式传入 `project_id` 时，始终优先使用显式值。
2. 未显式传入时，回退到 `WATCHDOG_DEFAULT_PROJECT_ID`。
3. 若仍未知 `project_id`，应先调用 `GET /api/v1/watchdog/sessions`，或在只知道 native thread 时调用 `GET /api/v1/watchdog/sessions/by-native-thread/{native_thread_id}` 做稳定解析。
4. 所有 write action 都要求显式提供非空 `idempotency_key`，这样重试和 receipt 查询才有稳定语义。

最小 Python 用法：

```python
from examples.openclaw_watchdog_client import WatchdogTemplateClient

client = WatchdogTemplateClient()
progress = client.query_progress()
stuck = client.query_stuck()
approval_inbox = client.list_approval_inbox()
```

若要直接对接 028 冻结后的 webhook / response contract，可从 `examples/openclaw_webhook_runtime.py`
起步。这个 reference runtime 只做三件事：

1. 接收 `POST /openclaw/v1/watchdog/envelopes` 的稳定 envelope，并校验固定请求头。
2. 返回最小 receipt：`accepted`、`envelope_id`、`receipt_id`、`received_at`。
3. 把用户结构化响应回传到 `POST /api/v1/watchdog/openclaw/responses`。

这里的边界不要漂移：

- OpenClaw 只做接收、渲染、输入、回传。
- OpenClaw 不做决策、不做风险分类、不维护第二套审批状态机。
- OpenClaw 不维护第二套 session spine，也不直接向 A-Control-Agent 发 raw query。

OpenClaw 侧应优先配置为：对 **Watchdog 基址** 调用 010-022 收口后的 stable surface
（需 `Authorization: Bearer <WATCHDOG_API_TOKEN>`）：

- `GET /api/v1/watchdog/sessions` — 读取稳定跨项目 `SessionProjection[]` 目录
- `GET /api/v1/watchdog/sessions/{project_id}` — 读取稳定 `SessionProjection`
- `GET /api/v1/watchdog/sessions/by-native-thread/{native_thread_id}` — 在只知道 native thread_id 时解析稳定 `SessionProjection`
- `GET /api/v1/watchdog/sessions/{project_id}/facts` — 读取稳定 `ReplyModel(reply_code=session_facts, facts=FactRecord[])`
- `GET /api/v1/watchdog/sessions/{project_id}/progress` — 读取稳定 `TaskProgressView`
- `GET /api/v1/watchdog/sessions/{project_id}/workspace-activity` — 读取稳定 `WorkspaceActivityView`
- `GET /api/v1/watchdog/approval-inbox` — 读取稳定跨项目 pending approvals inbox；可选 `?project_id=...`
- `GET /api/v1/watchdog/sessions/{project_id}/pending-approvals` — 读取稳定审批队列
- `GET /api/v1/watchdog/sessions/{project_id}/stuck-explanation` — 读取稳定 stuck explanation reply
- `GET /api/v1/watchdog/sessions/{project_id}/blocker-explanation` — 读取稳定 blocker explanation reply
- `GET /api/v1/watchdog/sessions/{project_id}/events` — 读取稳定、版本化 `SessionEvent` SSE
- `GET /api/v1/watchdog/sessions/{project_id}/event-snapshot` — 读取稳定 `ReplyModel(reply_code=session_event_snapshot, events=SessionEvent[])` JSON snapshot；缺失 raw `event_id` 时会先补 deterministic synthetic id，再按 repeated `event_id` 去重
- `GET /api/v1/watchdog/action-receipts?action_code=...&project_id=...&idempotency_key=...` — 读取稳定 action receipt reply
- `POST /api/v1/watchdog/actions` — canonical write surface，提交 `WatchdogAction`
- `POST /api/v1/watchdog/sessions/{project_id}/actions/continue` — continue 的 alias wrapper
- `POST /api/v1/watchdog/sessions/{project_id}/actions/evaluate-supervision` — evaluate_supervision 的 alias wrapper，返回稳定 `SupervisionEvaluation`
- `POST /api/v1/watchdog/sessions/{project_id}/actions/post-guidance` — post_operator_guidance 的 alias wrapper，提交稳定 operator guidance
- `POST /api/v1/watchdog/sessions/{project_id}/actions/request-recovery` — request_recovery 的 alias wrapper，仅 advisory-only
- `POST /api/v1/watchdog/sessions/{project_id}/actions/execute-recovery` — execute_recovery 的 alias wrapper，触发稳定 recovery execution
- `GET /api/v1/watchdog/sessions/{project_id}/action-receipts/{action_code}/{idempotency_key}` — action receipt 的 alias wrapper
- `POST /api/v1/watchdog/approvals/{approval_id}/approve` — approve 的 alias wrapper
- `POST /api/v1/watchdog/approvals/{approval_id}/reject` — reject 的 alias wrapper
- `POST /api/v1/watchdog/openclaw/responses` — canonical approval response surface；以 `(envelope_id, response_action, client_request_id)` 做响应幂等

028 冻结后的 webhook / response contract 细节如下：

- Watchdog 主动投递入口固定为 `POST /openclaw/v1/watchdog/envelopes`。
- webhook 请求头最少要求 `Authorization`、`X-Watchdog-Delivery-Id`、`X-Watchdog-Timestamp`、`X-Watchdog-Signature`。
- 宿主 receipt 最少要求 `accepted=true`、`envelope_id`、`receipt_id`、`received_at`。
- 宿主回传审批响应时，`response_token`、`user_ref`、`channel_ref` 也属于冻结 contract 的必填字段。

如果 OpenClaw 需要稳定事件流，应优先使用：

- `GET /api/v1/watchdog/sessions/{project_id}/events` — stable SSE；`follow=true` 时会先发一段 stable bootstrap snapshot：其中包含 projected raw snapshot 事件，以及 continuity 相关的 selected canonical `Session Service` 事件（例如 `goal_contract_adopted_by_child_session`、`recovery_execution_suppressed`、`interaction_context_superseded`）；随后再继续把 raw `task_created / native_thread_registered / steer / handoff / resume / approval_decided` 投影为 `session_created / native_thread_bound / guidance_posted / handoff_requested / session_resumed / approval_resolved`，未知 raw 类型降级为 `session_updated`，并按 `event_id` 去重 A 侧可能重放的 backlog；如果 raw 事件缺失 `event_id`，则先按稳定字段指纹生成 deterministic synthetic id 后再去重；若 stream startup 失败，则回退到已拿到的 bootstrap 事件；`follow=false` 的 snapshot 读取会额外合并更完整的 selected canonical `Session Service` 事件（包括 `goal_contract_*`）
- `GET /api/v1/watchdog/sessions/{project_id}/event-snapshot` — stable JSON snapshot，返回 `ReplyModel(reply_code=session_event_snapshot, events=SessionEvent[])`；它与上面的 stable SSE 共享同一份 event schema version，但快照读取会把 projected raw 事件与 selected canonical `Session Service` 事件合并；缺失 raw `event_id` 时会先补 deterministic synthetic id，再按 repeated `event_id` 去重，确保 recovery / goal-contract lineage 在 control link 降级时仍可读；不提供 follow / cursor，只表达“一次性读取当前稳定事件快照”

如果只需要 raw 透传，legacy 代理路径仍可用：

- `GET /api/v1/watchdog/tasks/{project_id}/events` — 由 Watchdog 代理的任务事件流（支持 `follow=true|false`）

仓库内示例：

```bash
export WATCHDOG_BASE_URL=http://<B的IP>:8720
export WATCHDOG_API_TOKEN=<与 WATCHDOG_API_TOKEN 相同>
export WATCHDOG_DEFAULT_PROJECT_ID=<可选，单项目时推荐>
uv run python examples/openclaw_watchdog_client.py
```

更多路径见 `docs/openapi/watchdog.json`（运行 `uv run python scripts/export_openapi.py` 可重新生成）。

说明：

- 017 新增的 `GET /api/v1/watchdog/sessions` 与 OpenClaw adapter `list_sessions`
  复用同一份 stable directory builder，适合在尚未知晓 `project_id` 时先拉取会话目录。

- 018 新增的 `GET /api/v1/watchdog/sessions/by-native-thread/{native_thread_id}` 与 OpenClaw
  adapter `get_session_by_native_thread` 复用同一份 stable session builder，适合 OpenClaw
  只有 native thread_id、尚未显式缓存 `project_id` 时做稳定会话解析；A 侧 raw
  `GET /api/v1/tasks/by-thread/{thread_id}` 继续存在，但不再承担 stable contract 角色。

- 019 新增的 `GET /api/v1/watchdog/sessions/{project_id}/workspace-activity` 与 OpenClaw
  adapter `get_workspace_activity` 复用同一份 stable workspace activity builder，返回
  `ReplyModel(reply_code=workspace_activity_view, workspace_activity=WorkspaceActivityView)`；
  它不会让 OpenClaw 直接消费 raw 工作区摘要，也不会引入新的动作面。A 侧 raw
  `GET /api/v1/tasks/{project_id}/workspace-activity` 继续存在，但不再承担 stable contract 角色。

- canonical 动作面始终是 `POST /api/v1/watchdog/actions`，路径级动作只是便于人工调用的包装。
- 020 新增的稳定 operator guidance 动作是 `WatchdogAction(action_code=post_operator_guidance)`；
  它要求 `arguments.message` 非空，可选 `reason_code` 与 `stuck_level`，成功时返回
  `WatchdogActionResult(reply_code=action_result, effect=steer_posted)`。alias route
  `POST /api/v1/watchdog/sessions/{project_id}/actions/post-guidance` 只是 canonical 动作的包装；
  A 侧 raw `POST /api/v1/tasks/{project_id}/steer` 继续存在，但不再承担 stable contract 角色。
- 022 新增的 `GET /api/v1/watchdog/sessions/{project_id}/facts` 与 OpenClaw adapter
  `list_session_facts` 复用同一份 stable facts builder，返回
  `ReplyModel(reply_code=session_facts, facts=FactRecord[])`。它承担“事实真值层”角色；
  015 引入的 `stuck-explanation` / `blocker-explanation` 继续承担“解释层”角色，二者并存，
  不互相替代，也不引入 fact history / filter / 分页语义。
- 015 新增的两个 explanation route 仍然复用既有 `ReplyModel`，不会新增 explanation DTO，也不会推进 session spine contract/schema version；它们与 OpenClaw adapter 共享同一套 explanation builder。
- 016 新增的 `GET /api/v1/watchdog/approval-inbox` 复用既有 `ApprovalProjection`，返回稳定 `ReplyModel(reply_code=approval_inbox)`；它只覆盖 pending approvals inbox，不提供 history / status passthrough，也不替换 legacy `/watchdog/approvals` raw proxy。
- 026 新增的 canonical approval loop 会把 `require_user_decision` 物化为本地 persisted approval envelope；宿主回流时只允许 `approve`、`reject`、`execute_action` 三种 response action，同一 `(envelope_id, response_action, client_request_id)` 重放时会复用已持久化 response record，不会重复执行审批决定或底层 canonical action。
- 014 新增的稳定监管评估动作是 `WatchdogAction(action_code=evaluate_supervision)`；它返回 `WatchdogActionResult(reply_code=supervision_evaluation)` 与 `SupervisionEvaluation`，必要时才执行一次 advisory steer。
- `request_recovery` 仍只返回恢复可用性说明，不会触发真实恢复执行；真实执行动作是 012 新增的 `execute_recovery`。
- 013 新增的 action receipt 读面只查询本地持久化 receipt，返回 `ReplyModel(reply_code=action_receipt|action_receipt_not_found)`；它不会重放动作，也不会借道 legacy recover / approvals / steer 路由推断结果。
- 原有 `progress / evaluate / approvals / recover / events` raw / legacy 接口继续存在，但不再承担 stable contract 角色；`/watchdog/tasks/{project_id}/events` 仍是 raw/legacy，`/watchdog/sessions/{project_id}/events` 才是 011 引入的 stable 事件面，`/watchdog/tasks/{project_id}/recover` 是复用 012 recovery kernel 的兼容入口，`/watchdog/tasks/{project_id}/evaluate` 则是复用 014 supervision evaluation kernel 的兼容入口。

若 B 侧需要更实时地感知 A 的任务变化，A-Control-Agent 现已提供：

- `GET /api/v1/tasks/{project_id}/events` — 基础 SSE 事件流

若 OpenClaw 不直接访问 A，也可通过 Watchdog 代理：

- `GET /api/v1/watchdog/tasks/{project_id}/events` — B 侧透传 A 的 SSE 事件流

默认会持续跟随新事件；若只想读取当前已落盘事件，可加 `?follow=false`。

---

## 4. 两机服务如何对接（ checklist）

1. **网络**：从 B `curl` 到 `WATCHDOG_A_AGENT_BASE_URL/healthz` 成功。  
2. **Token**：`WATCHDOG_A_AGENT_TOKEN` **等于** A 的 `A_AGENT_API_TOKEN`。  
3. **防火墙 / 安全组**：A 的 `A_AGENT_PORT` 仅对 B（或 VPN 网段）开放。  
4. **生产建议**：前面加 **反向代理 + TLS**（如 nginx/Caddy），对外只暴露 HTTPS；Token 用密钥管理。  
5. **验证**：在 B 上带 Watchdog token 调 `GET .../watchdog/sessions/{project_id}/progress`，若 A 无此任务应返回业务错误而非连接失败。
6. **版本一致**：A 与 B 均已 `git checkout` 到同一个提交；推荐在两机分别执行 `git rev-parse HEAD`，并确认两边结果一致且等于部署当时的 `origin/main` 最新提交。

---

## 5. 监控与文档

- **Prometheus**：`GET /metrics`（A、Watchdog 各一份）。Watchdog 额外固定导出 `watchdog_ops_alert_active{alert="..."}` 五类告警 gauge：`approval_pending_too_long`、`blocked_too_long`、`delivery_failed`、`mapping_incomplete`、`recovery_failed`。  
- **Health**：`GET /healthz`。Watchdog 返回 `status` 与 `active_alerts`；有活动告警时状态会降为 `degraded`。  
- **Ops Alerts**：`GET /api/v1/watchdog/ops/alerts`。这个接口是 operator 看的结构化告警面。  
- **Audit / Replay**：forensic 只消费 canonical records：`policy_decisions.json`、`canonical_approvals.json`、`delivery_outbox.json`、`action_receipts.json`。  
- **OpenAPI**：`uv run python scripts/export_openapi.py` → `docs/openapi/`。  
- **需求真值**：仓库根目录 `openclaw-codex-watchdog-prd.md`。

---

### 5.1 最小 operator runbook

1. 先看 `GET /healthz`。若 `status=degraded`，读取 `active_alerts` 判断是否需要进一步排障。
2. 再看 `GET /api/v1/watchdog/ops/alerts`。当前冻结的五类告警分别对应：
   - `approval_pending_too_long`：审批长期未处理，先检查 `GET /api/v1/watchdog/approval-inbox` 与宿主消息投递。
   - `blocked_too_long`：策略已判定 `block_and_alert` 但长期未消解，先看 `policy_decisions.json` 与人工处置记录。
   - `delivery_failed`：delivery worker 已进入死信，先查 `delivery_outbox.json` 与 OpenClaw receipt。
   - `mapping_incomplete`：映射不完整导致决策退化，需要补宿主展示映射或 policy 侧字段映射。
   - `recovery_failed`：`execute_recovery` 有非 completed receipt，先查 `action_receipts.json` 与 A 侧 handoff / resume 执行情况。
3. 若要做 forensic，使用本地 canonical records 做审计与 replay；不要用 raw/legacy route 反推真值。
4. 若问题是 A 侧连通性，先从 B 机验证 `WATCHDOG_A_AGENT_BASE_URL/healthz`，再核对 `WATCHDOG_A_AGENT_TOKEN` 与 A 的 `A_AGENT_API_TOKEN`。

### 5.2 安装、升级、回滚与密钥轮换

安装与升级纪律固定如下：

1. 在 A、B 两机分别执行 `git fetch --tags origin`，记录 `origin/main` 的最新提交摘要。
2. 先在 A 机 `git checkout <RELEASE_REF> && uv sync`，然后 `launchctl kickstart -k` 重启 A-Control-Agent。
3. 验证 A 机 `GET /healthz` 正常后，再在 B 机执行同一 `git checkout <RELEASE_REF> && uv sync`，然后重启 Watchdog。
4. 升级完成后，从 B 机验证 `GET /healthz`、`GET /api/v1/watchdog/ops/alerts`、`GET /api/v1/watchdog/sessions`，最后再验证 OpenClaw 调用 Watchdog。

回滚纪律固定如下：

1. 先选定同一历史提交 `ROLLBACK_REF`，A、B 都只回滚到这个提交，不做手工混搭。
2. 若是 Watchdog 新版本问题，先回滚 B 并验证 `GET /healthz` 与 stable routes；若问题来自 A/B 契约不匹配，再同步回滚 A。
3. 回滚后保留原数据目录，不删除 `policy_decisions.json`、`delivery_outbox.json`、`action_receipts.json` 与 `session_spine.json`，以免丢失审计链。

密钥轮换纪律固定如下：

1. 先生成新的 `A_AGENT_API_TOKEN`、`WATCHDOG_API_TOKEN`、`WATCHDOG_OPENCLAW_WEBHOOK_TOKEN`。
2. 先更新服务端接受方配置，再更新调用方配置，避免短时间双向鉴权错配。
3. 轮换 A/B 之间共享凭证时，按 A -> B 顺序重启；轮换 OpenClaw <-> Watchdog webhook 凭证时，按 OpenClaw -> Watchdog 顺序更新。
4. 轮换完成后重新验证 `GET /healthz`、`GET /api/v1/watchdog/ops/alerts` 与一次最小 webhook / response 闭环。

### 5.3 公网与入口方案

- 推荐做法是只让 Watchdog 暴露在固定 HTTPS 域名后面，由 nginx / Caddy / cloudflared tunnel 等反向代理处理 TLS 与公网入口。
- A-Control-Agent 只建议暴露在内网、VPN 或固定 allowlist 网段，不建议让 OpenClaw 或公网直接访问 A。
- 若必须跨公网访问 A，应至少增加 TLS、源地址限制、独立 token 与更短轮换周期；默认部署口径仍是不开放 A 的公网入口。

---

## 6. 若要「完善开发」——请你提供的信息清单

下面这些会显著减少对接试错时间；能提供的尽量结构化给出（可脱敏）。

### 6.1 环境与网络

- A、B 的 **操作系统**、是否用 **Docker**、是否用 **Tailscale/固定内网 IP**。  
- Watchdog 访问 A 的 **最终 URL**（含是否 HTTPS）、**是否经 mTLS**。  
- 允许的 **延迟与超时** 要求（默认 `WATCHDOG_HTTP_TIMEOUT_S=3`）。

### 6.2 安全与鉴权

- 是否沿用 **单 Bearer Token**，还是需要 **每环境多 Token**、**轮换策略**。  
- OpenClaw 调用 Watchdog 时，是否还有 **网关层鉴权**（API Key、JWT）。

### 6.3 Codex 侧（扩展到远端或非本地控制面时）

- 若不用本地子进程 bridge，而要接入**远端 Codex app-server**（或等价服务），请提供其 **Base URL**、**鉴权方式**（Header/Token）。  
- **线程 / 会话** 与 `project_id` 的映射规则（谁创建、谁更新）。  
- **事件或轮询**：是否有 transcript、turn、审批事件；**字段名与样例 JSON**（哪怕一条真实脱敏样本）。  
- 期望 A-Control-Agent **向下调用** 的能力列表（只读状态 / steer / handoff 等）。

### 6.4 OpenClaw 侧

- 飞书消息到 OpenClaw 后，**路由到哪个 HTTP 路径**（只读 progress 还是也要 evaluate/审批决策）。  
- **project_id** 从哪里来（用户口令解析、固定映射表等）。  
- 是否需要 **Webhook 回写** 或 **仅轮询**。

### 6.5 运维

- **日志聚合**（是否必须 JSON）、**指标** 接入 Prometheus 的 job 名。  
- **数据目录** 是否必须放在持久卷（`A_AGENT_DATA_DIR`、`WATCHDOG_DATA_DIR`）。

---

## 7. 常见问答

**Q：B 能直接调 A 吗？**  
可以（同一套 Bearer），但架构上推荐 **只让 OpenClaw → Watchdog**，由 Watchdog 统一策略与审计。

**Q：A 和 B 需不需要各自保留一份代码工程？**
需要，但不要求两边承担相同组件。A 至少要跑 `A-Control-Agent`；`Watchdog` 既可跑在 B，也可与 A 同机。最稳的方式仍是两边都固定到同一个 `RELEASE_REF`，避免契约漂移。

**Q：没有 Codex app-server 能用吗？**  
能。若 A-Control-Agent 与 Codex Desktop 同机，可直接走本地 `~/.codex` 自动采集；否则也能用
`POST /api/v1/tasks/native-threads` 手动/外部注册。若要下行控制 Codex 会话，则开启
`A_AGENT_CODEX_BRIDGE_ENABLED=true` 以启动本地 app-server bridge。

**Q：任务事件流现在支持到什么程度？**
当前已提供三层读面：
- A 侧 `GET /api/v1/tasks/{project_id}/events` — 原始 SSE
- Watchdog 侧 `GET /api/v1/watchdog/tasks/{project_id}/events` — raw 透传 SSE
- Watchdog 侧 `GET /api/v1/watchdog/sessions/{project_id}/events` — 011 新增 stable SSE

stable 事件的 raw 投影当前覆盖 `session_created`、`native_thread_bound`、
`guidance_posted`、`handoff_requested`、`session_resumed`、`approval_resolved`，
未知 raw 类型降级为 `session_updated`。在 snapshot 读面里，Watchdog 还会补充
selected canonical `Session Service` 事件（例如 `goal_contract_adopted_by_child_session`
对应的 child continuation 事实），所以外部读者不需要再额外拼接 recovery / goal-contract
真相。未提供 WebSocket，也还不是完整 transcript 流。

**Q：Token 泄露怎么办？**  
轮换 `A_AGENT_API_TOKEN` / `WATCHDOG_API_TOKEN`，并限制源 IP / 使用 TLS。

**Q：飞书和 OpenClaw 之间要不要改单独的通道？**
不用。飞书仍然把消息交给 OpenClaw；新增的是 OpenClaw 到 Watchdog 的 HTTP 调用逻辑。

---

若你后续提供 **§6** 中的网络地址、Token 策略、以及 Codex/OpenClaw 的接口样例，可以在新工作项里继续实现 **真实 Codex 客户端**、**OpenClaw 路由模板** 等（仍以 PRD 与 `specs/` 为准）。
