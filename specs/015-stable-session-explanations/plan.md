---
related_doc:
  - "openclaw-codex-watchdog-prd.md"
  - "docs/architecture/openclaw-codex-watchdog-g0-and-v010-design.md"
  - "specs/015-stable-session-explanations/spec.md"
---

# 实施计划：015-stable-session-explanations

## 目标

在不新增 contract 对象、不扩张动作面、不回退到 raw API 的前提下，补齐 `why_stuck` / `explain_blocker` 的 HTTP stable read surface，并把 explanation 生成逻辑从“adapter 专有实现”收束为 API 与 adapter 共享的稳定 builder。

## 架构摘要

- **Surface completion**：015 不是新能力，而是把 010 已冻结的 explanation 语义补齐到 HTTP stable surface。
- **Shared builder-first**：先抽出 explanation reply builder，再让 API route 与 adapter 共同复用，避免规则漂移。
- **No contract delta**：015 不新增对象、枚举或字段，因此 `contract_version` / `schema_version` 保持不变。
- **Stable-only**：explanation route 只能基于 `SessionReadBundle + FactRecord` 生成，不旁路 legacy `progress / evaluate / approvals / recover / events`。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Shared Reply Builders | `src/watchdog/services/session_spine/replies.py` | 冻结并复用 session/progress/approvals/explanations 的稳定 `ReplyModel` builder |
| Stable API Surface | `src/watchdog/api/session_spine_queries.py` | 暴露 stuck / blocker explanation route，并复用 shared builder |
| L3 Adapter | `src/watchdog/services/adapters/openclaw/adapter.py`, `src/watchdog/services/adapters/openclaw/reply_model.py` | 迁移到 shared explanation builder；不再自持 explanation 过滤逻辑 |
| 验证与文档 | `tests/test_watchdog_session_spine_api.py`, `tests/test_watchdog_openclaw_adapter.py`, `tests/test_watchdog_session_spine_contracts.py`, `README.md`, `docs/getting-started.zh-CN.md`, `docs/openapi/watchdog.json` | 锁定 route、共享 builder、adapter 非回归与文档口径 |

## 依赖顺序

1. **先冻结 015 surface 边界**
   - 明确 015 不做 contract 版本推进，也不新增 DTO。
2. **再抽 shared reply builder**
   - 先把 explanation 生成逻辑变成单一来源，再接 API route，避免实现后再回头对齐。
3. **再接 stable explanation routes**
   - API 直接复用 `build_session_read_bundle(...) + shared builder`，不再写一套 ad-hoc message 逻辑。
4. **最后做 adapter 非回归、文档与 OpenAPI**
   - 确保 HTTP stable surface 与 adapter 口径一致，并把 015 纳入对外说明。

## 分阶段计划

### Phase 1：冻结 015 explanation surface

交付内容：

- `specs/015-stable-session-explanations/*`
- 015 范围声明：仅补 stable read routes + shared builder

关键原则：

- 不推进 session spine schema version
- 不新增 `ReplyCode` / `ActionCode`
- explanation 仍然是 `ReplyModel`

### Phase 2：建立 shared reply builder

交付内容：

- 新增 `src/watchdog/services/session_spine/replies.py`
- explanation builder 从 adapter 侧收拢到共享层

关键原则：

- `why_stuck` 与 `explain_blocker` 继续只依赖 `FactRecord`
- 若顺手把 session/progress/approvals builder 也收拢到共享层，可以做，但不得扩成 unrelated refactor

### Phase 3：接入 stable explanation routes

交付内容：

- `GET /api/v1/watchdog/sessions/{project_id}/stuck-explanation`
- `GET /api/v1/watchdog/sessions/{project_id}/blocker-explanation`

关键原则：

- route `data` 返回稳定 `ReplyModel`
- error path 继续复用 stable read error envelope
- 不增加第二套 query 参数或 intent tunnel

### Phase 4：adapter 非回归、文档与 OpenAPI

交付内容：

- adapter 切到 shared builder
- README / getting-started / OpenAPI 同步 015 stable read surface
- `.ai-sdlc` 推进到下一个 work item

关键原则：

- adapter 语义不变，只改变复用边界
- 文档明确 015 是 HTTP stable surface completion，而非新 contract 版本

## 回滚锚点

- **Phase 1 完成后**：015 scope 可先冻结，不影响既有实现。
- **Phase 2 完成后**：即使 route 尚未接入，adapter 也已拥有单一 explanation builder。
- **Phase 3 完成后**：HTTP stable surface 已可独立使用，文档可随后补。

## 测试计划

### 契约 / 非版本推进测试

- 验证 `ReplyCode.STUCK_EXPLANATION` 与 `ReplyCode.BLOCKER_EXPLANATION` 继续存在
- 验证 session spine `schema_version` 在 015 中保持 `2026-04-05.014`

### Shared Builder / API 测试

- `stuck-explanation` route 返回 `ReplyModel(reply_code=stuck_explanation)`
- `blocker-explanation` route 返回 `ReplyModel(reply_code=blocker_explanation)`
- 两个 route 均返回 `facts`、`session` 与 `progress`
- control-link error 继续走稳定错误 envelope

### Adapter 非回归测试

- adapter `why_stuck` 继续输出 `stuck_explanation`
- adapter `explain_blocker` 继续输出 `blocker_explanation`
- adapter 与 API 对同一输入产出的事实集和 reply code 一致

### Stable Read 非回归测试

- `get_session` / `get_progress` / `pending-approvals` 既有 stable route 行为不回归
- explanation route 的接入不影响 `events` / `actions` / `receipts`

## 主要风险与应对

### 风险 1：API 和 adapter 各写一套 explanation 规则

应对：

- 引入 shared reply builder
- 用测试锁定 API 与 adapter 的 facts / reply_code 一致

### 风险 2：为了补 route 又引入新的 explanation DTO

应对：

- 规格明确复用既有 `ReplyModel`
- 契约测试锁定 `schema_version` 不推进

### 风险 3：route 偷读 legacy/raw 返回体

应对：

- route 只允许依赖 `build_session_read_bundle(...)`
- tasks 和测试显式禁止 raw route 旁路实现

## 验收口径

只有当以下条件同时满足，015 才算达标：

1. HTTP 已存在稳定 `stuck-explanation` 与 `blocker-explanation` read routes。
2. 两个 route 返回已冻结的 `ReplyModel(reply_code=stuck_explanation|blocker_explanation)`，不新增 DTO。
3. API 与 adapter 已复用同一 explanation builder，不再存在双份逻辑。
4. session spine `schema_version` 保持不变，说明 015 只是 stable surface completion。
5. README、getting-started、OpenAPI 与测试口径都已同步到 015。
