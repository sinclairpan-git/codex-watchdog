# 任务分解：015-stable-session-explanations

> 对应规格：`specs/015-stable-session-explanations/spec.md`
>
> 对应总设计：`docs/architecture/codex-watchdog-g0-and-v010-design.md`

## Batch 1

### Task 15.1 Shared explanation builder 与非版本推进锁定

- **任务编号**：T151
- **状态**：已完成（2026-04-06 回填）
- **依赖**：无
- **文件**：`src/watchdog/services/session_spine/replies.py`, `src/watchdog/services/adapters/feishu/reply_model.py`, `tests/test_watchdog_session_spine_contracts.py`, `tests/test_watchdog_feishu_adapter.py`
- **可并行**：否
- **验收标准**：
  1. explanation reply builder 从 adapter 专有逻辑收拢到 shared 层；
  2. `why_stuck` 与 `explain_blocker` 继续仅基于 `FactRecord + stable read model`；
  3. 015 不推进 session spine `schema_version`，仍保持 `2026-04-05.014`。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_contracts.py tests/test_watchdog_feishu_adapter.py`

### Task 15.2 Stable explanation read routes

- **任务编号**：T152
- **状态**：已完成（2026-04-06 回填）
- **依赖**：T151
- **文件**：`src/watchdog/api/session_spine_queries.py`, `src/watchdog/main.py`, `tests/test_watchdog_session_spine_api.py`
- **可并行**：否
- **验收标准**：
  1. 存在 `GET /api/v1/watchdog/sessions/{project_id}/stuck-explanation`；
  2. 存在 `GET /api/v1/watchdog/sessions/{project_id}/blocker-explanation`；
  3. 两个 route 的 `data` 都返回稳定 `ReplyModel`；
  4. route 只复用 stable read bundle，不新增 raw/legacy 旁路。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_api.py`

## Batch 2

### Task 15.3 API / adapter 一致性与非回归收口

- **任务编号**：T153
- **状态**：已完成（2026-04-06 回填）
- **依赖**：T152
- **文件**：`tests/test_watchdog_session_spine_api.py`, `tests/test_watchdog_feishu_adapter.py`, `tests/integration/test_feishu_integration_spine.py`
- **可并行**：否
- **验收标准**：
  1. API 与 adapter 对同一输入返回相同 `reply_code`；
  2. API 与 adapter 的 explanation facts 集一致；
  3. explanation route 接入不会破坏 `get_session` / `get_progress` / `pending-approvals` / events / actions / receipts 既有稳定行为。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_api.py tests/test_watchdog_feishu_adapter.py tests/integration/test_feishu_integration_spine.py`

### Task 15.4 文档、OpenAPI 与项目状态收口

- **任务编号**：T154
- **状态**：已完成（2026-04-06 回填）
- **依赖**：T152
- **文件**：`README.md`, `docs/getting-started.zh-CN.md`, `docs/openapi/watchdog.json`, `.ai-sdlc/project/config/project-state.yaml`
- **可并行**：是
- **验收标准**：
  1. README 与 getting-started 把 explanation route 纳入 stable read surface；
  2. OpenAPI 暴露两个 explanation route；
  3. 文档明确 015 不新增 contract 版本，只补 stable HTTP explanation surface；
  4. `.ai-sdlc` 推进到下一个 work item 序号。
- **验证**：人工核对 + `rg -n "stuck-explanation|blocker-explanation|why_stuck|explain_blocker|2026-04-05.014" README.md docs/getting-started.zh-CN.md docs/openapi/watchdog.json .ai-sdlc/project/config/project-state.yaml`
