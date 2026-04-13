# 任务分解：034-memory-hub-codex-critical

> 对应规格：`specs/034-memory-hub-codex-critical/spec.md`
>
> 对应计划：`specs/034-memory-hub-codex-critical/plan.md`

## Task 34.1 冻结 034 formal docs 与 Memory Hub 受约束边界

- **任务编号**：T341
- **状态**：已完成（2026-04-13）
- **目标**：把总实施计划中的 `Task 5` 正式拆成 canonical execution work item，并把 `Memory Hub` 收紧为受约束的 retrieval/provider facade。
- **文件**：
  - `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
  - `specs/034-memory-hub-codex-critical/spec.md`
  - `specs/034-memory-hub-codex-critical/plan.md`
  - `specs/034-memory-hub-codex-critical/tasks.md`
  - `specs/034-memory-hub-codex-critical/task-execution-log.md`
- **可并行**：否
- **验收标准**：
  1. 已明确 `Session Service + Goal Contract` 仍是唯一运行时真相源；
  2. 已明确四类内容只是内部实现分区，不是 Hermes/Anthropic 官方原生模型；
  3. 已明确 session replay、JIT expansion、security verdict、provider lifecycle 与 canonical degrade event 是正式边界。
- **验证**：人工审阅 formal docs 与总实施计划中的 Task 5 边界一致。
- **完成情况**：
  1. 已新增 `spec.md`、`plan.md`、`tasks.md`、`task-execution-log.md` 与 `.ai-sdlc/work-items/034-*` 元数据；
  2. 已把 Task 5 的口径从“统一记忆平台”收紧为 `Codex-critical` retrieval/provider facade；
  3. 已吸收 Hermes/Anthropic 对抗评审结论，补入 replayability、JIT expansion、安全门禁与 provider lifecycle。

## Task 34.2 写失败测试锁定 session replay、packet inputs 与安全门禁

- **任务编号**：T342
- **状态**：待执行
- **目标**：用失败测试先锁定 `Memory Hub` 一期的正式 contract，避免实现回退到中心化 packet/harness 设计。
- **文件**：
  - `tests/test_watchdog_memory_hub.py`
  - `tests/test_watchdog_memory_packets.py`
  - `tests/test_watchdog_memory_degradation.py`
- **可并行**：否
- **验收标准**：
  1. 覆盖 `Session Service.get_events(...)` 或等价事件切片接口；
  2. 覆盖 packet inputs 默认只返回摘要、refs 与 expansion handles；
  3. 覆盖 `security_verdict`、provider lifecycle、provider memory ops 与 canonical degrade event；
  4. 覆盖 compaction 后仍可通过 cursor/range/anchor 恢复关键 raw events，而不是只剩 summary/packet inputs；
  5. 覆盖 context quality metrics：`key_fact_recall`、`irrelevant_summary_precision`、`token_budget_utilization`、`expansion_miss_rate`；
  6. 覆盖 future worker/sub-agent packet schema 至少保留 `scope`、`parent_session_id`、`worker_task_ref`、`retrieval_handles`、`distilled_summary_ref`，且不会绕过 retrieval/ref contract；
  7. 覆盖至少一个 fixture 会产出并持久化 context quality metrics，阈值留给后续 release gate 决定。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_memory_hub.py tests/test_watchdog_memory_packets.py tests/test_watchdog_memory_degradation.py`

## Task 34.3 实现最小 Memory Hub Codex-critical 垂直切片

- **任务编号**：T343
- **状态**：待执行
- **目标**：交付 resident facade、session search archive、skill metadata、packet inputs、provider lifecycle 与 fallback path 的最小可用实现。
- **文件**：
  - `src/watchdog/services/memory_hub/models.py`
  - `src/watchdog/services/memory_hub/contracts.py`
  - `src/watchdog/services/memory_hub/service.py`
  - `src/watchdog/services/memory_hub/indexer.py`
  - `src/watchdog/services/memory_hub/skills.py`
  - `src/watchdog/services/memory_hub/packets.py`
  - `src/watchdog/services/session_service/service.py`
  - `src/watchdog/services/session_spine/orchestrator.py`
  - `src/watchdog/services/delivery/store.py`
- **可并行**：否
- **验收标准**：
  1. `Memory Hub` 只输出 retrieval facade 与 packet inputs，不拥有 final packet policy；
  2. runtime 在 outage/conflict/security 失效时能回退到 `Session Service + runtime snapshot`；
  3. resident write surface、skill source-of-truth 和 provider memory ops 都有受控实现，不绕过 frozen packet block；
  4. skill source-of-truth 明确以 `source_ref + content_hash` 识别更新，local source 优先，shared/external source 默认 read-only；
  5. preview contracts 继续 disabled by default，不进入一期 release gate。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_memory_hub.py tests/test_watchdog_memory_packets.py tests/test_watchdog_memory_degradation.py`

## Task 34.4 运行 Memory Hub / runtime / docs 相关验证

- **任务编号**：T344
- **状态**：待执行
- **目标**：确认 `Memory Hub` 收口后，主路径、降级路径与 docs contract 都不回退。
- **文件**：
  - `tests/test_watchdog_memory_hub.py`
  - `tests/test_watchdog_memory_packets.py`
  - `tests/test_watchdog_memory_degradation.py`
  - `tests/test_watchdog_session_spine_runtime.py`
  - `tests/test_long_running_autonomy_doc_contracts.py`
- **可并行**：否
- **验收标准**：
  1. `Memory Hub` 相关测试通过；
  2. runtime / fallback 没有因为新边界产生行为回退；
  3. replay 语义级恢复、security verdict 枚举和 degrade `reason_code/source_ref` 都被验证；
  4. formal docs 与总实施计划中的 Task 5 保持一致。
- **验证**：
  - `uv run pytest -q tests/test_watchdog_memory_hub.py tests/test_watchdog_memory_packets.py tests/test_watchdog_memory_degradation.py tests/test_watchdog_session_spine_runtime.py tests/test_long_running_autonomy_doc_contracts.py`

## Task 34.5 更新执行日志与 handoff 摘要

- **任务编号**：T345
- **状态**：待执行
- **目标**：同步 formal docs、task execution log 与 `.ai-sdlc` 元数据，固定后续 handoff。
- **文件**：
  - `specs/034-memory-hub-codex-critical/task-execution-log.md`
  - `.ai-sdlc/work-items/034-memory-hub-codex-critical/execution-plan.yaml`
  - `.ai-sdlc/work-items/034-memory-hub-codex-critical/runtime.yaml`
  - `.ai-sdlc/work-items/034-memory-hub-codex-critical/resume-pack.yaml`
  - `.ai-sdlc/work-items/034-memory-hub-codex-critical/latest-summary.md`
- **可并行**：否
- **验收标准**：
  1. 执行日志已记录对抗评审结论与设计收口；
  2. `.ai-sdlc` 元数据能准确恢复到下一执行入口；
  3. handoff 明确后续 work item 只消费 retrieval/input contracts，不把 Memory Hub 升级成新的 orchestrator。
- **验证**：人工审阅执行日志与 `.ai-sdlc` 元数据一致。

## 整体验收

- 034 是长时运行自治一期的 `Task 5`，只负责把 `Memory Hub` 收敛为 `Codex-critical` retrieval/provider facade。
- 034 完成后，主路径应具备 resident budget、session search archive、skill metadata、JIT expansion、安全门禁与 canonical degrade/fallback。
- 034 不正式实现 `User Model`、`Periodic Nudge`、自动 shared promotion、sub-agent orchestration 或 release gate。
