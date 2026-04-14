# 执行日志：038-future-worker-canonical-execution-and-governance

## 2026-04-14

### Phase 1：formal docs / spec freeze

- 基于 `WI-035` 和 `WI-037` 的 handoff，正式追加 `WI-038`。
- 把目标边界收紧为：
  - worker/sub-agent 只作为 canonical execution contract 实现，不扩张为通用 worker framework；
  - worker requested/start/heartbeat/summary/completed/failed/cancelled/consumed/rejected 都必须进入 `Session Service`；
  - worker 只能消费冻结的 `DecisionTrace`、packet refs、retrieval handles 与 distilled summary；
  - worker 不得直接修改 Goal Contract、approval、risk band、completion truth 或 release gate verdict；
  - stale/late/duplicate/supersede/crash recovery 都必须 fail closed 并进入 canonical truth。
- 已创建 `spec.md / plan.md / tasks.md / task-execution-log.md` 与 `.ai-sdlc/work-items/038-*` 基线。
- 本地验证：
  - `uv run pytest -q tests/test_long_running_autonomy_doc_contracts.py` -> `3 passed in 0.02s`
- 对抗复核：
  - Anthropic Manager 专家：无 blocking/P1；
  - Hermes Agent 专家：无 blocking/P1。
- `T381` 已满足 formal docs baseline 条件，下一执行入口切到 `T382`，开始 worker lifecycle / consume / reject 红测。
