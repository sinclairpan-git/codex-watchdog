# Codex Live Control Bridge Implementation Plan

> 该计划已执行完成；以下内容保留为 008 实际落地结果与约束归档。

**Goal:** 让 OpenClaw 继续只通过 Watchdog / A-Control-Agent 的稳定 REST 边界控制本机 Codex live session，008 只交付 `steer + approval + resume` 控制面，不包含 `SSE / WebSocket` 实时事件流。

**Architecture:** A-Control-Agent 托管本地 `codex app-server --listen stdio://` bridge，负责 JSON-RPC 初始化、`thread/resume`、`thread/read`、`turn/start`、`turn/steer`、审批请求映射、决策回写，以及 task / approval store 与审计同步。实时事件流保留到 009。

**Tech Stack:** FastAPI, asyncio, stdio JSON-RPC, local `codex` CLI, file-backed stores

---

## Final Scope

### In Scope

- A-Control-Agent 生命周期内维护本地 Codex bridge
- 线程恢复、线程读取、活跃 turn 跟踪
- `POST /api/v1/tasks/{project_id}/steer` 真实注入 live session
- `POST /api/v1/tasks/{project_id}/resume` 真实恢复 thread 并注入 handoff summary
- Codex 审批请求落库、任务状态同步、人工决策回写
- 统一审计：`bridge_connected`、`bridge_disconnected`、`approval_created`、`approval_decided`、`resume_requested`、`resume_failed` 与既有 `steer_injected` / `resume`

### Out of Scope

- `SSE / WebSocket` 实时事件流
- OpenClaw 直连 Codex app-server
- 直接修改 `~/.codex` 内部状态文件
- 多机远程代理发现

## Delivered Design

### Bridge Contract

- bridge 统一封装 `thread/resume`、`thread/read`、`turn/start`、`turn/steer`
- `turn/start` / `turn/steer` 统一按 app-server v2 `input[]` 文本输入协议发送
- bridge 缓存 `thread_id -> latest_snapshot` 与 `thread_id -> active_turn_id`
- `thread/read` 与 `thread/resume` 会从 thread snapshot 中回推活跃 turn

### Approval Flow

- bridge 接到 `item/commandExecution/requestApproval` 等 server request 后，标准化写入 `ApprovalsStore`
- 同步更新任务 `pending_approval`、`approval_risk`、`status=waiting_human`、`phase=approval`
- 决策接口先回写 live bridge，成功后才落审批结果；回写失败时保留 `pending`

### Resume / Steer Flow

- `steer` 根据 thread 是否存在活跃 turn 选择 `turn/start` 或 `turn/steer`
- `resume` 先记 `resume_requested`，bridge 失败时转 `resume_failed`
- 仅在 bridge 成功后把任务状态回写为 `running`

## Verification

- `uv run pytest tests/test_codex_app_server_bridge.py -q`
- `uv run pytest tests/test_a_control_agent_control_flow.py -q`
- `uv run pytest tests/test_a_control_agent.py tests/test_m2_watchdog_supervision.py -q`
- `uv run pytest -q`
- `uv run ruff check src tests examples`
- `uv run python -m ai_sdlc verify constraints`

## Outcome

- 008 已按规格完成控制面闭环
- 009 再承接实时事件流，不在本次实现范围内
