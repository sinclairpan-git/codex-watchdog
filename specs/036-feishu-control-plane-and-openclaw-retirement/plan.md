---
related_doc:
  - "docs/architecture/codex-long-running-autonomy-design.md"
  - "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
  - "specs/036-feishu-control-plane-and-openclaw-retirement/spec.md"
  - "specs/030-session-service-event-truth-write-barrier/spec.md"
  - "specs/031-session-spine-events-projection-read-surface/spec.md"
  - "specs/033-recovery-transaction-lineage/spec.md"
  - "specs/035-brain-decision-boundary-and-release-gate/spec.md"
---

# 实施计划：036-feishu-control-plane-and-openclaw-retirement

## 目标

把现有人机交互主路径从 OpenClaw webhook/callback 迁到 Feishu 控制面，同时冻结 interaction context、通知投递中间态、actor binding、ACL 与 supersede 纪律，使 OpenClaw 只保留兼容读写协议。

## 架构摘要

- **Feishu is the only primary control plane**：`src/watchdog/services/feishu_control/service.py` 与 `src/watchdog/api/feishu_control.py` 承载主控制入口；高风险确认、人工 override、通知回执与窗口续发语义都从这里进入，而不是继续由 OpenClaw callback 主导。
- **Events first, controls second**：任何审批、回执、override 或 stale/expired 交互都必须先写 `Session Service` canonical events，再驱动 approval/projection/delivery 更新；外部 handler 只负责合同校验与事件映射。
- **Interaction family is single-active**：同一 `interaction_family_id` 只能有一个当前有效 context；需要补发、重试、过期续发时必须先 supersede 旧 context，再创建新 context，并且 attempt 幂等键必须固定。
- **OpenClaw becomes compatibility-only**：`openclaw_bootstrap.py`、`openclaw_callbacks.py` 与 `OpenClawAdapter` 继续提供迁移期读写协议，但不能再决定主链路、交互有效性或通知真相。
- **Main wiring makes the boundary visible**：`src/watchdog/main.py` 必须显式注册 Feishu 主入口，并让 OpenClaw surface 的文案和依赖关系都体现“兼容层”而不是“主控制面”。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Feishu control contracts | `src/watchdog/services/feishu_control/service.py`, `src/watchdog/api/feishu_control.py` | 定义 Feishu control request/response、ACL、actor binding、DM-only 高风险确认、interaction validity、replay protection 与 event-first mapping |
| Main app wiring | `src/watchdog/main.py` | 注册 Feishu 主控制面 API，初始化主路径依赖，并把 OpenClaw surface 降级为 compatibility-only |
| Delivery truth and retry state | `src/watchdog/services/delivery/store.py`, `src/watchdog/services/delivery/worker.py` | 承担通知 outbox、delivery attempt、requeue、supersede、receipt 与 stale/audit 的状态真相面，不允许 API handler 自行分叉状态 |
| Event schema and read-side projection | `src/watchdog/services/session_service/models.py`, `src/watchdog/services/session_spine/projection.py` | 冻结 `interaction_context_superseded`、`interaction_window_expired` 等事件类型及其读侧投影，确保 Feishu/OpenClaw 共用同一套事件语义 |
| Compatibility surfaces | `src/watchdog/api/openclaw_bootstrap.py`, `src/watchdog/api/openclaw_callbacks.py`, `src/watchdog/services/adapters/openclaw/adapter.py` | 保留迁移期 bootstrap / callbacks / stable read-write compatibility contract，但统一复用 control-plane interaction validity 与 write barrier discipline |
| Delivery and interaction semantics | `tests/test_watchdog_notification_delivery.py`, `tests/test_watchdog_feishu_control.py`, `tests/test_openclaw_contracts.py` | 冻结通知投递中间态、单活跃 interaction family、旧上下文审计化、Feishu DM 限制与 OpenClaw compatibility 边界 |

## 边界纪律

- 036 不得让任何 Feishu 或 OpenClaw handler 直接修改 approval/delivery/runtime store 而不先写 `Session Service` event。
- 036 不得把 OpenClaw bootstrap/callbacks 换个名字继续当主控制面；它们只能消费共享 control-plane contract。
- 036 不得复用旧 `interaction_context_id` 处理重发、补发、过期窗口恢复或 stale interaction。
- 036 不得让高风险动作通过群聊、无 actor binding、跨项目 actor 或过期上下文获得批准。
- 036 不正式完成 e2e golden path，只冻结 Task 8 需要消费的 Feishu/control-plane contract。

## 依赖顺序

1. **先冻结 formal docs 与 036 work item 元数据**
   - 把总实施计划中的 `Task 7` 正式拆成 canonical execution work item；
   - 明确当前仓库的主控制入口仍偏向 OpenClaw compatibility surface，需要在 036 中调转主次。
2. **再写失败测试锁定 Feishu control semantics**
   - 先证明当前仓库缺少 Feishu 主控制服务、ACL 与 interaction validity contract；
   - 先证明当前通知投递与 OpenClaw callbacks 还没有单活跃 context / supersede / stale reply 的正式锁定。
3. **再实现最小 Feishu control plane**
   - 新建 Feishu service/API，并把审批、override、通知回执映射为 event-first workflow；
   - 同步补齐 interaction family / attempt idempotency / DM-only confirmation 规则。
4. **再收口 OpenClaw compatibility 与 main wiring**
   - 让 `main.py` 以 Feishu surface 为主入口；
   - 让 OpenClaw bootstrap/callbacks/adapter 只保留迁移期兼容协议与审计入口。
5. **最后运行验证并更新 handoff**
   - 固定后续 e2e work item 只消费 Feishu control contract 与 notification truth，不再从 OpenClaw 入口补主链路语义。

## 分阶段计划

### Phase 1：冻结 036 formal docs、任务分解与执行元数据

交付内容：

- `specs/036-feishu-control-plane-and-openclaw-retirement/spec.md`
- `specs/036-feishu-control-plane-and-openclaw-retirement/plan.md`
- `specs/036-feishu-control-plane-and-openclaw-retirement/tasks.md`
- `specs/036-feishu-control-plane-and-openclaw-retirement/task-execution-log.md`
- `.ai-sdlc/work-items/036-feishu-control-plane-and-openclaw-retirement/*`

关键原则：

- 先把 036 收紧为“Feishu 主控制面 + OpenClaw compatibility-only”；
- 明确它只消费 030-035 已冻结的 truth/projection/recovery/brain contracts。

### Phase 2：写失败测试锁定 Feishu control、notification midstate 与 compatibility 边界

交付内容：

- `tests/test_watchdog_feishu_control.py`
- `tests/test_watchdog_notification_delivery.py`
- `tests/test_openclaw_contracts.py`

关键原则：

- 红测优先锁定 DM-only 高风险确认、actor binding、ACL、过期与 replay protection；
- 红测优先锁定通知投递必须经过 `notification_delivery_succeeded|failed|requeued` 与 `interaction_context_superseded`；
- 红测优先锁定 OpenClaw 只剩兼容层而非主执行入口。

### Phase 3：实现最小 Feishu control plane 与 interaction validity

交付内容：

- `src/watchdog/services/feishu_control/service.py`
- `src/watchdog/api/feishu_control.py`
- `src/watchdog/main.py`
- `src/watchdog/services/delivery/store.py`
- `src/watchdog/services/delivery/worker.py`
- `src/watchdog/services/session_service/models.py`
- `src/watchdog/services/session_spine/projection.py`

关键原则：

- 先实现 Feishu command gateway、ACL、actor binding 与 event-first mapping；
- 先把 interaction family 的单活跃规则、窗口过期与 replay protection 收成明确 contract；
- 同步把 notification truth / requeue / supersede / stale audit 的状态面明确绑定到 delivery + event schema/projection 模块。

### Phase 4：收口 OpenClaw compatibility、通知投递恢复与主入口切换

交付内容：

- `src/watchdog/api/openclaw_bootstrap.py`
- `src/watchdog/api/openclaw_callbacks.py`
- `src/watchdog/services/adapters/openclaw/adapter.py`
- `src/watchdog/services/delivery/store.py`
- `src/watchdog/services/delivery/worker.py`
- `src/watchdog/services/session_service/models.py`
- `src/watchdog/services/session_spine/projection.py`
- `tests/test_watchdog_feishu_control.py`
- `tests/test_watchdog_notification_delivery.py`
- `tests/test_openclaw_contracts.py`
- `tests/test_watchdog_ops.py`

关键原则：

- OpenClaw 只保留稳定读写兼容协议与迁移期 bootstrap，不再主导控制真相；
- delivery outbox、attempt、requeue、supersede 与 stale/audit 的状态面必须有明确 owner，不能散落在 API handler 中；
- 晚到送达、晚到回复、窗口过期与补发后的旧上下文只能进入审计，不得双生效。

### Phase 5：运行验证并交接到 e2e golden path work item

交付内容：

- `specs/036-feishu-control-plane-and-openclaw-retirement/task-execution-log.md`
- `.ai-sdlc/work-items/036-feishu-control-plane-and-openclaw-retirement/latest-summary.md`

关键原则：

- handoff 必须明确 Feishu 是唯一主控制面，OpenClaw 只剩 compatibility-only surface；
- Task 8 只能消费 036 冻结的 interaction/notification/control-plane contract，不再补回 OpenClaw 主链路语义。

## 测试计划

- `tests/test_watchdog_feishu_control.py`
  - 高风险确认只允许 DM
  - `interaction_context_id`、`interaction_family_id`、actor binding、ACL、过期与 replay protection 被显式冻结
  - approval/override/control 命令必须先写 canonical event 再更新下游状态
- `tests/test_watchdog_notification_delivery.py`
  - `notification_announced` 与送达结果分离
  - `notification_delivery_failed`、`notification_requeued`、`interaction_context_superseded` 与 `interaction_window_expired` 被锁定
  - 同一 interaction family 只有一个活跃 context，旧上下文晚到回执/回复只进审计
- `tests/test_openclaw_contracts.py`
  - OpenClaw 入口退为 compatibility-only surface
  - bootstrap/callbacks 复用共享 control-plane contract，不再独立决定有效性
  - OpenClaw 仍可提供 stable read / action receipt / migration callback，但不能直接成为主控制面
- `tests/test_watchdog_ops.py`
  - ops/read-side 对 Feishu 主控制面与通知中间态的可观测字段不回退

## 主要风险与应对

### 风险 1：Feishu 接进来后仍然把真相写在 callback/store 分支里

应对：

- 所有 handler 先写 `Session Service` canonical events；
- 用测试锁死 event-first discipline，禁止 direct store mutation。

### 风险 2：补发、重试和窗口过期后出现双活跃上下文

应对：

- 强制 interaction family 单活跃；
- 晚到消息只能进入审计，不能反向激活旧 context。

### 风险 3：OpenClaw 名义上退役，实际上仍承担主职责

应对：

- `main.py` 显式注册 Feishu 为主入口；
- OpenClaw tests 只验证 compatibility contract，不再验证主链路决策。

### 风险 4：Task 7 顺手侵入 Brain/release gate 核心实现

应对：

- 036 只消费 035 已冻结的 Brain trace / release gate verdict；
- 不在本 work item 改写 provider/release gate contract。

## 验收口径

只有当以下条件同时满足，036 才算完成：

1. Feishu 已成为唯一主控制面，高风险确认只能在有效 DM interaction 中生效；
2. interaction context、interaction family、actor binding、ACL、过期与 replay protection 都已形成正式 contract；
3. 审批确认、通知回执、人工 override 与窗口恢复都遵守 event-first write barrier；
4. 通知投递中间态、单活跃上下文与 supersede/expired/stale 语义已被测试锁定；
5. `main.py`、OpenClaw bootstrap/callbacks/adapter 已体现 compatibility-only 边界，而不是继续承担主控制职责；
6. 后续 e2e work item 可以直接消费 036 冻结的 Feishu/control-plane contract，而不需要补回 OpenClaw 主链路语义。
