# 任务分解：022-stable-session-facts

> 对应规格：`specs/022-stable-session-facts/spec.md`

## Task 22.1 Contract 与版本语义

- **目标**：冻结 stable session facts reply contract 与 022 schema version。
- **涉及文件**：
  - `src/watchdog/contracts/session_spine/enums.py`
  - `src/watchdog/contracts/session_spine/versioning.py`
  - `tests/test_watchdog_session_spine_contracts.py`
- **完成标准**：
  1. 存在 `ReplyKind.FACTS`；
  2. 存在 `ReplyCode.SESSION_FACTS`；
  3. `SESSION_SPINE_SCHEMA_VERSION` 推进到 `2026-04-05.022`；
  4. `SESSION_EVENTS_SCHEMA_VERSION` 仍保持 `2026-04-05.011`。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_contracts.py -k session_facts`

## Task 22.2 L2 Reply Builder

- **目标**：把稳定 `FactRecord[]` 收敛为统一 facts reply。
- **涉及文件**：
  - `src/watchdog/services/session_spine/replies.py`
  - `tests/test_watchdog_session_spine_contracts.py`
- **完成标准**：
  1. 存在 `build_session_facts_reply(...)`；
  2. builder 输入是既有 `SessionReadBundle`，不重新读取 raw 数据；
  3. 输出 `ReplyModel(reply_code=session_facts, facts=...)`。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_contracts.py -k session_facts`

## Task 22.3 Stable API Surface

- **目标**：暴露 canonical stable facts route。
- **涉及文件**：
  - `src/watchdog/api/session_spine_queries.py`
  - `tests/test_watchdog_session_spine_api.py`
- **完成标准**：
  1. 存在 `GET /api/v1/watchdog/sessions/{project_id}/facts`；
  2. route 复用既有 `build_session_read_bundle(...)`；
  3. route 返回稳定 `ReplyModel(facts=FactRecord[])`；
  4. 015 explanation route 不回归。
- **验证**：`uv run pytest -q tests/test_watchdog_session_spine_api.py -k facts`

## Task 22.4 OpenClaw Adapter Intent

- **目标**：让 OpenClaw 通过主 `intent -> ReplyModel` 闭环消费 stable facts。
- **涉及文件**：
  - `src/watchdog/services/adapters/openclaw/intents.py`
  - `src/watchdog/services/adapters/openclaw/reply_model.py`
  - `src/watchdog/services/adapters/openclaw/adapter.py`
  - `tests/test_watchdog_openclaw_adapter.py`
  - `tests/integration/test_openclaw_integration_spine.py`
- **完成标准**：
  1. adapter 支持 `list_session_facts`；
  2. `handle_intent("list_session_facts")` 返回稳定 `ReplyModel(reply_code=session_facts)`；
  3. adapter 与 HTTP route 共用同一 facts reply builder；
  4. facts truth source 不旁路 raw/legacy route。
- **验证**：`uv run pytest -q tests/test_watchdog_openclaw_adapter.py tests/integration/test_openclaw_integration_spine.py -k facts`

## Task 22.5 文档、OpenAPI 与项目状态收口

- **目标**：同步 022 对外口径，并推进 work item state。
- **涉及文件**：
  - `README.md`
  - `docs/getting-started.zh-CN.md`
  - `docs/openapi/watchdog.json`
  - `.ai-sdlc/project/config/project-state.yaml`
- **完成标准**：
  1. README 与 getting-started 已写清 facts truth source vs explanation layer；
  2. OpenAPI 暴露 `GET /api/v1/watchdog/sessions/{project_id}/facts`；
  3. `.ai-sdlc` 推进到 `023`。
- **验证**：`uv run python scripts/export_openapi.py`

## 整体验收

- 调用方已经可以通过稳定 `ReplyModel(facts=FactRecord[])` 直接读取 session 事实真值，而不必只能从 explanation 或 session/progress 的附带字段里拆取。
- OpenClaw adapter 已将 `list_session_facts` 纳入主 `handle_intent -> ReplyModel` 闭环。
- 022 只补 `FactRecord` stable read seam，不改变 explanation contract，也不扩成 history/filter 产品。
