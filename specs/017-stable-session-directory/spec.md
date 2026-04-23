---
related_doc:
  - "codex-watchdog-prd.md"
  - "docs/architecture/codex-watchdog-g0-and-v010-design.md"
  - "specs/010-runtime-integration-spine/spec.md"
  - "specs/016-stable-approval-inbox/spec.md"
---

# Stable Session Directory — 功能规格说明

## 概述

在 `010-016` 完成 stable session spine、events、recovery、receipt、supervision、explanation 与 approval inbox 之后，Watchdog 对 Feishu 的 stable read surface 还剩一个明显缺口：

- 已有 `GET /api/v1/watchdog/sessions/{project_id}`，适用于“已知 project_id”；
- 已有 `GET /api/v1/watchdog/approval-inbox`，适用于“未知 project_id 但要先看审批”；
- 但“先枚举当前有哪些受监管会话，再决定查看哪个 session”的能力，仍只有 Codex runtime service 的 raw `/api/v1/tasks`。

这意味着上层如果还不知道 `project_id`，就必须回退到 raw task schema，而不是继续消费 Watchdog 的稳定 session contract。

017 的唯一目标固定为：

> 建立 stable session directory read surface，让 Feishu 与其他调用方能够在未知 `project_id` 的情况下读取跨项目 `SessionProjection[]`，并继续通过同一套 stable contract 跳转到单会话读取、审批、解释或动作面。

## 功能需求

- **FR-1701**：017 必须补一个独立 stable session directory read surface；不得把 stable 语义直接塞回 Codex runtime service 的 raw `/api/v1/tasks`。
- **FR-1702**：017 的 canonical stable route 固定为：
  - `GET /api/v1/watchdog/sessions`
- **FR-1703**：该 route 返回稳定 `ReplyModel`，其中：
  - `reply_kind=session`
  - `reply_code=session_directory`
  - `intent_code=list_sessions`
  - `sessions` 为稳定 `SessionProjection[]`
- **FR-1704**：017 必须继续复用既有 `SessionProjection`，不得引入新的 parallel DTO，也不得把 raw task row 直接透传给 stable route。
- **FR-1705**：每个 `SessionProjection` 必须继续保留：
  - `project_id`
  - `thread_id`
  - `native_thread_id`
  - `session_state`
  - `activity_phase`
  - `attention_state`
  - `headline`
  - `pending_approval_count`
  - `available_intents`
- **FR-1706**：stable session directory 必须基于 Codex runtime service `list_tasks()` 与 pending approvals 聚合构建，保证 `pending_approval_count` 和 `available_intents` 与单 session 读取口径一致。
- **FR-1707**：017 不新增新的 write action，也不改变 `POST /api/v1/watchdog/actions` 及其 alias 语义。
- **FR-1708**：Feishu adapter 必须新增 `list_sessions` intent，并返回与 HTTP stable route 同源的 `ReplyModel`；不得在 adapter 层自己拼 raw task list 文案。
- **FR-1709**：017 必须推进 session spine schema version，并把新增 `reply_code=session_directory` 与 `ReplyModel.sessions` 作为正式稳定契约的一部分；`contract_version` 继续保持 `watchdog-session-spine/v1alpha1`。
- **FR-1710**：017 不引入分页、排序、搜索、过滤器、历史会话或 archive 语义；只覆盖“当前可见 session directory”。
- **FR-1711**：017 必须补齐 contract 测试、stable directory API 测试、adapter 测试、最小 integration 测试，并显式补一条 legacy `/api/v1/tasks` 非回归，确认 stable directory 不替换原始 runtime 侧任务列表。
- **FR-1712**：README、getting-started 与 OpenAPI 必须把 session directory 纳入 stable read surface，并明确：
  - `/watchdog/sessions`：稳定跨项目 session directory
  - `/watchdog/sessions/{project_id}`：稳定单会话读取
  - `/api/v1/tasks`：Codex runtime service raw task list，继续存在但不承担 stable contract 角色

### 用户故事 1：Feishu 在未知 project_id 时先拿目录

Feishu 需要先知道当前有哪些正在监管中的 session，再决定是否读取单 session、查看 explanation 或发起动作。

场景 1：调用 `GET /api/v1/watchdog/sessions`，返回多个项目的稳定 `SessionProjection[]`。

场景 2：返回的每个 session 都带稳定 `thread_id=session:{project_id}` 与 `native_thread_id`，便于上层继续跳转。

### 用户故事 2：目录与单 session 共享同一 stable projection 口径

同一个项目从 session directory 和单 session read surface 看上去应该是同一套稳定对象，而不是两个语义相近但字段不同的 DTO。

场景 1：`/watchdog/sessions` 中 `repo-a` 的 `pending_approval_count` 与 `/watchdog/sessions/repo-a` 一致。

场景 2：`available_intents` 的判定逻辑与单 session 读取保持一致，不因目录模式而降级。

### 用户故事 3：Adapter 与 HTTP 共享同一目录语义

Feishu adapter `list_sessions` 与 HTTP stable route 应该读取同一份共享 builder，而不是各自维护一份 session list 映射。

场景 1：adapter 返回的 `reply_code` 与 HTTP route 完全一致。

场景 2：HTTP 与 adapter 返回的 session 顺序和关键信息一致。

## 非目标

- 不新增 session 搜索、分页、排序、cursor、状态过滤、archive 或 history 查询。
- 不改变既有 `GET /api/v1/watchdog/sessions/{project_id}`、`/progress`、`/pending-approvals`、`/stuck-explanation`、`/blocker-explanation`。
- 不改变任何 stable write action、receipt、events 或 supervision 语义。
- 不替换或删除 Codex runtime service raw `/api/v1/tasks`。
