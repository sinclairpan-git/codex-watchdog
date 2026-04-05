---
related_doc:
  - "openclaw-codex-watchdog-prd.md"
  - "docs/architecture/openclaw-codex-watchdog-g0-and-v010-design.md"
  - "specs/018-stable-native-thread-resolution/spec.md"
---

# 实施计划：018-stable-native-thread-resolution

## 目标

在不新增 contract 对象、不推进 schema version、不回退到 raw `/by-thread` 直连的前提下，补齐一个 stable native-thread resolution surface，使调用方在只持有 `native_thread_id` 时，也能直接获得同源 `SessionProjection` reply。

## 架构摘要

- **Resolution, not new DTO**：018 只是补一个稳定 lookup seam，返回仍然是既有 `ReplyModel(reply_code=session_projection)`。
- **A-client lookup first**：先在 A-client 层补 `/api/v1/tasks/by-thread/{thread_id}` 读取，再在 L2 做稳定投影；API 与 adapter 不直接碰 raw payload。
- **No contract delta**：018 不新增字段、枚举或 reply code，因此 session spine `contract_version` / `schema_version` 保持 017 口径。
- **Canonical route 明确**：`GET /api/v1/watchdog/sessions/by-native-thread/{native_thread_id}` 是新的 stable 主读面；A raw `/api/v1/tasks/by-thread/{thread_id}` 继续存在但不承担 stable contract 角色。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| A Client | `src/watchdog/services/a_client/client.py` | 新增按 native thread 读取 task envelope 的最小 client 方法 |
| L2 Session Projection | `src/watchdog/services/session_spine/service.py`, `src/watchdog/services/session_spine/replies.py` | 构建 `build_session_read_bundle_by_native_thread(...)` 并产出同源 session reply |
| Stable API Surface | `src/watchdog/api/session_spine_queries.py` | 暴露 canonical native-thread resolution route；注意静态路由顺序必须先于 `/sessions/{project_id}` |
| L3 Adapter | `src/watchdog/services/adapters/openclaw/intents.py`, `src/watchdog/services/adapters/openclaw/adapter.py` | 新增 `get_session_by_native_thread` intent，要求 `arguments.native_thread_id` |
| 验证与文档 | `tests/test_watchdog_session_spine_api.py`, `tests/test_watchdog_openclaw_adapter.py`, `tests/integration/test_openclaw_integration_spine.py`, `tests/test_a_control_agent.py`, `README.md`, `docs/getting-started.zh-CN.md`, `docs/openapi/watchdog.json`, `.ai-sdlc/project/config/project-state.yaml` | 锁定 stable route、adapter、raw `/by-thread` 非回归与对外口径 |

## 依赖顺序

1. **先冻结 018 边界**
   - 明确 018 只补 stable native-thread resolution，不新增 contract 字段或平行 DTO。
2. **再补 A-client 与共享 L2 builder**
   - 先把 `/by-thread` 读取收进 A-client，再形成单一 resolution builder，避免 API / adapter 各写一套 lookup。
3. **再接 stable API route 与 adapter intent**
   - HTTP 与 OpenClaw 共用同一 builder，不再绕行 session directory 或 raw body。
4. **最后补 raw `/by-thread` 非回归、文档与状态**
   - 明确 stable vs raw 的角色边界，并推进 `.ai-sdlc`。

## 分阶段计划

### Phase 1：冻结 018 native-thread resolution surface

交付内容：

- `specs/018-stable-native-thread-resolution/*`
- 018 范围声明：仅补 stable lookup route + adapter intent

关键原则：

- 不推进 session spine schema version
- 不新增 `ReplyCode` / `ActionCode`
- 返回体继续是 `ReplyModel(reply_code=session_projection)`

### Phase 2：建立共享 native-thread resolution builder

交付内容：

- `AControlAgentClient` 新增 `/by-thread` 读取方法
- `build_session_read_bundle_by_native_thread(...)`
- 共享 session reply builder 能承载 `intent_code=get_session_by_native_thread`

关键原则：

- API 与 adapter 只调用共享 builder
- 不让 raw `/by-thread` body 穿透到 stable route

### Phase 3：接入 stable API route 与 adapter intent

交付内容：

- `GET /api/v1/watchdog/sessions/by-native-thread/{native_thread_id}`
- adapter `get_session_by_native_thread`

关键原则：

- 静态路由必须先于 `/sessions/{project_id}` 注册
- adapter 读取 `arguments.native_thread_id`
- 错误路径继续复用稳定 error envelope / control-link error reply

### Phase 4：raw 非回归、文档与项目状态收口

交付内容：

- raw `/api/v1/tasks/by-thread/{thread_id}` 非回归
- README / getting-started / OpenAPI 同步 018 stable route
- `.ai-sdlc` 推进到下一个 work item

关键原则：

- 文档明确 018 是 stable lookup seam，不是 raw route 替代品
- 不把 018 扩成 session history 或 thread search

## 回滚锚点

- **Phase 1 完成后**：018 scope 可先冻结，不影响既有实现。
- **Phase 2 完成后**：共享 resolution builder 已可先被单元测试覆盖，即使 route / adapter 尚未接入。
- **Phase 3 完成后**：HTTP 与 adapter 已可独立验证，文档与状态可随后补。

## 测试计划

### 契约 / 非版本推进测试

- 验证 session spine `schema_version` 在 018 中保持 `2026-04-05.017`
- 验证 native-thread resolution 复用 `ReplyModel(reply_code=session_projection)`，不新增 DTO

### Stable API 测试

- `GET /api/v1/watchdog/sessions/by-native-thread/{native_thread_id}` 返回稳定 `ReplyModel`
- route 在 `native_thread_id` 存在时返回正确 `project_id / thread_id / native_thread_id`
- route 在 lookup miss 或 upstream 异常时返回稳定错误 envelope

### Adapter 测试

- `get_session_by_native_thread` 读取 `arguments.native_thread_id`
- adapter 与 HTTP route 对同一输入产出同源 session reply
- `get_session` / `list_sessions` / `list_approval_inbox` 等既有 intent 不回归

### Integration / Legacy 非回归测试

- HTTP stable route 与 adapter 共享同一 resolution 语义
- raw `/api/v1/tasks/by-thread/{thread_id}` 继续存在且基础行为不回归

## 主要风险与应对

### 风险 1：静态路由被 `/sessions/{project_id}` 吞掉

应对：

- 在 `session_spine_queries.py` 中把 `/sessions/by-native-thread/{native_thread_id}` 放在 `/sessions/{project_id}` 之前
- API 测试显式锁定该路径返回 200 而不是被当成 project_id

### 风险 2：API 与 adapter 各写一套 native-thread lookup

应对：

- 先补共享 L2 builder
- 测试锁定 HTTP 与 adapter 对同一 `native_thread_id` 的结果一致

### 风险 3：018 被顺手扩成 thread search / history

应对：

- 规格明确只支持单个精确 `native_thread_id`
- tasks 与文档显式排除 batch / prefix / archive 语义

## 验收口径

只有当以下条件同时满足，018 才算达标：

1. 存在独立 stable route `GET /api/v1/watchdog/sessions/by-native-thread/{native_thread_id}`。
2. 该 route 返回既有 `ReplyModel(reply_code=session_projection)`，不新增平行 DTO。
3. OpenClaw adapter 已支持 `get_session_by_native_thread`，且与 HTTP route 复用同一共享 builder。
4. session spine `schema_version` 保持不变，说明 018 只是 stable lookup surface completion。
5. raw `/api/v1/tasks/by-thread/{thread_id}` 已有显式非回归验证。
6. README、getting-started、OpenAPI 与 `.ai-sdlc` 口径都已同步到 018。
