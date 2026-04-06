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

示例脚本：`examples/openclaw_watchdog_client.py`。它提供 `WatchdogTemplateClient`，面向 OpenClaw / 外部机器人封装最小 HTTP 路由模板；本仓库不包含飞书或 OpenClaw runtime，只提供可复用 stable route 调用层。需设置 `WATCHDOG_BASE_URL`、`WATCHDOG_API_TOKEN`，可选 `WATCHDOG_DEFAULT_PROJECT_ID` 与 `WATCHDOG_OPERATOR`。

OpenClaw 最小模板与 stable route 的对应关系：

| 消息类型 | 模板方法 | 稳定路由 |
|------|------|------|
| 查询进展 | `query_progress(project_id)` | `GET /api/v1/watchdog/sessions/{project_id}/progress` |
| 查询卡点 | `query_stuck(project_id)` | `GET /api/v1/watchdog/sessions/{project_id}/stuck-explanation` |
| 继续推进 | `continue_session(project_id, operator, idempotency_key)` | `POST /api/v1/watchdog/sessions/{project_id}/actions/continue` |
| 查询审批 inbox | `list_approval_inbox(project_id?)` | `GET /api/v1/watchdog/approval-inbox` |
| 审批决策 | `approve_approval(approval_id)` / `reject_approval(approval_id)` | `POST /api/v1/watchdog/approvals/{approval_id}/approve|reject` |

`project_id` 路由策略：

- 显式传入 `project_id` 时优先使用显式值。
- 未显式传入时，模板会回退到 `WATCHDOG_DEFAULT_PROJECT_ID`。
- 两者都没有时，应先调用 `GET /api/v1/watchdog/sessions` 或 `GET /api/v1/watchdog/sessions/by-native-thread/{native_thread_id}` 完成稳定会话解析。

010-022 收口后的 OpenClaw 最小稳定接口面：

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
