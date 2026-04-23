---
related_doc:
  - "codex-watchdog-prd.md"
  - "docs/architecture/codex-watchdog-g0-and-v010-design.md"
  - "specs/022-stable-session-facts/spec.md"
---

# 实施计划：022-stable-session-facts

## 目标

把 `FactRecord` 从“稳定读模型中的附带字段”提升为一个独立的 stable read surface，让 Feishu 与其他上层调用方可以直接读取版本化 facts truth source，同时保持 explanation layer 与现有 session/progress route 不变。

## 架构摘要

- **Contract-first**：022 只扩 reply kind/code 与 route，不新增新的 facts DTO。
- **Truth-source reuse**：facts route、adapter intent 与 explanation 继续共享同一份 `SessionReadBundle + FactRecord` 构建链路。
- **Truth vs explanation split**：`facts` route 暴露事实真值；`why_stuck` / `explain_blocker` 继续负责解释表达。
- **Adapter symmetry**：Feishu adapter 的 `list_session_facts` 必须进入主 `handle_intent -> ReplyModel` 闭环。
- **Schema bump scope**：只推进 session spine reply schema 到 `2026-04-05.022`；事件 schema version 保持 `2026-04-05.011`。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Contract | `src/watchdog/contracts/session_spine/enums.py`, `src/watchdog/contracts/session_spine/versioning.py`, `tests/test_watchdog_session_spine_contracts.py` | 新增 `ReplyKind.FACTS`、`ReplyCode.SESSION_FACTS`，推进 session spine schema version |
| L2 Reply Builder | `src/watchdog/services/session_spine/replies.py` | 新增 stable facts reply builder，输入 `SessionReadBundle`，输出 `ReplyModel(facts=...)` |
| Stable API Surface | `src/watchdog/api/session_spine_queries.py` | 暴露 `GET /api/v1/watchdog/sessions/{project_id}/facts`，复用既有 session read bundle |
| L3 Adapter | `src/watchdog/services/adapters/feishu/intents.py`, `src/watchdog/services/adapters/feishu/reply_model.py`, `src/watchdog/services/adapters/feishu/adapter.py` | 把 `list_session_facts` 纳入 `handle_intent -> ReplyModel`，并复用同一 facts reply builder |
| 验证与文档 | `tests/test_watchdog_session_spine_api.py`, `tests/test_watchdog_feishu_adapter.py`, `tests/integration/test_feishu_integration_spine.py`, `tests/test_watchdog_session_spine_contracts.py`, `README.md`, `docs/getting-started.zh-CN.md`, `docs/openapi/watchdog.json`, `.ai-sdlc/project/config/project-state.yaml` | 锁定 contract、route、adapter、integration、015 explanation 非回归与对外口径 |

## 依赖顺序

1. **先冻结 022 contract 与文档**
   - 定稿 route、reply kind/code、schema bump 与 explanation 边界。
2. **再补失败测试**
   - 先锁住 schema version、facts route、adapter intent 与 explanation 非回归。
3. **再实现 reply builder、API route 与 adapter wiring**
   - 只复用 `build_session_read_bundle(...)` 与既有 `FactRecord[]`。
4. **最后更新对外文档、OpenAPI 与项目状态**
   - 把 facts truth source vs explanation layer 的边界写入 README / getting-started / OpenAPI，并推进 `.ai-sdlc`。

## 分阶段计划

### Phase 1：冻结 stable facts contract

交付内容：

- `specs/022-stable-session-facts/*`
- `ReplyKind.FACTS`
- `ReplyCode.SESSION_FACTS`
- `SESSION_SPINE_SCHEMA_VERSION=2026-04-05.022`

关键原则：

- 不新增 `ReplyModel` 字段
- `facts[]` 继续复用既有 `FactRecord`
- explanation route 不改语义

### Phase 2：先补测试，再实现 reply builder

交付内容：

- contract failing tests
- facts route failing tests
- adapter / integration failing tests
- `build_session_facts_reply(...)`

关键原则：

- builder 只接收既有 `SessionReadBundle`
- message 保持最小、可预测，例如 `N fact(s)`
- 不在 builder 中重新读 raw 数据

### Phase 3：接入 stable API route 与 Feishu intent

交付内容：

- `GET /api/v1/watchdog/sessions/{project_id}/facts`
- `list_session_facts` intent

关键原则：

- API route 只负责 transport
- adapter 与 HTTP route 共用同一 builder
- explanation 与 session/progress route 保持不变

### Phase 4：文档、OpenAPI、state 与 explanation 非回归收口

交付内容：

- README / getting-started / OpenAPI
- `.ai-sdlc/project/config/project-state.yaml`
- explanation regression verification

关键原则：

- 文档明确 facts truth source vs explanation layer
- 不把 022 扩成 facts history / filter 产品

## 回滚锚点

- **Phase 1 完成后**：022 scope、route 与 reply contract 可先冻结，不影响现有实现。
- **Phase 2 完成后**：facts semantics 已被测试锁住，即使 route / adapter 尚未接入也不会漂移。
- **Phase 3 完成后**：HTTP 与 adapter 已打通，可独立验证；文档与状态可随后补齐。

## 测试计划

### 契约测试

- 验证 `SESSION_SPINE_SCHEMA_VERSION` 推进到 `2026-04-05.022`
- 验证 `ReplyKind.FACTS` 与 `ReplyCode.SESSION_FACTS` 已冻结
- 验证 `ReplyModel.facts` 继续承载稳定 `FactRecord[]`

### Stable API 测试

- `GET /api/v1/watchdog/sessions/{project_id}/facts` 返回 `ReplyModel(facts=...)`
- route 返回的 `facts[]` 使用稳定 `FactRecord`
- route 失败时继续走统一 control-link error 语义

### Adapter / Integration 测试

- Feishu adapter 支持 `list_session_facts`
- `handle_intent("list_session_facts")` 返回与 HTTP route 同源的 stable reply
- facts 列表与 session/progress/explanation 共用同一 truth source

### 015 Explanation 非回归测试

- `GET /api/v1/watchdog/sessions/{project_id}/stuck-explanation` 继续返回 `reply_code=stuck_explanation`
- `GET /api/v1/watchdog/sessions/{project_id}/blocker-explanation` 继续返回 `reply_code=blocker_explanation`

## 主要风险与应对

### 风险 1：为了做 facts route，再复制一份 raw 事实组装逻辑

应对：

- 统一复用 `build_session_read_bundle(...)`
- 测试显式锁住 facts route、session route 与 explanation route 的 facts 同源

### 风险 2：facts route 与 explanation route 角色混淆

应对：

- `reply_kind=facts` 与 `reply_code=session_facts` 单独冻结
- README / OpenAPI 明确 truth source vs explanation layer 的区别

### 风险 3：为了暴露 facts 而推进了不必要的 DTO 字段变更

应对：

- 不新增新的 `ReplyModel` 字段
- 仅 bump session spine schema version，保持 event schema 不变

## 验收口径

只有当以下条件同时满足，022 才算达标：

1. 存在稳定 reply `ReplyKind.FACTS / ReplyCode.SESSION_FACTS`。
2. 存在 `GET /api/v1/watchdog/sessions/{project_id}/facts`。
3. Feishu adapter 已支持 `handle_intent("list_session_facts") -> ReplyModel`。
4. `facts[]` 与既有 explanation / session / progress 读模型同源。
5. `SESSION_SPINE_SCHEMA_VERSION` 已推进到 `2026-04-05.022`，且 `SESSION_EVENTS_SCHEMA_VERSION` 未改变。
6. 015 explanation route 已有显式非回归验证。
7. README、getting-started、OpenAPI 与 `.ai-sdlc` 已同步到 022。
