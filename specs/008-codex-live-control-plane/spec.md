---
related_doc:
  - "openclaw-codex-watchdog-prd.md"
---

# Codex Live Control Plane — 功能规格说明

## 概述

在已具备本地 `~/.codex` 只读线程同步的基础上，补齐 **A-Control-Agent → 本机 Codex live session** 的真实控制闭环。008 只交付控制面：A-Control-Agent 负责托管本地 `codex app-server` bridge，承接 `steer / approval / resume` 并把结果写回现有 task / approval store 与审计。OpenClaw 仍只通过 Watchdog / A-Control-Agent 的稳定 REST 接口工作；实时 `SSE / WebSocket` 事件流拆到后续 009。

## 功能需求

- **FR-801**：A-Control-Agent 启动时可按配置拉起并维护本地 `codex app-server --listen stdio://` bridge；bridge 需支持初始化、健康探测、断线重连与进程清理。
- **FR-802**：bridge 至少封装 `thread/resume`、`thread/read`、`turn/start`、`turn/steer` 四类请求，并缓存 `thread_id -> active_turn_id / latest_snapshot`，供上层 API 判断线程空闲/活跃状态。
- **FR-803**：`POST /api/v1/tasks/{project_id}/steer` 不再仅写本地 store；当线程空闲时注入 `turn/start`，线程活跃时注入 `turn/steer`，成功后更新任务 `last_summary`、`last_progress_at`、`status`、`phase` 与审计。
- **FR-804**：bridge 接收到 Codex 审批请求时，A-Control-Agent 需将其标准化落入 `ApprovalsStore`，记录 `approval_id -> app_server_request_id` 映射，并同步任务 `pending_approval`、`approval_risk`、`status`、`phase`。
- **FR-805**：`POST /api/v1/approvals/{approval_id}/decision` 需要真实回写 Codex bridge；成功后清理映射并回写审批状态，失败时保留 `pending` 或显式标记回写失败原因。
- **FR-806**：`POST /api/v1/tasks/{project_id}/resume` 需要真实调用 `thread/resume`；若请求带 `handoff_summary`，在恢复成功后按线程状态选择 `turn/start` 或 `turn/steer` 注入续跑摘要，并保留现有 handoff / audit 语义。
- **FR-807**：所有 control-plane 动作记录统一审计事件，至少覆盖 `bridge_connected`、`bridge_disconnected`、`steer_injected`、`approval_created`、`approval_decided`、`resume_requested`、`resume_failed`。
- **FR-808**：008 明确不交付 `GET .../events` 的 `SSE / WebSocket` 实时流，也不让 OpenClaw 直接连接 Codex app-server；这些纳入 009。

### 用户故事 1：实时 steer 注入 live 会话

OpenClaw 通过 Watchdog 触发一次 soft steer。

场景 1：目标线程当前无活跃 turn，A-Control-Agent 调用 `turn/start` 发起新的受控 turn，并在任务状态中留下新的进展时间戳。

场景 2：目标线程已有活跃 turn，A-Control-Agent 调用 `turn/steer` 将保守指令注入现有 live 会话，而不是只更新本地 store。

### 用户故事 2：审批请求形成真实闭环

Codex live session 发起权限审批请求。

场景 1：A-Control-Agent 把请求登记为 pending approval，并同步任务 `waiting_for_approval` 语义。

场景 2：外部调用决策接口后，决策结果被真实回写到 Codex bridge，请求从 pending 转为 approved / rejected。

### 用户故事 3：handoff 后可真实 resume

任务已经生成 handoff summary，需要在同一 thread 或恢复后的 thread 上续跑。

场景 1：`resume` 成功恢复 thread，并把 `handoff_summary` 注入 live session。

场景 2：若恢复失败，接口返回显式错误，任务状态与审计可见失败原因，而不是误报为 `running`。

## 非目标

- 不实现 `SSE / WebSocket` 事件流实时 UI；该能力单独纳入 009。
- 不让 OpenClaw 直接连接 Codex app-server 或理解底层 JSON-RPC。
- 不通过直接修改 `~/.codex` 状态文件来注入控制指令。
