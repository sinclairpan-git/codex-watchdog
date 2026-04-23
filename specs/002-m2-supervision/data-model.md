# 数据模型补充（M2）

## 任务快照扩展（相对 001）

- `stuck_level`：0–4（PRD §6.5）
- `failure_count`：int
- `last_error_signature`：string | null
- `last_progress_at`：ISO8601 字符串（已存在则沿用）

## 审计记录（JSONL 单行）

- `ts`：ISO8601
- `project_id`：string
- `action`：`stuck_eval` | `steer_injected` | `loop_escalation` | …
- `reason`：string
- `source`：`watchdog` | `a_control_agent`
- `payload`：可选 JSON 对象（如 steer 文本摘要）

## task_events（runtime 侧最小）

- `event_id`：string
- `project_id` / `thread_id`
- `event_type`：`steer`
- `event_source`：`watchdog` | `policy`
- `payload_json`：含 `message` 与 PRD `source`/`reason` 映射
