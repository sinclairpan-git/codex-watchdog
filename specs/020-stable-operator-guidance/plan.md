---
related_doc:
  - "codex-watchdog-prd.md"
  - "docs/architecture/codex-watchdog-g0-and-v010-design.md"
  - "specs/020-stable-operator-guidance/spec.md"
---

# 实施计划：020-stable-operator-guidance

## 目标

把 raw `POST /api/v1/tasks/{project_id}/steer` 收敛为稳定、版本化、可幂等的 operator-guidance write surface，让 Feishu 与其他上层调用方通过 session spine canonical action 提交最小人工指导消息。

## 架构摘要

- **Canonical action first**：020 不新增专用写模型，继续以 `WatchdogAction -> WatchdogActionResult` 为唯一 stable write contract，只扩展 `ActionCode.POST_OPERATOR_GUIDANCE`。
- **Alias route is wrapper only**：`POST /api/v1/watchdog/sessions/{project_id}/actions/post-guidance` 只是人类友好的 alias wrapper，内部必须映射回 canonical `POST /api/v1/watchdog/actions` 语义。
- **Executor reuse**：动作执行复用既有 `post_steer(...)`；不新增另一套 Codex runtime service 直连逻辑。
- **Stable vs raw boundary**：stable 面负责版本化 action code、idempotency 与统一结果模型；A raw `/api/v1/tasks/{project_id}/steer` 继续存在，但只做 legacy compatibility。
- **Schema bump required**：020 新增 stable action code，因此 session spine `schema_version` 推进到 `2026-04-05.020`。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Contract | `src/watchdog/contracts/session_spine/enums.py`, `src/watchdog/contracts/session_spine/versioning.py` | 新增 `ActionCode.POST_OPERATOR_GUIDANCE` 并推进 schema version |
| L2 Action | `src/watchdog/services/session_spine/actions.py` | 校验 `arguments.message / reason_code / stuck_level`，复用 `post_steer(...)`，统一产出 `WatchdogActionResult` |
| Stable API Surface | `src/watchdog/api/session_spine_actions.py` | 暴露 alias route，并把 top-level payload 映射回 canonical action arguments |
| L3 Adapter | `src/watchdog/services/adapters/feishu/intents.py`, `src/watchdog/services/adapters/feishu/adapter.py` | 新增 `post_operator_guidance` intent，映射到新 action code |
| 验证与文档 | `tests/test_watchdog_session_spine_contracts.py`, `tests/test_watchdog_action_idempotency.py`, `tests/test_watchdog_session_spine_api.py`, `tests/test_watchdog_feishu_adapter.py`, `tests/integration/test_feishu_integration_spine.py`, `tests/test_m2_steer.py`, `README.md`, `docs/getting-started.zh-CN.md`, `docs/openapi/watchdog.json`, `.ai-sdlc/project/config/project-state.yaml` | 锁定 contract、幂等、alias、adapter、integration、legacy 非回归与对外口径 |

## 依赖顺序

1. **先冻结 020 contract 与文档**
   - 定稿 action code、stable 参数名、alias route 与 raw 边界。
2. **再补失败测试**
   - 先锁定 idempotency、canonical/alias 一致性、adapter intent 与 legacy non-regression。
3. **再实现 action executor 与 API wrapper**
   - 把 operator guidance 收口到同一个 `execute_watchdog_action(...)` 分支。
4. **最后更新对外文档、OpenAPI 与项目状态**
   - 把 stable write surface 写入 README / getting-started / OpenAPI，并推进 `.ai-sdlc`。

## 分阶段计划

### Phase 1：冻结 stable operator-guidance contract

交付内容：

- `specs/020-stable-operator-guidance/*`
- `ActionCode.POST_OPERATOR_GUIDANCE`
- 020 schema version

关键原则：

- 仍然以 `WatchdogAction.arguments` 作为参数承载
- 不新增独立 raw passthrough object
- action code 扩展必须通过 schema bump 明示

### Phase 2：先补测试，再实现 executor

交付内容：

- action/idempotency failing tests
- canonical/alias API failing tests
- adapter/integration failing tests
- `execute_watchdog_action(...)` 的 operator-guidance 分支

关键原则：

- `message` 必须由统一 helper 校验
- `reason_code` 默认 `operator_guidance`
- `stuck_level` 范围与 raw `/steer` 保持一致

### Phase 3：接入 stable API alias 与 Feishu intent

交付内容：

- `/api/v1/watchdog/sessions/{project_id}/actions/post-guidance`
- `post_operator_guidance` intent

关键原则：

- alias route 只做 payload 映射，不私有实现
- adapter、canonical route、alias route 共用同一执行路径

### Phase 4：文档、OpenAPI、state 与 legacy 非回归收口

交付内容：

- README / getting-started / OpenAPI
- `.ai-sdlc/project/config/project-state.yaml`
- raw `/steer` 非回归验证

关键原则：

- 文档明确 stable vs raw 角色边界
- 不把 020 扩成 supervisor/channel runtime 项目

## 回滚锚点

- **Phase 1 完成后**：020 scope 与 contract 可先冻结，不影响现有实现。
- **Phase 2 完成后**：核心 operator-guidance 逻辑已被测试锁住，即使 alias / adapter 尚未接入。
- **Phase 3 完成后**：canonical、alias 与 adapter 已打通，可独立验证；文档与状态可随后补齐。

## 测试计划

### 契约测试

- 验证 `SESSION_SPINE_SCHEMA_VERSION` 推进到 `2026-04-05.020`
- 验证 `ActionCode.POST_OPERATOR_GUIDANCE` 已冻结

### Action / Idempotency 测试

- `post_operator_guidance` 相同 `idempotency_key` 只下发一次 steer
- `message` 缺失或 `stuck_level` 非法时返回稳定错误结果

### Stable API 测试

- canonical route 与 alias route 共享同一稳定结果
- alias route 的 top-level `message / reason_code / stuck_level` 会映射到 canonical arguments
- API 层不为 operator guidance 新开平行执行分支

### Adapter / Integration 测试

- Feishu adapter 支持 `post_operator_guidance`
- adapter、canonical route、alias route 对同一输入产出同源结果

### Legacy 非回归测试

- raw `/api/v1/tasks/{project_id}/steer` 继续工作
- 既有 `continue_session` / `evaluate_supervision` 的 steer 语义不回归

## 主要风险与应对

### 风险 1：alias route 直接调 raw `/steer`，绕过 canonical action

应对：

- 在 API 层只构造 `WatchdogAction`
- 测试显式锁住 canonical/alias 结果一致

### 风险 2：参数校验分散在 API 和 adapter，导致语义漂移

应对：

- 把 `message / reason_code / stuck_level` 校验收进 action 层 helper
- 测试从 executor、API、adapter 三层同时覆盖

### 风险 3：020 顺手改变既有 continue/evaluate 的 steer 行为

应对：

- 只新增 `POST_OPERATOR_GUIDANCE` 分支
- 保留现有 `continue_session` / `evaluate_supervision` 路径和测试

## 验收口径

只有当以下条件同时满足，020 才算达标：

1. 存在稳定动作 `ActionCode.POST_OPERATOR_GUIDANCE`。
2. canonical `POST /api/v1/watchdog/actions` 可执行 `post_operator_guidance`。
3. 存在 alias route `POST /api/v1/watchdog/sessions/{project_id}/actions/post-guidance`，且只是 canonical wrapper。
4. Feishu adapter 已支持 `post_operator_guidance`。
5. session spine `schema_version` 已推进到 `2026-04-05.020`。
6. raw `/api/v1/tasks/{project_id}/steer` 已有显式非回归验证。
7. README、getting-started、OpenAPI 与 `.ai-sdlc` 已同步到 020。
