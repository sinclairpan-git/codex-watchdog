---
related_doc:
  - "openclaw-codex-watchdog-prd.md"
---

# PRD 实现偏差收口 — 功能规格说明

## 概述

将前期梳理的**实现偏差**纳入可验收工作项：在本仓库内能修复的（状态机、监管信号补强、恢复编排、可观测性），与必须依赖外部系统或明确 Out of Scope 的条目分册记录。

## 功能需求

- **FR-501**：`POST .../steer` 支持可选 **`stuck_level`**，写入持久化任务记录；Watchdog `evaluate` 在注入 steer 时传入 **`next_stuck_level`**（与 PRD §6.5 对齐）。
- **FR-502**：`handoff` 成功更新任务时同时写入 **`stuck_level: 4`**（PRD §6.5「已进入 handoff / resume」）。
- **FR-503**：`evaluate_stuck` 在可取得任务 `cwd` 时，结合 **`repo_activity.recent_change_count`**（与现有 `workspace-activity` 同源逻辑）：若窗口内存在文件系统变更，则**不**因仅 `last_progress_at` 过期而 `should_steer`（对齐 PRD §5.2「无文件变更」维度之一）。
- **FR-504**：Watchdog **`recover`** 在 handoff 成功后，支持配置项 **`recover_auto_resume`**（默认 false）：为 true 时顺序调用 A 侧 **`resume`**，完成「critical → handoff → resume」编排（对齐 PRD 叙述的最小可测闭环）。
- **FR-505**：在 `research.md` 中登记**仍属偏差但本迭代不编码**的项：真实 Codex app-server、飞书人工闭环、SSE `/events`、完整 transcript 卡顿等。

### 用户故事 1：stuck_level 可信

场景 1：Watchdog 触发 soft steer 后，查询任务可见 `stuck_level` 与 `evaluate.next_stuck_level` 一致（如 2）。

场景 2：handoff 完成后任务 `stuck_level` 为 4（或与 §6.5 注释一致）。

### 用户故事 2：监管信号更接近 PRD

场景 1：工作区在统计窗口内仍有文件变更时，`evaluate` 不因时间阈值单独触发 steer（返回明确 reason）。

### 用户故事 3：恢复编排可配置

场景 1：`recover_auto_resume=true` 且 handoff 成功时，响应体或审计能体现已尝试 `resume`。

## 非目标

- 不实现飞书推送、不实现 Codex 真实协议对接、不实现 SSE 事件流（见 FR-505）。
