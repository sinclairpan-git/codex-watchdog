# 数据模型：审批

与 PRD §7.2、`tasks` / `approvals` 最小字段（§12.3）对齐：

- `approval_id`：`appr_*`
- `project_id`, `thread_id`
- `risk_level`：`L0` | `L1` | `L2` | `L3`
- `command`, `reason`, `alternative`
- `status`：`pending` | `approved` | `rejected`
- `requested_at`, `decided_at`, `decided_by`
