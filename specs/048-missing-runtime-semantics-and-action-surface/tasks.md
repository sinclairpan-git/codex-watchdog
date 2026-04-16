# 任务分解：048-missing-runtime-semantics-and-action-surface

> 对应规格：`specs/048-missing-runtime-semantics-and-action-surface/spec.md`
>
> 对应计划：`specs/048-missing-runtime-semantics-and-action-surface/plan.md`

## Task 48.1 冻结 048 owner 行范围、边界与 formal docs

- **任务编号**：T481
- **状态**：已完成
- **目标**：把 `WI-048` 的 22 条 owner 行、边界纪律与 AI-SDLC handoff 收敛为 formal truth，并完成对抗评审。
- **文件**：
  - `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
  - `specs/048-missing-runtime-semantics-and-action-surface/spec.md`
  - `specs/048-missing-runtime-semantics-and-action-surface/plan.md`
  - `specs/048-missing-runtime-semantics-and-action-surface/tasks.md`
  - `specs/048-missing-runtime-semantics-and-action-surface/task-execution-log.md`
  - `.ai-sdlc/work-items/048-missing-runtime-semantics-and-action-surface/*`
  - `.ai-sdlc/state/checkpoint.yml`
  - `.ai-sdlc/project/config/project-state.yaml`
- **可并行**：否
- **验收标准**：
  1. 已把 owner=`WI-048` 的 22 条矩阵行固定为当前 work item 范围；
  2. 已明确 048 只做 runtime semantics / action surface / fail-closed boundary / Memory Hub hot-path semantics；
  3. 已明确 `matrix-row-0013 / 0015 / 0017` 在 048 只交付 semantic effect，不进入 `WI-049` 负责的渠道绑定；
  4. 已明确 048 不进入 `WI-049` 的入口闭环与 `WI-050` 的验证/NFR；
  5. Anthropic Manager Expert 与 Hermes Agent Expert 复核后无 blocking/P1；
  6. `runtime.yaml` 与 `resume-pack.yaml` 已写入 reviewed docs baseline、approval status、approved_by 与 canonical branch，其中 `docs_baseline_ref` 必须按 `spec.md` 中冻结的 deterministic hash recipe 生成；
  7. `checkpoint.yml` 已切到 `WI-048`，`project-state.yaml.next_work_item_seq=49`。
- **验证**：
  - 人工审阅 formal docs 与 `.ai-sdlc` 元数据一致

## Task 48.2 写失败测试锁定 canonical state、action、risk 与 memory runtime contract

- **任务编号**：T482
- **状态**：已完成
- **目标**：先用失败测试固定 048 的 runtime semantics contract，而不是边写边解释。
- **文件**：
  - `src/watchdog/services/session_spine/task_state.py`
  - `src/watchdog/services/action_executor/steer.py`
  - `src/watchdog/contracts/session_spine/enums.py`
  - `src/watchdog/services/session_spine/actions.py`
  - `src/a_control_agent/risk/classifier.py`
  - `src/watchdog/services/memory_hub/service.py`
  - `tests/test_watchdog_runtime_semantics.py`
  - `tests/test_watchdog_action_execution.py`
  - `tests/test_watchdog_steer.py`
  - `tests/test_a_control_agent.py`
  - `tests/test_watchdog_memory_hub.py`
  - `tests/test_watchdog_memory_degradation.py`
- **可并行**：否
- **验收标准**：
  1. 覆盖 canonical task status / phase normalize contract；
  2. 覆盖 `continue / pause / resume / summarize / force_handoff / retry_with_conservative_path` 的 stable action 映射；
  3. 覆盖 canonical state machine 的合法 source/target state、required guard 与非法转移拒绝语义；
  4. 覆盖 waiting-for-direction / break-loop / severe takeover / handoff summary 的模板与 effect；
  5. 覆盖 risk boundary 对 workspace/network/system/credential/destructive/publish 的 fail-closed 判定；
  6. 覆盖 `Memory Hub` hot-path retrieval、degrade 与 conflict semantics，且冲突时以 `Session Service + Goal Contract` 为准；
  7. 覆盖 compatibility mapping 不破坏现有 raw task payload / legacy bridge。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_runtime_semantics.py tests/test_watchdog_action_execution.py tests/test_watchdog_steer.py tests/test_a_control_agent.py tests/test_watchdog_memory_hub.py tests/test_watchdog_memory_degradation.py`

## Task 48.3 实现 canonical state normalization、steer registry 与 stable action surface

- **任务编号**：T483
- **状态**：已完成
- **目标**：把状态/阶段、模板和动作从零散常量与临时路由收口为 canonical runtime surface。
- **文件**：
  - `src/watchdog/services/session_spine/task_state.py`
  - `src/a_control_agent/storage/tasks_store.py`
  - `src/a_control_agent/services/codex/client.py`
  - `src/watchdog/services/action_executor/steer.py`
  - `src/watchdog/contracts/session_spine/enums.py`
  - `src/watchdog/services/session_spine/actions.py`
  - `src/watchdog/api/session_spine_actions.py`
  - `tests/test_watchdog_runtime_semantics.py`
  - `tests/test_watchdog_action_execution.py`
  - `tests/test_watchdog_steer.py`
- **可并行**：否
- **验收标准**：
  1. canonical task status / phase 已可从 legacy raw values 稳定归一化；
  2. steer template registry 已覆盖 soft/waiting-for-direction/break-loop/handoff summary；
  3. stable action surface 已覆盖 PRD 用户动作枚举并产出 canonical effect / receipt；
  4. severe-threshold takeover、unclear-goal human decision、break-loop conservative retry 都有正式 runtime path；
  5. 不新增新的入口层或绕过既有 recovery hot path。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_runtime_semantics.py tests/test_watchdog_action_execution.py tests/test_watchdog_steer.py`

## Task 48.4 实现 fail-closed approval boundary 与 Memory Hub hot-path semantics

- **任务编号**：T484
- **状态**：已完成
- **目标**：让审批边界和 Memory Hub 连续性从 advisory contract 变成运行时语义。
- **文件**：
  - `src/a_control_agent/risk/classifier.py`
  - `src/a_control_agent/services/codex/app_server_bridge.py`
  - `src/watchdog/services/memory_hub/service.py`
  - `src/watchdog/services/session_spine/recovery.py`
  - `src/watchdog/services/brain/service.py`
  - `tests/test_a_control_agent.py`
  - `tests/test_watchdog_memory_hub.py`
  - `tests/test_watchdog_memory_degradation.py`
- **可并行**：否
- **验收标准**：
  1. risk boundary 已覆盖 workspace/network/system/credential/destructive/publish 六类显式边界；
  2. 禁止事项已落实为 hard block / human gate，而不是继续 advisory；
  3. `Memory Hub` 已进入 recovery/decision input 的最小 hot path；
  4. `memory_unavailable_degraded` / `memory_conflict_detected` 等 degrade path 已写入 canonical events/facts；
  5. `AI_AutoSDLC` 阶段输入仍保持 advisory，不覆盖 Goal Contract 真相。
- **验证**：
  - `uv run pytest -q tests/test_a_control_agent.py tests/test_watchdog_memory_hub.py tests/test_watchdog_memory_degradation.py`

## Task 48.5 完成 048 整体验证并交接 WI-049

- **任务编号**：T485
- **状态**：已完成
- **目标**：正式关闭 048，并把入口闭环条款交给 `WI-049` 消费。
- **文件**：
  - `specs/048-missing-runtime-semantics-and-action-surface/task-execution-log.md`
  - `.ai-sdlc/work-items/048-missing-runtime-semantics-and-action-surface/execution-plan.yaml`
  - `.ai-sdlc/work-items/048-missing-runtime-semantics-and-action-surface/runtime.yaml`
  - `.ai-sdlc/work-items/048-missing-runtime-semantics-and-action-surface/resume-pack.yaml`
  - `.ai-sdlc/work-items/048-missing-runtime-semantics-and-action-surface/latest-summary.md`
- **可并行**：否
- **验收标准**：
  1. 048 负责的 22 条 owner 行已具备实现、验证与 stable route 证据；
  2. `WI-049` 只需要补主入口和自然语言/渠道映射，不再需要重新定义 runtime semantics；
  3. `latest-summary` 与 `task-execution-log` 已留档验证命令和 residual risk；
  4. `.ai-sdlc` 元数据已准确恢复到 `WI-049` 前的下一执行入口。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_runtime_semantics.py tests/test_watchdog_action_execution.py tests/test_watchdog_steer.py tests/test_a_control_agent.py tests/test_watchdog_memory_hub.py tests/test_watchdog_memory_degradation.py`
