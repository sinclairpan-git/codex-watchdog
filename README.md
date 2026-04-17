# OpenClaw × Codex 双机会话监管系统

需求真值见根目录 `openclaw-codex-watchdog-prd.md`。本仓库以 AI-SDLC 工作项递进交付：**M1** 基础链路、`specs/002-*` M2 监管、`specs/004-*` M3 审批、`specs/005-*` M4 恢复、`specs/006-*` **M5 加固**（指标、集成测试、OpenAPI 与 OpenClaw 调用示例等，不含飞书/OpenClaw 渠道插件）。

**部署与 A/B 机使用说明（含对接参数清单）**：见 [`docs/getting-started.zh-CN.md`](docs/getting-started.zh-CN.md)。

## 组件

| 目录 | 说明 |
|------|------|
| `src/a_control_agent/` | A 机侧：任务 / steer / handoff / resume / 审批、持久化、`/metrics` |
| `src/watchdog/` | 宿主前置层：stable session spine、progress / evaluate / recover / 审批代理、`/metrics`；可独立跑在 OpenClaw 所在机，也可与 A 同机常驻后再对外暴露稳定入口 |
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
uv run uvicorn watchdog.main:create_runtime_app --host 127.0.0.1 --port 8720 --factory --app-dir src
```

配置样例：`config/examples/*.env.example`。

外部集成 smoke 验收：

```bash
export WATCHDOG_BASE_URL=http://127.0.0.1:8720
export WATCHDOG_API_TOKEN=dev-token-change-me
uv run python scripts/watchdog_external_integration_smoke.py
uv run python scripts/watchdog_external_integration_smoke.py --target feishu
uv run python scripts/watchdog_external_integration_smoke.py --target feishu-control
uv run python scripts/watchdog_external_integration_smoke.py --target provider
uv run python scripts/watchdog_external_integration_smoke.py --target memory
```

这组检查默认统一验证 `GET /healthz`、飞书 `url_verification`、OpenAI-compatible provider 接线与失败回退、以及 Memory Hub preview route。`--target feishu-control` 额外补一条 repo-local 的 Feishu callback contract smoke：它会向 `/api/v1/watchdog/feishu/events` 发送 `im.message.receive_v1` 的 DM 文本事件，内容为 `repo:<project_id> /goal <goal_message>`，借此确认官方事件入口能被归一成 `goal_contract_bootstrap`。该检查需要先配置 `WATCHDOG_SMOKE_FEISHU_CONTROL_PROJECT_ID` 与 `WATCHDOG_SMOKE_FEISHU_CONTROL_GOAL_MESSAGE`；若未配置会返回 `skipped`，若已配置但契约不一致则直接失败。

若需要常驻与开机自启，仓库已提供：

- `scripts/start_watchdog.sh`
- `scripts/install_watchdog_launchd.sh`
- `scripts/start_watchdog_endpoint_notifier.sh`
- `scripts/install_watchdog_endpoint_notifier_launchd.sh`
- `config/examples/com.openclaw.watchdog.endpoint-notifier.plist`
- `config/examples/com.openclaw.watchdog.plist`

在 macOS 上准备好 `.env.w` 后可直接执行：

```bash
WATCHDOG_ENV_FILE="$PWD/.env.w" ./scripts/install_watchdog_launchd.sh
WATCHDOG_ENV_FILE="$PWD/.env.w" ./scripts/install_watchdog_endpoint_notifier_launchd.sh
```

该脚本会安装 `~/Library/LaunchAgents/com.openclaw.watchdog.plist`，并执行 `launchctl bootstrap` 与 `launchctl kickstart -k`；重启后会自动恢复。

## 可观测性（M5 / 029）

两侧服务均提供 **`GET /metrics`**（Prometheus 文本）。其中 Watchdog 从 029 起额外冻结了最小运维面：

- `GET /healthz`：返回 `status=ok|degraded` 与 `active_alerts`。
- `GET /api/v1/watchdog/ops/alerts`：返回当前活动告警清单，需 `Authorization: Bearer <WATCHDOG_API_TOKEN>`。
- `GET /metrics`：除既有审计计数外，固定导出 `watchdog_ops_alert_active{alert="..."}` 五类 gauge：
  - `approval_pending_too_long`
  - `blocked_too_long`
  - `delivery_failed`
  - `mapping_incomplete`
  - `recovery_failed`

相关阈值与刷新周期由以下环境变量控制：

- `WATCHDOG_SESSION_SPINE_REFRESH_INTERVAL_SECONDS`
- `WATCHDOG_RESIDENT_ORCHESTRATOR_INTERVAL_SECONDS`
- `WATCHDOG_PROGRESS_SUMMARY_INTERVAL_SECONDS`
- `WATCHDOG_OPS_BLOCKED_TOO_LONG_SECONDS`
- `WATCHDOG_OPS_APPROVAL_PENDING_TOO_LONG_SECONDS`

## 审计与回放（029）

029 新增的审计与回放语义只消费前序 work item 已持久化的 canonical records，不反向改写业务契约：

- 审计查询：`src/watchdog/services/audit/service.py`
- forensic replay：`src/watchdog/services/audit/replay.py`
- truth sources：`policy_decisions.json`、`canonical_approvals.json`、`delivery_outbox.json`、`action_receipts.json`

回放只回答“发生了什么、按什么顺序发生”，不重放动作，不补执行 delivery，也不回退到 raw/legacy route 推断状态。

## 部署纪律

- 逻辑拓扑保持 `OpenClaw -> Watchdog -> A-Control-Agent -> Codex`；`Watchdog` 不再强制要求物理部署在 B 机。
- 若 A 机就是唯一稳定的 Codex 宿主机，可直接把 `Watchdog` 与 `A-Control-Agent` 同机部署在 A，再通过 HTTPS / tunnel / 反代把 `Watchdog` 暴露给 B 上的 OpenClaw。
- A 与 B 必须运行同一提交；升级顺序固定为先 A、再 B、最后验证 OpenClaw -> Watchdog。
- 回滚时同样按提交回退，避免 A/B 漂在不同契约版本。
- Bearer token 需要独立保管并支持轮换；公网暴露只建议经 TLS 反向代理对外开放 Watchdog，不建议让 OpenClaw 直连 A。
- 完整 operator runbook、安装/升级/回滚、密钥轮换与公网暴露建议见 `docs/getting-started.zh-CN.md`。

## OpenAPI 与集成示例

```bash
python scripts/export_openapi.py
```

示例脚本：`examples/openclaw_watchdog_client.py` 与 `examples/openclaw_webhook_runtime.py`。前者提供 `WatchdogTemplateClient`，封装 OpenClaw / 外部机器人访问 Watchdog 的最小 stable route 调用层；后者提供最小 reference runtime，演示宿主如何接收 Watchdog webhook、返回 receipt，并把结构化用户响应回传给 Watchdog。仓库仍不包含飞书插件或生产级 OpenClaw runtime。需设置 `WATCHDOG_BASE_URL`、`WATCHDOG_API_TOKEN`，可选 `WATCHDOG_DEFAULT_PROJECT_ID` 与 `WATCHDOG_OPERATOR`。

OpenClaw 最小模板与 stable route 的对应关系：

| 消息类型 | 模板方法 | 稳定路由 |
|------|------|------|
| 查询进展 | `query_progress(project_id)` | `GET /api/v1/watchdog/sessions/{project_id}/progress` |
| 查询卡点 | `query_stuck(project_id)` | `GET /api/v1/watchdog/sessions/{project_id}/stuck-explanation` |
| 继续推进 | `continue_session(project_id, operator, idempotency_key)` | `POST /api/v1/watchdog/sessions/{project_id}/actions/continue` |
| 查询审批 inbox | `list_approval_inbox(project_id?)` | `GET /api/v1/watchdog/approval-inbox` |
| 审批决策 | `approve_approval(approval_id, operator, idempotency_key, note)` / `reject_approval(approval_id, operator, idempotency_key, note)` | `POST /api/v1/watchdog/approvals/{approval_id}/approve|reject` |
| 审批响应回流 | 宿主回传 `envelope_id + envelope_type + approval_id + decision_id + response_action + response_token + user_ref + channel_ref + client_request_id` | `POST /api/v1/watchdog/openclaw/responses` |

`project_id` 路由策略：

- 显式传入 `project_id` 时优先使用显式值。
- 未显式传入时，模板会回退到 `WATCHDOG_DEFAULT_PROJECT_ID`。
- 两者都没有时，应先调用 `GET /api/v1/watchdog/sessions` 或 `GET /api/v1/watchdog/sessions/by-native-thread/{native_thread_id}` 完成稳定会话解析。
- 所有 write action 都要求显式提供非空 `idempotency_key`，以匹配 stable action / receipt 语义。

028 冻结后的 OpenClaw webhook / response contract 要点：

- Watchdog 主动投递入口固定为 `POST /openclaw/v1/watchdog/envelopes`。
- webhook 请求头至少包含 `Authorization`、`X-Watchdog-Delivery-Id`、`X-Watchdog-Timestamp`、`X-Watchdog-Signature`。
- 宿主成功 receipt 至少返回 `accepted=true`、`envelope_id`、`receipt_id`、`received_at`；缺任一字段的 `2xx` 仍视为 retryable failure。
- 宿主回传审批响应时，必须走 `POST /api/v1/watchdog/openclaw/responses`，并带齐冻结的结构化 response contract。
- reference runtime 只做 envelope 消费、展示映射、结构化回传；不做策略、不做风险分类、不维护第二套内核状态。

010-026 收口后的 OpenClaw 最小稳定接口面：

- `GET /api/v1/watchdog/sessions` 返回稳定跨项目 `SessionProjection[]` 目录
- `GET /api/v1/watchdog/sessions/{project_id}` 返回稳定 `SessionProjection`
- `GET /api/v1/watchdog/sessions/by-native-thread/{native_thread_id}` 通过 native thread 解析稳定 `SessionProjection`
- `GET /api/v1/watchdog/sessions/{project_id}/facts` 返回稳定 `ReplyModel(reply_code=session_facts, facts=FactRecord[])`
- `GET /api/v1/watchdog/sessions/{project_id}/progress` 返回稳定 `TaskProgressView`
- `GET /api/v1/watchdog/sessions/{project_id}/workspace-activity` 返回稳定 `WorkspaceActivityView`
- `GET /api/v1/watchdog/approval-inbox` 返回稳定跨项目 pending approvals inbox
- `GET /api/v1/watchdog/sessions/{project_id}/pending-approvals` 返回稳定审批队列
- `GET /api/v1/watchdog/sessions/{project_id}/stuck-explanation` 返回稳定 `ReplyModel(reply_code=stuck_explanation)`
- `GET /api/v1/watchdog/sessions/{project_id}/blocker-explanation` 返回稳定 `ReplyModel(reply_code=blocker_explanation)`
- `GET /api/v1/watchdog/sessions/{project_id}/events` 返回稳定、版本化的 `SessionEvent` SSE
- `GET /api/v1/watchdog/sessions/{project_id}/event-snapshot` 返回稳定 `ReplyModel(reply_code=session_event_snapshot, events=SessionEvent[])` JSON snapshot
- `GET /api/v1/watchdog/action-receipts?action_code=...&project_id=...&idempotency_key=...` 返回稳定、版本化的 action receipt reply
- `POST /api/v1/watchdog/actions` 是 canonical write surface，提交 `WatchdogAction`
- `POST /api/v1/watchdog/sessions/{project_id}/actions/continue`
- `POST /api/v1/watchdog/sessions/{project_id}/actions/evaluate-supervision`
- `POST /api/v1/watchdog/sessions/{project_id}/actions/post-guidance`
- `POST /api/v1/watchdog/sessions/{project_id}/actions/request-recovery`
- `POST /api/v1/watchdog/sessions/{project_id}/actions/execute-recovery`
- `GET /api/v1/watchdog/sessions/{project_id}/action-receipts/{action_code}/{idempotency_key}`
- `POST /api/v1/watchdog/approvals/{approval_id}/approve`
- `POST /api/v1/watchdog/approvals/{approval_id}/reject`
- `POST /api/v1/watchdog/openclaw/responses` 以 `(envelope_id, response_action, client_request_id)` 作为 canonical response idempotency key

其中路径级动作接口只是 alias wrapper；真正稳定的动作契约是
`WatchdogAction -> WatchdogActionResult`。`request_recovery` 在 010 仍是
advisory-only，只返回恢复可用性说明，不触发真实 handoff / resume。012 在此基础上新增
`execute_recovery`，它才是 stable surface 上显式触发 handoff / optional resume 的动作。
013 在此基础上新增了 stable receipt read surface；它只读本地持久化 `ActionReceiptStore`，
返回 `ReplyModel(reply_code=action_receipt|action_receipt_not_found)`，不会重放动作也不会回退到 raw/legacy 路由。
014 在此基础上新增了 `evaluate_supervision` 稳定动作；它返回版本化
`WatchdogActionResult(reply_code=supervision_evaluation)` 与 `SupervisionEvaluation`，
必要时执行一次 advisory steer。原有
`POST /api/v1/watchdog/tasks/{project_id}/evaluate` 继续保留，但现在只是复用 014 稳定内核的兼容壳。
015 在不推进 contract/schema version 的前提下，补齐了
`GET /api/v1/watchdog/sessions/{project_id}/stuck-explanation` 与
`GET /api/v1/watchdog/sessions/{project_id}/blocker-explanation` 两个 stable read route；
它们与 OpenClaw adapter 复用同一套 explanation builder，继续只基于稳定 `SessionReadBundle + FactRecord`
产出 `ReplyModel(reply_code=stuck_explanation|blocker_explanation)`。
016 在此基础上新增了 `GET /api/v1/watchdog/approval-inbox`，把跨项目待处理审批收敛为稳定
`ReplyModel(reply_code=approval_inbox, approvals=ApprovalProjection[])`。它与 session 级
`pending-approvals` 的区别是：前者面向全局 inbox，后者面向单项目会话视角；legacy
`GET /api/v1/watchdog/approvals` 与 `POST /api/v1/watchdog/approvals/{approval_id}/decision`
继续保留，但不承担 stable contract 角色。
026 在此基础上新增 canonical approval / response 闭环：`require_user_decision`
会物化为本地 persisted approval envelope，宿主只允许回传 `approve`、`reject`、
`execute_action` 三种 canonical response action；同一
`(envelope_id, response_action, client_request_id)` 重放时，不会重复执行 approval
decision 或底层 canonical action。
027 在此基础上新增 reliable delivery outbox baseline。canonical decision / approval response
现在会写入持久 `decision_outbox` 与 `delivery_outbox`，由后台 `DeliveryWorker` 按
同一 `session_id` 下 `fact_snapshot_version -> outbox_seq` 的顺序回调
`POST /openclaw/v1/watchdog/envelopes`；不同 session 允许并行。当前冻结的投递矩阵是：
`auto_execute_and_notify -> DecisionEnvelope + NotificationEnvelope(decision_result)`、
`require_user_decision -> ApprovalEnvelope`、审批响应后再补
`NotificationEnvelope(notification_kind=approval_result)`、`block_and_alert -> critical notification`。
只有同时满足 `HTTP 2xx + accepted=true + envelope_id match + receipt_id present` 才算 delivered；
协议不完整的 `2xx`、`408`、`429`、`5xx` 与网络超时都会进入指数退避重试，超过
`WATCHDOG_DELIVERY_MAX_ATTEMPTS` 后记录 `delivery_failed` 与 dead-letter operator note。
017 在此基础上新增了 `GET /api/v1/watchdog/sessions`，把“未知 project_id 时的跨项目会话发现”
收敛为稳定 `ReplyModel(reply_code=session_directory, sessions=SessionProjection[])`；
OpenClaw adapter 同步新增 `list_sessions` intent，继续复用同一份 L2 directory builder，
不直读 raw task schema，也不引入新的动作面或分页/过滤语义。
018 在此基础上新增了 `GET /api/v1/watchdog/sessions/by-native-thread/{native_thread_id}`，
把“只知道 native thread_id 时的稳定会话解析”收敛为 canonical stable route；它复用
现有 `ReplyModel(reply_code=session_projection)` 与 `SessionProjection + FactRecord`，
不会新增 DTO / reply code，也不会推进 session spine schema version。OpenClaw adapter
同步新增 `get_session_by_native_thread` intent，继续复用同一份 L2 session builder；
A 侧 raw `GET /api/v1/tasks/by-thread/{thread_id}` 继续保留，但不承担 stable contract 角色。
019 在此基础上新增了 `GET /api/v1/watchdog/sessions/{project_id}/workspace-activity`，
把 workspace 文件活动摘要收敛为稳定 `ReplyModel(reply_code=workspace_activity_view)`；
它返回 `WorkspaceActivityView`，继续复用既有 `SessionProjection + FactRecord` 语义，
供 OpenClaw adapter 的 `get_workspace_activity` intent 与 HTTP read surface 共用同一份
L2 builder。A 侧 raw `GET /api/v1/tasks/{project_id}/workspace-activity` 继续保留，
但不承担 stable contract 角色。
020 在此基础上新增了 `post_operator_guidance` 稳定动作；canonical 写面仍是
`POST /api/v1/watchdog/actions`，其 `WatchdogAction.arguments` 以 `message` 为必填，
可选 `reason_code`（默认 `operator_guidance`）与 `stuck_level`（`0..4`）。
人类友好的 alias route 是
`POST /api/v1/watchdog/sessions/{project_id}/actions/post-guidance`，它只是包装 canonical
动作契约。动作成功时返回
`WatchdogActionResult(reply_code=action_result, effect=steer_posted)`；A 侧 raw
`POST /api/v1/tasks/{project_id}/steer` 继续保留，但不承担 stable contract 角色。
021 在 011 的 stable `SessionEvent` 投影层旁边新增了
`GET /api/v1/watchdog/sessions/{project_id}/event-snapshot`，把一次性事件快照收敛为
`ReplyModel(reply_code=session_event_snapshot, events=SessionEvent[])` JSON read surface。
它与 011 的 stable SSE route 共享同一份事件投影与 event schema version，不新增 follow /
cursor / backfill 语义，也不改变原有 SSE 的实时行为；OpenClaw adapter 同步新增
`list_session_events` intent，继续只消费稳定 `SessionEvent[]`，不直读 raw SSE。
022 在此基础上新增了 `GET /api/v1/watchdog/sessions/{project_id}/facts`，把 session 当前
稳定事实真值收敛为 `ReplyModel(reply_code=session_facts, facts=FactRecord[])` read surface。
它继续复用既有 `SessionReadBundle + FactRecord`，不新增 fact DTO、filter、history、分页
或新的动作语义；`why_stuck` / `explain_blocker` 两条 explanation route 继续保留解释层角色，
与 facts truth source 并存而不是互相替代。OpenClaw adapter 同步新增 `list_session_facts`
intent，继续复用同一份 facts reply builder，不直读 raw/legacy route。
025 在此基础上新增了 canonical policy engine 与 decision evidence layer。当前策略接缝固定为
只消费 resident session spine 的 persisted snapshot：`evaluate_session_policy_from_persisted_spine(...)`
不会直接向 A-Control-Agent 发 raw query 取事实。canonical decision record 由
`watchdog.services.policy.decisions.PolicyDecisionStore` 去重，稳定键是 `decision_key`，
最小证据包包含 `facts`、`matched_policy_rules`、`risk_class`、`decision`、
`decision_reason`、`why_*_escalated`、`policy_version`、`fact_snapshot_version`、
`idempotency_key` 与 `operator_notes`；它供后续 026/027 直接复用，不在 025 执行真实动作或投递。

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
但不再承担 OpenClaw 稳定契约角色。`POST /api/v1/watchdog/tasks/{project_id}/recover`
现在只是兼容壳，内部复用 012 的稳定 recovery execution 内核；
`POST /api/v1/watchdog/tasks/{project_id}/evaluate` 也是兼容壳，内部复用 014 的稳定 supervision evaluation 内核。

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

027 新增的 Watchdog 下行配置最少包括：

- `WATCHDOG_OPENCLAW_WEBHOOK_BASE_URL`
- `WATCHDOG_OPENCLAW_WEBHOOK_TOKEN`
- `WATCHDOG_DELIVERY_WORKER_INTERVAL_SECONDS`
- `WATCHDOG_DELIVERY_INITIAL_BACKOFF_SECONDS`
- `WATCHDOG_DELIVERY_MAX_ATTEMPTS`

如果 A 机使用 `cloudflared quick tunnel` 给 Watchdog 暴露临时公网地址，且你希望该地址变化后自动同步给 B 机上的 OpenClaw bootstrap 服务，还需要：

- `WATCHDOG_BOOTSTRAP_WEBHOOK_BASE_URL`
- `WATCHDOG_BOOTSTRAP_WEBHOOK_TOKEN`
- `WATCHDOG_PUBLIC_TUNNEL_LOG_PATH`
- `WATCHDOG_PUBLIC_URL_STATE_FILE`
- `WATCHDOG_PUBLIC_URL_NOTIFY_INTERVAL_SECONDS`
- `WATCHDOG_PUBLIC_URL_SOURCE`

如果 B 机上的 OpenClaw envelope webhook 也使用临时公网地址，A 机 Watchdog 还支持反向 bootstrap：

- `POST /api/v1/watchdog/bootstrap/openclaw-webhook`
- 鉴权：`Authorization: Bearer <WATCHDOG_API_TOKEN>`
- 请求体：`event_type=openclaw_webhook_base_url_changed`、`openclaw_webhook_base_url`、`changed_at`、`source`
- `WATCHDOG_OPENCLAW_WEBHOOK_ENDPOINT_STATE_FILE`：持久化最新 B 机公网 webhook 根地址；默认位于 `WATCHDOG_DATA_DIR/openclaw_webhook_endpoint.json`
- delivery client 每次发送 `POST /openclaw/v1/watchdog/envelopes` 前，都会先读取该持久化文件；只有 store miss 时才回退到 `WATCHDOG_OPENCLAW_WEBHOOK_BASE_URL`

对应本地持久文件默认位于 `WATCHDOG_DATA_DIR` 下：

- `policy_decisions.json`
- `canonical_approvals.json`
- `approval_responses.json`
- `delivery_outbox.json`
- `action_receipts.json`
- `openclaw_webhook_endpoint.json`

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

当前 release entry docs 固定为 `v0.6.0`：

- Windows offline bundle: `ai-sdlc-offline-0.6.0.zip`
- macOS / Linux offline bundle: `ai-sdlc-offline-0.6.0.tar.gz`
- Release notes: `docs/releases/v0.6.0.md`
