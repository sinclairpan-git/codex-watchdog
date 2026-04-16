# Spec：068-feishu-ingress-event-subscription-contract

## 背景

当前仓库已经具备两块 Feishu 相关能力，但还缺一块正式 owner：

- `WI-064` 已完成 `FeishuAppDeliveryClient`，也就是 **Watchdog -> Feishu outbound**；
- `WI-049/064` 已冻结 `/api/v1/watchdog/feishu/control`，也就是 **repo-internal canonical control contract**。

仍未正式落地的是 **Feishu 官方 event subscription / webhook ingress**：

- 当前没有 URL verification challenge 入口；
- 当前没有把 Feishu 官方 event envelope 适配成 canonical `FeishuControlRequest`；
- 当前没有 fail-closed 的 DM 文本消息 -> project/session 绑定规则。

`WI-068` 的目标是把这条官方 ingress 主链补齐，但 scope 只收敛到最小可用切片：**challenge + text message ingress + canonical normalization**，不在本工单内顺手引入第二套控制状态机。

## 范围

### In Scope

- `src/watchdog/api/feishu_ingress.py`
- `src/watchdog/services/feishu_ingress/service.py`
- `src/watchdog/services/feishu_control/service.py`
- `src/watchdog/main.py`
- `src/watchdog/settings.py`
- `tests/test_watchdog_feishu_ingress.py`
- `tests/test_openclaw_contracts.py`
- `ai_sdlc` 工单文档与状态同步

### Out of Scope

- 不在本工单内实现 Feishu interactive card 富交互渲染；
- 不在本工单内重写 `/api/v1/watchdog/feishu/control` canonical contract；
- 不在本工单内补齐 Feishu 审批卡片按钮回调；
- 不在本工单内扩 Memory Hub / Brain / Release Gate 的新语义。

## Formal Source

- `docs/architecture/codex-long-running-autonomy-design.md`
- `docs/architecture/openclaw-codex-watchdog-full-product-loop-design.md`
- `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
- `.ai-sdlc/work-items/064-feishu-direct-delivery-runtime/latest-summary.md`
- `src/watchdog/api/feishu_control.py`

## 非 Owner 约束

- **FR-6801**：Feishu 官方 ingress 只能归一到现有 canonical `/api/v1/watchdog/feishu/control` 语义，不得再造第二套控制状态机。
- **FR-6802**：所有不完整、不可鉴权、不可绑定的官方 ingress 请求必须 fail-closed。
- **FR-6803**：DM 仍然是高风险控制的唯一正式渠道；群聊消息不得被提升成高风险确认。
- **FR-6804**：本工单只补官方 ingress 与归一层，不扩大到 outbound 富消息或审批卡片协议。

## 功能需求

- **FR-6805**：新增 Feishu 官方 ingress route，支持 URL verification challenge。
- **FR-6806**：challenge 必须校验 `verification token`；配置缺失或 token 不匹配时 fail-closed。
- **FR-6807**：支持 Feishu 文本消息事件归一到 canonical `command_request` / `goal_contract_bootstrap`。
- **FR-6808**：project/session 绑定必须 fail-closed：
  - 显式 `repo:` / `project:` / `thread:` 前缀优先；
  - 只有在当前恰好存在一个活跃任务时，才允许自动绑定；
  - 其余歧义输入必须拒绝。
- **FR-6809**：`goal_contract_bootstrap` 只允许 DM 文本触发，且必须能解析到 `project_id` 与 `session_id`。
- **FR-6810**：文本消息解析失败、内容非文本、chat/channel 不符合要求、绑定不明确时，必须返回可观测的 fail-closed 错误。
- **FR-6811**：OpenAPI/route contract 必须暴露新的 Feishu ingress path。
- **FR-6812**：`goal_contract_bootstrap` 必须基于 Feishu `header.event_id` 做已应用事件判重；旧事件重放不得在后续 contract 变更后再次改写当前 goal contract。
- **FR-6813**：单活跃任务自动绑定必须直接绑定被选中的 active task 线程，不得再通过 `project_id -> current_thread` 的间接映射落到过期 session。

## 验证要求

- URL verification challenge pass / fail；
- `im.message.receive_v1` 文本消息能：
  - 通过显式 `repo:` 前缀进入 `command_request`；
  - 在单活跃任务场景自动绑定并进入 `goal_contract_bootstrap`；
  - 在多任务歧义或非 DM 条件下 fail-closed；
- 旧 Feishu `event_id` 重放不会覆盖较新的 goal contract；
- 同一 project 存在 completed + running 两条 task 时，自动绑定必须落到 active session；
- `tests/test_openclaw_contracts.py` 能看到新的 route；
- `ai_sdlc verify constraints` 通过。

## Docs baseline hash recipe

artifact set 固定为：

- `specs/068-feishu-ingress-event-subscription-contract/spec.md`
- `specs/068-feishu-ingress-event-subscription-contract/plan.md`
- `specs/068-feishu-ingress-event-subscription-contract/tasks.md`
- `specs/068-feishu-ingress-event-subscription-contract/task-execution-log.md`
- `.ai-sdlc/work-items/068-feishu-ingress-event-subscription-contract/execution-plan.yaml`
- `.ai-sdlc/work-items/068-feishu-ingress-event-subscription-contract/latest-summary.md`
