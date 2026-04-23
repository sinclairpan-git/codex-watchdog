---
related_doc:
  - "codex-watchdog-prd.md"
---

# 数据与行为补充：008-codex-live-control-plane

## Codex runtime service 配置增量

- `codex_bridge_enabled`：bool，默认 `true`；允许在不需要 live control plane 的环境中关闭 bridge。
- `codex_app_server_command`：string，默认 `codex app-server --listen stdio://`；允许替换为包装脚本或显式二进制路径。
- `codex_bridge_startup_timeout_seconds`：float，控制 bridge 初始化超时。
- `codex_bridge_request_timeout_seconds`：float，控制单次 JSON-RPC 请求超时。
- `codex_bridge_reconnect_backoff_seconds`：float，控制断线后的重连退避。

## Bridge 运行时状态

- `thread_id -> latest_snapshot`：缓存最近一次 `thread/read` 或恢复后的线程摘要。
- `thread_id -> active_turn_id`：用于区分线程当前应走 `turn/start` 还是 `turn/steer`。
- `approval_id -> app_server_request_id`：把外部审批记录映射回 Codex server request。
- `bridge_state`：至少区分 `starting / ready / degraded / disconnected`。

## Store 增量字段

- 任务记录建议补充：
  - `control_mode`：`local_snapshot` 或 `live_bridge`
  - `last_control_error`：最近一次 live control plane 失败摘要
- 审批记录建议补充：
  - `request_kind`：如 `command_execution`、`file_change`、`permissions`
  - `app_server_request_id`
  - `callback_status`：`pending / delivered / failed`
