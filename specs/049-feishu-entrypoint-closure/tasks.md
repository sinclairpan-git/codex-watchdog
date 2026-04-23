# 任务分解：049-feishu-entrypoint-closure

> 对应规格：`specs/049-feishu-entrypoint-closure/spec.md`
>
> 对应计划：`specs/049-feishu-entrypoint-closure/plan.md`

## Task 49.1 冻结 049 owner 行范围、入口边界与 formal docs

- **任务编号**：T491
- **状态**：已完成
- **目标**：把 `WI-049` 的 owner 行、入口边界与 AI-SDLC handoff 固定为 formal truth。
- **文件**：
  - `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
  - `specs/049-feishu-entrypoint-closure/spec.md`
  - `specs/049-feishu-entrypoint-closure/plan.md`
  - `specs/049-feishu-entrypoint-closure/tasks.md`
  - `specs/049-feishu-entrypoint-closure/task-execution-log.md`
  - `.ai-sdlc/work-items/049-feishu-entrypoint-closure/*`
  - `.ai-sdlc/state/checkpoint.yml`
  - `.ai-sdlc/project/config/project-state.yaml`
- **可并行**：否
- **验收标准**：
  1. 已固定 owner=`WI-049` 的矩阵条目范围与代表性入口类别；
  2. 已明确 049 只做 Feishu / Feishu / natural-language 入口闭环，不重新定义 048 runtime semantics；
  3. 已把 checkpoint、branch、`next_work_item_seq` 与 docs baseline 收口到 049；
  4. 已明确 Feishu primary / Feishu compatibility-only 边界。
- **验证**：
  - 人工审阅 formal docs 与 `.ai-sdlc` 元数据一致

## Task 49.2 写失败测试锁定正式入口与自然语言映射 contract

- **任务编号**：T492
- **状态**：已完成
- **目标**：先用失败测试冻结 Feishu 主入口、Feishu compatibility 入口与自然语言映射 contract。
- **文件**：
  - `src/watchdog/services/feishu_control/service.py`
  - `src/watchdog/api/feishu_control.py`
  - `src/watchdog/services/adapters/feishu/adapter.py`
  - `src/watchdog/services/adapters/feishu/intents.py`
  - `tests/test_watchdog_feishu_control.py`
  - `tests/test_watchdog_feishu_adapter.py`
  - `tests/integration/test_feishu_integration_spine.py`
- **可并行**：否
- **验收标准**：
  1. 覆盖 Feishu 主入口查询/控制命令；
  2. 覆盖自然语言短指令到 canonical intent 的稳定映射；
  3. 覆盖 Feishu compatibility 入口复用共享 mapping / routing；
  4. 覆盖入口层不绕过 canonical approval / receipt / audit 纪律。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_feishu_control.py tests/test_watchdog_feishu_adapter.py tests/integration/test_feishu_integration_spine.py`

## Task 49.3 实现 Feishu primary command gateway 与 shared intent mapping

- **任务编号**：T493
- **状态**：已完成
- **目标**：补齐 Feishu 主入口的查询/控制命令消费，并建立共享 intent / natural-language mapping。
- **文件**：
  - `src/watchdog/services/feishu_control/service.py`
  - `src/watchdog/api/feishu_control.py`
  - `src/watchdog/services/adapters/feishu/intents.py`
  - `tests/test_watchdog_feishu_control.py`
- **可并行**：否
- **验收标准**：
  1. Feishu 可直接触达 canonical query / action route；
  2. 最小自然语言命令集已稳定映射；
  3. 入口层仍复用 canonical approval / receipt / audit。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_feishu_control.py`

## Task 49.4 实现 Feishu compatibility entry route 与 project routing 收口

- **任务编号**：T494
- **状态**：已完成
- **目标**：让 Feishu compatibility surface 复用共享 intent mapping / routing / canonical route。
- **文件**：
  - `src/watchdog/services/adapters/feishu/adapter.py`
  - `src/watchdog/api/feishu_responses.py`
  - `tests/test_watchdog_feishu_adapter.py`
  - `tests/integration/test_feishu_integration_spine.py`
- **可并行**：否
- **验收标准**：
  1. Feishu 兼容入口不再维护独立语义；
  2. `project_id` / `native_thread_id` / entry context 可稳定路由到 canonical target；
  3. Feishu 继续保持 compatibility-only，不承接新主链路语义。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_feishu_adapter.py tests/integration/test_feishu_integration_spine.py`

## Task 49.5 完成 049 整体验证并交接 WI-050

- **任务编号**：T495
- **状态**：已完成
- **目标**：正式关闭 049，并把验证/NFR 条款交给 `WI-050`。
- **文件**：
  - `specs/049-feishu-entrypoint-closure/task-execution-log.md`
  - `.ai-sdlc/work-items/049-feishu-entrypoint-closure/execution-plan.yaml`
  - `.ai-sdlc/work-items/049-feishu-entrypoint-closure/runtime.yaml`
  - `.ai-sdlc/work-items/049-feishu-entrypoint-closure/resume-pack.yaml`
  - `.ai-sdlc/work-items/049-feishu-entrypoint-closure/latest-summary.md`
- **可并行**：否
- **验收标准**：
  1. 049 负责的入口条款已具备实现、验证与 live route / compatibility route 证据；
  2. `WI-050` 只需要补验证、性能、重启、安全与验收，不再补正式入口；
  3. `.ai-sdlc` 元数据已准确恢复到 `WI-050` 前的下一执行入口。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_feishu_control.py tests/test_watchdog_feishu_adapter.py tests/integration/test_feishu_integration_spine.py`
