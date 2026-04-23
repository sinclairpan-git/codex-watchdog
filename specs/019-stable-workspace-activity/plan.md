---
related_doc:
  - "codex-watchdog-prd.md"
  - "docs/architecture/codex-watchdog-g0-and-v010-design.md"
  - "specs/019-stable-workspace-activity/spec.md"
---

# 实施计划：019-stable-workspace-activity

## 目标

补齐 stable workspace activity surface，使 Feishu 与其他上层调用方可以基于 session spine contract 读取版本化工作区活动摘要，而不是继续绑定 Codex runtime service raw `/workspace-activity`。

## 架构摘要

- **New stable read object**：019 新增 `WorkspaceActivityView`，由 `ReplyModel.workspace_activity` 承载，不把 repo activity 继续塞在 raw `dict` 或 supervision 内部字段里。
- **L2 builder first**：先在 A-client 收 raw summary，再在 L2 共享 builder 内把 session 元信息和 activity 数据合成稳定 view；API 与 adapter 只消费该 builder。
- **Stable route 明确**：`GET /api/v1/watchdog/sessions/{project_id}/workspace-activity` 是唯一 canonical stable read route；A raw `/api/v1/tasks/{project_id}/workspace-activity` 继续存在但不是 stable contract。
- **Schema bump required**：019 新增 stable object、reply code 与 `ReplyModel` 字段，因此 session spine `schema_version` 推进到 `2026-04-05.019`。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Contract | `src/watchdog/contracts/session_spine/enums.py`, `src/watchdog/contracts/session_spine/models.py`, `src/watchdog/contracts/session_spine/versioning.py` | 新增 `WorkspaceActivityView`、`ReplyCode.WORKSPACE_ACTIVITY_VIEW`、`ReplyModel.workspace_activity` 与 019 schema version |
| A Client | `src/watchdog/services/a_client/client.py` | 新增最小 `/api/v1/tasks/{project_id}/workspace-activity` 读取方法 |
| L2 Projection | `src/watchdog/services/session_spine/service.py`, `src/watchdog/services/session_spine/projection.py`, `src/watchdog/services/session_spine/replies.py` | 构建共享 workspace-activity bundle、稳定 view 与 reply builder |
| Stable API Surface | `src/watchdog/api/session_spine_queries.py` | 暴露 canonical stable workspace activity route |
| L3 Adapter | `src/watchdog/services/adapters/feishu/intents.py`, `src/watchdog/services/adapters/feishu/adapter.py`, `src/watchdog/services/adapters/feishu/reply_model.py` | 新增 `get_workspace_activity` intent，并复用稳定 reply builder |
| 验证与文档 | `tests/test_watchdog_session_spine_contracts.py`, `tests/test_watchdog_session_spine_api.py`, `tests/test_watchdog_feishu_adapter.py`, `tests/integration/test_feishu_integration_spine.py`, `tests/test_a_control_agent.py`, `README.md`, `docs/getting-started.zh-CN.md`, `docs/openapi/watchdog.json`, `.ai-sdlc/project/config/project-state.yaml` | 锁定 contract、stable route、adapter、raw 非回归与外部口径 |

## 依赖顺序

1. **先冻结 019 contract**
   - 明确 `WorkspaceActivityView` 字段、reply code、schema bump 与 stable/raw 边界。
2. **再补 A-client 与 L2 builder**
   - 先把 raw `/workspace-activity` 收进 A-client，再建立共享 workspace-activity bundle 和 reply builder。
3. **再接 stable API route 与 adapter intent**
   - HTTP 与 Feishu 复用同一 builder，不自行拼装 repo activity。
4. **最后补测试、文档与项目状态**
   - 锁住 raw 非回归，对外文档改到 stable route，并推进 `.ai-sdlc`。

## 分阶段计划

### Phase 1：冻结 019 workspace activity contract

交付内容：

- `specs/019-stable-workspace-activity/*`
- 019 scope、对象字段、reply code 与 schema version 定稿

关键原则：

- 只补 read surface
- 不扩事件、不扩 supervisor
- stable object 必须带 session 身份字段

### Phase 2：建立共享 workspace activity builder

交付内容：

- `AControlAgentClient.get_workspace_activity_envelope(...)`
- `WorkspaceActivityView`
- 共享 workspace-activity read bundle 与 reply builder

关键原则：

- API 与 adapter 不碰 raw body
- `recent_minutes` 参数在 builder 内统一传递
- control-link / not-found 错误继续复用稳定 envelope

### Phase 3：接入 stable API route 与 Feishu intent

交付内容：

- `GET /api/v1/watchdog/sessions/{project_id}/workspace-activity`
- `get_workspace_activity` intent

关键原则：

- route 返回 `ReplyModel(reply_code=workspace_activity_view)`
- adapter 与 HTTP route 的 message / view 字段保持同源

### Phase 4：测试、文档与状态收口

交付内容：

- contract/API/adapter/integration/raw 非回归测试
- README / getting-started / OpenAPI
- `.ai-sdlc` 推进到下一个 work item

关键原则：

- 文档明确 stable vs raw 边界
- 非回归覆盖 raw `/workspace-activity` 基础行为

## 回滚锚点

- **Phase 1 完成后**：019 scope 与 schema bump 可先冻结，不影响现有实现。
- **Phase 2 完成后**：共享 builder 已可被单元测试覆盖，即使 API / adapter 尚未接入。
- **Phase 3 完成后**：stable route 与 adapter 已可独立验证，文档与状态可随后补齐。

## 测试计划

### 契约测试

- 验证 019 将 `SESSION_SPINE_SCHEMA_VERSION` 推进到 `2026-04-05.019`
- 验证 `ReplyModel` 挂载 `workspace_activity`
- 验证 `WorkspaceActivityView` 字段与 `ReplyCode.WORKSPACE_ACTIVITY_VIEW`

### Stable API 测试

- `GET /api/v1/watchdog/sessions/{project_id}/workspace-activity` 返回稳定 `ReplyModel`
- `recent_minutes` 正常透传到 A-client / L2 builder
- project miss / upstream 异常继续返回稳定 envelope

### Adapter 测试

- `get_workspace_activity` 需要 `project_id`
- `arguments.recent_minutes` 可覆盖默认窗口
- adapter 与 HTTP route 对同一输入产出同源结果

### Integration / Legacy 非回归测试

- Feishu adapter 可消费 `workspace_activity_view`
- raw `/api/v1/tasks/{project_id}/workspace-activity` 注册与基础行为不回归

## 主要风险与应对

### 风险 1：实现者直接透传 raw activity dict

应对：

- 在 contract 层冻结 `WorkspaceActivityView`
- 测试显式断言 `ReplyModel.workspace_activity` 是稳定对象，不是匿名字典字段

### 风险 2：session 元信息与 activity summary 分别在 API / adapter 拼接，导致语义漂移

应对：

- 先补共享 L2 builder
- 测试锁定 HTTP 与 adapter 对同一输入的关键字段一致

### 风险 3：019 顺手被扩成实时事件或写操作

应对：

- spec、plan、tasks 都明确 019 只补 read surface
- 不新增 action code、receipt 或 event schema

## 验收口径

只有当以下条件同时满足，019 才算达标：

1. 存在独立 stable route `GET /api/v1/watchdog/sessions/{project_id}/workspace-activity`。
2. 返回体使用 `ReplyModel(reply_code=workspace_activity_view)`，并携带稳定 `WorkspaceActivityView`。
3. Feishu adapter 已支持 `get_workspace_activity`，且与 HTTP route 复用同一共享 builder。
4. session spine `schema_version` 已推进到 `2026-04-05.019`。
5. raw `/api/v1/tasks/{project_id}/workspace-activity` 已有显式非回归验证。
6. README、getting-started、OpenAPI 与 `.ai-sdlc` 已同步到 019。
