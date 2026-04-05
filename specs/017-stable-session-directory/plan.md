---
related_doc:
  - "openclaw-codex-watchdog-prd.md"
  - "docs/architecture/openclaw-codex-watchdog-g0-and-v010-design.md"
  - "specs/017-stable-session-directory/spec.md"
---

# 实施计划：017-stable-session-directory

## 目标

在不改写现有单 session stable read surface、不破坏 A-Control-Agent raw `/api/v1/tasks` 的前提下，补齐一个面向跨项目的 stable session directory，使 OpenClaw 能先发现可监管 session，再跳转到单会话读取、解释或动作面。

## 架构摘要

- **Directory, not raw passthrough**：017 新增独立 stable directory route，不把 stable 语义塞回 A-Control-Agent raw `/api/v1/tasks`。
- **Reuse SessionProjection**：继续复用 `SessionProjection` 作为唯一 session DTO；017 只补全局发现入口与对应 `reply_code` / `ReplyModel.sessions`。
- **Shared aggregation path**：目录数据来自 `list_tasks()` 与 pending approvals 聚合；单 session 和目录共享同一 projection 逻辑，避免一套 session 语义出现两份来源。
- **Read-only increment**：017 只做稳定目录读取，不引入新的动作或运行时控制。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Neutral Contract | `src/watchdog/contracts/session_spine/enums.py`, `src/watchdog/contracts/session_spine/models.py`, `src/watchdog/contracts/session_spine/versioning.py` | 冻结 `session_directory` reply code、`ReplyModel.sessions` 字段与 017 schema version |
| L2 Session Directory | `src/watchdog/services/session_spine/service.py`, `src/watchdog/services/session_spine/projection.py`, `src/watchdog/services/session_spine/replies.py` | 加载 raw task list 与 pending approvals，并构建共享 `SessionProjection[]` / stable directory reply |
| Stable API Surface | `src/watchdog/api/session_spine_queries.py` | 暴露 `GET /api/v1/watchdog/sessions`，与单 session 路由共存 |
| L3 Adapter | `src/watchdog/services/adapters/openclaw/intents.py`, `src/watchdog/services/adapters/openclaw/adapter.py`, `src/watchdog/services/adapters/openclaw/reply_model.py` | 新增 `list_sessions` intent，并复用同一 stable directory builder |
| 验证与文档 | `tests/test_watchdog_session_spine_contracts.py`, `tests/test_watchdog_session_spine_api.py`, `tests/test_watchdog_openclaw_adapter.py`, `tests/integration/test_openclaw_integration_spine.py`, `tests/test_a_control_agent.py`, `README.md`, `docs/getting-started.zh-CN.md`, `docs/openapi/watchdog.json`, `.ai-sdlc/project/config/project-state.yaml` | 锁定 contract、stable directory route、adapter、integration 与 raw tasks 非回归 |

## 依赖顺序

1. **先冻结 contract delta**
   - 先明确 `ReplyCode.SESSION_DIRECTORY`、`ReplyModel.sessions` 与 017 schema version，避免 API / adapter 提前写死未冻结字段。
2. **再建立共享 session directory builder**
   - 先让“跨项目 raw tasks + pending approvals -> stable SessionProjection[]”有单一来源，再接 API 与 adapter。
3. **再接 stable API 与 adapter**
   - HTTP 与 OpenClaw adapter 同时复用共享 builder，避免目录与单 session 语义再次分叉。
4. **最后补 legacy 非回归、文档与状态**
   - 确保新增 stable directory 不会误伤 A-Control-Agent raw `/api/v1/tasks`，并同步对外文档。

## 分阶段计划

### Phase 1：冻结 017 stable session directory contract

交付内容：

- `specs/017-stable-session-directory/*`
- `ReplyCode.SESSION_DIRECTORY`
- `ReplyModel.sessions: list[SessionProjection]`
- `SESSION_SPINE_SCHEMA_VERSION = 2026-04-05.017`

关键原则：

- `contract_version` 保持 `watchdog-session-spine/v1alpha1`
- 不新增新的 session DTO
- 不给目录读取引入分页/搜索/排序

### Phase 2：建立共享 session directory aggregation 与 reply builder

交付内容：

- L2 读取全局 raw task list
- 聚合 pending approvals
- 构建稳定 `SessionProjection[]`
- `ReplyModel(reply_code=session_directory)` builder

关键原则：

- 目录与单 session 共享 `SessionProjection` 判定逻辑
- 不拼 raw `/api/v1/tasks` envelope
- `pending_approval_count` 与 `available_intents` 口径一致

### Phase 3：接入 stable directory route 与 adapter intent

交付内容：

- `GET /api/v1/watchdog/sessions`
- adapter `list_sessions`

关键原则：

- route 与 adapter 都只依赖共享 builder
- 单 session 路由行为保持不变
- 017 不新增 write action

### Phase 4：非回归、文档与项目状态收口

交付内容：

- stable directory 的 contract / API / adapter / integration 测试
- raw `/api/v1/tasks` 非回归
- README / getting-started / OpenAPI 更新
- `.ai-sdlc` 推进到下一个 work item

关键原则：

- 文档明确 stable vs raw 的角色分工
- legacy A 侧 raw task list 继续存在但不承担 stable contract 角色

## 回滚锚点

- **Phase 1 完成后**：contract 已冻结，但还未影响运行时。
- **Phase 2 完成后**：共享 builder 已可单独验证，即便 API / adapter 尚未接入也不会影响现有路径。
- **Phase 3 完成后**：stable directory 已可被 HTTP 与 OpenClaw 消费；legacy 非回归与文档可后补。

## 测试计划

### Contract 测试

- `ReplyCode.SESSION_DIRECTORY` 已存在
- `ReplyModel.sessions` 已存在且默认空列表
- session spine `schema_version` 已推进到 `2026-04-05.017`

### Stable Directory API 测试

- `GET /api/v1/watchdog/sessions` 返回 `ReplyModel(reply_code=session_directory)`
- 返回 `sessions` 中每项都是稳定 `SessionProjection`
- `pending_approval_count`、`thread_id`、`native_thread_id` 与 project 对齐
- control-link error 继续返回稳定错误 envelope

### Adapter 测试

- `list_sessions` 返回与 HTTP route 同源的 `ReplyModel`
- adapter 在 `list_sessions` 下不要求 `project_id`
- adapter 不直连 raw `/api/v1/tasks` 以外的 ad-hoc 目录逻辑

### 最小集成测试

- API 与 adapter 对同一组 raw tasks / approvals 返回相同的 `reply_code`
- API 与 adapter 对同一项目返回一致的 `project_id` / `thread_id` / `pending_approval_count`

### Legacy 非回归测试

- A-Control-Agent raw `/api/v1/tasks` 仍返回既有 raw task list 结构
- 新增 stable directory route 不影响旧路径注册或行为

## 主要风险与应对

### 风险 1：目录与单 session 的 projection 逻辑分叉

应对：

- 017 强制复用 `SessionProjection`
- 测试同时锁定目录和单 session 关键字段一致

### 风险 2：为了做目录而引入新 DTO 或 raw passthrough

应对：

- contract 测试锁定 `ReplyModel.sessions`
- API / adapter 只返回 `SessionProjection[]`

### 风险 3：adapter 为了支持 `list_sessions` 自己再写一套聚合逻辑

应对：

- adapter 只复用共享 directory builder
- integration 测试锁定 HTTP 与 adapter 输出一致

## 验收口径

只有当以下条件同时满足，017 才算达标：

1. 存在独立 stable route `GET /api/v1/watchdog/sessions`。
2. 返回体是稳定 `ReplyModel(reply_code=session_directory)`，其 `sessions` 项为 `SessionProjection[]`。
3. OpenClaw adapter 已支持 `list_sessions`，且与 HTTP route 复用同一共享 builder。
4. session spine `schema_version` 已推进到 `2026-04-05.017`。
5. A-Control-Agent raw `/api/v1/tasks` 已有显式非回归验证。
