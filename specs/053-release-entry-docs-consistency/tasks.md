# 任务分解：053-release-entry-docs-consistency

> 对应规格：`specs/053-release-entry-docs-consistency/spec.md`
>
> 对应计划：`specs/053-release-entry-docs-consistency/plan.md`

## Task 53.1 冻结 053 owner 边界与 formal docs

- **任务编号**：T531
- **状态**：已完成
- **目标**：把 release docs consistency blocker 收敛成 053 的 formal truth。
- **文件**：
  - `docs/architecture/coverage-audit-closeout-execution-design.md`
  - `README.md`
  - `specs/053-release-entry-docs-consistency/*`
  - `.ai-sdlc/work-items/053-release-entry-docs-consistency/*`
  - `.ai-sdlc/state/checkpoint.yml`
  - `.ai-sdlc/project/config/project-state.yaml`
- **可并行**：否
- **验收标准**：
  1. 已明确 053 只承接 release entry docs consistency；
  2. 已明确 053 不处理 artifact 生成与发布自动化；
  3. 已完成 work item formal docs、mirror 与 checkpoint 切换。
- **验证**：
  - 人工审阅 formal docs 与 `.ai-sdlc` 一致

## Task 53.2 写失败测试锁定 release docs validator 与 repo-local CLI

- **任务编号**：T532
- **状态**：已完成
- **目标**：先用 red tests 锁定 release docs consistency gate。
- **文件**：
  - `tests/test_release_docs_contracts.py`
  - `tests/test_ai_sdlc_repo_cli.py`
- **可并行**：否
- **验收标准**：
  1. 缺失 release entry docs、README drift、policy / checklist drift 都有显式红测；
  2. repo-local CLI 在补齐文档前先失败再修复。
- **验证**：
  - `uv run pytest -q tests/test_release_docs_contracts.py tests/test_ai_sdlc_repo_cli.py`

## Task 53.3 实现最小 release docs validator 并接入 repo-local ai_sdlc

- **任务编号**：T533
- **状态**：已完成
- **目标**：让 repo-local `verify constraints` 覆盖 release docs consistency。
- **文件**：
  - `src/watchdog/validation/release_docs_contracts.py`
  - `src/watchdog/validation/__init__.py`
  - `ai_sdlc/cli.py`
- **可并行**：否
- **验收标准**：
  1. validator 能发现缺失 entry doc 与 token drift；
  2. CLI 输出稳定 blocker 文案。
- **验证**：
  - `uv run pytest -q tests/test_release_docs_contracts.py tests/test_ai_sdlc_repo_cli.py`

## Task 53.4 补齐 release entry docs 并完成 smoke 验证

- **任务编号**：T534
- **状态**：已完成
- **目标**：补齐缺失的 `v0.6.0` release entry docs，并跑通 repo-local CLI。
- **文件**：
  - `README.md`
  - `docs/releases/v0.6.0.md`
  - `USER_GUIDE.zh-CN.md`
  - `packaging/offline/README.md`
  - `docs/框架自迭代开发与发布约定.md`
  - `docs/pull-request-checklist.zh.md`
- **可并行**：否
- **验收标准**：
  1. 所有固定 entry docs 存在；
  2. token contract 满足 `v0.6.0` gate；
  3. `python -m ai_sdlc verify constraints` 通过。
- **验证**：
  - `python -m ai_sdlc verify constraints`

## Task 53.5 完成 053 整体验证并回写 formal memory

- **任务编号**：T535
- **状态**：已完成
- **目标**：关闭 053，并把 release docs consistency closeout 正式回写到 `.ai-sdlc`。
- **文件**：
  - `specs/053-release-entry-docs-consistency/task-execution-log.md`
  - `.ai-sdlc/work-items/053-release-entry-docs-consistency/*`
  - `.ai-sdlc/state/checkpoint.yml`
  - `.ai-sdlc/project/config/project-state.yaml`
- **可并行**：否
- **验收标准**：
  1. release docs validator、entry docs 与 repo-local CLI 已完成 formal 验证；
  2. `.ai-sdlc` 元数据准确指向 054。
- **验证**：
  - `uv run pytest -q tests/test_ai_sdlc_reconciliation.py tests/test_long_running_autonomy_doc_contracts.py tests/test_ai_sdlc_repo_cli.py tests/test_framework_contracts.py tests/test_release_docs_contracts.py`
