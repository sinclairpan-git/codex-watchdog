---
related_doc:
  - "codex-watchdog-prd.md"
  - "docs/architecture/codex-watchdog-g0-and-v010-design.md"
---

# 实施计划：010-runtime-integration-spine

## 目标

在不实现完整实时监管与自动恢复体系的前提下，交付一套 **可长期演进的 Feishu 集成脊柱**：通过中立 contract 包、L2 稳定投影层、L3 独立 adapter spine，以及 canonical `WatchdogAction -> WatchdogActionResult` 动作面，让 Feishu 只依赖稳定契约而不再耦合 raw Watchdog / Codex runtime service 字段。

## 架构摘要

- **Contract-first**：先冻结中立 contract 包，后做投影、动作和 adapter。
- **L2/L3 分层**：L2 负责 raw -> stable contract 的投影与动作结果生成；L3 只负责 `intent_code -> ReplyModel` 适配。
- **Canonical write surface**：所有 write 行为统一落到 `POST /api/v1/watchdog/actions`；路径级动作路由只是包装别名。
- **Advisory-only recovery**：`request_recovery` 只给出恢复可用性说明，不执行 handoff / resume。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Contract | `src/watchdog/contracts/session_spine/enums.py`, `models.py`, `versioning.py` | 冻结对象、枚举、版本字段 |
| L2 Projection | `src/watchdog/services/session_spine/facts.py`, `projection.py` | raw task / approval / stuck signal -> stable read model |
| L2 Action | `src/watchdog/services/session_spine/actions.py`, `src/watchdog/storage/action_receipts.py` | `WatchdogAction` 执行、`WatchdogActionResult` 生成、幂等收据 |
| Stable API Surface | `src/watchdog/api/session_spine_queries.py`, `session_spine_actions.py`, `src/watchdog/main.py` | 暴露 stable query / action surface |
| L3 Adapter | `src/watchdog/services/adapters/feishu/intents.py`, `reply_model.py`, `adapter.py` | Feishu intent/reply 映射 |
| Legacy 保持不动为主 | `src/watchdog/api/progress.py`, `supervision.py`, `approvals_proxy.py`, `recover_watchdog.py`, `events_proxy.py` | 继续存在，但不承担 stable contract 角色 |

## 依赖顺序

1. **先冻结 contract 包**
   - 没有这一层，后续 projection / adapter 都会继续漂。
   - 先把 `SessionProjection`、`TaskProgressView`、`FactRecord`、`WatchdogAction`、`WatchdogActionResult`、`ReplyModel` 和版本字段钉死。
2. **再做 L2 projection**
   - 把现有 raw task / approval / stuck analyzer 统一投影成稳定读模型。
   - 这一层要先把 `thread_id / native_thread_id` 与 `FactRecord` 跑通。
3. **再做 L2 action runner + receipt store**
   - 先有统一动作执行与幂等收据，才能安全暴露 canonical action route。
4. **再接 Stable API Surface**
   - 先接 canonical `POST /watchdog/actions`，再补 alias route。
   - 所有 read/write 路由都只返回 stable contract，不直接透 raw envelope shape。
5. **最后接 L3 Feishu adapter**
   - adapter 只消费 stable API / service。
   - `why_stuck`、`explain_blocker` 与 `request_recovery` 的最终 reply 由 adapter 产出。

## 分阶段计划

### Phase 1：冻结中立 contract 包

交付内容：

- 定义 `contract_version` 与 `schema_version`
- 定义 `SessionProjection`
- 定义 `TaskProgressView`
- 定义 `FactRecord`
- 定义 `ApprovalProjection`
- 定义 `WatchdogAction`
- 定义 `WatchdogActionResult`
- 定义 `ReplyModel`
- 冻结 `reply_code`、`action_code`、`action_status`、`effect`、`session_state`、`activity_phase`、`attention_state`

完成条件：

- contract 对象不含 `feishu` 渠道命名
- `thread_id / native_thread_id` 语义被正式区分
- `ReplyModel.reply_code` 不再缺席

回滚点：

- 如果 contract 命名或字段仍未稳定，禁止继续写 projection / API / adapter

### Phase 2：建立 L2 稳定投影层

交付内容：

- raw task -> `SessionProjection`
- raw task -> `TaskProgressView`
- raw approval -> `ApprovalProjection`
- supervision / stuck / link state -> `FactRecord[]`
- `why_stuck` 与 `explain_blocker` 读取事实的规则

关键实现原则：

- `FactRecord` 是解释真值，不在 adapter 临时拼接
- `TaskProgressView` 承载可解释信号，不回退成“只有 summary 的 DTO”
- `request_recovery` 所需事实由 L2 生成，不调用真实恢复动作

风险点：

- 当前 raw 数据里 `thread_id` 与 native thread 可能混用
- 部分 blocker 需要从 pending approval / link error / stuck analyzer 组合推导

### Phase 3：建立 canonical action 模型与幂等收据

交付内容：

- `WatchdogAction` 执行入口
- `WatchdogActionResult` 统一结果模型
- 最小 action receipt store
- `continue_session` 绑定现有 `evaluate -> steer`
- `request_recovery` 输出 advisory-only 结果
- `approve_approval` / `reject_approval` 封装现有 Codex runtime service decision 路径

关键实现原则：

- canonical action route 先于 alias route
- 收据键至少基于 `(action_code, project_id, approval_id, idempotency_key)`
- duplicate request 不产生重复 side effect

回滚点：

- 如果幂等收据模型不稳定，不能开放 alias route

### Phase 4：暴露 Stable API Surface

交付内容：

- `GET /api/v1/watchdog/sessions/{project_id}`
- `GET /api/v1/watchdog/sessions/{project_id}/progress`
- `GET /api/v1/watchdog/sessions/{project_id}/pending-approvals`
- `POST /api/v1/watchdog/actions`
- 需要时补充 continue / request-recovery / approve / reject alias route

关键实现原则：

- read 接口 `data` 返回 `ReplyModel`
- write 接口 `data` 返回 `WatchdogActionResult`
- alias route 统一转内部 canonical action handler

风险点：

- 当前仓库已有 raw / legacy API，命名非常接近
- 若 main.py 同时注册 raw + stable route，需要明确 tags 与 OpenAPI 标注，避免误导集成方
- stable route 接入不得破坏现有 progress / evaluate / approvals / recover / events 的注册与基础行为

### Phase 5：接入 L3 Feishu adapter spine

交付内容：

- intent registry
- reply builder
- adapter 主入口
- `why_stuck` / `explain_blocker` / `request_recovery` 的最终 adapter 行为

关键实现原则：

- adapter 不得直连 Codex runtime service
- adapter 不得访问 raw route 或 raw store
- adapter 不得混入飞书 / 渠道 runtime

### Phase 6：文档、OpenAPI 与验收收口

交付内容：

- `docs/openapi/watchdog.json` 新增 stable contract surface
- `README.md` 与 `docs/getting-started.zh-CN.md` 区分 stable vs raw/legacy
- tasks / spec / OpenAPI 口径一致

关键实现原则：

- canonical action route 必须写明
- alias route 必须明确标注为 wrapper
- `request_recovery` advisory-only 必须写明

## 测试计划

### 契约测试

- 验证所有 contract 对象包含 `contract_version` / `schema_version`
- 验证 `ReplyModel.reply_code`、`WatchdogActionResult.action_status`、`effect` 枚举域
- 验证 `thread_id / native_thread_id` 字段存在且语义不混淆

### 投影层测试

- 验证 raw task / approval / link error -> `SessionProjection` / `TaskProgressView` / `FactRecord`
- 验证 `why_stuck` 与 `explain_blocker` 所依赖的事实集稳定
- 验证 `request_recovery` 只构造恢复可用性说明，不触发 side effect

### API / 动作测试

- 验证 `POST /api/v1/watchdog/actions` 为 canonical write surface
- 验证 alias route 与 canonical route 返回同构结果
- 验证同一 `idempotency_key` 重放不会重复执行

### Adapter 测试

- 验证冻结 intent 集完整支持
- 验证 `reply_code` 正确区分 `stuck_explanation`、`blocker_explanation`、`recovery_availability`
- 验证未知 intent 返回 `unsupported_intent`
- 验证 `why_stuck` 与 `explain_blocker` 基于 `FactRecord` 与 stable read model 构造，不新增 raw route 旁路

### 最小集成测试

- `continue_session` 成功 / 阻塞 / 链路错误
- `request_recovery` 可恢复 / 不可恢复 / 链路错误
- `approve_approval` / `reject_approval`
- legacy `progress / evaluate / approvals / recover / events` 接口注册与基础行为非回归

## 主要风险与应对

### 风险 1：继续把渠道语义写进 Watchdog 内核

应对：

- contract 包禁止使用 `feishu` 命名
- adapter 单独放在 `services/adapters/feishu/`

### 风险 2：动作面再次碎成多条 URL 语义

应对：

- 先实现 `POST /watchdog/actions`
- alias route 仅作为薄包装

### 风险 3：`request_recovery` 再次越界到真实恢复执行

应对：

- contract 上冻结 `effect=advisory_only`
- 测试明确断言“不会调用 handoff / resume”

### 风险 4：幂等设计缺席导致审批与 continue 重试脆弱

应对：

- 增加 `action_receipts` 最小存储
- 在 API 与 adapter 两层都验证 idempotency key 行为

## 验收口径

只有当以下条件同时满足，010 才允许冻结开工：

1. 中立 contract 包、L2 投影层、L3 adapter spine 的模块落点已经写清。
2. `request_recovery`、`why_stuck`、`explain_blocker` 已明确留在 010 范围内。
3. canonical write surface 明确是 `WatchdogAction -> WatchdogActionResult`。
4. `FactRecord`、`TaskProgressView`、`ReplyModel.reply_code`、`thread_id / native_thread_id`、版本字段与幂等语义都已写入文档。
5. tasks 的文件落点与上述边界一致，而不是继续指向 `src/watchdog/services/feishu/*`。
