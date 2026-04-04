---
related_doc:
  - "openclaw-codex-watchdog-prd.md"
---

# M2 监管能力 — 功能规格说明

## 概述

在 M1 已打通 A-Control-Agent 与 Watchdog 基础 API 的前提下，本工作项交付 **stuck 判断、自动 steer、循环失败检测、基础审计日志**（PRD §18 M2、§5.2、§5.4、§8、§13.3），且与既有 `001` 数据模型兼容。

## 功能需求

- **FR-101**：Watchdog 应能基于任务快照中的时间戳与 `stuck_level` 字段，按 PRD §8.1 默认阈值计算是否进入更高 stuck 等级（仅规则与状态迁移，不要求真实 transcript 流）。
- **FR-102**：A-Control-Agent 应实现 `POST /api/v1/tasks/{project_id}/steer`（PRD §9.3.3），将 steer 文本写入任务事件/审计，并更新 `last_summary` 或等价字段。
- **FR-103**：系统应检测「同类错误重复」或「failure_count 连续上升」路径下的循环失败风险，并将 `failure_count` / `last_error_signature` 用于升级判断（PRD §5.4、§6.3）。
- **FR-104**：所有自动 steer、stuck 升级、循环打断决策须写入可查询的审计记录（时间、原因、动作类型，PRD §13.3）。
- **FR-105**：Watchdog 应暴露只读查询或内部 API，供策略引擎读取某 `project_id` 的 stuck 分析结果（可与 progress 合并或独立模块）。

### 用户故事 1：无进展卡顿分级

监管方希望按时间阈值识别「无进展」，以便后续自动 steer 或提醒。

场景 1：当 `last_progress_at` 距现在超过 8 分钟且无文件变更信号时，系统将 `stuck_level` 提升至至少 2 或触发 steer 记录。

场景 2：当未达到阈值时，`stuck_level` 保持为 0 或 1，仅记审计不 steer。

### 用户故事 2：自动 steer 注入

监管方希望在 stuck 满足策略时向 Codex 侧注入 steer，而不绕过审批边界。

场景 1：当策略判定需 soft steer 时，调用 A-Control-Agent steer 接口并写入审计。

场景 2：当 steer 因鉴权失败被拒绝时，审计记录失败原因且不伪造成功。

### 用户故事 3：循环失败与审计

监管方希望同类错误重复出现时提升 `failure_count` 并留下可追溯记录。

场景 1：当同一 `last_error_signature` 连续出现时，增加 `failure_count` 并写审计。

场景 2：当 `failure_count` 达到策略上限时，任务状态可迁移为 `stuck` 或保持 `running` 但标记需人工（由配置决定，本工作项以实现计数与审计为准）。
