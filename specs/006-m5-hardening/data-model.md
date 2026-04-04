---
related_doc:
  - "openclaw-codex-watchdog-prd.md"
---

# 数据与接口补充：006-m5-hardening

## 任务状态

- `resume` 路径：`resuming` → `running`（同一请求内两次持久化更新）。

## workspace-activity 响应（示例）

- `cwd_exists`: bool
- `files_scanned`: int
- `latest_mtime_iso`: str | null
- `recent_change_count`: int（在扫描集合内最近 N 分钟内有 mtime 变更的文件数，N 可配置默认 15）

## Codex 占位

- `CodexClient` Protocol：`ping() -> bool`；`describe_thread(thread_id: str) -> dict[str, Any]` 等最小方法，默认返回空结构。
