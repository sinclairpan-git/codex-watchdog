# 数据模型（与 PRD 对齐）

## 任务状态（主状态）

`created` | `running` | `waiting_for_direction` | `waiting_for_approval` | `stuck` | `handoff_in_progress` | `resuming` | `paused` | `completed` | `failed`（PRD §6.1）

## 任务阶段（phase）

`planning` | `code_reading` | `editing_source` | `editing_tests` | `running_tests` | `debugging` | `summarizing` | `handoff`（PRD §6.2）

## 任务快照（字段）

- `project_id`, `thread_id`, `cwd`, `task_title`, `status`, `phase`
- `context_pressure`: `low` | `medium` | `high` | `critical`
- `stuck_level`: 0–4（PRD §6.5）
- `pending_approval`, `approval_risk`, `last_progress_at`, `files_touched`, `failure_count`, `last_error_signature` 等（PRD §6.3）

## 审批对象

- `approval_id`, `project_id`, `thread_id`, `risk_level`（L0–L3）, `command`, `reason`, `alternative`, `status`, 时间戳与决策人（PRD §7.2）

## 持久化拆分

- **runtime 侧**：`tasks`, `task_events`, `approvals`, `thread_mapping`, `handoff_summaries` 目录（PRD §12.1）
- **watchdog 侧**：`watchdog_snapshots`, `watchdog_actions`, `approval_decisions`, `notification_history`（PRD §12.2）
