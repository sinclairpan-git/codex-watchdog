# Task Execution Log：062-global-design-provider-memory-closure

## 2026-04-16 Phase 1

- 已重新对齐原始全局设计，而不是只围绕当前脏树局部缺口推进。
- 已确认当前仍未落地的核心缺口集中在：
  - `OpenAI-compatible Brain provider runtime`
  - `Memory Hub` durable memory / ingestion
  - `Session Service -> Memory Hub` 沉淀闭环
- 已创建 `WI-062` formal docs skeleton。

## 2026-04-16 Phase 2

- 已新增 failing tests：
  - `tests/test_watchdog_brain_provider_runtime.py`
  - `tests/test_watchdog_memory_hub.py` 中的 durable memory / app wiring 覆盖
- 首轮 targeted 结果：
  - `uv run pytest -q tests/test_watchdog_brain_provider_runtime.py tests/test_watchdog_memory_hub.py`
  - 结果：`4 failed, 4 passed`
  - 失败点真实锁定为：
    - `Settings` 缺少 provider 配置；
    - `BrainDecisionService` 尚未接入 provider；
    - `MemoryHubService` 尚无 persistent store；
    - `create_app()` 尚未暴露 `memory_hub_service` 与 ingest wiring。

## 2026-04-16 Phase 3

- 已新增 `src/watchdog/services/brain/provider_runtime.py`。
- 已让 `BrainDecisionService` 支持 `OpenAI-compatible` provider 配置、结构化输出映射与 fail-closed 回退。
- 已让 `DecisionIntent` / `DecisionTrace` 反映真实 provider/model，而不是固定写死为 rule-based。

## 2026-04-16 Phase 4

- 已新增 `src/watchdog/services/memory_hub/store.py`。
- 已让 `MemoryHubService` 支持：
  - `from_data_dir(...)`
  - `register_project(...)`
  - `upsert_resident_memory(...)`
  - `store_archive_entry(...)`
  - `ingest_session_event(...)`
  - `resident_capsule` 输出
- 已在 `create_app()` 中接入 `app.state.memory_hub_service`，并让 `SessionService` 事件写入后异步沉淀到 `Memory Hub`。

## 2026-04-16 Phase 5

- targeted 验证：
  - `uv run pytest -q tests/test_watchdog_brain_provider_runtime.py tests/test_watchdog_memory_hub.py`
  - 结果：`9 passed in 0.40s`
- broader verification：
  - `uv run pytest -q tests/test_watchdog_brain_provider_runtime.py tests/test_watchdog_provider_certification.py tests/test_watchdog_brain_decision_loop.py tests/test_watchdog_memory_hub.py tests/test_watchdog_memory_packets.py tests/test_watchdog_memory_degradation.py tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_feishu_control.py tests/test_watchdog_action_execution.py tests/e2e/test_watchdog_autonomy_golden_path.py tests/test_watchdog_ops.py`
  - 结果：`120 passed in 3.66s`
  - `python -m ai_sdlc verify constraints` -> `Constraints OK`
- 对抗评审结论已吸收的项：
  - 已补 `DecisionTrace` 对真实 provider/model 的断言；
  - 已补 Memory Hub restart 后 `project + skill metadata` 的持久化断言。
- 对抗评审保留的下一阶段残余缺口：
  - `Session Service -> Memory Hub` 目前仍通过同步 listener 做 post-commit ingest，还未升级为真正的 async sink / queue。
