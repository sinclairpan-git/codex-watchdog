# 任务分解：035-brain-decision-boundary-and-release-gate

> 对应规格：`specs/035-brain-decision-boundary-and-release-gate/spec.md`
>
> 对应计划：`specs/035-brain-decision-boundary-and-release-gate/plan.md`

## Task 35.1 冻结 035 formal docs 与 Brain / Release Gate 执行边界

- **任务编号**：T351
- **状态**：已完成（2026-04-13）
- **目标**：把总实施计划中的 `Task 6` 正式拆成 canonical execution work item，并把 035 收紧为 Brain 决策层、DecisionTrace、provider certification、只读 replay 与低风险自动决策资格门禁。
- **文件**：
  - `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
  - `specs/035-brain-decision-boundary-and-release-gate/spec.md`
  - `specs/035-brain-decision-boundary-and-release-gate/plan.md`
  - `specs/035-brain-decision-boundary-and-release-gate/tasks.md`
  - `specs/035-brain-decision-boundary-and-release-gate/task-execution-log.md`
  - `.ai-sdlc/work-items/035-brain-decision-boundary-and-release-gate/*`
- **可并行**：否
- **验收标准**：
  1. 已明确 035 只做 `Brain` 决策边界与 release gate，不提前实现 Feishu/control-plane 或 e2e golden path；
  2. 已明确当前实现断点是 `policy.engine` 与 `ResidentOrchestrator` 直接串接，而不是从零起一套新 runtime；
  3. 已明确 035 只消费 030-034 提供的 canonical truth / projection / goal / recovery / memory contracts；
  4. 已明确 035 会先冻结 `brain_intent -> runtime disposition` adapter、替换旧 action-first 入口，再做 runtime wiring。
- **验证**：人工审阅 `spec.md / plan.md / tasks.md / .ai-sdlc` 元数据与总实施计划中的 Task 6 边界一致。
- **完成情况**：
  1. 已补齐 `plan.md`、`tasks.md`、`task-execution-log.md` 与 `.ai-sdlc/work-items/035-*` 元数据；
  2. 已把 035 的执行口径从“补 Brain 闭环”收紧为 `DecisionIntent + DecisionTrace + release-gated runtime consume`；
  3. 已固定下一执行入口为 `T352`，先写失败测试锁定 contract，再进入实现。

## Task 35.2 写失败测试锁定 Brain contract、DecisionTrace、provider certification 与 release gate

- **任务编号**：T352
- **状态**：未开始
- **目标**：用失败测试先锁定 035 的正式输入输出 contract，避免实现回退到“policy 直接 auto execute”或“Brain 直接拼 prompt/动执行”的旧路径。
- **文件**：
  - `tests/test_watchdog_brain_decision_loop.py`
  - `tests/test_watchdog_provider_certification.py`
  - `tests/test_watchdog_decision_replay.py`
  - `tests/test_watchdog_release_gate.py`
  - `tests/test_watchdog_release_gate_evidence.py`
- **可并行**：否
- **验收标准**：
  1. 覆盖 `DecisionInputBuilder` 只生成 versioned `decision_packet_input`，只包含摘要、refs、expansion handles、hashes、provenance、freshness 与 context quality；
  2. 覆盖 `Brain` 只输出 `observe_only / suggest_only / require_approval / propose_execute / propose_recovery / candidate_closure / reject`；
  3. 覆盖 `brain_intent -> runtime disposition` adapter 规则，不允许直接把旧 `decision_result` 伪装成 Brain intent，也不允许未迁移下游时直接替换现有枚举；
  4. 覆盖 `ResidentOrchestrator` 不再以旧 `_select_action_ref()` 作为 Brain 的唯一入口；`observe_only / candidate_closure / propose_recovery` 不会被 action-first 路径短路；
  5. 覆盖 `DecisionTrace` 至少保留 `session_event_range/cursor`、`goal_contract_version`、`policy_ruleset_hash`、`memory_packet_input_ids`、`memory_packet_input_hashes`、`provider/model/prompt/schema`、approval 读取与 degrade reason；
  6. 覆盖 hash/provenance 来源映射：`memory_packet_input_hashes` 来自冻结 packet payload，provider/tool/policy/version hash 来自 harness/runtime config，`memory_provider_adapter_hash` 来自 Memory Hub adapter contract；
  7. 覆盖 `DecisionTrace.approval_read` 精确记录 `approval_event_id/log_seq`、`approval_id`、`status`、`requested_action`、`session_id`、`project_id`、`fact_snapshot_version`、`goal_contract_version`、`expires_at` 与 `decided_by`，并排除 superseded/expired/rejected/旧 session/旧 snapshot；
  8. 覆盖 inference provider certification 与 memory provider adapter certification 分离，且任一输入版本漂移都会使旧资格失效；
  9. 覆盖 `packet_replay` 与 `session_semantic_replay` 都只读，缺输入时返回 `replay_incomplete`；
  10. 覆盖 `candidate_closure` 只能作为候选完成判断，必须经 `Goal Contract + Policy Gate + Session truth` 二次确认；
  11. 覆盖 future worker/sub-agent schema 只允许声明式 trace refs，不允许 command lease、approval mutation、goal patch、completion write 或 provider credentials；
  12. 覆盖 release gate report 缺字段、过期、hash 不一致、approval stale 或 memory conflict 时只能降级为 `suggest_only / require_approval`；
  13. 覆盖 observe-only / session search / memory write mirror 不会被 release gate 误阻断。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_brain_decision_loop.py tests/test_watchdog_provider_certification.py tests/test_watchdog_decision_replay.py tests/test_watchdog_release_gate.py tests/test_watchdog_release_gate_evidence.py`

## Task 35.3 实现最小 Brain contracts、decision input builder 与 validator/certification/replay

- **任务编号**：T353
- **状态**：未开始
- **目标**：交付 Brain 的最小可用决策面与审计面，让 runtime 能消费声明式结果，而不是自由拼接 prompt 与执行。
- **文件**：
  - `src/watchdog/services/brain/__init__.py`
  - `src/watchdog/services/brain/models.py`
  - `src/watchdog/services/brain/decision_input_builder.py`
  - `src/watchdog/services/brain/service.py`
  - `src/watchdog/services/brain/validator.py`
  - `src/watchdog/services/brain/provider_certification.py`
  - `src/watchdog/services/brain/replay.py`
  - `src/watchdog/services/policy/decisions.py`
  - `src/watchdog/services/session_service/models.py`
  - `src/watchdog/services/session_service/service.py`
- **可并行**：否
- **验收标准**：
  1. `Brain` contracts 已定义 `DecisionIntent`、`DecisionTrace`、`DecisionPacketInput`、replay result 与 certification record；
  2. `policy/decisions.py` 已显式承载 `brain_intent -> runtime disposition` adapter，而不是把 mapping 藏在 evidence 或 orchestrator 分支中；
  3. `DecisionInputBuilder` 复用 `SessionService.get_events(...)` 与 034 的 memory packet contract，不接管 prompt assembly；
  4. validator 能基于 Goal Contract readiness、risk policy、approval freshness、memory degrade/conflict 与 certification verdict 给出明确校验结果；
  5. replay harness 能区分 `packet_replay` 与 `session_semantic_replay`，并输出 drift / missing context / unsafe decision / override 差异；
  6. Session event 与 canonical decision evidence 已能携带 `DecisionTrace` 必要引用，不引入第二真相层；
  7. future worker trace/schema 已明确只读、声明式且不越权。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_brain_decision_loop.py tests/test_watchdog_provider_certification.py tests/test_watchdog_decision_replay.py`

## Task 35.4 接入 release gate evidence/runtime consume，并锁定低风险自动决策资格门禁

- **任务编号**：T354
- **状态**：未开始
- **目标**：把 035 的决策与审计 contract 真正接到现有 runtime，让 orchestrator 只在资格满足时消费 `propose_execute`。
- **文件**：
  - `src/watchdog/services/brain/release_gate_evidence.py`
  - `src/watchdog/services/brain/release_gate.py`
  - `scripts/generate_release_gate_report.py`
  - `docs/operations/release-gate-runbook.md`
  - `src/watchdog/services/policy/engine.py`
  - `src/watchdog/services/policy/decisions.py`
  - `src/watchdog/services/session_spine/orchestrator.py`
  - `src/watchdog/services/session_service/models.py`
  - `src/watchdog/services/session_service/service.py`
  - `tests/fixtures/release_gate_packets.jsonl`
  - `tests/fixtures/release_gate_shadow_runs.jsonl`
  - `tests/fixtures/release_gate_expected_report.json`
  - `tests/fixtures/release_gate_label_manifest.json`
  - `tests/test_watchdog_release_gate.py`
  - `tests/test_watchdog_release_gate_evidence.py`
  - `tests/test_watchdog_policy_engine.py`
  - `tests/test_watchdog_session_spine_runtime.py`
- **可并行**：否
- **验收标准**：
  1. release gate evidence 至少冻结 `certification_packet_corpus`、`shadow_decision_ledger` 与 `release_gate_report`；
  2. `scripts/generate_release_gate_report.py` 与 runbook 明确产出 `label_manifest`、冻结窗口、`generated_by`、`report_approved_by`、`artifact_ref` 与报告哈希，禁止人工拼接；
  3. release gate verdict 的 PASS/FAIL/degrade、`report_id/report_hash`、`input_hash`、`decision_trace_ref`、`approval_read_ref` 与 `degrade_reason` 必须先绑定到 `decision_proposed / decision_validated` 或等价 canonical event family；
  4. `policy.engine` 不再直接把 “goal ready + no uncertainty” 等价成 auto execute，而是消费 Brain/validator/release gate verdict；
  5. `ResidentOrchestrator` 只在 `propose_execute` 且 release gate/approval/runtime 条件都满足时进入命令执行；
  6. `PolicyDecisionStore` 继续作为 projection/evidence，不得成为第二真相层；Session event 写入失败时不得创建 command、claim lease 或执行；
  7. provider/model/prompt/schema/risk-policy/tool-schema/memory-adapter、`decision_input_builder_version`、`policy_engine_version`、TTL/expiry、当前 input hash 任一变化都会使旧 report 失效并自动降级。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_release_gate.py tests/test_watchdog_release_gate_evidence.py tests/test_watchdog_policy_engine.py tests/test_watchdog_session_spine_runtime.py`

## Task 35.5 更新执行日志与 handoff 摘要

- **任务编号**：T355
- **状态**：未开始
- **目标**：同步 formal docs、执行日志与 `.ai-sdlc` 元数据，固定后续 handoff。
- **文件**：
  - `specs/035-brain-decision-boundary-and-release-gate/task-execution-log.md`
  - `.ai-sdlc/work-items/035-brain-decision-boundary-and-release-gate/execution-plan.yaml`
  - `.ai-sdlc/work-items/035-brain-decision-boundary-and-release-gate/runtime.yaml`
  - `.ai-sdlc/work-items/035-brain-decision-boundary-and-release-gate/resume-pack.yaml`
  - `.ai-sdlc/work-items/035-brain-decision-boundary-and-release-gate/latest-summary.md`
- **可并行**：否
- **验收标准**：
  1. 执行日志已记录 red/green/review 闭环与关键设计收口；
  2. `.ai-sdlc` 元数据能准确恢复到下一执行入口；
  3. handoff 明确后续 Feishu/control-plane 与 e2e work item 只消费 Brain trace/replay/release gate/future worker contract；
  4. handoff 明确 future worker start/complete/fail 只能回写 Session events，不得直接修改 Goal Contract、approval、risk band 或 completion truth。
- **验证**：
  - `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py`
  - 人工审阅执行日志与 `.ai-sdlc` 元数据一致

## 整体验收

- 035 是长时运行自治一期的 `Task 6`，只负责把 Brain 收紧为声明式决策层，并补齐 DecisionTrace、provider certification、replay 与低风险自动决策资格门禁。
- 035 完成后，runtime 应只消费 `DecisionIntent + DecisionTrace + validator/release gate verdict`，而不是继续让 `policy.engine` 直接驱动 auto execute。
- 035 完成后，release gate 的 PASS/FAIL/degrade 与 approval freshness 都应先进入 canonical Session decision events，再允许进入 hands。
- 035 不正式实现 Feishu 主控制面、worker/sub-agent orchestration 或 e2e golden path。
