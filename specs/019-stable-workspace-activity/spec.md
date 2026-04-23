---
related_doc:
  - "codex-watchdog-prd.md"
  - "docs/architecture/codex-watchdog-g0-and-v010-design.md"
  - "specs/010-runtime-integration-spine/spec.md"
  - "specs/014-stable-supervision-evaluation/spec.md"
  - "specs/018-stable-native-thread-resolution/spec.md"
---

# Stable Workspace Activity — 功能规格说明

## 概述

在 `010-018` 完成 stable session spine、events、receipts、supervision、explanations、approval inbox、session directory 与 native-thread resolution 之后，当前还有一个明显的 raw 缺口：

- Codex runtime service 已经提供 `GET /api/v1/tasks/{project_id}/workspace-activity`；
- `014` 的 supervision evaluation 已经消费同源 repo activity 信号；
- 但 Feishu 与其他上层调用方仍然没有稳定的 workspace-activity read surface，只能继续依赖 raw A payload。

019 的唯一目标固定为：

> 建立 stable workspace-activity read surface，让 Feishu 与其他调用方能够通过 Watchdog stable contract 获取版本化工作区活动摘要，而不是直接绑定 Codex runtime service raw `/workspace-activity` 响应。

## 功能需求

- **FR-1901**：019 必须新增独立 stable object `WorkspaceActivityView`，不得把 workspace activity 继续作为匿名 `dict`、supervision 内部字段或 raw passthrough 暴露。
- **FR-1902**：019 的 canonical stable route 固定为：
  - `GET /api/v1/watchdog/sessions/{project_id}/workspace-activity`
- **FR-1903**：该 route 返回稳定 `ReplyModel`，其中：
  - `reply_kind=session`
  - `reply_code=workspace_activity_view`
  - `intent_code=get_workspace_activity`
  - `workspace_activity` 为稳定 `WorkspaceActivityView`
  - `session` 为同源 `SessionProjection`
  - `facts` 为同源 `FactRecord[]`
- **FR-1904**：`WorkspaceActivityView` 至少包含以下稳定字段：
  - `project_id`
  - `thread_id`
  - `native_thread_id`
  - `recent_window_minutes`
  - `cwd_exists`
  - `files_scanned`
  - `latest_mtime_iso`
  - `recent_change_count`
- **FR-1905**：019 必须在 Watchdog L2 内通过共享 builder 把 session 元信息与 Codex runtime service `/workspace-activity` 原始摘要投影为 `WorkspaceActivityView`；HTTP route 与 adapter 不得直接拼 raw payload。
- **FR-1906**：Feishu adapter 必须新增 `get_workspace_activity` intent，并通过 stable builder 返回与 HTTP route 同源的 `ReplyModel`。
- **FR-1907**：stable route 与 adapter 都必须支持 `recent_minutes` 参数；默认值为 `15`，并与 raw A route 一样限制在 `1..1440` 分钟范围内。
- **FR-1908**：019 必须新增 `ReplyModel.workspace_activity` 字段与 `ReplyCode.WORKSPACE_ACTIVITY_VIEW`，因此 session spine `schema_version` 必须从 `2026-04-05.017` 推进到 `2026-04-05.019`。
- **FR-1909**：019 不新增新的 stable write action、receipt、event 或 supervisor 行为；workspace activity 只作为 read surface 暴露。
- **FR-1910**：当 project 不存在、control-link 异常或上游返回非法 payload 时，019 必须继续复用稳定 error envelope；不得泄露 raw upstream body。
- **FR-1911**：README、getting-started 与 OpenAPI 必须明确写清：
  - `/api/v1/watchdog/sessions/{project_id}/workspace-activity`：stable workspace activity route
  - `/api/v1/tasks/{project_id}/workspace-activity`：Codex runtime service raw route，继续存在但不承担 stable contract 角色
- **FR-1912**：019 必须补齐契约测试、API 测试、adapter 测试、最小 integration 测试，以及 raw `/workspace-activity` 非回归测试。

### 用户故事 1：Feishu 可以稳定读取当前工作区活动摘要

Feishu 需要判断项目最近是否真的有文件活动，但不应该自己碰 raw A payload。

场景 1：调用 `GET /api/v1/watchdog/sessions/proj-a/workspace-activity`，返回 `ReplyModel(reply_code=workspace_activity_view)`。

场景 2：返回体同时包含 `session.project_id / thread_id / native_thread_id` 与 `workspace_activity.recent_change_count`，上层无需二次拼装。

### 用户故事 2：HTTP 与 adapter 共用同一套 workspace activity 语义

同一个 `project_id + recent_minutes` 在 HTTP stable route 与 Feishu adapter 上应得到同源结果。

场景 1：adapter `get_workspace_activity(project_id=..., arguments.recent_minutes=...)` 与 HTTP route 返回相同 `reply_code` 与关键字段。

场景 2：两者的 `recent_change_count`、`latest_mtime_iso` 与 session 身份字段一致。

### 用户故事 3：raw `/workspace-activity` 继续存在，但不再是 stable contract

已有脚本和历史测试可能仍依赖 Codex runtime service raw route。

场景 1：019 落地后，raw `/api/v1/tasks/{project_id}/workspace-activity` 继续工作且基础行为不回归。

场景 2：README / OpenAPI 明确 stable vs raw 的角色边界。

## 非目标

- 不扩成实时 workspace activity event stream。
- 不把 workspace activity 与 stuck explanation / supervision evaluation 混成一个复合 reply。
- 不新增 workspace scan 写动作、强制刷新、缓存控制或后台采集 daemon。
- 不改变既有 `GET /api/v1/watchdog/sessions/{project_id}`、`/progress`、`/events`、`/action-receipts`、`/approval-inbox` 的 contract。
