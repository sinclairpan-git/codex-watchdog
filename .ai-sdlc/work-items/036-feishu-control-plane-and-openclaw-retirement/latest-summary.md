# Development Summary

Status: in_progress
Total Tasks: 5
Completed Tasks: 3
Halted Tasks: 0
Total Batches: 5
Completed Batches: 3
Last Committed Task: T363

## Notes
- `WI-036` 已从总实施计划 `Task 7` 正式拆出，目标是让 `Feishu` 成为唯一主控制面，并把 `OpenClaw` 收口为 compatibility-only surface。
- 当前 formal docs 已冻结的关键边界：
  - 高风险确认只允许有效 Feishu DM；
  - `interaction_context_id` / `interaction_family_id` / actor binding / ACL / expiry / replay protection 是正式 contract；
  - 审批确认、通知回执、人工 override、窗口 supersede/expired 都必须先落 `Session Service` canonical events；
  - 同一 interaction family 只允许一个有效 context，旧上下文晚到消息只进审计。
- 已根据 Anthropic Manager 对抗评审补齐 delivery ownership：`src/watchdog/services/delivery/store.py`、`src/watchdog/services/delivery/worker.py`、`src/watchdog/services/session_service/models.py` 与 `src/watchdog/services/session_spine/projection.py` 现在是 036 的正式实现边界，负责 notification truth / requeue / supersede / stale audit 的状态与读侧投影。
- Hermes Agent 专家与 Anthropic Manager 专家最终复核均无 blocking/P1，`T361` 已可作为 036 的 docs baseline。
- `T362` / `T363` 已完成：
  - Feishu 主 control route 已落地；
  - DM-only approval、expired window、superseded context、receipt-first event ordering 已锁进测试；
  - interaction metadata 已贯通到 delivery/session projection。
- 当前下一执行入口是 `T364`：继续收口 OpenClaw compatibility-only surface，并把 bootstrap/callback/adapter 本体与新主控制面边界对齐。

## Latest Verification
- `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py` -> `3 passed in 0.04s`
- Hermes Agent 专家对抗评审（formal docs 修订后）-> `No blocking/P1 issues found.`
- Anthropic Manager 专家对抗评审（delivery ownership 修订后）-> `No blocking/P1 issues found.`
- `uv run pytest -q tests/test_watchdog_feishu_control.py tests/test_watchdog_notification_delivery.py tests/test_openclaw_contracts.py` -> `11 passed in 1.04s`
- `uv run pytest -q tests/test_watchdog_feishu_control.py tests/test_watchdog_notification_delivery.py tests/test_openclaw_contracts.py tests/test_watchdog_delivery_worker.py tests/test_watchdog_approval_loop.py tests/test_watchdog_ops.py tests/test_watchdog_session_spine_projection.py tests/test_long_running_autonomy_doc_contracts.py` -> `77 passed in 1.59s`

## Handoff
- 当前可直接继续 `T364`：把 `openclaw_bootstrap.py`、`openclaw_callbacks.py` 与 `OpenClawAdapter` 明确收口为 compatibility-only surface。
- 后续实现不得回退到“OpenClaw callback 决定控制真相”或“先改 store 再补事件”的旧路径。
