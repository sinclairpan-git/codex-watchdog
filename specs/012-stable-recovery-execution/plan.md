---
related_doc:
  - "codex-watchdog-prd.md"
  - "docs/architecture/codex-watchdog-g0-and-v010-design.md"
  - "specs/012-stable-recovery-execution/spec.md"
---

# 实施计划：012-stable-recovery-execution

## 目标

在不破坏 `010` advisory-only recovery 语义、不触碰 `011` stable event scope 的前提下，交付一个 **可稳定调用、可幂等重试、与 legacy recover 并存** 的真实恢复执行动作，让上层通过 canonical `WatchdogAction -> WatchdogActionResult` 执行最小 handoff / optional resume 闭环。

## 架构摘要

- **Contract-first**：先在 `session_spine` contract 内新增 `execute_recovery` 所需的 action / reply / effect 枚举，并推进 schema version。
- **Execution Orchestration 分离**：把真实恢复编排封装成单独服务，让 stable action 与 legacy recover route 复用同一执行内核，而不是复制 HTTP 调用分支。
- **Canonical vs Legacy 分离**：`POST /api/v1/watchdog/actions` 是 stable 主面；legacy `/watchdog/tasks/{project_id}/recover` 继续存在，但只做兼容包装。
- **Adapter 只消费 stable result**：Feishu adapter 只依赖 `WatchdogActionResult` 与 `ReplyModel.reply_code`，不直接处理 legacy raw recover payload。

## 模块边界与文件落点

| 层 | 文件落点 | 责任 |
|---|---|---|
| Contract | `src/watchdog/contracts/session_spine/enums.py`, `models.py`, `versioning.py` | 扩展 `ActionCode`、`ReplyCode`、`Effect`，推进 session spine schema version |
| L2 Recovery Execution | `src/watchdog/services/session_spine/recovery.py`, `src/watchdog/services/a_client/client.py` | 封装 task 读取、handoff、optional resume、稳定结果映射 |
| L2 Action | `src/watchdog/services/session_spine/actions.py` | 把 `execute_recovery` 接入 canonical `WatchdogAction` 执行流与幂等收据 |
| Stable API Surface | `src/watchdog/api/session_spine_actions.py`, `src/watchdog/main.py` | 暴露 canonical/alias stable action route |
| Legacy 兼容 | `src/watchdog/api/recover_watchdog.py` | 复用 recovery execution 内核，保持旧 route 非回归 |
| L3 Adapter | `src/watchdog/services/adapters/feishu/intents.py`, `adapter.py`, `reply_model.py` | 新增 `execute_recovery` intent，并稳定映射 `ReplyModel` |
| 验证与文档 | `tests/test_watchdog_action_idempotency.py`, `tests/test_watchdog_recovery_execution.py`, `tests/test_watchdog_session_spine_api.py`, `tests/test_watchdog_feishu_adapter.py`, `tests/integration/test_stable_recovery_execution.py`, `README.md`, `docs/getting-started.zh-CN.md`, `docs/openapi/watchdog.json` | 锁定稳定行为、非回归与接入文档 |

## 依赖顺序

1. **先冻结 contract 与版本语义**
   - 没有新增 `ActionCode` / `ReplyCode` / `Effect`，后续实现只会退回 ad-hoc message 拼装。
   - 先把 schema version 变更明确下来，避免“加了新动作但 version 不动”的漂移。
2. **再做 recovery execution 内核**
   - 把 handoff / optional resume / noop 判定放进单一服务。
   - 先稳定执行语义，再接 stable route 与 legacy route。
3. **再接 canonical action 与 alias route**
   - `execute_recovery` 进入 `execute_watchdog_action()`，继续复用幂等收据。
   - alias route 只映射 action body，不重复执行业务逻辑。
4. **最后补 adapter、文档与非回归**
   - adapter 只看 stable result。
   - docs/OpenAPI 同步强调 `request_recovery` 与 `execute_recovery` 的语义分离。

## 分阶段计划

### Phase 1：冻结 012 stable recovery contract

交付内容：

- `ActionCode.EXECUTE_RECOVERY`
- `ReplyCode.RECOVERY_EXECUTION_RESULT`
- `Effect.HANDOFF_TRIGGERED`
- `Effect.HANDOFF_AND_RESUME`
- session spine `schema_version` 推进到 `2026-04-05.012`

关键原则：

- `contract_version` 继续保持 `watchdog-session-spine/v1alpha1`
- `request_recovery` 现有枚举和值不变
- 新动作与旧 advisory 动作语义并存，而不是替换

风险点：

- 若只新增 message 而不新增 `reply_code/effect`，上层仍要靠字符串分支
- 若 schema version 不推进，版本语义会再次失真

### Phase 2：建立 L2 recovery execution 内核

交付内容：

- 读取 task envelope 并判断 `context_pressure`
- critical 时执行 handoff
- 配置开启时执行 optional resume
- 将执行结果映射成稳定内部 outcome

关键原则：

- stable 结果不暴露 legacy raw payload 结构
- handoff 成功是主结果；resume 失败只能降级表达，不能抹掉 handoff 成功
- legacy route 与 stable action 复用同一内核

风险点：

- 若 stable/legacy 分别实现，会再次出现行为漂移
- 若 resume 失败直接抛错，会让幂等与后续人工恢复变脆弱

### Phase 3：接入 canonical action、alias route 与 legacy wrapper

交付内容：

- `POST /api/v1/watchdog/actions` 支持 `execute_recovery`
- `POST /api/v1/watchdog/sessions/{project_id}/actions/execute-recovery`
- legacy `/watchdog/tasks/{project_id}/recover` 改为复用内核并保持行为兼容

关键原则：

- canonical action 仍是主入口
- alias route 仅做 body 映射
- legacy route 输出保持原字段：`action=noop|handoff_triggered|handoff_and_resume`

### Phase 4：接入 Feishu adapter 与文档

交付内容：

- adapter 新增 `execute_recovery` intent
- `ReplyModel(reply_code=recovery_execution_result)`
- README / getting-started / OpenAPI 更新

关键原则：

- adapter 不直连 Codex runtime service recovery endpoints
- docs 明确 `request_recovery` 只是 advisory，`execute_recovery` 才是真实执行

### Phase 5：测试与收口

交付内容：

- 契约测试
- recovery execution 单元测试
- stable API / adapter 测试
- 最小集成测试
- legacy recover 非回归

## 测试计划

### 契约测试

- 验证 `ActionCode`、`ReplyCode`、`Effect` 新增值
- 验证 session spine `schema_version` 推进
- 验证 `request_recovery` 既有 advisory-only 契约未被改写

### Recovery Execution 测试

- `context_pressure != critical` 返回稳定 noop，且不调用 handoff / resume
- `critical` 时调用 handoff，返回 `effect=handoff_triggered`
- `recover_auto_resume=true` 时调用 handoff 后继续 resume，返回 `effect=handoff_and_resume`
- resume 失败时仍保留 handoff 成功结果与稳定 message
- 相同幂等键重试不重复 side effect

### API 测试

- canonical route 接受 `action_code=execute_recovery`
- alias route 与 canonical route 返回同一 `WatchdogActionResult`
- legacy `/watchdog/tasks/{project_id}/recover` 输出字段不回归

### Adapter 测试

- `execute_recovery` intent 映射到 stable action
- adapter 返回 `ReplyModel(reply_code=recovery_execution_result)`
- `request_recovery` 仍返回 `ReplyCode.recovery_availability`

### 最小集成测试

- fake A client 走通 `critical -> handoff`
- fake A client 走通 `critical -> handoff_and_resume`
- stable action 与 legacy recover route 并存

## 主要风险与应对

### 风险 1：真实恢复执行再次挤回 legacy path-only 设计

应对：

- 新增 action code 与 alias route，但把 canonical route 写成唯一主面
- API 测试同时覆盖 canonical 和 alias

### 风险 2：resume 失败语义不稳定

应对：

- 先定义稳定 `effect` 与 message 降级规则
- 测试锁定 “handoff 成功优先、resume 失败降级表达” 的行为

### 风险 3：010 advisory-only recovery 被误改

应对：

- 保留并复测 `request_recovery`
- 文档明确两个动作的分工，不复用同一个 action code

## 验收口径

只有当以下条件同时满足，012 才算达标：

1. `execute_recovery` 已作为新的稳定 action code 接入 canonical `WatchdogAction -> WatchdogActionResult`。
2. `request_recovery` 仍保持 advisory-only。
3. stable action 与 legacy recover route 共用同一执行内核，但输出各自契约。
4. Feishu adapter 已支持 `execute_recovery`，且返回稳定 `ReplyModel(reply_code=recovery_execution_result)`。
5. session spine schema version、OpenAPI、README、getting-started 与测试都已同步到 012。
