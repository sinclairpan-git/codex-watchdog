# 任务分解：051-high-coupling-test-hardening

> 对应规格：`specs/051-high-coupling-test-hardening/spec.md`
>
> 对应计划：`specs/051-high-coupling-test-hardening/plan.md`

## Task 51.1 冻结 051 owner 边界与 formal docs

- **任务编号**：T511
- **状态**：已完成
- **目标**：把 `BL-2026-04-06-001` 与 `WI-050` handoff 收敛成 051 的 formal truth。
- **文件**：
  - `docs/architecture/coverage-audit-closeout-execution-design.md`
  - `docs/project-backlog.zh-CN.md`
  - `specs/051-high-coupling-test-hardening/*`
  - `.ai-sdlc/work-items/051-high-coupling-test-hardening/*`
  - `.ai-sdlc/state/checkpoint.yml`
  - `.ai-sdlc/project/config/project-state.yaml`
- **可并行**：否
- **验收标准**：
  1. 已明确 051 的唯一 owner 来源是 backlog 条目与 `WI-050` handoff；
  2. 已明确 051 不承接 release blocker、不改产品语义；
  3. 已完成 work item formal docs、mirror 与 checkpoint 切换。
- **验证**：
  - 人工审阅 formal docs 与 `.ai-sdlc` 一致

## Task 51.2 写失败测试锁定 fake/stub contract 与最小 seam smoke

- **任务编号**：T512
- **状态**：已完成
- **目标**：先用 red tests 锁定 `FakeAClient` / stub drift 与最小高价值接缝烟测。
- **文件**：
  - `tests/test_watchdog_session_spine_api.py`
  - `tests/integration/test_feishu_integration_spine.py`
  - `tests/test_codex_app_server_bridge.py`
  - `tests/test_a_control_agent_control_flow.py`
- **可并行**：否
- **验收标准**：
  1. `FakeAClient` 至少对 `list_approvals/get_envelope/get_envelope_by_thread/list_tasks/decide_approval/trigger_resume/trigger_pause/trigger_handoff/get_workspace_activity_envelope` 建立签名契约；
  2. 存在一条覆盖 `approval -> callback -> restart -> stable read semantics` 的最小 `seam-smoke` 红测；
  3. 失败原因能明确指向 drift 或接缝缺口，而不是泛化失败。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_session_spine_api.py tests/integration/test_feishu_integration_spine.py -k "fake_a_client or seam_smoke"`

## Task 51.3 固定高耦合场景矩阵与 targeted suites

- **任务编号**：T513
- **状态**：已完成
- **目标**：把已有高风险测试整理为正式矩阵，并固定 `targeted-bridge / targeted-a-control / targeted-watchdog` 三层局部入口。
- **文件**：
  - `specs/051-high-coupling-test-hardening/seam-matrix.md`
  - `tests/test_codex_app_server_bridge.py`
  - `tests/test_a_control_agent_control_flow.py`
  - `tests/test_watchdog_session_spine_api.py`
  - `tests/integration/test_feishu_integration_spine.py`
- **可并行**：否
- **验收标准**：
  1. bridge / a-control / watchdog 三组 targeted seam 均有正式矩阵项；
  2. 已明确哪些已有测试是正式矩阵项，哪些不再继续扩写；
  3. targeted 入口具备稳定命令与测试集合。
- **验证**：
  - `uv run pytest -q tests/test_codex_app_server_bridge.py tests/test_a_control_agent_control_flow.py tests/test_watchdog_session_spine_api.py`

## Task 51.4 固定 seam-smoke / full 验证入口并做最小测试基建修补

- **任务编号**：T514
- **状态**：已完成
- **目标**：把 `seam-smoke / full` 入口固定成正式命令，并只在必要时补最小测试基建。
- **文件**：
  - `specs/051-high-coupling-test-hardening/seam-matrix.md`
  - `tests/test_codex_app_server_bridge.py`
  - `tests/test_a_control_agent_control_flow.py`
  - `tests/test_watchdog_session_spine_api.py`
  - `tests/integration/test_feishu_integration_spine.py`
- **可并行**：否
- **验收标准**：
  1. `seam-smoke` 和 `full` 有稳定入口，不再依赖临时拼命令；
  2. 若存在测试基建修补，改动范围局限在测试替身、fixture 或命令编排；
  3. 不把 051 扩大成生产代码增强项。
- **验证**：
  - `uv run pytest -q tests/test_codex_app_server_bridge.py tests/test_a_control_agent_control_flow.py tests/test_watchdog_session_spine_api.py tests/integration/test_feishu_integration_spine.py`

## Task 51.5 完成 051 整体验证并回写 backlog / formal memory

- **任务编号**：T515
- **状态**：已完成
- **目标**：关闭 051，并把高耦合测试强化结果正式回写到 backlog 与 `.ai-sdlc`。
- **文件**：
  - `docs/project-backlog.zh-CN.md`
  - `specs/051-high-coupling-test-hardening/task-execution-log.md`
  - `.ai-sdlc/work-items/051-high-coupling-test-hardening/*`
- **可并行**：否
- **验收标准**：
  1. seam matrix、contract tests 与三层验证入口已正式关闭；
  2. backlog 条目已被消化或重标状态；
  3. `.ai-sdlc` 元数据准确指向 051 之后的下一执行入口。
- **验证**：
  - `uv run pytest -q tests/test_codex_app_server_bridge.py tests/test_a_control_agent_control_flow.py tests/test_watchdog_session_spine_api.py tests/integration/test_feishu_integration_spine.py tests/test_ai_sdlc_reconciliation.py tests/test_long_running_autonomy_doc_contracts.py`
