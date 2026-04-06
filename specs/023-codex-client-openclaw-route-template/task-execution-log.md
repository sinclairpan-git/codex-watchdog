# Task Execution Log: 023-codex-client-openclaw-route-template

## 2026-04-06

- 当前轮次只补 formal docs 与 `.ai-sdlc` work item 状态，不进入产品实现。
- 已完成任务：T231。
- 结果摘要：已手工补齐 `spec.md`、`plan.md`、`tasks.md`，把 023 scope 固定为“真实 Codex 客户端接缝 + OpenClaw 路由模板”，并将 active work item 从 022 推进到 023。
- `workitem init` 失败原因：`ai_sdlc.core.workitem_scaffold.WorkitemScaffolder` 默认把模板目录解析到 `.venv/lib/python3.11/templates`，导致 `template not found: /Users/sinclairpan/project/openclaw-codex-watchdog/.venv/lib/python3.11/templates/spec-template.md`。
- 处理方式：按 canonical direct-formal 同一目录边界手工落盘 `specs/023-codex-client-openclaw-route-template/`，不等待脚手架修复。
- 代码审查：本次未改 `src/`、`tests/` 与运行时代码，只更新 formal docs 与 `.ai-sdlc` 状态文件。
- 已完成任务：T232。
- T232 结果摘要：`CodexAppServerBridge.ingest_server_request()` 现在会把 `ApprovalsStore` 已自动批准的低风险请求与待人工审批请求分流处理。自动批准分支会立即按既有 callback 语义回写给 Codex，不再把 task 错标成 `waiting_human`；待人工审批分支继续登记 `_pending_approvals`、回写 `pending_approval` / `approval_risk` / `phase=approval`。
- T232 测试补充：把错误的“重启后恢复权限审批 pending 回调”样本替换为符合既有审批规格的回归测试，锁定低风险 `item/permissions/requestApproval` 会自动通过并立即回写 `{"permissions": ..., "scope": "session"}`。
- 验证：
  - `./.venv/bin/pytest -q tests/test_codex_app_server_bridge.py`
  - `./.venv/bin/pytest -q tests/test_codex_local_client.py tests/test_codex_app_server_bridge.py`
- 已完成任务：T233。
- T233 结果摘要：`/api/v1/tasks/{project_id}/steer` 现在会通过同一条 `codex_bridge` 接缝执行控制动作；当 bridge 在 `active_turn_id` / `turn/start` / `turn/steer` 上抛错时，API 不再冒成 500，而是返回稳定的 `CONTROL_LINK_ERROR` envelope，并向 `audit.jsonl` 追加 `steer_failed` 记录。失败时不会误写 `last_summary`，已有 task 状态保持不变。
- T233 测试补充：新增 bridge 掉线回归测试，先验证旧实现会返回 500，再锁定修复后的稳定降级与审计落点。
- 验证：
  - `./.venv/bin/pytest -q tests/test_a_control_agent.py -k steer_bridge_failure_returns_control_link_error_and_audit`
  - `./.venv/bin/pytest -q tests/test_a_control_agent.py`
  - `./.venv/bin/pytest -q tests/test_a_control_agent_control_flow.py`
- 已完成任务：T234。
- T234 结果摘要：`examples/openclaw_watchdog_client.py` 现在提供 `WatchdogTemplateClient`，把 OpenClaw 常见消息模板收敛到 stable Watchdog routes，至少覆盖查询进展、查询卡点、继续推进、审批 inbox 与审批决策。模板显式支持 `WATCHDOG_BASE_URL`、`WATCHDOG_API_TOKEN`、`WATCHDOG_DEFAULT_PROJECT_ID` 与 `WATCHDOG_OPERATOR`，并采用“显式 `project_id` 优先，缺省回退环境变量”的路由策略。
- T234 文档补充：`README.md`、`docs/getting-started.zh-CN.md` 与 `config/examples/watchdog.env.example` 已写清仓库只交付可复用 HTTP 模板，不包含飞书/OpenClaw runtime，并补齐消息类型到 stable route 的映射。
- 验证：
  - `./.venv/bin/pytest -q tests/integration/test_openclaw_integration_spine.py -k openclaw_template_routes`
  - `uv run pytest -q tests/integration/test_openclaw_integration_spine.py`
