# OpenClaw × Codex 双机监管：部署与使用指引

本文说明本仓库**实际交付了什么**、**A 机 / B 机各自跑什么**、**两机如何对接**，以及若要继续完善集成，你需要向开发侧提供哪些信息。

---

## 1. 本仓库交付了什么（边界）

| 交付物 | 说明 |
|--------|------|
| **A-Control-Agent** | 运行在 **A 机** 的 FastAPI 服务：任务创建/查询、steer、handoff、resume、审批、工作区活动摘要、审计与 `/metrics`。已内置两层 Codex 集成：`1)` 默认读取同机 `~/.codex` 自动发现当前 active workspace 的 thread；`2)` 可选启动本地 `codex app-server --listen stdio://` bridge，执行下行控制与审批回写。 |
| **Watchdog** | 运行在 **B 机** 的 FastAPI 服务：通过 HTTP **调用 A** 拉取任务状态，提供 stable session spine、稳定 supervision evaluation / recover / 审批与事件读面，以及 `/metrics`。 |
| **OpenClaw 侧** | 本仓库**不包含**飞书机器人、也不包含 OpenClaw 插件；仅提供 **HTTP API** 与 `examples/openclaw_watchdog_client.py` 示例，由你在 OpenClaw 里配置「调用 Watchdog 的 URL + Token」。 |

**数据流（目标架构）**：

```text
飞书 → OpenClaw(B) → Watchdog(B) ──HTTPS+Bearer──→ A-Control-Agent(A) ──stdio/本地子进程──→ Codex app-server（可选）
```

当前实现中，**OpenClaw 只需对接 Watchdog**；Watchdog 再对接 A-Control-Agent。

---

## 2. A 机（跑 Codex 的开发机）怎么用

### 2.1 你需要准备什么

- Python **≥ 3.11**，建议用 [uv](https://github.com/astral-sh/uv) 或 venv。
- 本仓库克隆到 A 机（或仅部署打包后的服务与配置）。
- 与 B 机 **网络互通**（同局域网 / VPN / Tailscale 等），且 A 上服务监听地址能被 B 访问（勿把服务只绑在 `127.0.0.1` 若 B 在另一台机器）。

### 2.2 安装与启动（开发态示例）

```bash
cd openclaw-codex-watchdog
uv sync
# 或: pip install -e ".[dev]"
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
| `A_AGENT_CODEX_BRIDGE_ENABLED` | 是否启用本地 Codex app-server bridge（默认 `false`） |
| `A_AGENT_CODEX_BRIDGE_COMMAND` | 启动命令；默认 `codex app-server --listen stdio://` |
| `A_AGENT_CODEX_BRIDGE_REQUEST_TIMEOUT_SECONDS` | bridge 请求超时（默认 `10` 秒） |

加载环境变量后启动（`--app-dir src` 指向包路径）：

```bash
set -a && source .env.a && set +a
uv run uvicorn a_control_agent.main:app --host "$A_AGENT_HOST" --port "$A_AGENT_PORT" --app-dir src
```

健康检查：`GET http://<A的IP>:<端口>/healthz`

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

### 3.1 Watchdog 安装与启动

同样在本仓库目录：

```bash
uv sync
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

启动：

```bash
set -a && source .env.w && set +a
uv run uvicorn watchdog.main:app --host "$WATCHDOG_HOST" --port "$WATCHDOG_PORT" --app-dir src
```

健康检查：`GET http://<B的IP>:<端口>/healthz`

### 3.2 OpenClaw 怎么调 Watchdog（不经过本仓库代码）

OpenClaw 侧应优先配置为：对 **Watchdog 基址** 调用 010-020 收口后的 stable surface
（需 `Authorization: Bearer <WATCHDOG_API_TOKEN>`）：

- `GET /api/v1/watchdog/sessions` — 读取稳定跨项目 `SessionProjection[]` 目录
- `GET /api/v1/watchdog/sessions/{project_id}` — 读取稳定 `SessionProjection`
- `GET /api/v1/watchdog/sessions/by-native-thread/{native_thread_id}` — 在只知道 native thread_id 时解析稳定 `SessionProjection`
- `GET /api/v1/watchdog/sessions/{project_id}/progress` — 读取稳定 `TaskProgressView`
- `GET /api/v1/watchdog/sessions/{project_id}/workspace-activity` — 读取稳定 `WorkspaceActivityView`
- `GET /api/v1/watchdog/approval-inbox` — 读取稳定跨项目 pending approvals inbox；可选 `?project_id=...`
- `GET /api/v1/watchdog/sessions/{project_id}/pending-approvals` — 读取稳定审批队列
- `GET /api/v1/watchdog/sessions/{project_id}/stuck-explanation` — 读取稳定 stuck explanation reply
- `GET /api/v1/watchdog/sessions/{project_id}/blocker-explanation` — 读取稳定 blocker explanation reply
- `GET /api/v1/watchdog/sessions/{project_id}/events` — 读取稳定、版本化 `SessionEvent` SSE
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

如果 OpenClaw 需要稳定事件流，应优先使用：

- `GET /api/v1/watchdog/sessions/{project_id}/events` — stable SSE，事件会从 raw `task_created / native_thread_registered / steer / handoff / resume / approval_decided` 投影为 `session_created / native_thread_bound / guidance_posted / handoff_requested / session_resumed / approval_resolved`，未知 raw 类型降级为 `session_updated`

如果只需要 raw 透传，legacy 代理路径仍可用：

- `GET /api/v1/watchdog/tasks/{project_id}/events` — 由 Watchdog 代理的任务事件流（支持 `follow=true|false`）

仓库内示例：

```bash
export WATCHDOG_BASE_URL=http://<B的IP>:8720
export WATCHDOG_API_TOKEN=<与 WATCHDOG_API_TOKEN 相同>
uv run python examples/openclaw_watchdog_client.py <project_id>
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
- 015 新增的两个 explanation route 仍然复用既有 `ReplyModel`，不会新增 explanation DTO，也不会推进 session spine contract/schema version；它们与 OpenClaw adapter 共享同一套 explanation builder。
- 016 新增的 `GET /api/v1/watchdog/approval-inbox` 复用既有 `ApprovalProjection`，返回稳定 `ReplyModel(reply_code=approval_inbox)`；它只覆盖 pending approvals inbox，不提供 history / status passthrough，也不替换 legacy `/watchdog/approvals` raw proxy。
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

---

## 5. 监控与文档

- **Prometheus**：`GET /metrics`（A、Watchdog 各一份）。  
- **OpenAPI**：`uv run python scripts/export_openapi.py` → `docs/openapi/`。  
- **需求真值**：仓库根目录 `openclaw-codex-watchdog-prd.md`。

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

**Q：没有 Codex app-server 能用吗？**  
能。若 A-Control-Agent 与 Codex Desktop 同机，可直接走本地 `~/.codex` 自动采集；否则也能用
`POST /api/v1/tasks/native-threads` 手动/外部注册。若要下行控制 Codex 会话，则开启
`A_AGENT_CODEX_BRIDGE_ENABLED=true` 以启动本地 app-server bridge。

**Q：任务事件流现在支持到什么程度？**
当前已提供三层读面：
- A 侧 `GET /api/v1/tasks/{project_id}/events` — 原始 SSE
- Watchdog 侧 `GET /api/v1/watchdog/tasks/{project_id}/events` — raw 透传 SSE
- Watchdog 侧 `GET /api/v1/watchdog/sessions/{project_id}/events` — 011 新增 stable SSE

stable 事件当前覆盖 `session_created`、`native_thread_bound`、`guidance_posted`、
`handoff_requested`、`session_resumed`、`approval_resolved`，未知 raw 类型降级为
`session_updated`。未提供 WebSocket，也还不是完整 transcript 流。

**Q：Token 泄露怎么办？**  
轮换 `A_AGENT_API_TOKEN` / `WATCHDOG_API_TOKEN`，并限制源 IP / 使用 TLS。

---

若你后续提供 **§6** 中的网络地址、Token 策略、以及 Codex/OpenClaw 的接口样例，可以在新工作项里继续实现 **真实 Codex 客户端**、**OpenClaw 路由模板** 等（仍以 PRD 与 `specs/` 为准）。
