---
related_doc:
  - "openclaw-codex-watchdog-prd.md"
  - "docs/architecture/openclaw-codex-watchdog-g0-and-v010-design.md"
  - "specs/014-stable-supervision-evaluation/spec.md"
---

# 实施计划：014-stable-supervision-evaluation

## 目标

在不扩张常驻监管、不重做 stuck 规则、不破坏 010-013 既有 stable surface 的前提下，交付一个 **可版本化、可幂等、可被 receipt 查询复用** 的 stable supervision evaluation seam，把 legacy `POST /watchdog/tasks/{project_id}/evaluate` 收编到 canonical `WatchdogAction -> WatchdogActionResult` 体系内。

## 架构摘要

- **Contract-first**：先冻结 `SupervisionEvaluation`、`SupervisionReasonCode`、`ActionCode.evaluate_supervision` 与 `ReplyCode.supervision_evaluation`，再推进实现。
- **Canonical action-first**：稳定主面仍是 `POST /api/v1/watchdog/actions`；evaluation 不是新开平行写接口，而是新的 canonical action。
- **Stable inner kernel**：L2 负责把 `evaluate_stuck(...)`、repo activity 信号、thread 身份与 steer side effect 统一收束成 `SupervisionEvaluation + WatchdogActionResult`；legacy route 只做 compatibility wrapper。
- **Receipt-compatible**：014 继续复用 013 的 receipt/key 模型，使 `evaluate_supervision` 结果可以被既有 action receipt surface 查询。
- **Adapter 不旁路 legacy**：L3 OpenClaw adapter 只消费稳定 action 语义，不直连 `supervision.py` legacy route。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Contract | `src/watchdog/contracts/session_spine/enums.py`, `src/watchdog/contracts/session_spine/models.py`, `src/watchdog/contracts/session_spine/versioning.py` | 新增 action/reply/reason 枚举、`SupervisionEvaluation`、`WatchdogActionResult.supervision_evaluation`，并推进 schema version |
| L2 Evaluation Kernel | `src/watchdog/services/session_spine/supervision.py`, `src/watchdog/services/session_spine/actions.py`, `src/watchdog/services/status_analyzer/stuck.py` | 统一生成稳定 supervision evaluation，并执行业务允许的最小 steer side effect |
| Stable API Surface | `src/watchdog/api/session_spine_actions.py`, `src/watchdog/api/supervision.py` | 接入 canonical action、human-friendly alias，以及 legacy compatibility shell |
| L3 Adapter | `src/watchdog/services/adapters/openclaw/intents.py`, `src/watchdog/services/adapters/openclaw/adapter.py`, `src/watchdog/services/adapters/openclaw/reply_model.py` | 新增 `evaluate_supervision` intent，并映射稳定 reply |
| 验证与文档 | `tests/test_watchdog_session_spine_contracts.py`, `tests/test_watchdog_supervision_evaluation.py`, `tests/test_watchdog_action_idempotency.py`, `tests/test_watchdog_session_spine_api.py`, `tests/test_watchdog_openclaw_adapter.py`, `tests/test_watchdog_action_receipts.py`, `README.md`, `docs/getting-started.zh-CN.md`, `docs/openapi/watchdog.json` | 锁定 contract、内核、API、adapter、receipt 与 legacy 兼容边界 |

## 依赖顺序

1. **先冻结 contract 与 schema version**
   - 如果没有 `SupervisionEvaluation` 与稳定 reason code，后续实现会退回 `evaluation` 原始 dict。
2. **再建立 L2 supervision evaluation 内核**
   - 先把 `evaluate_stuck`、repo activity 抑制和 steer 发起统一到一个稳定内核，避免 canonical / alias / legacy 三处重复编排。
3. **再接 canonical action、alias route 与 legacy wrapper**
   - canonical action 是主面；alias route 只是可读性封装；legacy route 只保持兼容 transport。
4. **最后接 adapter、receipt 非回归与文档**
   - adapter 直接复用 stable action 语义；
   - receipt 查询可读取 `evaluate_supervision` 结果；
   - 文档明确 stable vs legacy 的边界。

## 分阶段计划

### Phase 1：冻结 014 supervision contract

交付内容：

- `ActionCode.EVALUATE_SUPERVISION`
- `ReplyCode.SUPERVISION_EVALUATION`
- `SupervisionReasonCode`
- `SupervisionEvaluation`
- `WatchdogActionResult.supervision_evaluation`
- session spine `schema_version` 推进到 `2026-04-05.014`

关键原则：

- `contract_version` 保持 `watchdog-session-spine/v1alpha1`
- 不引入第二套 route-level DTO 作为主契约
- 评估对象必须包含 `thread_id / native_thread_id` 与稳定时间字段

### Phase 2：建立 L2 supervision evaluation 内核

交付内容：

- 一个可复用的 supervision evaluation builder / executor
- 对 `evaluate_stuck(...)` 结果的稳定 reason code 映射
- `should_steer -> steer_sent/effect` 的稳定结果构造

关键原则：

- 继续复用既有 stuck 规则与 repo activity 信号
- 不新增 threshold override 或后台调度
- 相同幂等键不会重复发起 steer

### Phase 3：接入 canonical action、alias 与 legacy wrapper

交付内容：

- canonical `POST /api/v1/watchdog/actions` 支持 `action_code=evaluate_supervision`
- alias `POST /api/v1/watchdog/sessions/{project_id}/actions/evaluate-supervision`
- legacy `POST /api/v1/watchdog/tasks/{project_id}/evaluate` 内部复用稳定 evaluation 内核

关键原则：

- canonical route 返回稳定 `WatchdogActionResult`
- alias route 只包装 canonical action，不重复内核
- legacy route 维持基础 envelope 兼容，不承担 stable contract 角色

### Phase 4：接入 OpenClaw adapter 与文档

交付内容：

- adapter 新增 `evaluate_supervision` intent
- README / getting-started / OpenAPI 同步 stable evaluation surface

关键原则：

- adapter 不直连 legacy route
- 文档明确 `continue_session` 仍是“推进会话”，`evaluate_supervision` 则是“单次监管评估”

### Phase 5：测试与收口

交付内容：

- contract 测试
- evaluation kernel 测试
- stable API / adapter 测试
- receipt / idempotency 非回归
- legacy evaluate 基础兼容测试

## 回滚锚点

- **Phase 1 完成后**：即便后续实现暂停，contract 与 schema version 仍可作为 014 的冻结边界单独评审。
- **Phase 2 完成后**：L2 内核可先被 legacy route 复用，不要求 API / adapter 同步一次性切完。
- **Phase 3 完成后**：若 adapter 尚未接入，HTTP stable surface 已可独立验证。
- **Phase 4 完成后**：若文档先行合并，adapter 与 README/OpenAPI 仍可作为完整稳定入口使用。

## 测试计划

### 契约测试

- 验证 `ActionCode.EVALUATE_SUPERVISION`
- 验证 `ReplyCode.SUPERVISION_EVALUATION`
- 验证 `SupervisionReasonCode` 与 `SupervisionEvaluation` 字段集
- 验证 `WatchdogActionResult` 可稳定承载 `supervision_evaluation`
- 验证 session spine `schema_version` 推进

### Evaluation Kernel 测试

- `filesystem_activity_recent` 返回 `effect=noop` 且 `steer_sent=false`
- `stuck_soft` 返回 `effect=steer_posted` 且 `steer_sent=true`
- 缺失 `last_progress_at` 时返回稳定 `reason_code=no_last_progress_at`
- 幂等重试不会重复调用 `post_steer`

### API 测试

- canonical action route 接受 `evaluate_supervision`
- alias route 与 canonical route 对同一 action 返回相同语义 payload
- legacy `POST /watchdog/tasks/{project_id}/evaluate` 继续可调用，且基础 envelope 兼容
- error path 继续映射到稳定 action error 语义

### Adapter 测试

- `evaluate_supervision` intent 返回 `ReplyModel(reply_code=supervision_evaluation)`
- adapter 不直连 legacy route
- adapter 重试同一幂等键不会二次触发 steer

### Receipt / 集成测试

- `evaluate_supervision` 执行后可通过 013 receipt surface 查询到相同结果
- HTTP canonical route、adapter 与 receipt lookup 三者对同一 action result 一致
- `continue_session`、`execute_recovery`、legacy `evaluate` 行为不回归

## 主要风险与应对

### 风险 1：再次退回“路径级 evaluate API”

应对：

- 把 `evaluate_supervision` 冻结为 `ActionCode`
- 明确 alias / legacy 都只是 wrapper
- API 测试锁定 canonical 与 alias 一致

### 风险 2：supervision 规则与既有 `evaluate_stuck` 漂移

应对：

- L2 内核直接复用 `evaluate_stuck(...)`
- 不开放 threshold override
- 用测试锁定 `stuck_soft / filesystem_activity_recent / no_last_progress_at / within_threshold`

### 风险 3：幂等重试再次发起 steer

应对：

- 继续复用 013 之前已冻结的 receipt store
- `evaluate_supervision` 纳入同一 receipt key 语义
- 在 idempotency 测试里显式断言 `post_steer` 只调用一次

### 风险 4：adapter 偷走 legacy route

应对：

- adapter 只通过 stable action 服务层调用
- tasks 与测试显式禁止 adapter 直连 `/watchdog/tasks/{project_id}/evaluate`

## 验收口径

只有当以下条件同时满足，014 才算达标：

1. `evaluate_supervision` 已成为 canonical stable action，而不是新的路径级主契约。
2. `SupervisionEvaluation` 已冻结为版本化稳定对象，且字段集足够表达当前 supervision 结论。
3. 相同幂等键不会重复发起 steer，且结果可被 013 receipt surface 查询。
4. OpenClaw adapter 已支持 `evaluate_supervision`，并继续只消费 stable contract。
5. legacy `POST /watchdog/tasks/{project_id}/evaluate` 仍存在且基础兼容，但文档明确其不再承担 stable contract 角色。
6. README、getting-started、OpenAPI 与测试口径都已同步到 014。
