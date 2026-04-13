# 执行日志：036-feishu-control-plane-and-openclaw-retirement

## 2026-04-14

### Phase 1：formal docs / spec freeze

- 基于 `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md` 的 `Task 7`，正式拆出 `WI-036`。
- 把目标边界收紧为：
  - `Feishu` 成为唯一主控制面；
  - `OpenClaw` 退为 compatibility-only surface；
  - 审批确认、通知回执、人工 override 与交互窗口更新必须先写 `Session Service` canonical events；
  - 同一 `interaction_family_id` 只允许一个有效 `interaction_context_id`，旧上下文晚到消息只进审计。
- formal docs 基线完成后，进入 Hermes Agent 专家与 Anthropic Manager 专家的对抗评审。
- Anthropic Manager 对抗评审指出一个 P1：spec 已要求 delivery truth / requeue / supersede / stale audit，但 Task 7 / 036 初版未把状态面明确分配到具体模块。
- 已按该反馈补齐 ownership：
  - `src/watchdog/services/delivery/store.py`
  - `src/watchdog/services/delivery/worker.py`
  - `src/watchdog/services/session_service/models.py`
  - `src/watchdog/services/session_spine/projection.py`
  这些模块现在被正式列为 036 的实现边界，避免后续红测/实现阶段再临时改 scope。
- Hermes Agent 专家终审：无 blocking/P1，确认 Feishu 主控制面、Session truth 与 OpenClaw compatibility-only 边界表述一致。
- Anthropic Manager 专家终审：无 blocking/P1，确认 delivery ownership 已补齐，work item 可直接进入 `T362` 红测。

### Phase 2 / 3：Feishu control red -> green

- 新增 `tests/test_watchdog_feishu_control.py`：
  - 高风险 approval 仅允许 `dm`；
  - Feishu response 必须先写 `notification_receipt_recorded`，再进入 `approval_approved` / `human_override_recorded`；
  - 过期窗口写 `interaction_window_expired`；
  - superseded context 写 `interaction_context_superseded` 并拒绝旧上下文。
- 新增 `tests/test_watchdog_notification_delivery.py`：
  - interaction metadata 必须进入 `notification_announced` / `notification_delivery_succeeded` / `notification_requeued` 等 canonical events。
- 新增 `src/watchdog/services/feishu_control/service.py` 与 `src/watchdog/api/feishu_control.py`，并在 `main.py` 注册 `/api/v1/watchdog/feishu/control`。
- `delivery/envelopes.py`、`delivery/worker.py`、`session_service/models.py` 与 `session_spine/projection.py` 已补 interaction metadata 与新事件类型。
- 本地验证：
  - `uv run pytest -q tests/test_watchdog_feishu_control.py tests/test_watchdog_notification_delivery.py tests/test_openclaw_contracts.py` -> `11 passed in 1.04s`
  - `uv run pytest -q tests/test_watchdog_feishu_control.py tests/test_watchdog_notification_delivery.py tests/test_openclaw_contracts.py tests/test_watchdog_delivery_worker.py tests/test_watchdog_approval_loop.py tests/test_watchdog_ops.py tests/test_watchdog_session_spine_projection.py tests/test_long_running_autonomy_doc_contracts.py` -> `77 passed in 1.59s`
- 实现后再次尝试 Hermes / Anthropic 实现切片对抗评审，但 reviewer agent 未在时限内返回有效 blocking/P1 结论；当前以本地全量相关回归为主验证，并将下一轮 review 留在后续兼容层收口时一并执行。

### Phase 4：OpenClaw compatibility bootstrap metadata

- `openclaw_bootstrap.py` 的 legacy requeue path 已补 interaction metadata 镜像，保证兼容层触发的 `notification_requeued` 仍能带回 `interaction_context_id` / `interaction_family_id` / `actor_id`。
- `openclaw_callbacks.py` 与 `OpenClawAdapter` 已显式标注 compatibility-only 语义，避免后续继续把它们当主控制面入口扩张。
- 新增/扩展验证：
  - `uv run pytest -q tests/test_watchdog_openclaw_bootstrap.py tests/test_openclaw_contracts.py tests/test_watchdog_feishu_control.py tests/test_watchdog_notification_delivery.py` -> `12 passed in 1.59s`
  - `uv run pytest -q tests/test_watchdog_feishu_control.py tests/test_watchdog_notification_delivery.py tests/test_watchdog_openclaw_bootstrap.py tests/test_openclaw_contracts.py tests/test_watchdog_delivery_worker.py tests/test_watchdog_approval_loop.py tests/test_watchdog_ops.py tests/test_watchdog_session_spine_projection.py tests/test_long_running_autonomy_doc_contracts.py` -> `78 passed in 1.36s`
