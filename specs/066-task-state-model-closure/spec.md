# Spec：066-task-state-model-closure

## 背景

当前 `A-Control-Agent` 已经持久化了 `context_pressure`、`stuck_level`、`pending_approval`、
`approval_risk`、`files_touched` 等任务态字段，但整体仍停留在“部分实现、部分历史实现态共存”的状态：

- `status` 仍出现 `waiting_human` 等实现态；
- `phase` 仍出现 `planning` / `approval` / `recovery` / `editing_source` 等实现态；
- `TaskStore` 与 `/api/v1/tasks` 还没有把 PRD `6.1-6.5` 的正式枚举和对象字段冻结为单一 contract；
- 历史记录、native thread 同步与 bridge/approval 写回之间也缺少统一 normalize 语义。

`WI-066` 的目标是把任务状态模型收敛到 PRD 正式口径，并保证：

1. 新写入永远产出 PRD 定义的正式状态；
2. 历史实现态在读写边界被兼容归一；
3. 任务对象的核心字段集与 API 校验固定下来；
4. 不顺手扩张到新的动作域、控制面命令或产品入口。

## 范围

### In Scope

- `src/a_control_agent/storage/tasks_store.py`
- `src/a_control_agent/api/tasks.py`
- `src/a_control_agent/services/codex/client.py`
- `src/a_control_agent/services/codex/app_server_bridge.py`
- `src/a_control_agent/api/recovery.py`
- `tests/test_a_control_agent.py`
- 受影响的 `A-Control-Agent` / `Watchdog` task-state targeted 回归

### Out of Scope

- 不在本工单内补 `pause` / `summarize` / `force_handoff` / `retry_with_conservative_path` 的 stable action code；
- 不扩张 Feishu / OpenClaw 自然语言入口；
- 不重写 approval canonical loop；
- 不在本工单内改造非任务状态模型的监督策略。

## Formal Source

- `openclaw-codex-watchdog-prd.md`
- `docs/superpowers/specs/2026-04-14-coverage-audit-matrix.md`
- `src/a_control_agent/storage/tasks_store.py`
- `src/a_control_agent/api/tasks.py`
- `src/a_control_agent/services/codex/client.py`
- `src/a_control_agent/services/codex/app_server_bridge.py`
- `src/a_control_agent/api/recovery.py`
- `src/watchdog/services/session_spine/task_state.py`

## 非 Owner 约束

- **FR-6601**：任务状态模型必须以 PRD `6.1-6.5` 与现有
  `watchdog.services.session_spine.task_state` canonical runtime semantics 为 formal truth，不再允许新增 repo-local 私有枚举作为持久化输出。
- **FR-6602**：新写入必须只落 PRD 正式枚举；历史实现态只能作为兼容输入被 normalize。
- **FR-6603**：`pending_approval=true` 时，状态模型必须表现为“等待审批”的正式语义，而不是保留实现态别名。
- **FR-6604**：`context_pressure` 只允许 `low|medium|high|critical`；`stuck_level` 只允许 `0..4`。
- **FR-6605**：本工单只关闭任务状态模型 contract，不顺手引入新任务流程。

## 功能需求

- **FR-6606**：冻结 `status` 正式枚举，完整覆盖 PRD `6.1` 的
  `created` / `running` / `waiting_for_direction` / `waiting_for_approval` / `stuck` /
  `handoff_in_progress` / `resuming` / `paused` / `completed` / `failed`。
- **FR-6607**：冻结 `phase` 正式枚举，完整覆盖 PRD `6.2` 的
  `planning` / `code_reading` / `editing_source` / `editing_tests` / `running_tests` /
  `debugging` / `summarizing` / `handoff`。
- **FR-6608**：任务状态对象必须稳定包含：
  `project_id` / `thread_id` / `task_title` / `status` / `phase` / `last_progress_at` /
  `last_summary` / `files_touched` / `pending_approval` / `approval_risk` /
  `context_pressure` / `stuck_level` / `failure_count` / `last_error_signature`。
- **FR-6609**：`TaskStore` 必须在 create/native-thread/update 边界统一复用
  `watchdog.services.session_spine.task_state.normalize_task_status()` /
  `normalize_task_phase()` 的 canonical semantics。
- **FR-6609a**：共享 canonical helper 必须吸收 `resume_failed -> failed` 的 legacy status 归一规则，
  作为唯一真值入口；`A-Control-Agent` 不得在 helper 之外再维护第二套 `resume_failed` 私有映射。
- **FR-6610**：`/api/v1/tasks` 相关写接口必须拒绝不在正式枚举内的新值。
- **FR-6611**：受影响的 bridge/client/recovery 写回必须改为只写正式枚举。
- **FR-6613**：`resume_failed` 只能作为 legacy compatibility alias 输入；recovery 失败的持久化输出必须写成
  `status=failed`，错误细节通过 `last_error_signature`、event payload 或 audit surface 保留。
- **FR-6612**：targeted tests 必须证明：
  - 创建任务默认产出正式状态；
  - native thread 传入历史实现态时会被 normalize；
  - 非法 `status` / `phase` 被 API fail-closed；
  - 审批等待、handoff/recovery 等关键写回面不再落旧枚举。

## 设计决策

- **DD-6601**：正式 canonical semantics 直接对齐
  [`task_state.py`](/Users/sinclairpan/project/openclaw-codex-watchdog/src/watchdog/services/session_spine/task_state.py)，不再在 `A-Control-Agent`
  侧另起一套 status/phase 映射规则。
- **DD-6602**：legacy status 兼容映射固定为：
  - `waiting_human + pending_approval=true -> waiting_for_approval`
  - `waiting_human + pending_approval=false -> waiting_for_direction`
  - `done|complete -> completed`
  - `error|resume_failed -> failed`
- **DD-6602a**：`resume_failed` 不属于正式 contract；其兼容语义统一沉到共享
  `task_state.normalize_task_status()`，并要求 `A-Control-Agent` recovery 失败路径在实现阶段改为
  `failed + last_error_signature`，不得继续把 `resume_failed` 持久化进任务记录。
- **DD-6603**：legacy phase 兼容映射固定为：
  - `coding -> editing_source`
  - `approval -> planning`
  - `recovery -> handoff`
  - `done -> summarizing`
  - `planning` / `editing_source` 本身已是 PRD 正式 phase，不做降级映射。
- **DD-6604**：canonical normalize 只定义运行时/接口真值，不宣称重写历史原始事件；如需追溯 legacy 原值，以既有 audit / event stream 为准。

## Docs baseline hash recipe

`docs_baseline_ref` 生成方式沿用现有 work item 规则，artifact set 固定为：

- `specs/066-task-state-model-closure/spec.md`
- `specs/066-task-state-model-closure/plan.md`
- `specs/066-task-state-model-closure/tasks.md`
- `specs/066-task-state-model-closure/task-execution-log.md`
- `.ai-sdlc/work-items/066-task-state-model-closure/execution-plan.yaml`
- `.ai-sdlc/work-items/066-task-state-model-closure/latest-summary.md`
