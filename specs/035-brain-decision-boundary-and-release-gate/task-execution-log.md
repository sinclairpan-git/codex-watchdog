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
