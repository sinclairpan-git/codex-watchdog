---
related_doc:
  - "codex-watchdog-prd.md"
  - "docs/architecture/codex-watchdog-g0-and-v010-design.md"
  - "specs/016-stable-approval-inbox/spec.md"
---

# 实施计划：016-stable-approval-inbox

## 目标

在不改写现有 approve / reject stable action、不破坏 legacy approvals proxy 的前提下，补齐一个面向跨项目 pending approvals 的 stable inbox read surface，使 Feishu 能在不知道 `project_id` 的情况下先拿到稳定审批队列，再决定后续跳转或执行动作。

## 架构摘要

- **Stable inbox, not legacy mutation**：016 新增独立 stable inbox route，不把 stable 语义硬塞进现有 raw `/watchdog/approvals` proxy。
- **Reuse existing projection**：继续复用 `ApprovalProjection`，不引入新的审批 DTO；016 只补全局发现入口与对应 `reply_code`。
- **Contract bump required**：由于新增 `reply_code=approval_inbox` 与 adapter intent，session spine `schema_version` 需要推进。
- **Read/write separation preserved**：全局 inbox 只负责发现 pending approvals；approve / reject 仍走既有 stable action surface。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Neutral Contract | `src/watchdog/contracts/session_spine/enums.py`, `src/watchdog/contracts/session_spine/models.py`, `src/watchdog/contracts/session_spine/versioning.py` | 冻结 `approval_inbox` reply code、必要 query model 与 016 schema version |
| L2 Approval Inbox | `src/watchdog/services/session_spine/service.py`, `src/watchdog/services/session_spine/projection.py`, `src/watchdog/services/session_spine/replies.py` | 加载全局 pending approvals、可选按 `project_id` 过滤，并构建稳定 inbox reply |
| Stable API Surface | `src/watchdog/api/session_spine_queries.py` | 暴露 `GET /api/v1/watchdog/approval-inbox`，保持与 legacy `/watchdog/approvals` 分离 |
| L3 Adapter | `src/watchdog/services/adapters/feishu/intents.py`, `src/watchdog/services/adapters/feishu/adapter.py`, `src/watchdog/services/adapters/feishu/reply_model.py` | 新增 `list_approval_inbox` intent，并复用同一 stable inbox builder |
| 验证与文档 | `tests/test_watchdog_session_spine_contracts.py`, `tests/test_watchdog_session_spine_api.py`, `tests/test_watchdog_feishu_adapter.py`, `tests/test_m3_watchdog_approvals.py`, `README.md`, `docs/getting-started.zh-CN.md`, `docs/openapi/watchdog.json`, `.ai-sdlc/project/config/project-state.yaml` | 锁定 contract、stable route、adapter 与 legacy 非回归 |

## 依赖顺序

1. **先冻结 contract delta**
   - 先明确 `ReplyCode.APPROVAL_INBOX` 与 016 schema version，避免 API 和 adapter 先写死字符串。
2. **再建立 L2 approval inbox builder**
   - 先让“全局 pending approvals -> stable reply”有单一来源，再接 route 与 adapter。
3. **再接 stable API 与 adapter**
   - HTTP 与 Feishu adapter 同时复用共享 builder，避免再出现双份 approvals list 逻辑。
4. **最后补 legacy 非回归与文档**
   - 确保 016 新增稳定入口不会误伤 `/watchdog/approvals` raw proxy 或 `/decision` 兼容写面。

## 分阶段计划

### Phase 1：冻结 016 stable approval inbox contract

交付内容：

- `specs/016-stable-approval-inbox/*`
- `ReplyCode.APPROVAL_INBOX`
- `SESSION_SPINE_SCHEMA_VERSION = 2026-04-05.016`

关键原则：

- `contract_version` 保持 `watchdog-session-spine/v1alpha1`
- 不新增新的审批 DTO
- 不给 stable inbox 暴露任意 `status` passthrough

### Phase 2：建立共享 approval inbox reply builder

交付内容：

- L2 读取全局 `pending` approvals
- 可选 `project_id` 过滤
- `ReplyModel(reply_code=approval_inbox)` builder

关键原则：

- 只返回 `ApprovalProjection[]`
- 不拼 raw envelope
- builder 同时可供 HTTP 与 adapter 复用

### Phase 3：接入 stable inbox route 与 adapter intent

交付内容：

- `GET /api/v1/watchdog/approval-inbox`
- adapter `list_approval_inbox`

关键原则：

- route 与 adapter 都只依赖共享 builder
- session 级 `pending-approvals` route 行为保持不变
- approve / reject 继续走既有 stable action

### Phase 4：非回归、文档与状态收口

交付内容：

- raw `/watchdog/approvals` 与 `/decision` 非回归测试
- README / getting-started / OpenAPI 更新
- `.ai-sdlc` 推进到下一个 work item

关键原则：

- 明确区分 global inbox 与 session queue
- 文档说明 legacy approvals 仍存在但不承担 stable contract 角色

## 回滚锚点

- **Phase 1 完成后**：contract 冻结完成，但还未影响运行态。
- **Phase 2 完成后**：共享 builder 已可单独验证，即便 route 尚未接入也不会影响现有接口。
- **Phase 3 完成后**：stable inbox route 与 adapter 已可独立使用；legacy 非回归与文档可后补。

## 测试计划

### Contract 测试

- `ReplyCode.APPROVAL_INBOX` 已存在
- session spine `schema_version` 已推进到 `2026-04-05.016`
- `ApprovalProjection` 仍是 stable inbox 的唯一审批对象

### Stable Inbox API 测试

- `GET /api/v1/watchdog/approval-inbox` 返回 `ReplyModel(reply_code=approval_inbox)`
- 默认只返回 pending approvals
- `?project_id=...` 可收窄到单项目
- control-link error 继续返回稳定错误 envelope

### Adapter 测试

- `list_approval_inbox` 返回与 HTTP 同源的 `ReplyModel`
- adapter 不直连 raw `/watchdog/approvals`
- adapter 现有 `list_pending_approvals` / `approve_approval` / `reject_approval` 不回归

### Legacy 非回归测试

- `/api/v1/watchdog/approvals` 仍返回 raw proxy 语义
- `/api/v1/watchdog/approvals/{approval_id}/decision` 仍返回 raw proxy 语义
- 新增 stable inbox route 不影响旧路径注册

## 主要风险与应对

### 风险 1：把 stable inbox 和 legacy approvals proxy 混成一个路径

应对：

- 016 使用独立 route
- 文档与测试明确区分 stable vs raw

### 风险 2：为了做全局 inbox 再造一套审批 DTO

应对：

- 强制复用 `ApprovalProjection`
- contract 测试锁定无新 DTO

### 风险 3：adapter 绕过 stable surface 自己拉 raw approvals

应对：

- adapter 只复用共享 inbox builder
- 测试锁定 `list_approval_inbox` 与 HTTP 的 reply_code / approvals 一致

## 验收口径

只有当以下条件同时满足，016 才算达标：

1. 存在独立 stable route `GET /api/v1/watchdog/approval-inbox`。
2. 返回体是稳定 `ReplyModel(reply_code=approval_inbox)`，其 `approvals` 项为 `ApprovalProjection[]`。
3. Feishu adapter 已支持 `list_approval_inbox`，且与 HTTP 复用同一 stable inbox builder。
4. session spine `schema_version` 已推进到 `2026-04-05.016`。
5. legacy `/watchdog/approvals` 与 `/decision` 已有显式非回归验证。
