# Task Execution Log：053-release-entry-docs-consistency

## Phase 1：冻结 053 formal scope

- 已基于 release docs consistency blocker 与 `WI-052` handoff 正式创建 `WI-053`。
- 已明确 053 只承接 `v0.6.0` entry docs consistency 与 repo-local release docs gate。
- 已明确 artifact 生成与发布自动化不在 053 范围内。

## Phase 2：红测锁定 release docs validator 与 repo-local CLI

- 新增 `tests/test_release_docs_contracts.py`，覆盖缺失 entry doc、README drift、checklist drift 与 repo pass 场景。
- 扩展 `tests/test_ai_sdlc_repo_cli.py`，为 repo-local `verify constraints` 增加 release docs drift 场景。
- 首轮红测 `uv run pytest -q tests/test_release_docs_contracts.py tests/test_ai_sdlc_repo_cli.py` 失败，失败原因包括：
  - `watchdog.validation.release_docs_contracts` 尚不存在；
  - `status` 断言仍指向上一个 work item；
  - 临时 repo fixture 未隔离其他 gate。

## Phase 3：实现最小 release docs validator 并接入 repo-local ai_sdlc

- 新增 `src/watchdog/validation/release_docs_contracts.py`，对齐 `v0.6.0` release docs consistency token contract。
- 更新 `src/watchdog/validation/__init__.py` 暴露 release docs validator。
- 更新 `ai_sdlc/cli.py`，让 repo-local `verify constraints` 收口 release docs consistency。

## Phase 4：补齐 release entry docs 并完成 smoke 验证

- 更新 `README.md` 的 `## AI-SDLC` 入口，补齐 `v0.6.0` release notes 与 offline bundle markers。
- 新增：
  - `docs/releases/v0.6.0.md`
  - `USER_GUIDE.zh-CN.md`
  - `packaging/offline/README.md`
  - `docs/框架自迭代开发与发布约定.md`
  - `docs/pull-request-checklist.zh.md`
- 目标验证：
  - `uv run pytest -q tests/test_release_docs_contracts.py tests/test_ai_sdlc_repo_cli.py` -> `7 passed in 0.16s`
  - `python -m ai_sdlc verify constraints` -> `Constraints OK`
  - `python -m ai_sdlc status` -> 输出当前 `WI-053 / execute / next_work_item_seq=54`

## Phase 5：完成 053 整体验证并回写 formal memory

- 正式验证集：
  - `uv run pytest -q tests/test_ai_sdlc_reconciliation.py tests/test_long_running_autonomy_doc_contracts.py tests/test_ai_sdlc_repo_cli.py tests/test_framework_contracts.py tests/test_release_docs_contracts.py`
  - 结果：`22 passed in 0.19s`
- 收尾前已同步 `tests/test_ai_sdlc_repo_cli.py` 的 `status` 阶段断言，使其与 closeout 后的 `completed` 真值一致。
- 已进入 053 formal closeout，待回写 `.ai-sdlc` baseline hash 与 checkpoint 完成态。
