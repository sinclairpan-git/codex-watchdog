# 任务分解：036-feishu-control-plane-and-openclaw-retirement

> 对应规格：`specs/036-feishu-control-plane-and-openclaw-retirement/spec.md`
>
> 对应计划：`specs/036-feishu-control-plane-and-openclaw-retirement/plan.md`

## Task 36.1 冻结 036 formal docs 与 Feishu / OpenClaw 执行边界

- **任务编号**：T361
- **状态**：已完成（2026-04-14）
- **目标**：把总实施计划中的 `Task 7` 正式拆成 canonical execution work item，并把 036 收紧为 Feishu 主控制面、interaction validity 与 OpenClaw compatibility-only 边界。
- **文件**：
  - `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
  - `specs/036-feishu-control-plane-and-openclaw-retirement/spec.md`
  - `specs/036-feishu-control-plane-and-openclaw-retirement/plan.md`
  - `specs/036-feishu-control-plane-and-openclaw-retirement/tasks.md`
  - `specs/036-feishu-control-plane-and-openclaw-retirement/task-execution-log.md`
  - `.ai-sdlc/work-items/036-feishu-control-plane-and-openclaw-retirement/*`
- **可并行**：否
- **验收标准**：
  1. 已明确 036 的主目标是 Feishu 成为唯一主控制面，OpenClaw 退为 compatibility-only surface；
  2. 已明确审批确认、通知回执、人工 override 与交互窗口更新都必须先落 `Session Service` canonical events；
  3. 已明确 interaction family 单活跃、DM-only 高风险确认、actor binding、ACL、过期与 replay protection 是 036 的正式 contract；
  4. 已明确 036 只消费 030-035 已冻结的 truth/projection/recovery/brain/release gate contracts，不提前做 e2e golden path。
- **验证**：人工审阅 `spec.md / plan.md / tasks.md / .ai-sdlc` 元数据与总实施计划中的 Task 7 边界一致。
- **完成情况**：
  1. 已创建 `spec.md / plan.md / tasks.md / task-execution-log.md` 与 `.ai-sdlc/work-items/036-*` 基线；
  2. 已把 Task 7 的 delivery ownership 明确分配到 `delivery/store.py`、`delivery/worker.py`、`session_service/models.py` 与 `session_spine/projection.py`；
  3. Hermes Agent 专家与 Anthropic Manager 专家最终复核均无 blocking/P1 问题。

## Task 36.2 写失败测试锁定 Feishu control、通知投递中间态与 OpenClaw compatibility contract

- **任务编号**：T362
- **状态**：已完成（2026-04-14）
- **目标**：用失败测试先锁定 Task 7 的正式输入输出 contract，避免实现继续把 OpenClaw callback 当主控制入口。
- **文件**：
  - `tests/test_watchdog_feishu_control.py`
  - `tests/test_watchdog_notification_delivery.py`
  - `tests/test_openclaw_contracts.py`
- **可并行**：否
- **验收标准**：
  1. 覆盖高风险确认只允许 Feishu DM；
  2. 覆盖 `interaction_context_id`、`interaction_family_id`、actor binding、ACL、过期与 replay protection；
  3. 覆盖审批确认、通知回执与人工 override 都必须先写 `Session Service` canonical event；
  4. 覆盖 `notification_delivery_succeeded|failed|requeued`、`interaction_context_superseded`、`interaction_window_expired` 与重建 context；
  5. 覆盖同一 interaction family 任意时刻只允许一个有效 context，旧上下文晚到消息只进审计；
  6. 覆盖 OpenClaw 入口退为 compatibility-only surface，而非主执行入口。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_feishu_control.py tests/test_watchdog_notification_delivery.py tests/test_openclaw_contracts.py`
- **完成情况**：
  1. 已新增 `tests/test_watchdog_feishu_control.py`，锁定 DM-only approval、receipt 先写 event、过期窗口拒绝与 superseded context 审计；
  2. 已新增 `tests/test_watchdog_notification_delivery.py`，锁定 interaction metadata 在 notification delivery success/requeue 事件中的传递；
  3. 已在 `tests/test_openclaw_contracts.py` 增补主 Feishu route 与 OpenClaw compatibility route 并存的 contract。

## Task 36.3 实现最小 Feishu control plane 与 interaction validity

- **任务编号**：T363
- **状态**：已完成（2026-04-14）
- **目标**：交付 Feishu 主控制面的最小服务/API 切片，让主入口和控制语义先站稳。
- **文件**：
  - `src/watchdog/services/feishu_control/service.py`
  - `src/watchdog/api/feishu_control.py`
  - `src/watchdog/main.py`
  - `src/watchdog/services/delivery/store.py`
  - `src/watchdog/services/delivery/worker.py`
  - `src/watchdog/services/session_service/models.py`
  - `src/watchdog/services/session_spine/projection.py`
- **可并行**：否
- **验收标准**：
  1. 已新增 Feishu control service/API，具备 DM-only 高风险确认、ACL、actor binding 与 replay protection；
  2. 已把审批/override/通知回执映射为 event-first workflow，而不是直接改 store；
  3. 已冻结 interaction family 单活跃、过期拒绝与续发新 context 的规则；
  4. 已明确 `delivery/store.py`、`delivery/worker.py`、`session_service/models.py` 与 `session_spine/projection.py` 共同承接通知投递中间态与新事件 schema，不再由 API handler 临时持有状态；
  5. `main.py` 已把 Feishu surface 注册为主入口。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_feishu_control.py -k 'dm or acl or replay or expired'`
- **完成情况**：
  1. 已新增 `src/watchdog/services/feishu_control/service.py` 与 `src/watchdog/api/feishu_control.py`，交付主 Feishu control route；
  2. `main.py` 已注册 `/api/v1/watchdog/feishu/control` 主入口；
  3. approval response 现在先写 `notification_receipt_recorded`，再进入 canonical approval/human override side effects；
  4. 已新增 `interaction_window_expired` 与 `interaction_context_superseded` 事件 contract，并把 interaction metadata 贯通到 delivery/session projection。

## Task 36.4 收口通知投递恢复与 OpenClaw compatibility 边界

- **任务编号**：T364
- **状态**：已完成（2026-04-14）
- **目标**：把通知投递中间态与 OpenClaw 兼容层真正接入主路径，使旧入口不再承担主控制职责。
- **文件**：
  - `src/watchdog/api/openclaw_bootstrap.py`
  - `src/watchdog/api/openclaw_callbacks.py`
  - `src/watchdog/services/adapters/openclaw/adapter.py`
  - `src/watchdog/services/delivery/store.py`
  - `src/watchdog/services/delivery/worker.py`
  - `src/watchdog/services/session_service/models.py`
  - `src/watchdog/services/session_spine/projection.py`
  - `tests/test_watchdog_notification_delivery.py`
  - `tests/test_openclaw_contracts.py`
  - `tests/test_watchdog_ops.py`
- **可并行**：否
- **验收标准**：
  1. 通知投递已显式产出送达成功、发送失败、重试排队、上下文 supersede 与窗口过期事件；
  2. 旧上下文的晚到送达/回复不会双生效，只进入审计；
  3. `delivery/store.py`、`delivery/worker.py`、`session_service/models.py` 与 `session_spine/projection.py` 已明确承接 notification truth / requeue / supersede / stale audit 的状态与投影；
  4. OpenClaw bootstrap/callbacks 只保留迁移期兼容协议，并复用共享 control-plane validity contract；
  5. ops/read-side 能看到 Feishu 主控制面与通知中间态事实，且不回退。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_notification_delivery.py tests/test_openclaw_contracts.py tests/test_watchdog_ops.py`
- **当前进展**：
  1. 已把 interaction metadata 贯通到 `delivery/envelopes.py`、`delivery/worker.py` 与 `session_spine/projection.py`；
  2. 已锁定 Feishu 主 route 与 OpenClaw compatibility route 同时存在的 contract；
  3. `openclaw_bootstrap.py` 触发 legacy requeue 时，已开始镜像 `interaction_context_id` / `interaction_family_id` / `actor_id` 等 metadata 到 canonical `notification_requeued` 事件；
  4. `openclaw_callbacks.py` 与 `OpenClawAdapter` 已显式标注 compatibility-only 语义；
  5. `openclaw_responses` 现在也先写 compatibility receipt，再进入 approval / human override side effects，旧入口已遵守同一条 event-first 纪律。

## Task 36.5 更新执行日志与 handoff 摘要

- **任务编号**：T365
- **状态**：已完成（2026-04-14）
- **目标**：同步 formal docs、执行日志与 `.ai-sdlc` 元数据，固定后续 e2e handoff。
- **文件**：
  - `specs/036-feishu-control-plane-and-openclaw-retirement/task-execution-log.md`
  - `.ai-sdlc/work-items/036-feishu-control-plane-and-openclaw-retirement/execution-plan.yaml`
  - `.ai-sdlc/work-items/036-feishu-control-plane-and-openclaw-retirement/runtime.yaml`
  - `.ai-sdlc/work-items/036-feishu-control-plane-and-openclaw-retirement/resume-pack.yaml`
  - `.ai-sdlc/work-items/036-feishu-control-plane-and-openclaw-retirement/latest-summary.md`
- **可并行**：否
- **验收标准**：
  1. 执行日志已记录 red/green/review 闭环与边界收口；
  2. `.ai-sdlc` 元数据能准确恢复到下一执行入口；
  3. handoff 明确 Task 8 只消费 036 的 Feishu/control-plane contract；
  4. handoff 明确 OpenClaw 只保留 compatibility-only surface，不得回升为主控制面。
- **验证**：
  - `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`
  - 人工审阅执行日志与 `.ai-sdlc` 元数据一致
- **完成情况**：
  1. 已同步 `task-execution-log.md`、`execution-plan.yaml`、`runtime.yaml`、`resume-pack.yaml` 与 `latest-summary.md`；
  2. 已记录 docs baseline、Feishu primary control surface、OpenClaw compatibility bootstrap/receipt 三个连续提交；
  3. 已记录实现期对抗 reviewer 多次超时未返回 blocking/P1 结论，当前以 79 个相关回归作为本轮收口证据。

## 整体验收

- 036 是长时运行自治一期的 `Task 7`，只负责把 Feishu 收敛为唯一主控制面，并把 OpenClaw 降为 compatibility-only surface。
- 036 完成后，审批确认、通知回执、人工 override 与交互窗口更新应统一走 event-first write barrier。
- 036 完成后，同一 interaction family 只能有一个活跃上下文；旧上下文晚到消息只进审计。
- 036 已完成 Feishu 主控制面迁移与 OpenClaw 主链路退役的一期 contract 收口；端到端 golden path 与一期通关验收留给后续 work item。
