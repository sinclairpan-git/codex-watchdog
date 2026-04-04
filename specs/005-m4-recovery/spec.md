---
related_doc:
  - "openclaw-codex-watchdog-prd.md"
---

# M4 恢复能力 — 功能规格说明

## 概述

交付 **handoff 摘要生成与落盘、resume/新线程续跑入口、context 临界时的状态迁移**（PRD §18 M4、§5.5、§8.3、§9.3.4–9.3.5）。与 Codex 真实线程切换的对接留接口占位。

## 功能需求

- **FR-301**：A-Control-Agent 实现 `POST /api/v1/tasks/{project_id}/handoff`：接受 `reason`，生成结构化 markdown 摘要写入仓库可配置目录，并更新任务状态（PRD §6.1 `handoff_in_progress` / 后续迁移）。
- **FR-302**：实现 `POST /api/v1/tasks/{project_id}/resume`：接受 `mode`（如 `resume_or_new_thread`）与 `handoff_summary`，将任务置为 `resuming` 再 `running`，并写审计（PRD §9.3.5）。
- **FR-303**：当 `context_pressure == critical` 时，策略层可触发 handoff 路径（本工作项以 API + 单元测试证明可调用性）。
- **FR-304**：Watchdog 提供 `POST /api/v1/watchdog/tasks/{project_id}/recover`：编排「拉取状态 → 若 critical 则调用 A handoff 或返回建议」（最小实现：转发或组合已有 progress + handoff）。

### 用户故事 1：生成 handoff 文件

开发者在上下文压力下需要可恢复的会话摘要。

场景 1：调用 handoff 接口后，返回 `handoff_file` 路径与非空 `summary` 字段。

场景 2：同一 `project_id` 重复 handoff 时覆盖或版本化由存储策略决定（本实现采用按时间戳文件名避免丢失）。

### 用户故事 2：resume 闭环

场景 1：`resume` 成功后任务状态为 `running` 且审计含 `resume` 动作。

场景 2：缺少 `project_id` 任务时返回 `NOT_FOUND` envelope。

### 用户故事 3：Watchdog 恢复编排

场景 1：`recover` 在 A 不可达时返回 `CONTROL_LINK_ERROR`。

场景 2：A 可达且 `context_pressure` 为 `critical` 时尝试调用 A 侧 handoff（可 mock）。
