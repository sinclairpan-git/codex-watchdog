# 执行日志：035-brain-decision-boundary-and-release-gate

> 对应规格：`specs/035-brain-decision-boundary-and-release-gate/spec.md`
>
> 对应任务：`specs/035-brain-decision-boundary-and-release-gate/tasks.md`

## 2026-04-13

- 完成 `T351`：已把总实施计划中的 `Task 6` 正式拆为 `WI-035`，并补齐 `plan.md`、`tasks.md`、`task-execution-log.md` 与 `.ai-sdlc/work-items/035-*` 元数据。
- 已确认 035 的实现断点来自当前仓库现状，而不是抽象 spec 复述：
  - `src/watchdog/services/policy/engine.py` 仍直接从 persisted facts 生成 `CanonicalDecisionRecord`；
  - `src/watchdog/services/session_spine/orchestrator.py` 仍直接根据 `decision_result` 进入 approval 或 auto execute；
  - `src/watchdog/services/memory_hub/packets.py` 与 `service.py` 已提供 bounded `packet_inputs`、`quality`、`refs` 与 `expansion_handles` contract，可作为 035 的 decision input 下游依赖；
  - `src/watchdog/services/session_service/service.py` 已具备 canonical event slice/query 与 recovery/memory anomaly writer，可作为 `DecisionTrace` 的 truth anchor。
- 本轮 formal docs 已明确收口：
  - 035 不把 `Brain` 做成新的 prompt/runtime 中枢；
  - `DecisionInputBuilder` 只输出 versioned `decision_packet_input`，不接管最终 prompt/messages/tool schema；
  - release gate 只约束低风险自动决策资格，没有有效 report 时必须退回 `suggest_only`、`require_approval` 或等价人工路径。
- 已完成一轮对抗式文档评审并按意见收紧执行边界：
  - 明确 `brain_intent -> runtime disposition` adapter 必须先冻结，不能直接拿旧 `decision_result` 假装 Brain intent；
  - 明确 Brain 不再被旧 `_select_action_ref()` 的 action-first 入口短路，而是先跑 Brain 再决定是否生成 executable `action_ref`；
  - 明确 `action approval` 与 `report_approved_by` 是两类不同语义，前者决定当前动作是否过 human gate，后者只是 release report 治理元数据；
  - 明确 release gate verdict、degrade reason、report/input hash、approval read ref 必须先写入 canonical Session decision event，再允许 command 创建/执行；
  - 明确 future worker schema 只冻结声明式 trace refs，不允许越权字段。
- 当前下一执行入口固定为 `T352`：先写失败测试锁住 `DecisionIntent`、`DecisionTrace`、provider certification、replay 与 runtime enforced release gate contract，再进入实现。
- 已启动 `T352/T353` 的第一轮 red-green：
  - 新增 `tests/test_watchdog_brain_decision_loop.py`、`tests/test_watchdog_provider_certification.py`、`tests/test_watchdog_decision_replay.py`、`tests/test_watchdog_release_gate.py`、`tests/test_watchdog_release_gate_evidence.py`，先锁 `brain` 模块存在性、DecisionTrace/approval/future-worker schema、provider/runtime drift 字段、release gate verdict 字段与 evidence bundle contract；
  - 初次 red 测试结果为：`uv run pytest -q tests/test_watchdog_brain_decision_loop.py tests/test_watchdog_provider_certification.py tests/test_watchdog_decision_replay.py tests/test_watchdog_release_gate.py tests/test_watchdog_release_gate_evidence.py` -> `12 failed in 0.13s`，失败点全部集中在 `watchdog.services.brain` 模块缺失；
  - 已补齐最小 `src/watchdog/services/brain/` contract 骨架：`models.py`、`decision_input_builder.py`、`service.py`、`validator.py`、`provider_certification.py`、`replay.py`、`release_gate.py`、`release_gate_evidence.py`；
  - 已补上 `src/watchdog/services/policy/decisions.py` 中的 `brain_intent -> runtime disposition` 显式 adapter，与 `CanonicalDecisionRecord.brain_intent / runtime_disposition` 字段，避免 Brain intent 只停留在文档。
- 当前已通过的局部验证：
  - `uv run pytest -q tests/test_watchdog_brain_decision_loop.py tests/test_watchdog_provider_certification.py tests/test_watchdog_decision_replay.py tests/test_watchdog_release_gate.py tests/test_watchdog_release_gate_evidence.py` -> `12 passed in 0.16s`
  - `uv run pytest -q tests/test_watchdog_policy_decisions.py -k 'brain_intent_adapter or carries_brain_intent'` -> `2 passed, 3 deselected in 0.09s`
  - `uv run pytest -q tests/test_watchdog_policy_decisions.py tests/test_watchdog_brain_decision_loop.py tests/test_watchdog_provider_certification.py tests/test_watchdog_decision_replay.py tests/test_watchdog_release_gate.py tests/test_watchdog_release_gate_evidence.py` -> `17 passed in 0.15s`
- 当前判断：
  - `T352` 已完成第一批 contract 红测与最小 green，但还没覆盖 release verdict canonical event、approval freshness 旧 session/旧 snapshot 降级、以及替换旧 action-first 入口；
  - `T353` 已开始落最小 contract skeleton，但还未接入 `policy.engine` / `ResidentOrchestrator` 的真实 runtime wiring。
- 已继续推进第二轮 red-green：
  - 在 `tests/test_watchdog_session_spine_runtime.py` 新增 runtime 红测，锁定 `decision_proposed / decision_validated` 必须携带 `brain_intent`、`validator_verdict` 与 `release_gate_verdict`，且 `SessionService.record_event()` 失败时 orchestrator 必须 fail-closed，不能继续创建 command 或执行；
  - 已在 `src/watchdog/services/session_spine/orchestrator.py` 的 `_record_decision_lifecycle()` 中补齐上述 payload 字段，把 release/validator verdict 真正写进 canonical Session decision events；
  - 在 `tests/test_watchdog_approval_loop.py` 新增 approval freshness 红测，锁定 canonical approval 至少要校验 `session_id / project_id / requested_action / fact_snapshot_version / goal_contract_version / expires_at / status`；
  - 已在 `src/watchdog/services/approvals/service.py` 中给 `CanonicalApprovalRecord` 补入 `goal_contract_version` 与 `expires_at`，并新增 `is_canonical_approval_fresh(...)` helper。
- 当前已通过的新增验证：
  - `uv run pytest -q tests/test_watchdog_session_spine_runtime.py -k 'records_release_gate_and_validator_verdict or fails_closed_when_decision_event_write_fails'` -> `2 passed, 24 deselected in 0.71s`
  - `uv run pytest -q tests/test_watchdog_approval_loop.py -k 'freshness or reuses_same_record or refreshes_pending_record'` -> `4 passed, 15 deselected in 0.81s`
  - `uv run pytest -q tests/test_watchdog_approval_loop.py tests/test_watchdog_policy_decisions.py tests/test_watchdog_brain_decision_loop.py tests/test_watchdog_provider_certification.py tests/test_watchdog_decision_replay.py tests/test_watchdog_release_gate.py tests/test_watchdog_release_gate_evidence.py tests/test_watchdog_session_spine_runtime.py -k 'freshness or reuses_same_record or refreshes_pending_record or brain or release_gate or decision or fails_closed_when_decision_event_write_fails or records_release_gate_and_validator_verdict or carries_brain_intent or brain_intent_adapter'` -> `25 passed, 37 deselected in 0.95s`
- 当前判断更新为：
  - release gate verdict 写回 canonical Session event 与 approval freshness contract 已开始落到真实代码，而不是只停留在 docs；
  - 下一硬边界仍是替换旧 `_select_action_ref()` 的 action-first 入口，让 Brain 不再被 runtime 预选动作短路。
