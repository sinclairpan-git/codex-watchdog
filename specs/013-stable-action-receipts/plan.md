---
related_doc:
  - "openclaw-codex-watchdog-prd.md"
  - "docs/architecture/openclaw-codex-watchdog-g0-and-v010-design.md"
  - "specs/013-stable-action-receipts/spec.md"
---

# 实施计划：013-stable-action-receipts

## 目标

在不扩张 `011` event scope、不改写 `012` action semantics 的前提下，交付一个 **可稳定查询、零副作用、复用既有幂等收据键模型** 的 action receipt read surface，让上层能读取既有 `WatchdogActionResult`，而不是通过重复提交动作来确认状态。

## 架构摘要

- **Contract-first**：先在 `session_spine` contract 内冻结 receipt query object、reply code 与 reply payload 扩展，再推进 schema version。
- **Lookup-only**：receipt 查询只读 `ActionReceiptStore`，不访问 A-Control-Agent，不重放 side effect，不把 query 面做成执行器。
- **Canonical vs Alias 分离**：`GET /api/v1/watchdog/action-receipts` 是 stable 主面；session 路径 alias 只做人类友好的 query wrapper。
- **Adapter 只消费 stable receipt reply**：OpenClaw adapter 只依赖 `ActionReceiptQuery -> ReplyModel`，不读取 receipt 存储文件，也不拼 transport-only 结果。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Contract | `src/watchdog/contracts/session_spine/enums.py`, `models.py`, `versioning.py` | 新增 receipt query object、reply code、ReplyModel payload 字段，并推进 schema version |
| Storage / Lookup | `src/watchdog/storage/action_receipts.py`, `src/watchdog/services/session_spine/receipts.py` | 封装稳定 receipt key lookup 与 receipt reply 构造 |
| Stable API Surface | `src/watchdog/api/session_spine_queries.py` | 暴露 canonical / alias stable receipt query route |
| L3 Adapter | `src/watchdog/services/adapters/openclaw/intents.py`, `adapter.py`, `reply_model.py` | 新增 `get_action_receipt` intent，并映射稳定 receipt reply |
| 验证与文档 | `tests/test_watchdog_session_spine_contracts.py`, `tests/test_watchdog_action_receipts.py`, `tests/test_watchdog_session_spine_api.py`, `tests/test_watchdog_openclaw_adapter.py`, `tests/integration/test_openclaw_integration_spine.py`, `README.md`, `docs/getting-started.zh-CN.md`, `docs/openapi/watchdog.json` | 锁定 contract、lookup、API、adapter 与集成行为 |

## 依赖顺序

1. **先冻结 contract 与 schema version**
   - 没有 `ActionReceiptQuery` / `ReplyCode.action_receipt`，后续实现会退回 ad-hoc query 参数与 message 判断。
2. **再建立 receipt lookup 内核**
   - 先把 key 计算与 stable reply 统一起来，避免 API 与 adapter 各自拼 key。
3. **再接 stable API surface**
   - canonical query route 作为主面；alias route 只映射 path/query，不重复 lookup 逻辑。
4. **最后接 adapter 与文档**
   - adapter 复用同一 stable lookup 服务。
   - docs/OpenAPI 明确“receipt query 是只读稳定面，不会重新执行动作”。

## 分阶段计划

### Phase 1：冻结 013 stable receipt contract

交付内容：

- `ActionReceiptQuery`
- `ReplyCode.ACTION_RECEIPT`
- `ReplyCode.ACTION_RECEIPT_NOT_FOUND`
- `ReplyModel.action_result`
- session spine `schema_version` 推进到 `2026-04-05.013`

关键原则：

- `contract_version` 保持不变
- `WatchdogActionResult` 继续作为 receipt 的核心稳定对象
- 通过新 reply code 区分 “查询到了 receipt” 与 “receipt 不存在”

### Phase 2：建立 L2 receipt lookup 内核

交付内容：

- receipt key 的统一 lookup 帮助函数
- `ActionReceiptStore` 的 query-side 访问入口
- stable `ReplyModel` 构造逻辑

关键原则：

- 只读本地 receipt 存储
- 不访问 A-Control-Agent
- 不因为 receipt 缺失而执行动作

### Phase 3：接入 canonical / alias stable API

交付内容：

- `GET /api/v1/watchdog/action-receipts`
- `GET /api/v1/watchdog/sessions/{project_id}/action-receipts/{action_code}/{idempotency_key}`

关键原则：

- canonical route 是主契约
- alias route 只是可读性包装
- 两条路由对同一 query 返回相同 `ReplyModel`

### Phase 4：接入 OpenClaw adapter 与文档

交付内容：

- adapter 新增 `get_action_receipt` intent
- README / getting-started / OpenAPI 更新 receipt query surface

关键原则：

- adapter 不直读 `action_receipts.json`
- docs 明确 receipt query 与 re-execute action 的边界

### Phase 5：测试与收口

交付内容：

- contract 测试
- receipt lookup 测试
- stable API / adapter 测试
- 最小集成测试
- 010-012 行为非回归

## 测试计划

### 契约测试

- 验证 `ActionReceiptQuery`、`ReplyCode.ACTION_RECEIPT`、`ReplyCode.ACTION_RECEIPT_NOT_FOUND`
- 验证 `ReplyModel` 可稳定承载 `action_result`
- 验证 session spine `schema_version` 推进

### Lookup 测试

- 通过已存在 receipt key 查询，返回稳定 `action_receipt`
- 查询不存在 receipt，返回稳定 `action_receipt_not_found`
- approval receipt 查询继续复用 `(action_code, project_id, approval_id, idempotency_key)` 组合键

### API 测试

- canonical route 返回 receipt reply
- alias route 与 canonical route 返回相同 payload
- receipt 缺失时返回稳定 `ReplyModel`，不访问 A 侧

### Adapter 测试

- `get_action_receipt` intent 可读取既有 receipt
- 缺少必要 query 参数时，adapter 返回稳定不可用 reply
- adapter 不重新执行 `continue_session` / `execute_recovery`

### 最小集成测试

- 先执行 stable action，再通过 receipt query 读取相同结果
- `execute_recovery` 的 receipt 可被稳定查询
- 查询 receipt 不会新增 side effect

## 主要风险与应对

### 风险 1：把 receipt 查询做成“重复执行动作”

应对：

- lookup 服务只接 `ActionReceiptStore`
- API / adapter 测试锁定“不访问 A-Control-Agent”

### 风险 2：API 与 adapter 各自拼 receipt key 导致漂移

应对：

- 统一 key 计算入口
- approval receipt 查询用测试锁住 `approval_id` 参与 key 计算

### 风险 3：receipt 缺失被退回 transport-only 404

应对：

- 通过新增 `ReplyCode.action_receipt_not_found` 冻结稳定语义
- route 与 adapter 都返回同一稳定 reply model

## 验收口径

只有当以下条件同时满足，013 才算达标：

1. 存在 canonical stable receipt query route，且查询键与既有幂等设计一致。
2. receipt 命中与未命中都通过稳定 `ReplyModel.reply_code` 表达。
3. receipt 查询不会访问 A-Control-Agent，也不会重新执行动作。
4. OpenClaw adapter 已支持 `get_action_receipt`，且不直读本地 receipt 文件。
5. session spine schema version、OpenAPI、README、getting-started 与测试都已同步到 013。
