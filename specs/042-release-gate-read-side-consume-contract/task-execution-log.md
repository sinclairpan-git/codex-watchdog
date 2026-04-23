# 执行日志：042-release-gate-read-side-consume-contract

## 2026-04-14

### Phase 1：formal docs / spec freeze

- 基于 `WI-041` 完成态，探索新的 canonical work item 候选。
- 本地收敛出的三个候选方向：
  - 方案 A：shared typed read-side consume contract；
  - 方案 B：shared release-gate report fixture/test factory；
  - 方案 C：继续扩 refresh/rebuild 命令与 operator workflow。
- 对抗复核结果：
  - Hermes Agent 专家：推荐方案 A；认为 B 只是测试配套，不是下一 canonical work item；C 有 P1 级 scope drift 风险；
  - Anthropic Manager 专家：推荐方案 A；要求范围进一步收窄为 `shared helper / typed model + ops/runtime consumer`，并强调 malformed / partial evidence fail closed。
- 冻结后的 042 边界：
  - 只做 `release_gate_verdict + release_gate_evidence_bundle` 的 shared typed read contract；
  - 首批 consumer 只覆盖 `src/watchdog/api/ops.py` 与 resident runtime 现有 read-side 路径；
  - 不新增 policy、schema、persistence、manifest、archive metadata、query facade 或新的 read platform。
- 已创建 `spec.md / plan.md / tasks.md / task-execution-log.md` 与 `.ai-sdlc/work-items/042-*` 基线。
- freeze 复核结果：
  - Hermes Agent 专家：无 blocking/P1；
  - Anthropic Manager 专家：无 blocking/P1。
- 当前下一执行入口固定为 `T422`：先写失败测试锁定 shared read-side consume contract，再进入实现。

### Phase 2：red tests 锁定 read-side consume contract

- 在 `tests/test_watchdog_ops.py` 新增红测，锁定：
  - `watchdog.services.brain.release_gate_read_contract` 模块与 `ReleaseGateDecisionReadSnapshot / read_release_gate_decision_evidence(...)` surface 必须存在；
  - `ops.py` 在 partial / malformed `release_gate_evidence_bundle` 下必须整包 fail closed，不能透传半截 blocker metadata。
- 在 `tests/test_watchdog_session_spine_runtime.py` 新增红测，锁定：
  - resident runtime 不能把缺字段的 pass verdict 当成 formal runtime gate；
  - formal report pass verdict 在缺 bundle 或 partial bundle 时必须 fail closed。
- 初次 red 结果：
  - `uv run pytest -q tests/test_watchdog_ops.py -k 'release_gate_read_contract_module_exports_typed_surface or drops_partial_release_gate_bundle_metadata'` -> `2 failed`
  - `uv run pytest -q tests/test_watchdog_session_spine_runtime.py -k 'release_gate_read_contract_runtime_module_exports_typed_surface or rejects_incomplete_pass_release_gate_verdict'` -> `2 failed`
- 红测确认的真实缺口：
  - `release_gate_read_contract` 模块尚不存在；
  - `ops.py` 与 resident runtime 仍直接消费裸 dict，并接受不完整 verdict/bundle。

### Phase 3：实现 shared read-side helper，并修掉两轮 P1

- 新增 `src/watchdog/services/brain/release_gate_read_contract.py`：
  - `ReleaseGateDecisionReadSnapshot`
  - `read_release_gate_decision_evidence(...)`
  - 统一 typed validation `release_gate_verdict` 与 `release_gate_evidence_bundle`，结构不合法时返回 `None`，由 consumer fail closed。
- 修改 `src/watchdog/api/ops.py`：
  - `_release_gate_blockers(...)` 改为只通过 shared helper 读取 blocker metadata；
  - partial / malformed bundle 不再透传半截 metadata。
- 修改 `src/watchdog/services/session_spine/orchestrator.py`：
  - `_decision_allows_auto_execute(...)` 与 `_decision_has_runtime_gate(...)` 改为通过 typed helper 读取 release gate evidence；
  - formal pass verdict 只有两种情况允许继续：
    - `report:resident_default` 非正式默认态；
    - 正式 report verdict + 可解析的完整 bundle；
  - `_record_decision_lifecycle(...)`、`_command_terminal_payload(...)`、`_command_terminal_metrics_summary(...)` 与 policy evaluate 前的 verdict 读取也已统一走 shared helper。
- 第一轮代码复核：
  - Hermes Agent 专家：无 blocking/P1；
  - Anthropic Manager 专家：指出 P1，formal pass verdict + malformed/partial bundle 仍可能通过 auto-execute。
- 第一轮修复：
  - 为 shared read snapshot 增加 raw payload presence；
  - resident runtime 在 bundle 出现但结构非法时 fail closed；
  - 新增 `test_resident_orchestrator_rejects_pass_verdict_with_partial_bundle`。
- 第二轮代码复核：
  - Hermes Agent 专家：指出 P1，formal report pass verdict 在 bundle 完全缺失时仍可能放行。
- 第二轮修复：
  - resident runtime 只在 `report:resident_default` 默认态允许无 bundle；
  - 对于任何非默认正式 report，缺 bundle / partial bundle / malformed bundle 一律 fail closed；
  - 新增 `test_resident_orchestrator_rejects_pass_verdict_without_bundle`；
  - future-worker patched evidence 与 `tests/e2e/test_watchdog_future_worker_execution.py` 一并补成完整 formal bundle。
- 代码提交：`be64da2 feat: formalize release gate read-side consume contract`。
- 最终代码复核：
  - Hermes Agent 专家：无 blocking/P1；
  - Anthropic Manager 专家：无 blocking/P1。

### Phase 4：完成 handoff 与 formal close-out

- 已同步 `tasks.md`、执行日志、总实施计划 Task 13 复选框与 `.ai-sdlc/work-items/042-*` 元数据。
- `WI-042` 现在是 release gate decision evidence read-side consume contract 的正式完成态。
- 后续任何新的 consumer 都只能复用 `src/watchdog/services/brain/release_gate_read_contract.py`，不得再手工剥取 `release_gate_verdict` 或 `release_gate_evidence_bundle`。
