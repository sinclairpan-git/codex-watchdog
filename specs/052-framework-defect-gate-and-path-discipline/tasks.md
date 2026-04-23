# 任务分解：052-framework-defect-gate-and-path-discipline

> 对应规格：`specs/052-framework-defect-gate-and-path-discipline/spec.md`
>
> 对应计划：`specs/052-framework-defect-gate-and-path-discipline/plan.md`

## Task 52.1 冻结 052 owner 边界与 formal docs

- **任务编号**：T521
- **状态**：已完成
- **目标**：把 framework defect backlog 与 README 命令约束收敛成 052 的 formal truth。
- **文件**：
  - `docs/architecture/coverage-audit-closeout-execution-design.md`
  - `docs/framework-defect-backlog.zh-CN.md`
  - `README.md`
  - `specs/052-framework-defect-gate-and-path-discipline/*`
  - `.ai-sdlc/work-items/052-framework-defect-gate-and-path-discipline/*`
  - `.ai-sdlc/state/checkpoint.yml`
  - `.ai-sdlc/project/config/project-state.yaml`
- **可并行**：否
- **验收标准**：
  1. 已明确 052 只承接 framework defect backlog 与 repo-local constraint entry；
  2. 已明确 052 不处理 release docs consistency 与业务 backlog；
  3. 已完成 work item formal docs、mirror 与 checkpoint 切换。
- **验证**：
  - 人工审阅 formal docs 与 `.ai-sdlc` 一致

## Task 52.2 写失败测试锁定 repo-local CLI、backlog contract 与 canonical path classifier

- **任务编号**：T522
- **状态**：已完成
- **目标**：先用 red tests 锁定 repo-local `ai_sdlc` 入口、framework backlog 校验与 formal 路径分类。
- **文件**：
  - `tests/test_ai_sdlc_repo_cli.py`
  - `tests/test_framework_contracts.py`
  - `docs/framework-defect-backlog.zh-CN.md`
- **可并行**：否
- **验收标准**：
  1. `python -m ai_sdlc verify constraints` / `status` 在当前仓库测试环境下先失败再修复；
  2. 缺失 canonical backlog、字段缺失、`docs/superpowers` formal 误落点都有显式红测；
  3. classifier 对 architecture / WI formal / forbidden path 的判断可直接断言。
- **验证**：
  - `uv run pytest -q tests/test_ai_sdlc_repo_cli.py tests/test_framework_contracts.py`

## Task 52.3 实现最小 validator、classifier 与 repo-local ai_sdlc 入口

- **任务编号**：T523
- **状态**：已完成
- **目标**：让仓库内自带的 `ai_sdlc` 入口串起 framework contract 与 canonical path checks。
- **文件**：
  - `ai_sdlc/__init__.py`
  - `ai_sdlc/__main__.py`
  - `ai_sdlc/cli.py`
  - `src/watchdog/validation/framework_contracts.py`
  - `src/watchdog/validation/__init__.py`
- **可并行**：否
- **验收标准**：
  1. repo-local CLI 支持 `verify constraints` 与 `status`；
  2. validator 能输出 framework backlog 缺省、字段缺失与 forbidden path 问题；
  3. classifier 能给出 canonical 期望路径。
- **验证**：
  - `uv run pytest -q tests/test_ai_sdlc_repo_cli.py tests/test_framework_contracts.py`

## Task 52.4 收敛 repo 文档并完成 targeted / smoke 验证

- **任务编号**：T524
- **状态**：已完成
- **目标**：修正 repo 文档不兼容项，并跑通 repo-local CLI smoke。
- **文件**：
  - `docs/framework-defect-backlog.zh-CN.md`
  - `README.md`
  - `tests/test_ai_sdlc_repo_cli.py`
  - `tests/test_framework_contracts.py`
- **可并行**：否
- **验收标准**：
  1. framework backlog 字段格式对 parser 友好；
  2. README 中 `python -m ai_sdlc` 约束入口与实际行为一致；
  3. repo-local CLI smoke 能在当前仓库执行并产出稳定结果。
- **验证**：
  - `python -m ai_sdlc verify constraints`
  - `python -m ai_sdlc status`

## Task 52.5 完成 052 整体验证并回写 formal memory

- **任务编号**：T525
- **状态**：已完成
- **目标**：关闭 052，并把 framework defect closeout 正式回写到 backlog 与 `.ai-sdlc`。
- **文件**：
  - `docs/framework-defect-backlog.zh-CN.md`
  - `specs/052-framework-defect-gate-and-path-discipline/task-execution-log.md`
  - `.ai-sdlc/work-items/052-framework-defect-gate-and-path-discipline/*`
  - `.ai-sdlc/state/checkpoint.yml`
  - `.ai-sdlc/project/config/project-state.yaml`
- **可并行**：否
- **验收标准**：
  1. repo-local CLI、framework contract 与 path classifier 已完成 formal 验证；
  2. 052 覆盖的 defect 已被消化或标记关闭；
  3. `.ai-sdlc` 元数据准确指向 052 之后的下一执行入口。
- **验证**：
  - `uv run pytest -q tests/test_ai_sdlc_reconciliation.py tests/test_long_running_autonomy_doc_contracts.py tests/test_ai_sdlc_repo_cli.py tests/test_framework_contracts.py`
