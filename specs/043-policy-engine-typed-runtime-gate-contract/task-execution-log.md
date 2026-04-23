# 执行日志：043-policy-engine-typed-runtime-gate-contract

## 2026-04-14

### Phase 1：formal docs / spec freeze

- 基于 `WI-042` 完成态，探索下一 canonical work item。
- 本地收敛出的三个候选方向：
  - 方案 A：typed runtime-gate contract for policy engine；
  - 方案 B：shared fixture/test helper 收口 formal release-gate bundle 构造；
  - 方案 C：把 e2e / golden path 的 release-gate 断言改成 typed helper 消费。
- 对抗复核结果：
  - Hermes Agent 专家：推荐方案 A；认为 B 只是测试配套，不是下一 canonical work item；C 有 P1 级 scope drift 风险；
  - Anthropic Manager 专家：推荐方案 A；要求范围进一步收窄为 `policy engine` consume seam，不新增 policy/schema/persistence/testing platform。
- 冻结后的 043 边界：
  - 只做 `policy engine` 对 runtime-gate evidence 的 typed consume contract；
  - 首批实现只覆盖 `src/watchdog/services/policy/engine.py` 与必要的 shared helper 收紧；
  - 不新增 policy 规则、schema、manifest、archive metadata、query facade、fixture platform 或 e2e 改造层。
- 已创建 `spec.md / plan.md / tasks.md / task-execution-log.md` 与 `.ai-sdlc/work-items/043-*` 基线。
- freeze 复核结果：
  - Hermes Agent 专家：无 blocking/P1；
  - Anthropic Manager 专家：无 blocking/P1。
- 当前下一执行入口固定为 `T432`：先写失败测试锁定 typed runtime-gate policy contract，再进入实现。

### Phase 2：red tests 锁定 policy-engine consume seam

- 在 `tests/test_watchdog_policy_engine.py` 新增 shared read contract module surface 红测，锁定 `policy engine` 必须依赖 shared typed runtime-gate contract。
- 新增 formal report pass verdict 缺 bundle 时必须 fail closed 的红测。
- 新增 `report:resident_default` 默认态不要求 formal evidence bundle 的红测，避免把 resident 默认路径误判成 formal report blocker。
- 红测结果：
  - `uv run pytest -q tests/test_watchdog_policy_engine.py` 初次执行失败 2 项，确认当前实现仍有 raw verdict dict consume seam，符合预期。

### Phase 3：实现 typed runtime-gate consume contract

- 在 `src/watchdog/services/brain/release_gate_read_contract.py` 收紧 shared helper：
  - 新增对完整 runtime-gate evidence payload 的 typed 读取；
  - 保留对 legacy raw `ReleaseGateVerdict` dict 的兼容读取，避免已有 call site 立即破坏。
- 在 `src/watchdog/services/policy/engine.py` 完成 consume seam 收口：
  - `_goal_contract_evidence(...)` 改为统一写入 typed verdict/bundle；
  - `_runtime_gate_override(...)` 改为只通过 shared typed snapshot 判断 pass / degraded / missing；
  - formal report `pass` 但缺 bundle 时强制 fail closed；
  - `report:resident_default` 默认态继续允许无 bundle 通行。
- 在 `src/watchdog/services/session_spine/orchestrator.py` 改为把完整 runtime-gate evidence 传给 `policy engine`，避免上游继续手工剥取 raw verdict。
- 在 `tests/test_watchdog_session_spine_runtime.py` 对齐 typed runtime-gate evidence payload，补齐 resident runtime 的正式消费路径。
- 实现批次提交：
  - `45f30c4 feat: formalize policy engine runtime gate contract`

### Phase 4：验证与对抗复核

- 验证结果：
  - `uv run pytest -q tests/test_watchdog_policy_engine.py` -> `11 passed in 0.21s`
  - `uv run pytest -q tests/test_watchdog_policy_engine.py tests/test_watchdog_session_spine_runtime.py tests/test_long_running_autonomy_doc_contracts.py` -> `60 passed in 4.39s`
- 对抗复核结果：
  - Hermes Agent 专家：无 blocking/P1；
  - Anthropic Manager 专家：无 blocking/P1。

### Phase 5：closeout / handoff

- formal docs 基线提交：
  - `12a2fd7 docs: add wi-043 policy engine gate contract plan`
- `WI-043` 现已完成，正式把 `policy engine` 中的 runtime-gate consume seam 收口到 shared typed contract。
- 后续 handoff 约束：
  - 后续任何 policy/runtime-gate consumer 都不得再复制 raw verdict dict 解释逻辑；
  - 如需解释 `release_gate_verdict + release_gate_evidence_bundle`，必须复用 `src/watchdog/services/brain/release_gate_read_contract.py`；
  - 后续 work item 应继续沿 canonical execution 链探索剩余生产 consume seam，而不是回退到测试整理主导。
