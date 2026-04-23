# Spec：064-feishu-direct-delivery-runtime

## 背景

虽然仓库已经在 `WI-036` / `WI-049` 完成了 Feishu 主入口与 Feishu compatibility-only 入口的 formal closeout，
但当前主动通知与审批出站仍默认绑定 `FeishuDeliveryClient` 与
`feishu_webhook_base_url`。这意味着 Feishu 现在更像“主入口壳子”，而不是真正闭环的唯一控制面。

`WI-064` 的目标是把出站 delivery 增补为可直连 Feishu 的 runtime，同时保留 Feishu 兼容层，避免回退到
“所有主动通知都先经过 Feishu webhook” 的旧主链路。

## 范围

### In Scope

- `src/watchdog/services/delivery/feishu_client.py`
- `src/watchdog/services/delivery/__init__.py`
- `src/watchdog/main.py`
- `src/watchdog/settings.py`
- `tests/test_watchdog_feishu_delivery.py`
- 受影响的 delivery / control-plane 回归

### Out of Scope

- 不在本工单内实现完整 Feishu 事件订阅网关；
- 不重写 `FeishuControlService` 的入站 ACL / interaction validity；
- 不删除 Feishu compatibility 路径；
- 不把 `AI_AutoSDLC` preview adapter 一并并入本工单。

## Formal Source

- `docs/architecture/codex-watchdog-full-product-loop-design.md`
- `docs/architecture/codex-long-running-autonomy-design.md`
- `specs/036-feishu-control-plane-primary-surface/spec.md`
- `specs/049-feishu-entrypoint-closure/spec.md`
- `src/watchdog/services/delivery/http_client.py`
- `src/watchdog/services/feishu_control/service.py`
- `src/watchdog/main.py`

## 非 Owner 约束

- **FR-6401**：Feishu 必须继续作为 primary control plane；Feishu 只能保留 compatibility-only surface。
- **FR-6402**：出站 delivery runtime 的切换不得绕过 `DeliveryWorker`、`DeliveryOutboxStore` 与 `Session Service` 的 event-first discipline。
- **FR-6403**：未配置 Feishu 直连参数时，系统必须继续兼容 Feishu legacy delivery。
- **FR-6404**：`WI-064` 只解决 outbound runtime，不在本轮宣称完整 Feishu bot ingress 也已一并闭环。

## 功能需求

- **FR-6405**：新增可配置的 Feishu direct delivery client，用于把 `DecisionEnvelope` / `NotificationEnvelope` / `ApprovalEnvelope` 直接投递到 Feishu。
- **FR-6406**：`create_app()` 必须根据明确的 transport 配置选择 delivery client，而不是硬编码 `FeishuDeliveryClient`。
- **FR-6407**：Feishu direct delivery 至少要支持：
  - tenant token 获取；
  - 文本消息发送；
  - 基于 message id 的 receipt 归档。
- **FR-6408**：现有 Feishu webhook bootstrap、compatibility callback 与 legacy store 不得被破坏。
- **FR-6409**：targeted tests 必须证明：
  - 配置 Feishu transport 后，出站先取 tenant token 再发消息；
  - `create_app()` wiring 会实例化 Feishu client；
  - 默认 transport 仍保持 Feishu compatibility。

## Docs baseline hash recipe

`docs_baseline_ref` 生成方式沿用现有 work item 规则，artifact set 固定为：

- `specs/064-feishu-direct-delivery-runtime/spec.md`
- `specs/064-feishu-direct-delivery-runtime/plan.md`
- `specs/064-feishu-direct-delivery-runtime/tasks.md`
- `specs/064-feishu-direct-delivery-runtime/task-execution-log.md`
- `.ai-sdlc/work-items/064-feishu-direct-delivery-runtime/execution-plan.yaml`
- `.ai-sdlc/work-items/064-feishu-direct-delivery-runtime/latest-summary.md`
